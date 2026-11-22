"""Leitura/escrita de CSV com contrato de schema e escrita atômica."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "id",
    "data_reclamacao",
    "canal",
    "texto_reclamacao",
    "produto",
    "status",
)
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252")
OUTPUT_ENCODING = "utf-8-sig"


class SchemaError(ValueError):
    """Arquivo fora do contrato esperado."""


class InputNotFoundError(FileNotFoundError):
    """Arquivo de entrada ausente."""


def timestamp() -> str:
    """Timestamp local para nomes de arquivo (``YYYYMMDD_HHMMSS``)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_csv_robust(path: Path) -> pd.DataFrame:
    """Lê CSV como texto (sem coerção), tentando UTF-8 com BOM e depois CP1252."""
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODINGS:
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        frame.columns = [str(col).strip() for col in frame.columns]
        return frame
    raise SchemaError(f"Não foi possível decodificar {path.name}: {last_error}")


def require_columns(df: pd.DataFrame, required: tuple[str, ...]) -> None:
    """Valida a presença das colunas obrigatórias."""
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SchemaError(f"Colunas ausentes: {missing}. Encontradas: {list(df.columns)}")


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    """Grava em arquivo temporário e renomeia (o consumidor nunca vê arquivo parcial)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False, encoding=OUTPUT_ENCODING)
    os.replace(tmp, path)


@contextmanager
def file_lock(path: Path) -> Iterator[bool]:
    """Lock cooperativo por arquivo (``<arquivo>.lock``); rende ``False`` se já bloqueado."""
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield True
    finally:
        lock.unlink(missing_ok=True)
