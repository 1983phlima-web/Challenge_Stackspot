import json

import httpx
import pytest

from challenge.ai.base import LLMError
from challenge.ai.factory import build_llm
from challenge.ai.stackspot import StackSpotClient
from challenge.config import ConfigError, Settings


def _client(handler):
    return StackSpotClient(
        agent_id="AG1",
        realm="meu-realm",
        client_id="cid",
        client_secret="sec",
        base_url="https://inf",
        auth_url="https://idm",
        max_retries=3,
        retry_base_delay_s=0,
        transport=httpx.MockTransport(handler),
    )


class FakeStackSpot:
    def __init__(self, chat_replies=None):
        self.token_calls, self.chat_calls, self.chat_auth, self.bodies = 0, 0, [], []
        self.chat_replies = list(chat_replies or [])

    def __call__(self, request):
        if request.url.path == "/meu-realm/oidc/oauth/token":
            self.token_calls += 1
            form = request.read().decode()
            assert "grant_type=client_credentials" in form and "client_id=cid" in form
            return httpx.Response(
                200, json={"access_token": f"tok{self.token_calls}", "expires_in": 3600}
            )
        assert request.url.path == "/v1/agent/AG1/chat"
        self.chat_calls += 1
        self.chat_auth.append(request.headers["Authorization"])
        self.bodies.append(json.loads(request.read()))
        if self.chat_replies:
            reply = self.chat_replies.pop(0)
            if reply is not None:
                return reply
        return httpx.Response(
            200, json={"message": '```json\n{"tensao": "Média"}\n```', "stop_reason": "stop"}
        )


def test_payload_autenticacao_e_cache_de_token():
    api = FakeStackSpot()
    client = _client(api)
    assert client.complete_json("SYS", "USR") == {"tensao": "Média"}
    client.complete_json("SYS", "USR")
    assert api.token_calls == 1 and api.chat_auth == ["Bearer tok1", "Bearer tok1"]
    body = api.bodies[0]
    assert body["streaming"] is False and body["stackspot_knowledge"] is False
    assert "SYS" in body["user_prompt"] and "USR" in body["user_prompt"]


def test_401_renova_token_e_repete():
    api = FakeStackSpot([httpx.Response(401)])
    assert _client(api).complete_json("s", "u") == {"tensao": "Média"}
    assert api.token_calls == 2 and api.chat_auth == ["Bearer tok1", "Bearer tok2"]


def test_429_e_5xx_sao_retentados():
    api = FakeStackSpot([httpx.Response(429), httpx.Response(502)])
    assert _client(api).complete_json("s", "u") == {"tensao": "Média"}
    assert api.chat_calls == 3


def test_credencial_invalida_nao_e_retentada():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(LLMError, match="autenticação"):
        _client(handler).complete_json("s", "u")
    assert calls == ["/meu-realm/oidc/oauth/token"]


def test_mensagem_ausente_e_erro():
    api = FakeStackSpot([httpx.Response(200, json={"outro": 1})])
    with pytest.raises(LLMError, match="inesperado"):
        _client(api).complete_json("s", "u")


def test_factory_exige_credenciais_no_ambiente(tmp_path, monkeypatch):
    s = Settings(
        base_dir=tmp_path, llm_provider="stackspot", stackspot_realm="r", stackspot_agent_id="a"
    )
    monkeypatch.delenv("STACKSPOT_CLIENT_ID", raising=False)
    with pytest.raises(ConfigError, match="STACKSPOT_CLIENT_ID"):
        build_llm(s)
    monkeypatch.setenv("STACKSPOT_CLIENT_ID", "id")
    monkeypatch.setenv("STACKSPOT_CLIENT_SECRET", "sec")
    assert isinstance(build_llm(s), StackSpotClient)


def test_check_sem_credenciais_reporta_fail(tmp_path, monkeypatch, capsys):
    from challenge.cli import main

    monkeypatch.delenv("STACKSPOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("STACKSPOT_CLIENT_SECRET", raising=False)
    cfg = tmp_path / "s.yaml"
    cfg.write_text(
        f"base_dir: '{tmp_path}'\nllm_provider: stackspot\nstackspot_realm: r\nstackspot_agent_id: a\n",
        encoding="utf-8",
    )
    assert main(["check", "--config", str(cfg)]) == 1
    assert "STACKSPOT_CLIENT_ID" in capsys.readouterr().out
