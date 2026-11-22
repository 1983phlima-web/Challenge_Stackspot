"""Utilitários de normalização e casamento textual."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(value: object) -> str:
    """Remove acentos, colapsa espaços e aplica casefold.

    Valores ``None`` resultam em string vazia.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _WS.sub(" ", text).strip().casefold()


def compile_term(term: str) -> re.Pattern[str]:
    r"""Compila um termo (com ``*`` opcional como curinga ``\w*``) para busca por palavra inteira."""
    escaped = re.escape(normalize(term)).replace(r"\*", r"\w*")
    return re.compile(rf"(?<!\w){escaped}(?!\w)")
