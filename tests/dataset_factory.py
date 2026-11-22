"""Fábrica determinística do dataset de validação: 500 casos válidos (500 textos distintos) + 40 inválidos.

Uso: ``python tests/dataset_factory.py --out dataset_challenge.csv --expected gabarito.csv``

O gabarito traz, por linha, a fila esperada (ou os motivos de rejeição) e o cenário de origem
(produto|tom|canal|status), de modo que o rótulo vale com ou sem IA.
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from corpus import generate_scenarios

HEADER = ["id", "data_reclamacao", "canal", "texto_reclamacao", "produto", "status"]
CANAL_VALUES = {
    "B": ["Banco Central"],
    "O": ["Ouvidoria"] * 9 + ["  ouvidoria "],
    "R": ["Redes Sociais"],
    "S": ["SAC"] * 9 + ["sac"],
    "Z": ["Chat", "WhatsApp", "Aplicativo"],
}
STATUS_VALUES = {"1": ["Aberta"], "2": ["Em análise"] * 9 + ["em analise"], "3": ["Resolvida"]}
PRODUTO_VARIANTS = {"Empréstimo": ["Empréstimo"] * 9 + ["emprestimo"]}


@dataclass(frozen=True)
class Case:
    """Linha do CSV com o resultado esperado."""

    linha: int
    row: list[str]
    expected_fila: str  # vazio quando rejeitada
    reject_reasons: str  # vazio quando válida
    cenario: str = ""


def build_cases(valid: int = 500, invalid: int = 40, seed: int = 2026) -> list[Case]:
    """Gera ``valid`` linhas válidas (textos distintos) e ``invalid`` linhas inválidas."""
    rng = random.Random(seed)
    start = date(2025, 9, 1)
    valid_rows: list[tuple[list[str], str, str]] = []
    for i, sc in enumerate(generate_scenarios(valid, seed), start=1):
        produto = rng.choice(PRODUTO_VARIANTS.get(sc.produto, [sc.produto]))
        row = [
            f"REC-2026-{i:05d}",
            (start + timedelta(days=rng.randint(0, 180))).isoformat(),
            rng.choice(CANAL_VALUES[sc.canal]),
            sc.text,
            produto,
            rng.choice(STATUS_VALUES[sc.status]),
        ]
        valid_rows.append((row, f"{sc.canal}{sc.produto_code}{sc.status}{sc.tension}", sc.cenario))

    n_dup = max(1, invalid // 8)

    def bad(kind: str, i: int) -> tuple[list[str], str]:
        row = [
            f"REC-X-{i:05d}",
            "2025-11-03",
            "Ouvidoria",
            "Texto qualquer de teste.",
            "Seguros",
            "Aberta",
        ]
        if kind == "combo":  # data inválida + texto vazio
            row[1], row[3] = "31/12/2025", ""
            return row, "data_invalida;texto_vazio"
        idx, value = {
            "id_vazio": (0, ""),
            "data_invalida": (1, rng.choice(["2025-13-45", "03/11/2025", "", "ontem"])),
            "texto_vazio": (3, "   "),
            "status_invalido": (5, rng.choice(["Cancelada", "", "Encerrada"])),
        }[kind]
        row[idx] = value
        return row, kind

    kinds = ["id_vazio", "data_invalida", "texto_vazio", "status_invalido", "combo"]
    bad_rows = [bad(kinds[i % len(kinds)], i) for i in range(invalid - n_dup)]

    total = valid + len(bad_rows)
    slots = sorted(rng.sample(range(total), len(bad_rows)))
    merged: list[tuple[list[str], str, str, str]] = []  # row, fila, motivo, cenario
    vi = bi = 0
    for pos in range(total):
        if bi < len(bad_rows) and pos == slots[bi]:
            merged.append((bad_rows[bi][0], "", bad_rows[bi][1], ""))
            bi += 1
        else:
            r, fila, cen = valid_rows[vi]
            merged.append((r, fila, "", cen))
            vi += 1
    for _ in range(n_dup):  # duplicatas ao final: a 1ª ocorrência do id continua válida
        src = rng.choice([m for m in merged if m[1]])[0]
        merged.append(
            (
                [src[0], "2025-12-01", "SAC", "Registro duplicado.", "Seguros", "Aberta"],
                "",
                "id_duplicado",
                "",
            )
        )
    return [Case(i, row, fila, why, cen) for i, (row, fila, why, cen) in enumerate(merged, start=1)]


def write_dataset(cases: list[Case], out: Path, expected: Path | None = None) -> None:
    """Grava o CSV de entrada e, opcionalmente, o gabarito."""
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(c.row for c in cases)
    if expected is not None:
        with expected.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["linha", "id", "fila_esperada", "motivos_rejeicao", "cenario"])
            writer.writerows(
                [c.linha, c.row[0], c.expected_fila, c.reject_reasons, c.cenario] for c in cases
            )


def main() -> None:
    """CLI do gerador."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valid", type=int, default=500)
    parser.add_argument("--invalid", type=int, default=40)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("dataset_challenge.csv"))
    parser.add_argument("--expected", type=Path, default=None)
    args = parser.parse_args()
    cases = build_cases(args.valid, args.invalid, args.seed)
    write_dataset(cases, args.out, args.expected)
    print(
        f"Gerado: {args.out} ({len(cases)} linhas: {args.valid} válidas + {args.invalid} inválidas)"
    )


if __name__ == "__main__":
    main()
