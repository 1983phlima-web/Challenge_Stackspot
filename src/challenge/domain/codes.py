"""Regras de montagem do código de fila: ``<Canal><Produto><Status><Tensão>`` (ex.: BEMP3A)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from challenge.text import normalize

CANAL_MAP: dict[str, str] = {
    "banco central": "B",
    "ouvidoria": "O",
    "redes sociais": "R",
    "sac": "S",
}
CANAL_LABEL: dict[str, str] = {
    "B": "Banco Central",
    "O": "Ouvidoria",
    "R": "Redes Sociais",
    "S": "SAC",
    "Z": "Outros",
}
CANAL_ORDER: dict[str, int] = {"B": 0, "O": 1, "R": 2, "S": 3, "Z": 4}

PRODUTO_MAP: dict[str, str] = {
    "emprestimo": "EMP",
    "investimentos": "INV",
    "cartao de credito": "CAR",
    "conta corrente": "CON",
    "seguros": "SEG",
}
PRODUTO_LABEL: dict[str, str] = {
    "EMP": "Empréstimo",
    "INV": "Investimentos",
    "CAR": "Cartão de Crédito",
    "CON": "Conta Corrente",
    "SEG": "Seguros",
    "SEM": "Outros",
}

STATUS_MAP: dict[str, str] = {"aberta": "1", "em analise": "2", "resolvida": "3"}
STATUS_LABEL: dict[str, str] = {"1": "Aberta", "2": "Em análise", "3": "Resolvida"}
STATUS_RESOLVED = "3"


class Tension(IntEnum):
    """Nível de tensão da reclamação (ordem crescente de gravidade)."""

    BAIXA = 1
    MEDIA = 2
    ALTA = 3

    @property
    def code(self) -> str:
        """Letra usada no código de fila."""
        return {1: "B", 2: "M", 3: "A"}[self.value]

    @property
    def label(self) -> str:
        """Rótulo de exibição."""
        return {1: "Baixa", 2: "Média", 3: "Alta"}[self.value]

    @classmethod
    def from_text(cls, value: object) -> Tension | None:
        """Interpreta 'Alta'/'Média'/'Baixa' (tolerante a acento e caixa)."""
        return {"alta": cls.ALTA, "media": cls.MEDIA, "baixa": cls.BAIXA}.get(normalize(value))

    @classmethod
    def from_code(cls, code: str) -> Tension:
        """Interpreta a letra A/M/B."""
        return {"A": cls.ALTA, "M": cls.MEDIA, "B": cls.BAIXA}[code]


TENSION_LABEL: dict[str, str] = {"A": "Alta", "M": "Média", "B": "Baixa"}


def canal_code(value: object) -> str:
    """Classe do canal; qualquer valor desconhecido vira ``Z``."""
    return CANAL_MAP.get(normalize(value), "Z")


def produto_code(value: object) -> str:
    """Classe do produto; qualquer valor desconhecido vira ``SEM``."""
    return PRODUTO_MAP.get(normalize(value), "SEM")


def status_code(value: object) -> str | None:
    """Classe do status (1-3); ``None`` se o valor não for reconhecido."""
    return STATUS_MAP.get(normalize(value))


_FILA_RE = re.compile(r"^([BORSZ])(EMP|INV|CAR|CON|SEG|SEM)([123])([AMB])$")


@dataclass(frozen=True)
class FilaCode:
    """Código de fila decomposto."""

    canal: str
    produto: str
    status: str
    tensao: Tension

    def __str__(self) -> str:
        """Representação canônica, ex.: ``BEMP3A``."""
        return f"{self.canal}{self.produto}{self.status}{self.tensao.code}"

    @classmethod
    def parse(cls, value: str) -> FilaCode:
        """Decompõe um código de fila; ``ValueError`` se inválido."""
        match = _FILA_RE.match(value.strip())
        if not match:
            raise ValueError(f"Código de fila inválido: {value!r}")
        return cls(match[1], match[2], match[3], Tension.from_code(match[4]))
