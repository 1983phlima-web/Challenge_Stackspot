"""Carga e validação de configuração (YAML + variáveis de ambiente ``CHALLENGE_*``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

ENV_PREFIX = "CHALLENGE_"
PROVIDERS = frozenset({"ollama", "stackspot", "none"})


class ConfigError(ValueError):
    """Configuração inválida ou incompleta."""


@dataclass(frozen=True)
class Settings:
    """Parâmetros imutáveis de execução."""

    # Pastas e arquivos
    base_dir: Path = Path(r"C:\Challenge")
    input_filename: str = "dataset_challenge.csv"
    fila_subdir: str = "Fila"
    output_subdir: str = "Output"
    logs_subdir: str = "Logs"
    reports_subdir: str = "Relatorios"
    rules_file: Path = Path("motor_regras.txt")
    policy_file: Path = Path("politica.txt")

    # IA (ollama | stackspot | none)
    llm_provider: str = "ollama"
    llm_model: str = ""  # Ollama: nome do modelo
    llm_base_url: str = ""  # vazio = padrão do provedor
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_retry_base_delay_s: float = 1.0
    llm_workers: int = 4
    mask_pii: bool = True

    # StackSpot AI (credenciais SOMENTE por variável de ambiente)
    stackspot_realm: str = ""
    stackspot_agent_id: str = ""
    stackspot_auth_url: str = ""  # vazio = https://idm.stackspot.com

    # Performer
    min_policy_confidence: float = 0.6
    policy_lexical_threshold: float = 2.0
    policy_top_k: int = 5
    mark_generated: bool = True
    loop_rounds_per_run: int = 2  # 1ª rodada + retentativas dos pendentes na mesma execução
    loop_retry_delay_s: float = 5.0
    max_loop_cycles: int = 5  # rodadas totais por arquivo antes de escalar para _nok

    # Relatórios e logs
    top_risks: int = 15
    log_level: str = "INFO"

    @property
    def input_path(self) -> Path:
        """Caminho do CSV de entrada."""
        return self.base_dir / self.input_filename

    @property
    def fila_dir(self) -> Path:
        """Pasta da base pré-processada."""
        return self.base_dir / self.fila_subdir

    @property
    def output_dir(self) -> Path:
        """Pasta dos arquivos ``_read``/``_loop``/``_ok``/``_nok``."""
        return self.base_dir / self.output_subdir

    @property
    def logs_dir(self) -> Path:
        """Pasta de logs analíticos e estatísticos."""
        return self.base_dir / self.logs_subdir

    @property
    def reports_dir(self) -> Path:
        """Pasta dos relatórios gerenciais."""
        return self.base_dir / self.reports_subdir

    def validate(self) -> None:
        """Valida invariantes da configuração."""
        if self.llm_provider not in PROVIDERS:
            raise ConfigError(f"llm_provider inválido: {self.llm_provider!r} ({sorted(PROVIDERS)})")
        positives = {
            "llm_workers": self.llm_workers,
            "llm_max_retries": self.llm_max_retries,
            "loop_rounds_per_run": self.loop_rounds_per_run,
            "max_loop_cycles": self.max_loop_cycles,
            "policy_top_k": self.policy_top_k,
        }
        for name, value in positives.items():
            if value < 1:
                raise ConfigError(f"{name} deve ser >= 1")
        if not 0.0 <= self.min_policy_confidence <= 1.0:
            raise ConfigError("min_policy_confidence deve estar entre 0 e 1")
        if self.llm_provider == "stackspot" and not (
            self.stackspot_realm and self.stackspot_agent_id
        ):
            raise ConfigError("stackspot exige stackspot_realm e stackspot_agent_id")

    @classmethod
    def load(cls, yaml_path: Path | None = None, **overrides: Any) -> Settings:
        """Combina defaults < YAML < variáveis de ambiente < overrides explícitos."""
        data: dict[str, Any] = {}
        if yaml_path is not None:
            with yaml_path.open(encoding="utf-8") as handle:
                data.update(yaml.safe_load(handle) or {})
        known = {f.name for f in fields(cls)}
        for name in known:
            env_value = os.environ.get(ENV_PREFIX + name.upper())
            if env_value is not None:
                data[name] = env_value
        data.update({k: v for k, v in overrides.items() if v is not None})
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"Chaves de configuração desconhecidas: {sorted(unknown)}")
        defaults = cls()
        kwargs = {k: _coerce(v, getattr(defaults, k)) for k, v in data.items()}
        for key in ("rules_file", "policy_file"):
            path = kwargs.get(key, getattr(defaults, key))
            if not path.is_absolute() and yaml_path is not None:
                kwargs[key] = (yaml_path.parent / path).resolve()
        settings = cls(**kwargs)
        settings.validate()
        return settings


def _coerce(raw: Any, default: Any) -> Any:
    """Coage ``raw`` ao tipo do valor default."""
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "sim", "yes", "s"}
    if isinstance(default, Path):
        return Path(str(raw))
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return str(raw)
