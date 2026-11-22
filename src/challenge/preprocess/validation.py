"""Validação e quarentena de linhas do CSV de entrada."""

from __future__ import annotations

import pandas as pd

from challenge.domain.codes import canal_code, produto_code, status_code
from challenge.infra.io import REQUIRED_COLUMNS


def validate_rows(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa linhas válidas (com colunas derivadas ``_data/_canal/_produto/_status``) das rejeitadas.

    Motivos de rejeição: id vazio/duplicado, data fora de ``YYYY-MM-DD``, texto vazio,
    status fora de {Aberta, Em análise, Resolvida}.
    Canal/produto desconhecidos NÃO rejeitam: viram ``Z``/``Sem`` conforme a regra de negócio.
    """
    df = raw.copy()
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].str.strip()
    df["_data"] = pd.to_datetime(df["data_reclamacao"], format="%Y-%m-%d", errors="coerce")
    df["_status"] = df["status"].map(status_code)

    checks = {
        "id_vazio": df["id"].eq(""),
        "id_duplicado": df["id"].ne("") & df["id"].duplicated(keep="first"),
        "data_invalida": df["_data"].isna(),
        "texto_vazio": df["texto_reclamacao"].eq(""),
        "status_invalido": df["_status"].isna(),
    }
    motivo = pd.Series("", index=df.index)
    for name, mask in checks.items():
        separado = motivo.where(motivo.eq(""), motivo + ";")
        motivo = motivo.where(~mask, separado + name)

    bad = motivo.ne("")
    rejected = raw.loc[bad].assign(motivo=motivo[bad]).reset_index(drop=True)
    valid = df.loc[~bad].copy()
    valid["_canal"] = valid["canal"].map(canal_code)
    valid["_produto"] = valid["produto"].map(produto_code)
    return valid.reset_index(drop=True), rejected
