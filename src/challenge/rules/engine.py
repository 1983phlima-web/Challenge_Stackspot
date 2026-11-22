"""Motor de Regras: termos ponderados que sinalizam tensão (arquivo TXT)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from challenge.domain.codes import Tension
from challenge.text import compile_term, normalize

DEFAULT_LIMIAR_ALTA = 3.0
DEFAULT_LIMIAR_MEDIA = 2.0


class RulesError(ValueError):
    """Arquivo de regras malformado."""


@dataclass(frozen=True)
class Rule:
    """Termo do motor de regras."""

    nivel: Tension
    termo: str
    peso: float
    piso: bool
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class RuleEvaluation:
    """Resultado da avaliação de um texto."""

    matches: tuple[Rule, ...]
    suggested: Tension
    floor: Tension | None

    @property
    def terms(self) -> tuple[str, ...]:
        """Termos detectados (para auditoria e prompt)."""
        return tuple(f"{r.termo}[{r.nivel.label}]" for r in self.matches)


class RulesEngine:
    """Avalia textos contra regras carregadas de TXT.

    Formato (``;`` como separador, ``#`` comentário)::

        @limiar_alta=3
        @limiar_media=2
        ALTA;procon;3;s      # nivel;termo;peso;piso(s/n)
        MEDIA;demora;1
    """

    def __init__(self, rules: list[Rule], limiar_alta: float, limiar_media: float) -> None:
        """Cria o motor a partir de regras já compiladas."""
        self._rules = rules
        self._limiar_alta = limiar_alta
        self._limiar_media = limiar_media

    def __len__(self) -> int:
        """Quantidade de regras."""
        return len(self._rules)

    @classmethod
    def from_file(cls, path: Path) -> RulesEngine:
        """Carrega e valida o arquivo de regras."""
        if not path.is_file():
            raise RulesError(f"Arquivo de regras não encontrado: {path}")
        return cls.from_text(path.read_text(encoding="utf-8-sig"))

    @classmethod
    def from_text(cls, content: str) -> RulesEngine:
        """Interpreta o conteúdo textual das regras."""
        rules: list[Rule] = []
        limiar_alta, limiar_media = DEFAULT_LIMIAR_ALTA, DEFAULT_LIMIAR_MEDIA
        for number, raw in enumerate(content.splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("@"):
                key, _, value = line[1:].partition("=")
                try:
                    number_value = float(value)
                except ValueError as exc:
                    raise RulesError(f"Linha {number}: valor inválido em {line!r}") from exc
                if key.strip() == "limiar_alta":
                    limiar_alta = number_value
                elif key.strip() == "limiar_media":
                    limiar_media = number_value
                else:
                    raise RulesError(f"Linha {number}: diretiva desconhecida {key!r}")
                continue
            parts = [p.strip() for p in line.split(";")]
            nivel = Tension.from_text(parts[0])
            if nivel is None or len(parts) < 2 or not parts[1]:
                raise RulesError(f"Linha {number}: esperado 'NIVEL;termo[;peso[;piso]]'")
            try:
                peso = float(parts[2]) if len(parts) > 2 and parts[2] else 1.0
            except ValueError as exc:
                raise RulesError(f"Linha {number}: peso inválido") from exc
            piso = len(parts) > 3 and normalize(parts[3]) in {"s", "sim", "true", "1"}
            rules.append(Rule(nivel, normalize(parts[1]), peso, piso, compile_term(parts[1])))
        if not rules:
            raise RulesError("Nenhuma regra válida encontrada")
        return cls(rules, limiar_alta, limiar_media)

    def evaluate(self, text: str) -> RuleEvaluation:
        """Detecta termos e sugere um nível; ``floor`` é o piso imposto por termos críticos."""
        norm = normalize(text)
        matches = tuple(r for r in self._rules if r.pattern.search(norm))
        alta = sum(r.peso for r in matches if r.nivel is Tension.ALTA)
        media = sum(r.peso for r in matches if r.nivel is Tension.MEDIA)
        if alta >= self._limiar_alta:
            suggested = Tension.ALTA
        elif alta + media >= self._limiar_media:
            suggested = Tension.MEDIA
        else:
            suggested = Tension.BAIXA
        floors = [r.nivel for r in matches if r.piso]
        return RuleEvaluation(matches, suggested, max(floors) if floors else None)
