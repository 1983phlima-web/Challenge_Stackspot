import pytest

from challenge.config import ConfigError, Settings


def test_defaults_e_yaml(tmp_path, monkeypatch):
    cfg = tmp_path / "s.yaml"
    cfg.write_text("llm_provider: none\nllm_workers: 2\nmask_pii: false\n", encoding="utf-8")
    s = Settings.load(cfg)
    assert (s.llm_provider, s.llm_workers, s.mask_pii) == ("none", 2, False)
    monkeypatch.setenv("CHALLENGE_LLM_WORKERS", "7")
    assert Settings.load(cfg).llm_workers == 7
    assert Settings.load(cfg, llm_workers=9).llm_workers == 9  # override explícito vence


def test_validacoes(tmp_path):
    cfg = tmp_path / "s.yaml"
    cfg.write_text("llm_provider: xpto\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="llm_provider"):
        Settings.load(cfg)
    cfg.write_text("chave_desconhecida: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="desconhecidas"):
        Settings.load(cfg)
    cfg.write_text("llm_provider: stackspot\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="stackspot_realm"):
        Settings.load(cfg)
    cfg.write_text("max_loop_cycles: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="max_loop_cycles"):
        Settings.load(cfg)


def test_provedor_ausente_no_pacote_da_erro_claro(tmp_path, monkeypatch):
    import importlib

    from challenge.ai.factory import build_llm

    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "challenge.ai.ollama":
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    with pytest.raises(ConfigError, match="não está incluído"):
        build_llm(Settings(base_dir=tmp_path, llm_provider="ollama"))
