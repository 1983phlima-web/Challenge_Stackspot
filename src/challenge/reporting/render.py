"""Renderização de relatórios gerenciais em Markdown e HTML autocontido."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class Section:
    """Seção de relatório: parágrafos (linhas '- ' viram lista) e tabelas nomeadas."""

    title: str
    paragraphs: list[str] = field(default_factory=list)
    tables: list[tuple[str, pd.DataFrame]] = field(default_factory=list)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_Sem dados._"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def render_markdown(title: str, subtitle: str, sections: list[Section]) -> str:
    """Gera o relatório em Markdown."""
    out = [f"# {title}", f"_{subtitle}_", ""]
    for sec in sections:
        out += [f"## {sec.title}", ""]
        out += [p if p.startswith("- ") else p + "\n" for p in sec.paragraphs]
        out.append("")
        for name, table in sec.tables:
            out += [f"**{name}**", "", _md_table(table), ""]
    return "\n".join(out)


_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;"
    "color:#1b1b1b}h1{border-bottom:3px solid #0b5cab}h2{color:#0b5cab;margin-top:2rem}"
    "table{border-collapse:collapse;margin:.5rem 0 1.5rem;font-size:.9rem}"
    "th,td{border:1px solid #ccd;padding:.3rem .6rem;text-align:left}th{background:#eef3fa}"
    "@media(prefers-color-scheme:dark){body{background:#14171c;color:#e6e6e6}"
    "th{background:#222a36}th,td{border-color:#445}h2{color:#6aaeff}}"
)


def render_html(title: str, subtitle: str, sections: list[Section]) -> str:
    """Gera o relatório em HTML (CSS inline, sem dependências externas)."""
    parts = [
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1><p><em>{html.escape(subtitle)}</em></p>",
    ]
    for sec in sections:
        parts.append(f"<h2>{html.escape(sec.title)}</h2>")
        bullets: list[str] = []
        for para in [*sec.paragraphs, ""]:
            if para.startswith("- "):
                bullets.append(para[2:])
                continue
            if bullets:
                parts.append(
                    "<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in bullets) + "</ul>"
                )
                bullets = []
            if para:
                parts.append(f"<p>{html.escape(para)}</p>")
        for name, table in sec.tables:
            parts.append(f"<h3>{html.escape(name)}</h3>")
            parts.append(
                table.to_html(index=False, escape=True, border=0)
                if not table.empty
                else "<p><em>Sem dados.</em></p>"
            )
    parts.append("</body></html>")
    return "\n".join(parts)


def write_report(
    reports_dir: Path, base_name: str, title: str, subtitle: str, sections: list[Section]
) -> tuple[Path, Path]:
    """Grava ``<base_name>.md`` e ``<base_name>.html``."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path, html_path = reports_dir / f"{base_name}.md", reports_dir / f"{base_name}.html"
    md_path.write_text(render_markdown(title, subtitle, sections), encoding="utf-8")
    html_path.write_text(render_html(title, subtitle, sections), encoding="utf-8")
    return md_path, html_path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Grava estatísticas em JSON legível."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
