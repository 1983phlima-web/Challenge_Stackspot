"""Fixtures compartilhadas e dublês de LLM."""

import functools
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from challenge.ai.base import LLMError
from challenge.config import Settings
from challenge.pii import mask_pii

ROOT = Path(__file__).resolve().parents[1]


def make_settings(base_dir: Path, **overrides: Any) -> Settings:
    """Settings de teste: sem IA por padrão, sem esperas."""
    params: dict[str, Any] = {
        "base_dir": base_dir,
        "rules_file": ROOT / "config" / "motor_regras.txt",
        "policy_file": ROOT / "config" / "politica.txt",
        "llm_provider": "none",
        "llm_workers": 4,
        "loop_retry_delay_s": 0.0,
        "llm_retry_base_delay_s": 0.0,
    }
    params.update(overrides)
    return Settings(**params)


_LABEL = {"A": "Alta", "M": "Média", "B": "Baixa"}
_TEXT_RE = re.compile(r"<reclamacao>\n(.*?)\n</reclamacao>", re.DOTALL)


@functools.cache
def oracle_labels() -> dict[str, str]:
    """Texto (já mascarado, como chega ao modelo) -> tensão do gabarito do dataset de 500 casos."""
    from dataset_factory import build_cases

    return {
        mask_pii(c.row[3].strip()): _LABEL[c.expected_fila[5]]
        for c in build_cases()
        if c.expected_fila
    }


class FakeLLM:
    """LLM determinístico. Com ``labels`` age como um modelo "perfeito" para a tensão (valida o fluxo);
    sem ``labels`` usa palavras-chave. Respostas: escolhe a 1ª política candidata."""

    name = "fake"

    def __init__(self, labels: dict[str, str] | None = None) -> None:
        self.labels = labels or {}
        self.calls = 0
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
            self.prompts.append(user)
        low = user.lower()
        if "TENSÃO" in system:
            match = _TEXT_RE.search(user)
            label = self.labels.get(match.group(1)) if match else None
            if label:
                return {"tensao": label, "confianca": 0.9, "justificativa": "gabarito"}
            if any(k in low for k in ("procon", "desesper", "golpe", "absurdo")):
                return {"tensao": "Alta", "confianca": 0.9, "justificativa": "ameaça"}
            if any(k in low for k in ("demora", "ninguém", "cobrança")):
                return {"tensao": "Média", "confianca": 0.8, "justificativa": "insatisfação"}
            return {"tensao": "Baixa", "confianca": 0.8, "justificativa": "dúvida"}
        ids = re.findall(r"\[(POL-[A-Z]+-\d+)\]", user)
        if ids:
            return {
                "politica_id": ids[0],
                "confianca": 0.95,
                "justificativa": "aderente",
                "resposta": "",
            }
        return {
            "politica_id": None,
            "confianca": 0.7,
            "justificativa": "sem política",
            "resposta": "Prezado(a), registramos sua solicitação e retornaremos em breve.",
        }

    def close(self) -> None:
        return None


class FlakyLLM:
    """Falha na geração de resposta para ids escolhidos (por N tentativas ou até ``healed``)."""

    name = "flaky"

    def __init__(self, inner: FakeLLM, fail_ids: set[str], fail_times: int | None = None) -> None:
        self.inner = inner
        self.fail_ids = fail_ids
        self.fail_times = fail_times
        self.healed = False
        self.attempts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if "TENSÃO" not in system and not self.healed:
            match = re.search(r"protocolo=([^;]+);", user)
            rid = match.group(1) if match else ""
            if rid in self.fail_ids:
                with self._lock:
                    self.attempts[rid] += 1
                    attempt = self.attempts[rid]
                if self.fail_times is None or attempt <= self.fail_times:
                    raise LLMError("falha injetada")
        return self.inner.complete_json(system, user)

    def close(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path: Path):
    return make_settings(tmp_path)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
