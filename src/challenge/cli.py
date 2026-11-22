"""Interface de linha de comando: ``challenge preprocess | perform | run-all``."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from challenge.ai.factory import build_llm
from challenge.config import ConfigError, Settings
from challenge.infra.io import InputNotFoundError, SchemaError, timestamp
from challenge.logging_setup import setup_logging
from challenge.performer.pipeline import PerformerPipeline
from challenge.preflight import FAIL, PASS, WARN, run_checks
from challenge.preprocess.pipeline import PreprocessPipeline
from challenge.reporting.render import write_json
from challenge.rules.engine import RulesError
from challenge.rules.policy import PolicyError

EXIT_OK, EXIT_PARTIAL, EXIT_INPUT, EXIT_UNEXPECTED = 0, 1, 2, 3
_log = logging.getLogger("challenge.cli")


def build_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos."""
    parser = argparse.ArgumentParser(prog="challenge", description=__doc__)
    parser.add_argument("command", choices=["preprocess", "perform", "run-all", "check"])
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--base-dir", type=Path, default=None, help="Sobrescreve a pasta base")
    parser.add_argument(
        "--smoke", action="store_true", help="check: executa os 2 processos em amostra"
    )
    parser.add_argument(
        "--golden", action="store_true", help="check: valida o dataset de 500 casos"
    )
    parser.add_argument(
        "--rows", type=int, default=40, help="check --smoke: nº de linhas da amostra"
    )
    parser.add_argument(
        "--golden-rows", type=int, default=None, help="check --golden: usa só as N primeiras linhas"
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=None,
        help="CSV de amostra (padrão: tests/data/dataset_500.csv)",
    )
    return parser


def _preprocess(settings: Settings, run_id: str) -> int:
    setup_logging(settings.logs_dir, run_id, "preprocess", settings.log_level)
    llm = build_llm(settings)
    try:
        result = PreprocessPipeline(settings, llm, run_id).run()
    finally:
        if llm is not None:
            llm.close()
    _log.info("Pré-processamento concluído: %s", result.read_path)
    return EXIT_OK


def _perform(settings: Settings, run_id: str) -> int:
    setup_logging(settings.logs_dir, run_id, "performer", settings.log_level)
    llm = build_llm(settings)
    try:
        outcomes = PerformerPipeline(settings, llm, run_id).run()
    finally:
        if llm is not None:
            llm.close()
    counts = {st: sum(o.status == st for o in outcomes) for st in ("ok", "loop", "nok", "skipped")}
    _log.info("Performer concluído: %s", counts)
    return EXIT_PARTIAL if counts["loop"] or counts["nok"] else EXIT_OK


def _check(settings: Settings, run_id: str, args: argparse.Namespace) -> int:
    setup_logging(settings.logs_dir, run_id, "check", settings.log_level)
    try:
        llm = build_llm(settings)
    except ConfigError as exc:
        print(f"[{FAIL}] credenciais/provedor: {exc}\n\nResumo: 0 PASS, 0 WARN, 1 FAIL")
        return EXIT_PARTIAL
    try:
        results = run_checks(
            settings,
            llm,
            smoke=args.smoke,
            golden=args.golden,
            rows=args.rows,
            sample=args.sample,
            golden_rows=args.golden_rows,
        )
    finally:
        if llm is not None:
            llm.close()
    for r in results:
        print(f"[{r.status}] {r.name}: {r.detail}")
    counts = {st: sum(r.status == st for r in results) for st in (PASS, WARN, FAIL)}
    print(f"\nResumo: {counts[PASS]} PASS, {counts[WARN]} WARN, {counts[FAIL]} FAIL")
    write_json(
        settings.logs_dir / f"preflight_{timestamp()}.json",
        {"run_id": run_id, "resumo": counts, "resultados": [asdict(r) for r in results]},
    )
    return EXIT_PARTIAL if counts[FAIL] else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada. Retorna 0 (ok), 1 (há lotes _loop/_nok), 2 (entrada/config), 3 (inesperado)."""
    args = build_parser().parse_args(argv)
    run_id = uuid.uuid4().hex[:8]
    try:
        yaml_path = args.config if args.config.is_file() else None
        settings = Settings.load(yaml_path, base_dir=args.base_dir)
        if args.command == "check":
            return _check(settings, run_id, args)
        code = EXIT_OK
        if args.command in {"preprocess", "run-all"}:
            code = _preprocess(settings, run_id)
        if args.command in {"perform", "run-all"} and code == EXIT_OK:
            code = _perform(settings, run_id)
        return code
    except (ConfigError, InputNotFoundError, SchemaError, RulesError, PolicyError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        logging.getLogger("challenge").error("Erro de entrada/configuração: %s", exc)
        return EXIT_INPUT
    except Exception:
        logging.getLogger("challenge").exception("Erro inesperado")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
