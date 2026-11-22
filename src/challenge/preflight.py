"""Verificação de implantação (``challenge check``): testes de ambiente, conectividade e ponta a ponta."""

from __future__ import annotations

import csv
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from challenge.ai.base import LLMClient
from challenge.config import Settings
from challenge.domain.codes import FilaCode
from challenge.infra.io import REQUIRED_COLUMNS, read_csv_robust, require_columns
from challenge.performer.pipeline import PerformerPipeline
from challenge.performer.responder import Complaint, Responder
from challenge.preprocess.pipeline import PreprocessPipeline
from challenge.preprocess.tension import TensionClassifier
from challenge.rules.engine import RulesEngine
from challenge.rules.policy import PolicyBook

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
MIN_FREE_GB = 2.0
MIN_AGREEMENT = 0.90  # concordância mínima de tensão
SEVERE_RATE = 0.01  # erros Alta→Baixa tolerados: até 1% das Alta
SLOW_CALL_S = 30.0
PROBE_TEXT = "Vou acionar o Procon e o Banco Central se não resolverem essa cobrança."
PROBE_COMPLAINT = "Estou cobrando juros além do que está em contrato e ninguém resolve."


@dataclass(frozen=True)
class CheckResult:
    """Resultado de uma verificação."""

    name: str
    status: str
    detail: str


def _guard(name: str, fn: Callable[[], list[CheckResult]]) -> list[CheckResult]:
    try:
        return fn()
    except Exception as exc:
        return [CheckResult(name, FAIL, f"{type(exc).__name__}: {exc}")]


def check_python() -> list[CheckResult]:
    """Versão do Python."""
    version = sys.version.split()[0]
    ok = sys.version_info >= (3, 11)
    return [CheckResult("python", PASS if ok else FAIL, f"{version} (exige >= 3.11)")]


def check_files(settings: Settings) -> list[CheckResult]:
    """Regras e política carregam e são válidas."""
    rules = RulesEngine.from_file(settings.rules_file)
    book = PolicyBook.from_file(settings.policy_file)
    return [
        CheckResult("motor_regras", PASS, f"{len(rules)} regras em {settings.rules_file.name}"),
        CheckResult("politica", PASS, f"{len(book)} políticas em {settings.policy_file.name}"),
    ]


def check_folders(settings: Settings) -> list[CheckResult]:
    """Pastas existem/são criadas e permitem escrita; espaço em disco; entrada presente e válida."""
    results: list[CheckResult] = []
    for name, folder in {
        "base": settings.base_dir,
        "Fila": settings.fila_dir,
        "Output": settings.output_dir,
        "Logs": settings.logs_dir,
        "Relatorios": settings.reports_dir,
    }.items():
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".preflight_{time.time_ns()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        results.append(CheckResult(f"escrita:{name}", PASS, str(folder)))
    free_gb = shutil.disk_usage(settings.base_dir).free / 1024**3
    results.append(
        CheckResult("disco", PASS if free_gb >= MIN_FREE_GB else WARN, f"{free_gb:.1f} GB livres")
    )
    if not settings.input_path.is_file():
        results.append(CheckResult("entrada", WARN, f"{settings.input_path} ainda não existe"))
    else:
        df = read_csv_robust(settings.input_path)
        require_columns(df, REQUIRED_COLUMNS)
        results.append(CheckResult("entrada", PASS, f"{len(df)} linhas, colunas válidas"))
    return results


def check_llm(settings: Settings, llm: LLMClient | None) -> list[CheckResult]:
    """Prompts reais: tensão, resposta e concorrência (detecta limite de requisições)."""
    if llm is None:
        return [CheckResult("ia", WARN, "provedor 'none': somente regras (sem IA)")]
    engine = RulesEngine.from_file(settings.rules_file)
    results: list[CheckResult] = []

    t0 = time.perf_counter()
    tension = TensionClassifier(engine, llm, mask=settings.mask_pii).classify(PROBE_TEXT)
    elapsed = time.perf_counter() - t0
    if tension.origem == "REGRAS_FALLBACK":
        return [
            CheckResult(
                "ia:tensao", FAIL, f"IA indisponível ou resposta inválida ({tension.justificativa})"
            )
        ]
    status = WARN if elapsed > SLOW_CALL_S else PASS
    verdict = (
        "esperado Alta"
        if tension.nivel.label == "Alta"
        else f"ATENÇÃO: veio {tension.nivel.label}, esperado Alta"
    )
    results.append(
        CheckResult(
            "ia:tensao",
            status if tension.nivel.label == "Alta" else WARN,
            f"{verdict}; {elapsed:.1f}s; origem {tension.origem}",
        )
    )

    book = PolicyBook.from_file(settings.policy_file)
    t0 = time.perf_counter()
    suggestion = Responder(book, llm, settings).suggest(
        Complaint("PREFLIGHT-1", PROBE_COMPLAINT, FilaCode.parse("OEMP1M"))
    )
    results.append(
        CheckResult(
            "ia:resposta", PASS, f"origem {suggestion.origem}; {time.perf_counter() - t0:.1f}s"
        )
    )

    workers = settings.llm_workers
    texts = [f"{PROBE_TEXT} (teste de concorrência {i})" for i in range(workers * 2)]
    classifier = TensionClassifier(engine, llm, mask=settings.mask_pii)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(classifier.classify, texts))
    failed = sum(o.origem == "REGRAS_FALLBACK" for o in outcomes)
    detail = f"{len(texts) - failed}/{len(texts)} ok com {workers} threads em {time.perf_counter() - t0:.1f}s"
    if failed == len(texts):
        results.append(CheckResult("ia:concorrencia", FAIL, detail))
    elif failed:
        results.append(
            CheckResult(
                "ia:concorrencia",
                WARN,
                detail + " — reduza llm_workers (possível limite de requisições)",
            )
        )
    else:
        results.append(CheckResult("ia:concorrencia", PASS, detail))
    return results


