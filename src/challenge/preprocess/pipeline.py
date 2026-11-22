"""Processo 1 — Pré-processamento: valida, classifica tensão, gera fila e arquivo ``_read``."""

from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from challenge.ai.base import LLMClient
from challenge.config import Settings
from challenge.domain.codes import (
    CANAL_LABEL,
    PRODUTO_LABEL,
    STATUS_LABEL,
    STATUS_RESOLVED,
    TENSION_LABEL,
)
from challenge.domain.ordering import order_queue
from challenge.infra.io import (
    REQUIRED_COLUMNS,
    InputNotFoundError,
    SchemaError,
    atomic_write_csv,
    read_csv_robust,
    require_columns,
    timestamp,
)
from challenge.logging_setup import AuditLog
from challenge.preprocess.tension import TensionClassifier, TensionResult
from challenge.preprocess.validation import validate_rows
from challenge.reporting.analytics import build_preprocess_sections
from challenge.reporting.render import write_json, write_report
from challenge.rules.engine import RulesEngine


@dataclass(frozen=True)
class PreprocessResult:
    """Artefatos e estatísticas do Processo 1."""

    fila_path: Path
    read_path: Path
    rejected_path: Path | None
    report_paths: tuple[Path, Path]
    stats: dict[str, Any]


def _counts(series: pd.Series, labels: dict[str, str]) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.map(labels).value_counts().items()}


class PreprocessPipeline:
    """Orquestra o Processo 1 de ponta a ponta."""

    def __init__(self, settings: Settings, llm: LLMClient | None, run_id: str) -> None:
        """Carrega o Motor de Regras e prepara o classificador."""
        self._s = settings
        self._run_id = run_id
        self._log = logging.getLogger("challenge.preprocess")
        self._rules = RulesEngine.from_file(settings.rules_file)
        self._log.info("Regras carregadas: %d", len(self._rules))
        self._classifier = TensionClassifier(self._rules, llm, mask=settings.mask_pii)

    def run(self) -> PreprocessResult:
        """Executa o pipeline completo."""
        s = self._s
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        ts = timestamp()
        if not s.input_path.is_file():
            raise InputNotFoundError(f"Entrada não encontrada: {s.input_path}")

        raw = read_csv_robust(s.input_path)
        require_columns(raw, REQUIRED_COLUMNS)
        if raw.empty:
            raise SchemaError("Arquivo de entrada sem linhas de dados")
        self._log.info("Entrada lida: %d linhas (%s)", len(raw), s.input_path)

        valid, rejected = validate_rows(raw)
        if valid.empty:
            raise SchemaError("Nenhuma linha válida após a validação")
        self._log.info("Validação: %d válidas, %d rejeitadas", len(valid), len(rejected))

        with AuditLog(s.logs_dir / f"audit_preprocess_{ts}.jsonl", self._run_id) as audit:
            for row in rejected.itertuples(index=False):
                audit.write("row_rejected", id=row.id, motivo=row.motivo)
            enriched = self._classify(valid, audit)

            fila_path = s.fila_dir / f"processadas_{ts}.csv"
            atomic_write_csv(enriched[[*REQUIRED_COLUMNS, "fila"]], fila_path)
            self._log.info("Base de fila gravada: %s", fila_path)

            rejected_path: Path | None = None
            if not rejected.empty:
                rejected_path = s.fila_dir / f"rejeitadas_{ts}.csv"
                atomic_write_csv(rejected, rejected_path)

            queue = order_queue(enriched)
            read_path = s.output_dir / f"{fila_path.stem}_read.csv"
            atomic_write_csv(queue[[*REQUIRED_COLUMNS, "fila"]], read_path)  # publicação atômica
            self._log.info("Arquivo ordenado publicado: %s (%d itens)", read_path, len(queue))

            for pos, row in enumerate(queue.itertuples(index=False), start=1):
                audit.write("row_queued", id=row.id, fila=row.fila, posicao=pos)

        stats = self._stats(raw, valid, rejected, enriched, queue, started, t0)
        ref_date = pd.Timestamp.now().normalize()
        sections = build_preprocess_sections(enriched, queue, stats, s.top_risks, ref_date)
        reports = write_report(
            s.reports_dir,
            f"relatorio_preprocessamento_{ts}",
            "Relatório Gerencial — Pré-processamento de Reclamações",
            f"Execução {self._run_id} em {started.astimezone():%d/%m/%Y %H:%M} · {fila_path.name}",
            sections,
        )
        write_json(s.logs_dir / f"stats_preprocess_{ts}.json", stats)
        self._log.info("Relatórios: %s | %s", *reports)
        return PreprocessResult(fila_path, read_path, rejected_path, reports, stats)

    def _classify(self, valid: pd.DataFrame, audit: AuditLog) -> pd.DataFrame:
        texts = valid["texto_reclamacao"].drop_duplicates().tolist()
        results: dict[str, TensionResult] = {}
        step = max(1, len(texts) // 10)
        with ThreadPoolExecutor(max_workers=self._s.llm_workers) as pool:
            futures = {pool.submit(self._classifier.classify, t): t for t in texts}
            for done, future in enumerate(as_completed(futures), start=1):
                results[futures[future]] = future.result()
                if done % step == 0 or done == len(texts):
                    self._log.info("Tensão classificada: %d/%d textos únicos", done, len(texts))
        res = valid["texto_reclamacao"].map(results)
        out = valid.copy()
        out["_tensao"] = [r.nivel.code for r in res]
        out["_origem"] = [r.origem for r in res]
        out["_termos"] = [list(r.termos) for r in res]
        out["fila"] = out["_canal"] + out["_produto"] + out["_status"] + out["_tensao"]
        for row, r in zip(out.itertuples(index=False), res, strict=True):
            audit.write(
                "row_classified",
                id=row.id,
                fila=row.fila,
                tensao=r.nivel.label,
                origem=r.origem,
                confianca=r.confianca,
                justificativa=r.justificativa,
                termos=list(r.termos),
                latencia_ms=round(r.latencia_ms, 1),
            )
        return out

    def _stats(
        self,
        raw: pd.DataFrame,
        valid: pd.DataFrame,
        rejected: pd.DataFrame,
        enriched: pd.DataFrame,
        queue: pd.DataFrame,
        started: datetime,
        t0: float,
    ) -> dict[str, Any]:
        motivos: Counter[str] = Counter()
        for value in rejected.get("motivo", []):
            motivos.update(value.split(";"))
        return {
            "run_id": self._run_id,
            "iniciado_em": started.isoformat(),
            "finalizado_em": datetime.now(UTC).isoformat(),
            "duracao_s": round(time.perf_counter() - t0, 2),
            "linhas_lidas": len(raw),
            "linhas_validas": len(valid),
            "linhas_rejeitadas": len(rejected),
            "rejeicoes_por_motivo": dict(motivos),
            "linhas_resolvidas_excluidas": int((enriched["_status"] == STATUS_RESOLVED).sum()),
            "linhas_na_fila_read": len(queue),
            "textos_unicos": int(valid["texto_reclamacao"].nunique()),
            "por_canal_fila": _counts(queue["_canal"], CANAL_LABEL) if len(queue) else {},
            "por_produto": _counts(enriched["_produto"], PRODUTO_LABEL),
            "por_status": _counts(enriched["_status"], STATUS_LABEL),
            "por_tensao": _counts(enriched["_tensao"], TENSION_LABEL),
            "origem_tensao": {
                str(k): int(v) for k, v in enriched["_origem"].value_counts().items()
            },
            "ia": self._classifier.snapshot(),
        }
