"""Livro de Políticas: respostas aprovadas, com recuperação por produto/canal/tensão/termos."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from challenge.domain.codes import CANAL_LABEL, PRODUTO_LABEL, FilaCode
from challenge.text import compile_term, normalize

_KEY_RE = re.compile(r"^(produto|canal|tensao|palavras|resposta)\s*:\s*(.*)$", re.IGNORECASE)
_ID_RE = re.compile(r"^\[([^\]]+)\]$")


class PolicyError(ValueError):
    """Arquivo de políticas malformado."""


@dataclass(frozen=True)
class Policy:
    """Política com resposta aprovada."""

    id: str
    produtos: frozenset[str]
    canais: frozenset[str]
    tensoes: frozenset[str]
    palavras: tuple[str, ...]
    resposta: str
    patterns: tuple[re.Pattern[str], ...] = field(repr=False, default=())

    def render(self, protocolo: str, produto: str) -> str:
        """Aplica os placeholders ``{id}`` e ``{produto}`` (apenas esses)."""
        return self.resposta.replace("{id}", protocolo).replace("{produto}", produto)


@dataclass(frozen=True)
class PolicyMatch:
    """Candidata recuperada, com pontuação lexical."""

    policy: Policy
    score: float
    hits: tuple[str, ...]


def _split(value: str) -> list[str]:
    return [normalize(v) for v in value.split(",") if v.strip()]


class PolicyBook:
    """Coleção de políticas carregada de TXT.

    Formato::

        [POL-001]
        produto: Empréstimo, Cartão de Crédito   # ou * (qualquer)
        canal: *                                 # rótulos ou letras (B,O,R,S,Z)
        tensao: *                                # Alta, Média, Baixa
        palavras: juros, contrato, cobranca indevida, desesper*
        resposta: Texto aprovado. Protocolo {id}.
    """

    def __init__(self, policies: list[Policy]) -> None:
        """Cria o livro a partir de políticas já interpretadas."""
        self._policies = policies

    def __len__(self) -> int:
        """Quantidade de políticas."""
        return len(self._policies)

    @classmethod
    def from_file(cls, path: Path) -> PolicyBook:
        """Carrega e valida o arquivo."""
        if not path.is_file():
            raise PolicyError(f"Arquivo de política não encontrado: {path}")
        return cls.from_text(path.read_text(encoding="utf-8-sig"))

    @classmethod
    def from_text(cls, content: str) -> PolicyBook:
        """Interpreta o conteúdo textual."""
        blocks: list[tuple[str, dict[str, str]]] = []
        current: dict[str, str] | None = None
        last_key = ""
        for number, raw in enumerate(content.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            id_match = _ID_RE.match(line)
            if id_match:
                current = {}
                blocks.append((id_match[1].strip(), current))
                last_key = ""
                continue
            if current is None:
                raise PolicyError(f"Linha {number}: conteúdo antes de qualquer [ID]")
            key_match = _KEY_RE.match(line)
            if key_match:
                last_key = key_match[1].lower()
                current[last_key] = key_match[2].strip()
            elif last_key:
                current[last_key] = f"{current[last_key]} {line}".strip()
            else:
                raise PolicyError(f"Linha {number}: formato inválido")
        policies = [cls._build(pid, data) for pid, data in blocks]
        if len({p.id.casefold() for p in policies}) != len(policies):
            raise PolicyError("IDs de política duplicados")
        return cls(policies)

    @staticmethod
    def _build(pid: str, data: dict[str, str]) -> Policy:
        if not data.get("resposta") or not data.get("palavras"):
            raise PolicyError(f"Política {pid}: 'palavras' e 'resposta' são obrigatórios")
        words = tuple(w.strip() for w in data["palavras"].split(",") if w.strip())
        return Policy(
            id=pid,
            produtos=frozenset(_split(data.get("produto", "*"))),
            canais=frozenset(_split(data.get("canal", "*"))),
            tensoes=frozenset(_split(data.get("tensao", "*"))),
            palavras=words,
            resposta=data["resposta"],
            patterns=tuple(compile_term(w) for w in words),
        )

    def find_candidates(self, text: str, fila: FilaCode, top_k: int = 5) -> list[PolicyMatch]:
        """Recupera as melhores políticas aplicáveis (filtros duros + pontuação lexical)."""
        norm = normalize(text)
        produto_keys = {normalize(PRODUTO_LABEL[fila.produto]), normalize(fila.produto)}
        canal_keys = {normalize(CANAL_LABEL[fila.canal]), normalize(fila.canal)}
        tensao_keys = {normalize(fila.tensao.label)}
        results: list[PolicyMatch] = []
        for policy in self._policies:
            if not _applies(policy.produtos, produto_keys):
                continue
            if not _applies(policy.canais, canal_keys):
                continue
            if not _applies(policy.tensoes, tensao_keys):
                continue
            hits = [
                w for w, p in zip(policy.palavras, policy.patterns, strict=True) if p.search(norm)
            ]
            if not hits:
                continue
            score = sum(1.0 + 0.5 * (len(normalize(h).split()) - 1) for h in hits)
            if "*" not in policy.produtos:
                score += 0.5
            results.append(PolicyMatch(policy, score, tuple(hits)))
        results.sort(key=lambda m: (-m.score, m.policy.id))
        return results[:top_k]


def _applies(allowed: frozenset[str], keys: set[str]) -> bool:
    return "*" in allowed or bool(allowed & keys)
