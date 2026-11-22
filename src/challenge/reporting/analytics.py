"""Análises gerenciais: Resumo, Tendências e Top Riscos (pré-processamento e Performer)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from challenge.domain.codes import CANAL_LABEL, PRODUTO_LABEL, STATUS_LABEL, TENSION_LABEL
from challenge.reporting.render import Section

CANAL_WEIGHT = {"B": 3.0, "O": 2.0, "R": 2.0, "S": 1.0, "Z": 1.0}
TENSION_WEIGHT = {"A": 3.0, "M": 2.0, "B": 1.0}
STATUS_WEIGHT = {"1": 1.5, "2": 1.0, "3": 0.0}
AGING_CAP_MONTHS = 5.0


def _dist(series: pd.Series, labels: dict[str, str], name: str) -> pd.DataFrame:
    counts = series.map(labels).value_counts()
    total = int(counts.sum()) or 1
    pct = (counts / total * 100).round(1)
    return pd.DataFrame({name: counts.index, "Qtd": counts.to_numpy(), "%": pct.to_numpy()})


def risk_scores(df: pd.DataFrame, ref_date: pd.Timestamp) -> pd.Series:
    """Score = (peso tensão × peso canal + envelhecimento) × peso status."""
    tens = df["_tensao"].map(TENSION_WEIGHT)
    canal = df["_canal"].map(CANAL_WEIGHT)
    status = df["_status"].map(STATUS_WEIGHT).fillna(0.0)
    age = ((ref_date - df["_data"]).dt.days.clip(lower=0) / 30).clip(upper=AGING_CAP_MONTHS)
    score: pd.Series = ((tens * canal + age) * status).round(2)
    return score


def _monthly(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(mes=df["_data"].dt.to_period("M").astype(str))


def trends_tables(df: pd.DataFrame) -> tuple[list[str], list[tuple[str, pd.DataFrame]]]:
    """Volume mensal, mix de tensão e variação por produto (último mês vs. anterior)."""
    m = _monthly(df)
    paragraphs: list[str] = []
    tables: list[tuple[str, pd.DataFrame]] = []
    vol = m.groupby("mes").size().rename("Qtd").reset_index().rename(columns={"mes": "Mês"})
    vol["Var. m/m %"] = (vol["Qtd"].pct_change() * 100).round(1)
    tables.append(("Volume mensal de reclamações", vol))
    share = (
        pd.crosstab(m["mes"], m["_tensao"].map(TENSION_LABEL), normalize="index")
        .mul(100)
        .round(1)
        .reindex(columns=["Alta", "Média", "Baixa"], fill_value=0)
        .reset_index()
        .rename(columns={"mes": "Mês"})
    )
    tables.append(("Mix de tensão por mês (%)", share))
    months = sorted(m["mes"].unique())
    if len(months) >= 2:
        prev, last = months[-2], months[-1]
        piv = pd.crosstab(m["_produto"].map(PRODUTO_LABEL), m["mes"])
        t = pd.DataFrame(
            {"Produto": piv.index, "Mês anterior": piv[prev].values, "Último mês": piv[last].values}
        )
        t["Δ"] = t["Último mês"] - t["Mês anterior"]
        t["Δ %"] = ((t["Último mês"] / t["Mês anterior"].replace(0, np.nan) - 1) * 100).round(1)
        tables.append(
            (f"Variação por produto ({prev} → {last})", t.sort_values("Δ", ascending=False))
        )
        top = t.sort_values("Δ", ascending=False).iloc[0]
        if top["Δ"] > 0:
            paragraphs.append(
                f"- Maior crescimento: **{top['Produto']}** (+{int(top['Δ'])} no último mês)."
            )
        alta = share.set_index("Mês")["Alta"]
        paragraphs.append(
            f"- Participação de tensão Alta: {alta.iloc[-2]}% → {alta.iloc[-1]}% ({prev} → {last})."
        )
    else:
        paragraphs.append("Dados cobrem menos de 2 meses; variações m/m indisponíveis.")
    return paragraphs, tables


def build_preprocess_sections(
    all_df: pd.DataFrame,
    queue_df: pd.DataFrame,
    stats: dict[str, Any],
    top_n: int,
    ref_date: pd.Timestamp,
) -> list[Section]:
    """Relatório do pré-processamento: Resumo, Tendências, Top Riscos."""
    lidas, rej = stats["linhas_lidas"], stats["linhas_rejeitadas"]
    alta_pct = round((all_df["_tensao"].eq("A").mean() * 100), 1) if len(all_df) else 0.0
    ia = stats["ia"]
    resumo = Section(
        "1. Resumo",
        [
            f"- Linhas lidas: **{lidas}**; válidas: **{stats['linhas_validas']}**; "
            f"rejeitadas: **{rej}** ({round(rej / lidas * 100, 1) if lidas else 0}%).",
            f"- Fila de trabalho (_read): **{stats['linhas_na_fila_read']}** itens "
            f"({stats['linhas_resolvidas_excluidas']} resolvidos excluídos).",
            f"- Tensão Alta no total: **{alta_pct}%**.",
            f"- IA: {ia.get('chamadas_ia_ok', 0)} chamadas OK, {ia.get('fallbacks', 0)} fallbacks para regras, "
            f"{ia.get('cache_hits', 0)} acertos de cache; latência média {ia['latencia_media_ms']} ms "
            f"(p95 {ia['latencia_p95_ms']} ms).",
            f"- Duração total: {stats['duracao_s']} s.",
        ],
        [
            ("Fila por canal", _dist(queue_df["_canal"], CANAL_LABEL, "Canal")),
            ("Base por produto", _dist(all_df["_produto"], PRODUTO_LABEL, "Produto")),
            ("Base por status", _dist(all_df["_status"], STATUS_LABEL, "Status")),
            ("Base por tensão", _dist(all_df["_tensao"], TENSION_LABEL, "Tensão")),
            (
                "Origem da classificação de tensão",
                _dist(all_df["_origem"], {k: k for k in all_df["_origem"].unique()}, "Origem"),
            ),
        ],
    )
    if stats["rejeicoes_por_motivo"]:
        resumo.tables.append(
            (
                "Qualidade dos dados: rejeições",
                pd.DataFrame(
                    Counter(stats["rejeicoes_por_motivo"]).most_common(),
                    columns=["Motivo", "Qtd"],
                ),
            )
        )
    t_par, t_tabs = trends_tables(all_df)
    tendencias = Section("2. Tendências", t_par, t_tabs)
    return [resumo, tendencias, _risk_section(queue_df, top_n, ref_date)]


def _risk_section(queue_df: pd.DataFrame, top_n: int, ref_date: pd.Timestamp) -> Section:
    sec = Section("3. Top Riscos")
    if queue_df.empty:
        sec.paragraphs.append("Fila vazia: nenhum item em aberto.")
        return sec
    q = queue_df.copy()
    q["Score"] = risk_scores(q, ref_date)
    q["Dias"] = (ref_date - q["_data"]).dt.days.clip(lower=0)
    regulatorio = q[(q["_tensao"] == "A") & q["_canal"].isin(["B", "O"])]
    sec.paragraphs += [
        f"- **{len(regulatorio)}** itens de tensão Alta em canais regulatórios (Banco Central/Ouvidoria).",
        f"- **{int(((q['_tensao'] == 'A') & (q['_status'] == '1')).sum())}** itens Alta ainda **Abertos**.",
        "- Score = (peso tensão × peso canal + envelhecimento) × peso status (ver SPEC §6.4).",
    ]
    top = q.sort_values(["Score", "Dias"], ascending=False).head(top_n)
    sec.tables.append(
        (
            f"Top {top_n} itens por risco",
            pd.DataFrame(
                {
                    "ID": top["id"],
                    "Canal": top["_canal"].map(CANAL_LABEL),
                    "Produto": top["_produto"].map(PRODUTO_LABEL),
                    "Status": top["_status"].map(STATUS_LABEL),
                    "Tensão": top["_tensao"].map(TENSION_LABEL),
                    "Dias": top["Dias"],
                    "Score": top["Score"],
                }
            ),
        )
    )
    combo = (
        q.assign(Canal=q["_canal"].map(CANAL_LABEL), Produto=q["_produto"].map(PRODUTO_LABEL))
        .groupby(["Canal", "Produto"])["Score"]
        .agg(["sum", "size"])
        .rename(columns={"sum": "Score total", "size": "Itens"})
        .sort_values("Score total", ascending=False)
        .head(10)
        .round(1)
        .reset_index()
    )
    sec.tables.append(("Concentração de risco (canal × produto)", combo))
    terms = Counter(t.split("[")[0] for lst in q["_termos"] for t in lst)
    sec.tables.append(
        (
            "Termos de risco mais frequentes",
            pd.DataFrame(terms.most_common(10), columns=["Termo", "Ocorrências"]),
        )
    )
    return sec


def build_performer_sections(meta: pd.DataFrame, stats: dict[str, Any]) -> list[Section]:
    """Relatório de uma rodada do Performer: Resumo, Tendências (cobertura) e Top Riscos."""
    n = stats["linhas"]
    origens = ["POLITICA", "POLITICA_LEXICAL", "IA_GERADA", "FALHA"]
    por_origem = meta["_origem"].value_counts()
    cobertura = round(float(meta["_origem"].isin(origens[:2]).mean() * 100), 1) if n else 0.0
    destino = {
        "ok": "concluído (_ok)",
        "loop": f"pendências persistidas em {stats['arquivo_loop']} para novo ciclo",
        "nok": "ciclos esgotados: pendências enviadas a _nok (análise humana)",
    }[stats["status_final"]]
    resumo = Section(
        "1. Resumo",
        [
            f"- Lote **{stats['lote']}**, ciclo **{stats['ciclo']}**: {destino}.",
            f"- Linhas: **{n}**; respondidas: **{stats['respondidas']}**; "
            f"pendentes: **{stats['falhas']}**; cobertura por política: **{cobertura}%**.",
            f"- Confiança média da IA: {stats['confianca_media']}; latência média "
            f"{stats['latencia_media_ms']} ms (p95 {stats['latencia_p95_ms']} ms).",
            f"- Duração: {stats['duracao_s']} s.",
        ],
        [
            (
                "Origem da resposta",
                pd.DataFrame({"Origem": por_origem.index, "Qtd": por_origem.values}),
            )
        ],
    )
    prod = meta.assign(Produto=meta["_produto"].map(PRODUTO_LABEL))
    cov = pd.crosstab(prod["Produto"], prod["_origem"]).reindex(columns=origens, fill_value=0)
    cov["% política"] = ((cov["POLITICA"] + cov["POLITICA_LEXICAL"]) / cov.sum(axis=1) * 100).round(
        1
    )
    uso = meta.loc[meta["_politica"].ne(""), "_politica"].value_counts()
    tendencias = Section(
        "2. Tendências",
        ["Produtos com menor cobertura de política são candidatos a novas políticas aprovadas."],
        [
            ("Cobertura de política por produto", cov.reset_index().sort_values("% política")),
            (
                "Políticas mais utilizadas",
                pd.DataFrame({"Política": uso.index, "Usos": uso.values}),
            ),
        ],
    )
    gerada_alta = meta[(meta["_origem"] == "IA_GERADA") & (meta["_tensao"] == "A")]
    baixa_conf = meta[(meta["_origem"] == "IA_GERADA") & (meta["_conf"].fillna(1) < 0.7)]
    riscos = Section(
        "3. Top Riscos",
        [
            f"- **{len(gerada_alta)}** respostas geradas por IA (sem política) em casos de tensão Alta: "
            "revisão humana prioritária.",
            f"- **{len(baixa_conf)}** respostas geradas com confiança < 0.7.",
            f"- **{stats['falhas']}** itens sem resposta nesta rodada.",
        ],
    )
    cols = {"id": "ID", "_origem": "Origem", "_conf": "Confiança", "_erro": "Erro"}
    riscos.tables = [
        (
            "Tensão Alta sem política (revisar)",
            gerada_alta[list(cols)].rename(columns=cols).head(20),
        ),
        (
            "Pendentes (até 20)",
            meta[meta["_origem"] == "FALHA"][list(cols)].rename(columns=cols).head(20),
        ),
    ]
    return [resumo, tendencias, riscos]
