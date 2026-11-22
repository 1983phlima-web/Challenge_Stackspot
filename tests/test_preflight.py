from pathlib import Path

from challenge.ai.base import LLMError
from challenge.cli import main
from challenge.preflight import FAIL, PASS, WARN, run_checks
from conftest import ROOT, FakeLLM, make_settings, oracle_labels

DATA = ROOT / "tests" / "data" / "dataset_500.csv"


def _by_name(results):
    return {r.name: r for r in results}


def test_tudo_ok_com_ia_simulada(tmp_path):
    s = make_settings(tmp_path)
    (tmp_path / s.input_filename).write_text(
        "id,data_reclamacao,canal,texto_reclamacao,produto,status\n", encoding="utf-8"
    )
    res = _by_name(
        run_checks(s, FakeLLM(oracle_labels()), smoke=True, golden=True, rows=60, sample=DATA)
    )
    assert not [r for r in res.values() if r.status == FAIL], res
    assert res["ia:tensao"].status == PASS and res["ia:concorrencia"].status == PASS
    assert res["golden:tensao"].status == PASS and "100.0%" in res["golden:tensao"].detail
    assert "Alta→Baixa: 0/" in res["golden:tensao"].detail
    assert res["smoke"].status in {PASS, WARN}
    assert res["golden:rejeicoes"].detail.startswith("40")


def test_regras_ausentes_falha(tmp_path):
    s = make_settings(tmp_path, rules_file=tmp_path / "nao_existe.txt")
    res = _by_name(run_checks(s, None))
    assert res["arquivos"].status == FAIL


def test_ia_devolvendo_lixo_falha(tmp_path):
    class Garbage(FakeLLM):
        def complete_json(self, system, user):
            raise LLMError("sem JSON")

    res = _by_name(run_checks(make_settings(tmp_path), Garbage(), smoke=True))
    assert res["ia:tensao"].status == FAIL and res["smoke"].status == WARN  # smoke ignorado


def test_limite_de_requisicoes_gera_aviso(tmp_path):
    class Limited(FakeLLM):
        def complete_json(self, system, user):
            if "concorrência" in user:
                raise LLMError("HTTP 429")
            return super().complete_json(system, user)

    res = _by_name(run_checks(make_settings(tmp_path, llm_workers=2), Limited()))
    assert res["ia:concorrencia"].status == FAIL  # todas as chamadas concorrentes falharam


def test_golden_detecta_ia_que_erra_a_tensao(tmp_path):
    class AlwaysLow(FakeLLM):
        def complete_json(self, system, user):
            if "TENSÃO" in system:
                return {"tensao": "Baixa", "confianca": 0.9, "justificativa": "x"}
            return super().complete_json(system, user)

    res = _by_name(run_checks(make_settings(tmp_path), AlwaysLow(), golden=True, sample=DATA))
    # o piso de regras (Procon, golpe) corrige parte; ainda assim há divergências em Média/Alta
    assert res["golden:tensao"].status == FAIL and "→" in res["golden:tensao"].detail
    assert res["golden:canal+produto+status"].status == PASS  # parte determinística segue exata


def test_cli_check_retorna_1_com_falha_e_0_sem(tmp_path, capsys):
    cfg = tmp_path / "s.yaml"
    base = f"base_dir: '{tmp_path}'\nllm_provider: none\n"
    cfg.write_text(
        base
        + f"rules_file: '{ROOT / 'config' / 'motor_regras.txt'}'\npolicy_file: '{ROOT / 'config' / 'politica.txt'}'\n",
        encoding="utf-8",
    )
    assert main(["check", "--config", str(cfg)]) == 0
    assert "Resumo:" in capsys.readouterr().out
    cfg.write_text(
        base
        + f"rules_file: '{tmp_path / 'x.txt'}'\npolicy_file: '{ROOT / 'config' / 'politica.txt'}'\n",
        encoding="utf-8",
    )
    assert main(["check", "--config", str(cfg)]) == 1
    assert list(Path(tmp_path / "Logs").glob("preflight_*.json"))


def test_golden_com_limite_de_linhas(tmp_path):
    res = _by_name(
        run_checks(
            make_settings(tmp_path),
            FakeLLM(oracle_labels()),
            golden=True,
            sample=DATA,
            golden_rows=100,
        )
    )
    assert res["golden:tensao"].status == PASS and "100.0%" in res["golden:tensao"].detail


def test_golden_somente_regras_passa_o_limiar(tmp_path):
    res = _by_name(run_checks(make_settings(tmp_path), None, golden=True, sample=DATA))
    assert res["golden:tensao"].status == PASS, res["golden:tensao"].detail
