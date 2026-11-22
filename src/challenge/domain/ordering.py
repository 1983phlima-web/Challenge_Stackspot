"""Ordenação da fila de trabalho (arquivo ``_read``)."""

from __future__ import annotations

import pandas as pd

from challenge.domain.codes import CANAL_ORDER, STATUS_RESOLVED

_TENSION_RANK = {"A": 0, "M": 1, "B": 2}
_STATUS_RANK = {"1": 0, "2": 1}


def order_queue(df: pd.DataFrame) -> pd.DataFrame:
    """Exclui resolvidas e ordena a fila.

    Colunas exigidas: ``id``, ``_canal``, ``_status``, ``_tensao``, ``_data``.

    Critérios, em sequência:
      1. Canal com mais itens (na própria fila) primeiro; empate segue B, O, R, S, Z.
      2. Tensão: Alta, Média, Baixa.
      3. Status: Aberta, Em análise.
      4. Desempate determinístico: data mais antiga e ``id``.
    """
    queue = df[df["_status"] != STATUS_RESOLVED].copy()
    if queue.empty:
        return queue
    queue["_n_canal"] = queue.groupby("_canal")["id"].transform("size")
    queue["_o_canal"] = queue["_canal"].map(CANAL_ORDER)
    queue["_o_tensao"] = queue["_tensao"].map(_TENSION_RANK)
    queue["_o_status"] = queue["_status"].map(_STATUS_RANK)
    queue = queue.sort_values(
        ["_n_canal", "_o_canal", "_o_tensao", "_o_status", "_data", "id"],
        ascending=[False, True, True, True, True, True],
        kind="stable",
    )
    return queue.drop(columns=["_n_canal", "_o_canal", "_o_tensao", "_o_status"])
