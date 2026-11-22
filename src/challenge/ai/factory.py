"""Fábrica de provedores de IA (importação sob demanda: cada pacote contém só o seu provedor)."""

from __future__ import annotations

import importlib
import os
from types import ModuleType

from challenge.ai.base import LLMClient
from challenge.config import ConfigError, Settings


def _load(provider: str) -> ModuleType:
    try:
        return importlib.import_module(f"challenge.ai.{provider}")
    except ModuleNotFoundError as exc:
        raise ConfigError(f"Provedor {provider!r} não está incluído neste pacote") from exc


def build_llm(settings: Settings) -> LLMClient | None:
    """Instancia o provedor configurado; ``None`` quando ``llm_provider == 'none'``."""
    provider = settings.llm_provider
    if provider == "none":
        return None
    module = _load(provider)
    client: LLMClient
    if provider == "ollama":
        client = module.OllamaClient(
            model=settings.llm_model or module.DEFAULT_MODEL,
            base_url=settings.llm_base_url or module.DEFAULT_URL,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
            retry_base_delay_s=settings.llm_retry_base_delay_s,
        )
        return client

    client_id = os.environ.get("STACKSPOT_CLIENT_ID", "")
    client_secret = os.environ.get("STACKSPOT_CLIENT_SECRET", "")
    if not (client_id and client_secret):
        raise ConfigError("Defina STACKSPOT_CLIENT_ID e STACKSPOT_CLIENT_SECRET no ambiente")
    client = module.StackSpotClient(
        agent_id=settings.stackspot_agent_id,
        realm=settings.stackspot_realm,
        client_id=client_id,
        client_secret=client_secret,
        base_url=settings.llm_base_url or module.DEFAULT_URL,
        auth_url=settings.stackspot_auth_url or module.DEFAULT_AUTH_URL,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        retry_base_delay_s=settings.llm_retry_base_delay_s,
    )
    return client
