"""Mascaramento de dados pessoais antes do envio a um provedor de IA (LGPD)."""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "[CARTAO]"),
    (re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}(?!\d)"), "[TELEFONE]"),
)


def mask_pii(text: str) -> str:
    """Substitui CPF, CNPJ, e-mail, cartão e telefone por marcadores genéricos."""
    for pattern, token in _PATTERNS:
        text = pattern.sub(token, text)
    return text
