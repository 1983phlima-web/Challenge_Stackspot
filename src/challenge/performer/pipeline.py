"""Processo 2 — Performer, com ciclo de reprocessamento (``_loop``).

Máquina de estados de um lote (``<base>`` = ``processadas_<ts>``)::

    <base>_read.csv ─┐                       ┌─ todas respondidas ─▶ <base>_ok.csv
                     ├─ rodada (N linhas) ───┤
    <base>_loop.csv ─┘                       ├─ pendentes ─────────▶ <base>_loop.csv  (novo ciclo)
                                             ├─ pendentes + ciclos esgotados ─▶ <base>_nok.csv
                                             └─ erro de arquivo ────────────▶ <base>_nok.csv

* Linhas respondidas vão para ``<base>_ok.csv`` (acumulado, na ordem original da fila).
* Linhas sem resposta ficam em ``<base>_loop.csv`` (mesma estrutura do ``_read``, sem ``Resposta``).
* Na mesma execução, os pendentes recebem até ``loop_rounds_per_run - 1`` rodadas extras; o que
  restar é persistido em ``_loop`` e retomado na próxima execução, até ``max_loop_cycles``.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from challenge.ai.base import LLMClient
from challenge.config import Settings
from challenge.domain.codes import FilaCode
from challenge.infra.io import (
    REQUIRED_COLUMNS,
    atomic_write_csv,
    file_lock,
    read_csv_robust,
    require_columns,
    timestamp,
)
from challenge.logging_setup import AuditLog
from challenge.performer.responder import Complaint, Responder, Suggestion
from challenge.reporting.analytics import build_performer_sections
from challenge.reporting.render import write_json, write_report
from challenge.rules.policy import PolicyBook

READ_SUFFIX = "_read"
LOOP_SUFFIX = "_loop"
RESPONSE_COLUMN = "Resposta"
GENERATED_PREFIX = "[Sugestão IA - revisar] "
INPUT_COLUMNS = (*REQUIRED_COLUMNS, "fila")


@dataclass(frozen=True)
class FileOutcome:
    """Resultado de um lote após as rodadas da execução."""

    source: Path
    status: str  # ok | loop | nok | skipped
    ok_path: Path | None = None
    loop_path: Path | None = None
    nok_path: Path | None = None
    stats: dict[str, Any] = field(default_factory=dict)


def _split_name(path: Path) -> tuple[str, str]:
    """Devolve ``(base, sufixo)`` para ``<base>_read.csv`` ou ``<base>_loop.csv``."""
    for suffix in (READ_SUFFIX, LOOP_SUFFIX):
        if path.stem.endswith(suffix):
            return path.stem[: -len(suffix)], suffix
    raise ValueError(f"Nome fora do padrão (_read/_loop): {path.name}")


class PerformerPipeline:
    """Orquestra o Processo 2."""

    def __init__(self, settings: Settings, llm: LLMClient | None, run_id: str) -> None:
        """Carrega a base de políticas."""
        self._s = settings
        self._run_id = run_id
        self._log = logging.getLogger("challenge.performer")
        book = PolicyBook.from_file(settings.policy_file)
        self._log.info("Políticas carregadas: %d", len(book))
        self._responder = Responder(book, llm, settings)

    # ------------------------------------------------------------------ orquestração
    def run(self) -> list[FileOutcome]:
        """Processa todos os lotes pendentes (``_read`` e ``_loop``) da pasta de saída."""
        out = self._s.output_dir
        files = sorted([*out.glob(f"*{READ_SUFFIX}.csv"), *out.glob(f"*{LOOP_SUFFIX}.csv")])
        self._log.info("Lotes pendentes: %d", len(files))
        return [self.process_batch(path) for path in files]

    def process_batch(self, path: Path) -> FileOutcome:
        """Executa a 1ª rodada e as retentativas de pendentes da mesma execução."""
        outcome = self._process_file(path)
        for round_no in range(2, self._s.loop_rounds_per_run + 1):
            if outcome.status != "loop" or outcome.loop_path is None:
                break
            self._log.info(
                "Rodada %d: reprocessando pendentes de %s", round_no, outcome.loop_path.name
            )
            time.sleep(self._s.loop_retry_delay_s)
            outcome = self._process_file(outcome.loop_path)
        return outcome

    def _process_file(self, path: Path) -> FileOutcome:
        """Uma rodada sobre um arquivo, com lock; erro de arquivo => ``_nok``."""
        with file_lock(path) as acquired:
            if not acquired:
                self._log.warning("%s já está em processamento; ignorado", path.name)
                return FileOutcome(path, "skipped")
            try:
                return self._round(path)
            except Exception:
                self._log.exception("Falha de arquivo em %s", path.name)
                base, _ = _split_name(path)
                nok = path.with_name(f"{base}_nok.csv")
                path.replace(nok)
                return FileOutcome(path, "nok", nok_path=nok, stats={"erro_arquivo": True})

    # ------------------------------------------------------------------ uma rodada
    def _round(self, path: Path) -> FileOutcome:
        started, t0, ts = datetime.now(UTC), time.perf_counter(), timestamp()
        base, suffix = _split_name(path)
        df = read_csv_robust(path)
        require_columns(df, INPUT_COLUMNS)
        state = self._load_state(base)
        if suffix == READ_SUFFIX or not state:
            state = {"base": base, "order": list(df["id"]), "cycles": 0}
        state["cycles"] = int(state["cycles"]) + 1
        cycle = state["cycles"]
        records = [{str(k): str(v) for k, v in row.items()} for row in df.to_dict("records")]
        self._log.info("Ciclo %d de %s: %d linhas", cycle, base, len(records))

        audit_path = self._s.logs_dir / f"audit_performer_{base}_c{cycle}_{ts}.jsonl"
        with (
            AuditLog(audit_path, self._run_id) as audit,
            ThreadPoolExecutor(max_workers=self._s.llm_workers) as pool,
        ):
            outcomes = list(pool.map(self._answer, records))
            respostas, meta = self._collect(records, outcomes, audit, cycle)

        failed_mask = [sug is None for sug, _ in outcomes]
        ok_df = df.loc[[not f for f in failed_mask]].assign(
            **{RESPONSE_COLUMN: [r for r, f in zip(respostas, failed_mask, strict=True) if not f]}
        )
        pending_df = df.loc[failed_mask]

        ok_path = path.with_name(f"{base}_ok.csv")
        loop_path = path.with_name(f"{base}_loop.csv")
        nok_path = path.with_name(f"{base}_nok.csv")
        status = self._persist(path, ok_df, pending_df, state, ok_path, loop_path, nok_path)

        stats = self._stats(
            base, status, cycle, len(records), meta, started, t0, ok_path, loop_path
        )
        stem = f"{base}_c{cycle}"
        sections = build_performer_sections(pd.DataFrame(meta), stats)
        write_report(
            self._s.reports_dir,
            f"relatorio_performer_{stem}",
            "Relatório Gerencial — Performer de Respostas",
            f"Execução {self._run_id} · lote {base} · ciclo {cycle}",
            sections,
        )
        write_json(self._s.logs_dir / f"stats_performer_{stem}.json", stats)
        return FileOutcome(
            path,
            status,
            ok_path if ok_path.exists() else None,
            loop_path if status == "loop" else None,
            nok_path if status == "nok" else None,
            stats,
        )

    def _answer(self, rec: dict[str, str]) -> tuple[Suggestion | None, str]:
        """Responde uma linha; falhas são isoladas e devolvidas como texto."""
        try:
            fila = FilaCode.parse(rec["fila"])
            return self._responder.suggest(Complaint(rec["id"], rec["texto_reclamacao"], fila)), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"[:300]

    def _collect(
        self,
        records: list[dict[str, str]],
        outcomes: list[tuple[Suggestion | None, str]],
        audit: AuditLog,
        cycle: int,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        respostas: list[str] = []
        meta: list[dict[str, Any]] = []
        for rec, (sug, erro) in zip(records, outcomes, strict=True):
            fila = rec["fila"]
            row = {"id": rec["id"], "_produto": fila[1:4], "_tensao": fila[-1], "_erro": erro}
            if sug is None:
                respostas.append("")
                meta.append(
                    {**row, "_origem": "FALHA", "_politica": "", "_conf": None, "_lat": 0.0}
                )
                audit.write("row_failed", id=rec["id"], ciclo=cycle, erro=erro)
                continue
            text = sug.resposta
            if sug.origem == "IA_GERADA" and self._s.mark_generated:
                text = GENERATED_PREFIX + text
            respostas.append(text)
            meta.append(
                {
                    **row,
                    "_origem": sug.origem,
                    "_politica": sug.politica_id or "",
                    "_conf": sug.confianca,
                    "_lat": sug.latencia_ms,
                }
            )
            audit.write(
                "row_answered",
                id=rec["id"],
                ciclo=cycle,
                origem=sug.origem,
                politica=sug.politica_id,
                confianca=sug.confianca,
                justificativa=sug.justificativa,
                latencia_ms=round(sug.latencia_ms, 1),
            )
        return respostas, meta

    # ------------------------------------------------------------------ persistência
    def _persist(
        self,
        source: Path,
        ok_df: pd.DataFrame,
        pending_df: pd.DataFrame,
        state: dict[str, Any],
        ok_path: Path,
        loop_path: Path,
        nok_path: Path,
    ) -> str:
        """Grava ``_ok`` (acumulado) e decide o destino dos pendentes. Ordem segura contra falhas."""
        if not ok_df.empty:
            merged = ok_df
            if ok_path.exists():
                merged = pd.concat([read_csv_robust(ok_path), ok_df], ignore_index=True)
                merged = merged.drop_duplicates("id", keep="last")
            position = {rid: i for i, rid in enumerate(state["order"])}
            merged = merged.assign(_p=merged["id"].map(position).fillna(len(position)))
            merged = merged.sort_values("_p", kind="stable").drop(columns="_p")
            atomic_write_csv(merged, ok_path)

        state_path = self._state_path(state["base"])
        if pending_df.empty:
            source.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            return "ok"
        if int(state["cycles"]) >= self._s.max_loop_cycles:
            atomic_write_csv(pending_df, nok_path)
            source.unlink(missing_ok=True)
            loop_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            self._log.error(
                "%d itens esgotaram %d ciclos -> %s",
                len(pending_df),
                self._s.max_loop_cycles,
                nok_path.name,
            )
            return "nok"
        atomic_write_csv(pending_df, loop_path)
        if source != loop_path:
            source.unlink(missing_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self._log.warning("%d itens pendentes persistidos em %s", len(pending_df), loop_path.name)
        return "loop"

    def _state_path(self, base: str) -> Path:
        return self._s.output_dir / f"{base}.state.json"

    def _load_state(self, base: str) -> dict[str, Any] | None:
        path = self._state_path(base)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._log.warning("Estado corrompido em %s; reiniciando contagem", path.name)
            return None
        return data if isinstance(data, dict) and {"order", "cycles"} <= set(data) else None

    # ------------------------------------------------------------------ estatísticas
    def _stats(
        self,
        base: str,
        status: str,
        cycle: int,
        n: int,
        meta: list[dict[str, Any]],
        started: datetime,
        t0: float,
        ok_path: Path,
        loop_path: Path,
    ) -> dict[str, Any]:
        frame = pd.DataFrame(meta)
        answered = frame[frame["_origem"] != "FALHA"]
        confs = [c for c in answered["_conf"] if pd.notna(c)]
        lat = sorted(answered["_lat"].tolist())
        failures = n - len(answered)
        return {
            "run_id": self._run_id,
            "lote": base,
            "ciclo": cycle,
            "status_final": status,
            "iniciado_em": started.isoformat(),
            "duracao_s": round(time.perf_counter() - t0, 2),
            "linhas": n,
            "respondidas": len(answered),
            "falhas": failures,
            "arquivo_ok": ok_path.name if ok_path.exists() else None,
            "arquivo_loop": loop_path.name if status == "loop" else None,
            "por_origem": {str(k): int(v) for k, v in frame["_origem"].value_counts().items()},
            "confianca_media": round(mean(confs), 3) if confs else None,
            "latencia_media_ms": round(mean(lat), 1) if lat else 0.0,
            "latencia_p95_ms": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else 0.0,
        }
