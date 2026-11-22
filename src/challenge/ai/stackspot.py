"""Provedor corporativo: agente StackSpot AI via Agents API (REST, sem streaming).

Autenticação: OAuth2 *client credentials* em ``{auth_url}/{realm}/oidc/oauth/token``.
Inferência: ``POST {base_url}/v1/agent/{agent_id}/chat``. As configurações do agente no portal
(LLM, instruções, Knowledge Sources) continuam valendo; por isso recomenda-se um agente dedicado,
sem Knowledge Sources. O prompt de sistema do domínio segue junto do ``user_prompt``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from challenge.ai.base import HttpLLMClient, LLMAuthError, LLMError, RetryableLLMError

DEFAULT_AUTH_URL = "https://idm.stackspot.com"
DEFAULT_URL = "https://genai-inference-app.stackspot.com"
_TOKEN_SKEW_S = 60.0


class TokenProvider:
    """Obtém e renova o *access token* (thread-safe, com margem de expiração)."""

    def __init__(
        self,
        http: httpx.Client,
        token_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Configura o provedor de token."""
        self._http = http
        self._url = token_url
        self._form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0
        self.fetches = 0

    def get(self) -> str:
        """Devolve um token válido, renovando se necessário."""
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            self._token, self._expires_at = self._fetch()
            return self._token

    def invalidate(self) -> None:
        """Descarta o token atual (ex.: após HTTP 401)."""
        with self._lock:
            self._token, self._expires_at = "", 0.0

    def _fetch(self) -> tuple[str, float]:
        try:
            response = self._http.post(self._url, data=self._form)
        except httpx.TransportError as exc:
            raise RetryableLLMError(f"transporte (token): {exc}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise RetryableLLMError(f"HTTP {response.status_code} (token)")
        if response.status_code >= 400:
            raise LLMError(f"Falha de autenticação StackSpot: HTTP {response.status_code}")
        try:
            body = response.json()
            token = str(body["access_token"])
            ttl = float(body.get("expires_in", 300))
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("Resposta de token StackSpot inesperada") from exc
        self.fetches += 1
        return token, time.monotonic() + max(ttl - _TOKEN_SKEW_S, 0.0)


class StackSpotClient(HttpLLMClient):
    """Cliente do agente StackSpot AI (``model`` guarda o ``agent_id``)."""

    name = "stackspot"

    def __init__(
        self,
        *,
        agent_id: str,
        realm: str,
        client_id: str,
        client_secret: str,
        base_url: str = DEFAULT_URL,
        auth_url: str = DEFAULT_AUTH_URL,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_base_delay_s: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Cria o cliente e o gerenciador de token."""
        super().__init__(
            model=agent_id,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_base_delay_s=retry_base_delay_s,
            transport=transport,
        )
        token_url = f"{auth_url.rstrip('/')}/{realm}/oidc/oauth/token"
        self.tokens = TokenProvider(self._http, token_url, client_id, client_secret)

    def _complete_text(self, system: str, user: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.tokens.get()}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "streaming": False,
            "user_prompt": f"{system}\n\n---\n\n{user}",
            "stackspot_knowledge": False,
            "return_ks_in_response": False,
        }
        try:
            body = self._post(f"{self._base_url}/v1/agent/{self.model}/chat", payload, headers)
        except LLMAuthError as exc:
            self.tokens.invalidate()  # força novo token na próxima tentativa
            raise RetryableLLMError(str(exc)) from exc
        message = body.get("message")
        if not isinstance(message, str):
            raise LLMError(f"Formato StackSpot inesperado: {list(body)}")
        return message
