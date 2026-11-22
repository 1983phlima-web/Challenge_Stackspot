"""Ciclo _loop do Performer sobre a fila de 500 casos."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from challenge.domain.codes import PRODUTO_LABEL, FilaCode
from challenge.performer.pipeline import PerformerPipeline
from challenge.preprocess.pipeline import PreprocessPipeline
from challenge.rules.policy import PolicyBook
from conftest import ROOT, FakeLLM, FlakyLLM, make_settings, oracle_labels
from dataset_factory import HEADER, build_cases, write_dataset

COLS = [*HEADER, "fila"]


def _read(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture
def lote(tmp_path):
    """Pré-processa 500 casos e devolve a fila + ids sem política aderente (falháveis)."""
    write_dataset(build_cases(), tmp_path / "dataset_challenge.csv")
    settings = make_settings(tmp_path)
    res = PreprocessPipeline(settings, FakeLLM(oracle_labels()), "pre").run()
    queue = _read(res.read_path)
    book = PolicyBook.from_file(settings.policy_file)
    sem_politica = [
        r.id
        for r in queue.itertuples()
        if not book.find_candidates(r.texto_reclamacao, FilaCode.parse(r.fila))
    ]
    assert len(sem_politica) >= 30
    return SimpleNamespace(
        settings=settings, queue=queue, ids=list(queue["id"]), failable=sem_politica
    )


def test_todos_respondidos_gera_somente_ok(lote):
    [out] = PerformerPipeline(lote.settings, FakeLLM(), "p").run()
    assert out.status == "ok" and out.loop_path is None
    ok = _read(out.ok_path)
    assert list(ok["id"]) == lote.ids  # ordem da fila preservada
    assert list(ok.columns) == [*COLS, "Resposta"] and (ok["Resposta"] != "").all()
    out_dir = lote.settings.output_dir
    assert not list(out_dir.glob("*_read.csv")) and not list(out_dir.glob("*_loop.csv"))
    assert not list(out_dir.glob("*.state.json")) and not list(out_dir.glob("*.lock"))


def test_politica_vai_verbatim_e_geradas_sao_marcadas(lote):
    [out] = PerformerPipeline(lote.settings, FakeLLM(), "p").run()
    ok = _read(out.ok_path).set_index("id")
    book = PolicyBook.from_file(lote.settings.policy_file)
    verbatim = gerada = 0
    for r in lote.queue.itertuples():
        fila = FilaCode.parse(r.fila)
        candidates = book.find_candidates(r.texto_reclamacao, fila)
        resposta = ok.loc[r.id, "Resposta"]
        if candidates:  # o dublê escolhe a 1ª candidata: texto aprovado, sem reescrita
            policy = candidates[0].policy
            assert resposta == policy.render(r.id, PRODUTO_LABEL[fila.produto])
            assert f"protocolo {r.id}" in resposta
            verbatim += 1
        else:
            assert resposta.startswith("[Sugestão IA - revisar]")
            gerada += 1
    assert verbatim > 100 and gerada >= 30


def test_segunda_rodada_recupera_pendentes(lote):
    fail = set(lote.failable[:25])
    llm = FlakyLLM(FakeLLM(), fail, fail_times=1)  # falha só na 1ª tentativa
    [out] = PerformerPipeline(lote.settings, llm, "p").run()
    assert out.status == "ok" and out.stats["ciclo"] == 2
    assert list(_read(out.ok_path)["id"]) == lote.ids
    stats = {
        int(p.stem.rsplit("_c", 1)[1]): json.loads(p.read_text(encoding="utf-8"))
        for p in lote.settings.logs_dir.glob("stats_performer_*_c*.json")
    }
    assert stats[1]["falhas"] == 25 and stats[1]["status_final"] == "loop"
    assert stats[2]["falhas"] == 0 and stats[2]["linhas"] == 25
    assert not list(lote.settings.output_dir.glob("*_loop.csv"))


def test_pendentes_persistem_em_loop_e_fecham_no_proximo_ciclo(lote):
    fail = set(lote.failable[:10])
    llm = FlakyLLM(FakeLLM(), fail, fail_times=None)  # falha sempre
    [out] = PerformerPipeline(lote.settings, llm, "p").run()
    assert out.status == "loop" and out.stats["ciclo"] == 2

    ok, loop = _read(out.ok_path), _read(out.loop_path)
    assert set(ok["id"]) == set(lote.ids) - fail and len(ok) == len(lote.ids) - 10
    assert set(loop["id"]) == fail and list(loop.columns) == COLS  # sem coluna Resposta
    state = json.loads(
        next(lote.settings.output_dir.glob("*.state.json")).read_text(encoding="utf-8")
    )
    assert state["cycles"] == 2

    llm.healed = True  # novo ciclo (próxima execução agendada)
    [out2] = PerformerPipeline(lote.settings, llm, "p2").run()
    assert out2.status == "ok" and out2.stats["linhas"] == 10
    assert list(_read(out2.ok_path)["id"]) == lote.ids  # ordem original restaurada
    assert not list(lote.settings.output_dir.glob("*_loop.csv"))
    assert not list(lote.settings.output_dir.glob("*.state.json"))


def test_ciclos_esgotados_escalam_para_nok(tmp_path):
    write_dataset(build_cases(), tmp_path / "dataset_challenge.csv")
    settings = make_settings(tmp_path, max_loop_cycles=2, loop_rounds_per_run=2)
    res = PreprocessPipeline(settings, FakeLLM(oracle_labels()), "pre").run()
    queue = _read(res.read_path)
    book = PolicyBook.from_file(settings.policy_file)
    fail = {
        r.id
        for r in queue.itertuples()
        if not book.find_candidates(r.texto_reclamacao, FilaCode.parse(r.fila))
    }
    llm = FlakyLLM(FakeLLM(), fail, fail_times=None)
    [out] = PerformerPipeline(settings, llm, "p").run()
    assert out.status == "nok" and out.loop_path is None
    nok = _read(out.nok_path)
    assert set(nok["id"]) == fail and list(nok.columns) == COLS
    assert set(_read(out.ok_path)["id"]) == set(queue["id"]) - fail
    assert not list(settings.output_dir.glob("*_loop.csv"))


def test_cli_retorna_1_quando_ha_pendencias(tmp_path):
    from challenge.cli import main

    write_dataset(build_cases(), tmp_path / "dataset_challenge.csv")
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        f"base_dir: '{tmp_path}'\nrules_file: '{ROOT / 'config' / 'motor_regras.txt'}'\n"
        f"policy_file: '{ROOT / 'config' / 'politica.txt'}'\nllm_provider: none\n"
        "loop_retry_delay_s: 0\nloop_rounds_per_run: 2\n",
        encoding="utf-8",
    )
    code = main(["run-all", "--config", str(cfg)])
    assert code == 1  # sem IA, itens sem política ficam em _loop
    assert list((tmp_path / "Output").glob("*_loop.csv")) and list(
        (tmp_path / "Output").glob("*_ok.csv")
    )
