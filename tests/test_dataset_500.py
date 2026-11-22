"""Validação com 500 casos válidos (500 textos distintos) + 40 inválidos, com gabarito independente."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from challenge.preprocess.pipeline import PreprocessPipeline
from challenge.text import normalize
from conftest import ROOT, FakeLLM, make_settings, oracle_labels
from dataset_factory import HEADER, build_cases, write_dataset

DATA = ROOT / "tests" / "data"
PII = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|@exemplo\.com\.br|\(11\) 9\d{4}-\d{4}")


@pytest.fixture(scope="module")
def cases():
    return build_cases()


@pytest.fixture(scope="module", params=["rules", "ai"])
def run(request, tmp_path_factory, cases):
    base = tmp_path_factory.mktemp(request.param)
    write_dataset(cases, base / "dataset_challenge.csv")
    settings = make_settings(base)
    llm = FakeLLM(oracle_labels()) if request.param == "ai" else None
    result = PreprocessPipeline(settings, llm, "t500").run()
    return SimpleNamespace(res=result, settings=settings, llm=llm, mode=request.param)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_arquivos_versionados_sao_reproduziveis(tmp_path, cases):
    write_dataset(cases, tmp_path / "d.csv", tmp_path / "g.csv")
    assert (tmp_path / "d.csv").read_text(encoding="utf-8") == (DATA / "dataset_500.csv").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "g.csv").read_text(encoding="utf-8") == (
        DATA / "dataset_500_expected.csv"
    ).read_text(encoding="utf-8")


def test_500_textos_distintos_entre_as_linhas_validas(cases):
    texts = [c.row[3].strip() for c in cases if not c.reject_reasons]
    assert len(texts) == 500 and len(set(texts)) == 500
    assert len({normalize(t) for t in texts}) == 500


def test_contagens(run):
    stats = run.res.stats
    assert (stats["linhas_lidas"], stats["linhas_rejeitadas"], stats["linhas_validas"]) == (
        540,
        40,
        500,
    )
    assert stats["textos_unicos"] == 500


def test_rejeicoes_com_motivos_corretos(run, cases):
    expected = [c.reject_reasons for c in cases if c.reject_reasons]
    got = _read(run.res.rejected_path)
    assert list(got["motivo"]) == expected and list(got.columns) == [*HEADER, "motivo"]


def test_fila_de_cada_linha_valida(run, cases):
    fila = _read(run.res.fila_path)
    valid = [c for c in cases if not c.reject_reasons]
    assert list(fila.columns) == [*HEADER, "fila"]
    assert list(fila["id"]) == [c.row[0] for c in valid]
    assert list(fila["texto_reclamacao"]) == [c.row[3].strip() for c in valid]
    got, want = list(fila["fila"]), [c.expected_fila for c in valid]
    assert [g[:5] for g in got] == [w[:5] for w in want]  # canal+produto+status: sempre exatos
    hits = sum(g == w for g, w in zip(got, want, strict=True))
    if run.mode == "ai":  # modelo "perfeito" (oráculo): valida o fluxo
        assert got == want
    else:  # somente Motor de Regras de exemplo: piso de regressão
        assert hits / len(want) >= 0.95
        assert not [1 for g, w in zip(got, want, strict=True) if w[5] == "A" and g[5] == "B"]


def test_fila_de_trabalho_ordenada_por_verificador_independente(run):
    fila = _read(run.res.fila_path)
    queue = fila[fila["fila"].str[4] != "3"]  # sem Resolvidas
    volume = queue["fila"].str[0].value_counts().to_dict()

    def key(row):
        f = row.fila
        return (
            -volume[f[0]],
            "BORSZ".index(f[0]),
            "AMB".index(f[5]),
            f[4],
            row.data_reclamacao,
            row.id,
        )

    expected_ids = [r.id for r in sorted(queue.itertuples(), key=key)]
    got = _read(run.res.read_path)
    assert list(got["id"]) == expected_ids
    assert not got["fila"].str[4].eq("3").any() and len(got) == run.res.stats["linhas_na_fila_read"]
    assert run.res.read_path.parent == run.settings.output_dir
    assert run.res.read_path.name == run.res.fila_path.stem + "_read.csv"


def test_canais_agrupados_do_maior_para_o_menor(run):
    letters = list(_read(run.res.read_path)["fila"].str[0])
    blocks = [letters[0]]
    for letter in letters[1:]:
        if letter != blocks[-1]:
            blocks.append(letter)
    assert len(blocks) == len(set(blocks)), "canal reaparece fora do seu bloco"
    sizes = [letters.count(b) for b in blocks]
    assert sizes == sorted(sizes, reverse=True)


def test_dentro_do_canal_alta_antes_de_media_antes_de_baixa(run):
    got = _read(run.res.read_path)
    for _, grp in got.groupby(got["fila"].str[0], sort=False):
        order = [("AMB".index(f[5]), f[4]) for f in grp["fila"]]
        assert order == sorted(order)


def test_auditoria_completa(run):
    [audit] = run.settings.logs_dir.glob("audit_preprocess_*.jsonl")
    events = [json.loads(line)["event"] for line in audit.read_text(encoding="utf-8").splitlines()]
    assert events.count("row_rejected") == 40 and events.count("row_classified") == 500
    assert events.count("row_queued") == run.res.stats["linhas_na_fila_read"]


def test_relatorio_gerencial(run):
    html = next(run.settings.reports_dir.glob("relatorio_preprocessamento_*.html")).read_text(
        encoding="utf-8"
    )
    for title in ("Resumo", "Tendências", "Top Riscos"):
        assert title in html


def test_ia_chama_uma_vez_por_texto_unico_e_mascara_pii(run):
    if run.mode != "ai":
        pytest.skip("somente com IA")
    assert run.llm.calls == 500
    joined = "\n".join(run.llm.prompts)
    assert not PII.search(joined)
    assert "[CPF]" in joined or "[EMAIL]" in joined or "[TELEFONE]" in joined
