"""Contrato de provedores de IA e utilitários de resiliência."""

from __future__ import annotations

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import httpx

T = TypeVar("T")
_log = logging.getLogger("challenge.ai")


class LLMError(Exception):
    """Falha definitiva na chamada ao modelo."""


class LLMAuthError(LLMError):
    """Credencial inválida/expirada (HTTP 401)."""


class RetryableLLMError(LLMError):
    """Falha transitória (rede, 429, 5xx, JSON inválido) elegível a nova tentativa."""


class LLMClient(Protocol):
    """Interface mínima exigida pelo domínio."""

    name: str

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Envia prompts e devolve um objeto JSON."""
        ...

    def close(self) -> None:
        """Libera recursos."""
        ...


def extract_json(raw: str) -> dict[str, Any]:
    """Extrai um objeto JSON de uma resposta (tolera cercas de markdown e texto extra)."""
    text = raw.strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMError(f"Resposta sem JSON válido: {text[:120]!r}")


def call_with_retries(fn: Callable[[], T], *, retries: int, base_delay: float = 1.0) -> T:
    """Executa ``fn`` com backoff exponencial + jitter para erros transitórios."""
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except RetryableLLMError as exc:
            if attempt == retries:
                raise LLMError(f"Falha após {retries} tentativas: {exc}") from exc
            delay = base_delay * 2 ** (attempt - 1) + random.uniform(0, 0.25)
            _log.warning("Tentativa %d/%d falhou (%s); nova em %.1fs", attempt, retries, exc, delay)
            time.sleep(delay)
    raise LLMError("retries deve ser >= 1")  # pragma: no cover


class HttpLLMClient(ABC):
    """Base para provedores HTTP (httpx síncrono, thread-safe)."""

    name = "http"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_s: float,
        max_retries: int,
        retry_base_delay_s: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Configura o cliente HTTP."""
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._retry_base_delay = retry_base_delay_s
        self._max_retries = max_retries
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        """Fecha o pool de conexões."""
        self._http.close()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Chama o modelo com retentativas e devolve o JSON da resposta."""
        return call_with_retries(
            lambda: self._once(system, user),
            retries=self._max_retries,
            base_delay=self._retry_base_delay,
        )

    def _once(self, system: str, user: str) -> dict[str, Any]:
        raw = self._complete_text(system, user)
        try:
            return extract_json(raw)
        except LLMError as exc:
            raise RetryableLLMError(str(exc)) from exc

    def _post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._http.post(url, json=payload, headers=headers)
        except httpx.TransportError as exc:
            raise RetryableLLMError(f"transporte: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableLLMError(f"HTTP {response.status_code}")
        if response.status_code == 401:
            raise LLMAuthError("HTTP 401: credencial inválida ou expirada")
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise RetryableLLMError("corpo não é JSON") from exc
        if not isinstance(body, dict):
            raise LLMError("corpo inesperado")
        return body

    @abstractmethod
    def _complete_text(self, system: str, user: str) -> str:
        """Devolve o texto bruto gerado pelo modelo."""