def _tmp_settings(settings: Settings, base: Path) -> Settings:
    return replace(settings, base_dir=base, loop_retry_delay_s=0.0)


def check_smoke(
    settings: Settings, llm: LLMClient | None, sample: Path, rows: int
) -> list[CheckResult]:
    """Executa Processo 1 e 2 reais sobre ``rows`` linhas, em pasta temporária (não toca em produção)."""
    if not sample.is_file():
        return [CheckResult("smoke", WARN, f"amostra ausente: {sample}")]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        lines = sample.read_text(encoding="utf-8").splitlines(keepends=True)[: rows + 1]
        (base / settings.input_filename).write_text("".join(lines), encoding="utf-8")
        s = _tmp_settings(settings, base)
        pre = PreprocessPipeline(s, llm, "preflight").run()
        outcomes = PerformerPipeline(s, llm, "preflight").run()
        states = Counter(o.status for o in outcomes)
        detail = f"fila={pre.stats['linhas_na_fila_read']} itens; Performer: {dict(states)}"
        if states.get("nok"):
            return [CheckResult("smoke", FAIL, detail)]
        return [CheckResult("smoke", WARN if states.get("loop") else PASS, detail)]


def check_golden(
    settings: Settings,
    llm: LLMClient | None,
    sample: Path,
    expected: Path,
    min_agreement: float = MIN_AGREEMENT,
    limit: int | None = None,
) -> list[CheckResult]:
    """Roda o Processo 1 no dataset do gabarito (500 textos distintos) e compara com o esperado.

    ``limit`` usa só as primeiras N linhas (reduz custo/tempo de chamadas à IA).
    """
    if not (sample.is_file() and expected.is_file()):
        return [
            CheckResult(
                "golden", WARN, f"dataset/gabarito ausentes: {sample.name}, {expected.name}"
            )
        ]
    with expected.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    lines = sample.read_text(encoding="utf-8").splitlines(keepends=True)
    if limit:
        lines, rows = lines[: limit + 1], rows[:limit]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / settings.input_filename).write_text("".join(lines), encoding="utf-8")
        res = PreprocessPipeline(_tmp_settings(settings, base), llm, "preflight").run()
        got = read_csv_robust(res.fila_path)["fila"].tolist()
    want = [r["fila_esperada"] for r in rows if r["fila_esperada"]]
    n_rejected = sum(1 for r in rows if r["motivos_rejeicao"])
    results = [
        CheckResult(
            "golden:rejeicoes",
            PASS if res.stats["linhas_rejeitadas"] == n_rejected else FAIL,
            f"{res.stats['linhas_rejeitadas']} (esperado {n_rejected})",
        )
    ]
    if len(got) != len(want):
        return [
            *results,
            CheckResult("golden:fila", FAIL, f"{len(got)} linhas, esperado {len(want)}"),
        ]
    bad_det = sum(g[:5] != w[:5] for g, w in zip(got, want, strict=True))
    results.append(
        CheckResult(
            "golden:canal+produto+status",
            PASS if bad_det == 0 else FAIL,
            f"{bad_det} divergências (esperado 0)",
        )
    )
    pairs = [(w[5], g[5]) for g, w in zip(got, want, strict=True)]
    hits = sum(a == b for a, b in pairs)
    agreement = hits / len(pairs) if pairs else 1.0
    n_alta = sum(1 for a, _ in pairs if a == "A")
    severe = sum(
        1 for a, b in pairs if a == "A" and b == "B"
    )  # Alta tratada como Baixa: erro grave
    confusion = Counter((a, b) for a, b in pairs if a != b)
    detail = f"{agreement:.1%} de concordância ({hits}/{len(pairs)}); Alta→Baixa: {severe}/{n_alta}"
    if confusion:
        detail += "; divergências (esperado→obtido): " + ", ".join(
            f"{a}→{b}:{n}" for (a, b), n in sorted(confusion.items())
        )
    ok = agreement >= min_agreement and severe <= int(SEVERE_RATE * n_alta)
    results.append(CheckResult("golden:tensao", PASS if ok else FAIL, detail))
    return results


def run_checks(
    settings: Settings,
    llm: LLMClient | None,
    *,
    smoke: bool = False,
    golden: bool = False,
    rows: int = 40,
    sample: Path | None = None,
    golden_rows: int | None = None,
) -> list[CheckResult]:
    """Executa a bateria de verificações em ordem de dependência."""
    sample = sample or Path("tests/data/dataset_500.csv")
    expected = sample.with_name(sample.stem + "_expected.csv")
    results = [*check_python(), *_guard("arquivos", lambda: check_files(settings))]
    results += _guard("pastas", lambda: check_folders(settings))
    llm_results = _guard("ia", lambda: check_llm(settings, llm))
    results += llm_results
    llm_ok = not any(r.status == FAIL for r in llm_results)
    if smoke:
        results += (
            _guard("smoke", lambda: check_smoke(settings, llm, sample, rows))
            if llm_ok
            else [CheckResult("smoke", WARN, "ignorado: IA com falha")]
        )
    if golden:
        results += (
            _guard(
                "golden", lambda: check_golden(settings, llm, sample, expected, limit=golden_rows)
            )
            if llm_ok
            else [CheckResult("golden", WARN, "ignorado: IA com falha")]
        )
    return results
