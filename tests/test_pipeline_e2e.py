import pandas as pd

from challenge.performer.pipeline import PerformerPipeline
from challenge.preprocess.pipeline import PreprocessPipeline

CSV = (
    "id,data_reclamacao,canal,texto_reclamacao,produto,status\n"
    'REC-1,2025-11-03,Ouvidoria,"Estou desesperado com a demora vocês estão me cobrando juros além do que está em contrato.",Empréstimo,Aberta\n'
    'REC-2,2025-11-04,SAC,"Gostaria de saber sobre meu resgate.",Investimentos,Em análise\n'
    'REC-3,2025-11-05,Ouvidoria,"Vou ao Procon por cobrança indevida.",Cartão de Crédito,Aberta\n'
    'REC-4,2025-11-06,Chat,"Obrigado, dúvida sobre apólice.",Consórcio,Resolvida\n'
    'REC-5,2025-11-07,Ouvidoria,"Teste",Seguros,Cancelada\n'
    'REC-1,2025-11-08,SAC,"Duplicado",Seguros,Aberta\n'
)


def _prepare(settings):
    settings.base_dir.mkdir(parents=True, exist_ok=True)
    settings.input_path.write_text(CSV, encoding="utf-8")


def test_preprocess_sem_ia(settings):
    _prepare(settings)
    res = PreprocessPipeline(settings, None, "t1").run()

    fila = pd.read_csv(res.fila_path, dtype=str)
    assert list(fila.columns)[-1] == "fila" and len(fila) == 4  # 2 rejeitadas
    assert res.fila_path.parent.name == "Fila" and res.rejected_path is not None
    queue = pd.read_csv(res.read_path, dtype=str)
    assert "REC-4" not in set(queue["id"])  # Resolvida excluída
    # Ouvidoria (maior fila) primeiro; sem IA o piso "procon" torna REC-3 Alta e REC-1 Média
    assert list(queue["id"])[:2] == ["REC-3", "REC-1"]
    assert queue.loc[0, "fila"] == "OCAR1A"


def test_performer_sem_ia_gera_loop_com_pendentes(settings):
    _prepare(settings)
    res = PreprocessPipeline(settings, None, "t1").run()
    [outcome] = PerformerPipeline(settings, None, "t1").run()
    # REC-2 não tem política aderente e não há IA: fica em _loop; REC-3/REC-1 vão para _ok
    assert outcome.status == "loop"
    assert not res.read_path.exists()
    ok = pd.read_csv(outcome.ok_path, dtype=str, keep_default_na=False)
    loop = pd.read_csv(outcome.loop_path, dtype=str, keep_default_na=False)
    assert list(ok["id"]) == ["REC-3", "REC-1"] and (ok["Resposta"] != "").all()
    assert list(loop["id"]) == ["REC-2"] and "Resposta" not in loop.columns


def test_fluxo_completo_com_ia(settings, fake_llm):
    _prepare(settings)
    res = PreprocessPipeline(settings, fake_llm, "t2").run()
    [outcome] = PerformerPipeline(settings, fake_llm, "t2").run()
    assert outcome.status == "ok"
    assert outcome.ok_path.name == res.read_path.name.replace("_read", "_ok")
    out = pd.read_csv(outcome.ok_path, dtype=str, keep_default_na=False)
    assert list(out.columns)[-1] == "Resposta" and (out["Resposta"] != "").all()
    assert "REC-1" in out.loc[0, "Resposta"]  # política verbatim com protocolo
    assert any(settings.reports_dir.glob("relatorio_*.html"))
    assert any(settings.logs_dir.glob("stats_*.json"))


def test_arquivo_ilegivel_vira_nok(settings):
    settings.output_dir.mkdir(parents=True)
    bad = settings.output_dir / "processadas_x_read.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    [outcome] = PerformerPipeline(settings, None, "t3").run()
    assert outcome.status == "nok"
    assert (settings.output_dir / "processadas_x_nok.csv").exists() and not bad.exists()


def test_lock_ativo_ignora_arquivo(settings):
    settings.output_dir.mkdir(parents=True)
    path = settings.output_dir / "processadas_y_read.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    (settings.output_dir / (path.name + ".lock")).write_text("123")
    [outcome] = PerformerPipeline(settings, None, "t4").run()
    assert outcome.status == "skipped" and path.exists()
