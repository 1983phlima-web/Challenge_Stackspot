import pandas as pd

from challenge.domain.ordering import order_queue


def _df(rows):
    return pd.DataFrame(rows, columns=["id", "_canal", "_status", "_tensao", "_data"]).assign(
        _data=lambda d: pd.to_datetime(d["_data"])
    )


def test_exclui_resolvidas_e_ordena_por_volume_tensao_status():
    df = _df(
        [
            ["1", "S", "1", "B", "2025-01-01"],
            ["2", "O", "2", "A", "2025-01-01"],
            ["3", "O", "1", "A", "2025-01-02"],
            ["4", "O", "1", "M", "2025-01-01"],
            ["5", "S", "3", "A", "2025-01-01"],  # resolvida: sai
            ["6", "B", "1", "A", "2025-01-01"],
        ]
    )
    out = order_queue(df)
    assert "5" not in set(out["id"])
    # O tem 3 itens (primeiro); depois empate B(1)/S(1) => B antes de S
    assert list(out["id"]) == ["3", "2", "4", "6", "1"]


def test_fila_vazia():
    assert order_queue(_df([["1", "S", "3", "A", "2025-01-01"]])).empty
