"""Logging estruturado (JSON) e trilha de auditoria analítica (JSONL)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any


class RunContextFilter(logging.Filter):
    """Injeta ``run_id`` e ``process_name`` em todos os registros."""

    def __init__(self, run_id: str, process_name: str) -> None:
        """Guarda o contexto da execução."""
        super().__init__()
        self._run_id = run_id
        self._process_name = process_name

    def filter(self, record: logging.LogRecord) -> bool:
        """Anexa o contexto ao registro."""
        record.run_id = self._run_id
        record.process_name = self._process_name
        return True


class JsonFormatter(logging.Formatter):
    """Serializa registros de log como uma linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", ""),
            "process": getattr(record, "process_name", ""),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(logs_dir: Path, run_id: str, process_name: str, level: str = "INFO") -> None:
    """Configura o logger ``challenge`` com arquivo rotativo (JSON) e console."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("challenge")
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    context = RunContextFilter(run_id, process_name)

    file_handler = RotatingFileHandler(
        logs_dir / f"{process_name}.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(context)

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(process_name)s:%(run_id)s] %(message)s")
    )
    console.addFilter(context)

    logger.addHandler(file_handler)
    logger.addHandler(console)


class AuditLog:
    """Escritor thread-safe de eventos analíticos em JSON Lines."""

    def __init__(self, path: Path, run_id: str) -> None:
        """Abre (append) o arquivo de auditoria."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._run_id = run_id
        self._lock = threading.Lock()
        self._handle = path.open("a", encoding="utf-8")

    def write(self, event: str, **fields: Any) -> None:
        """Grava um evento com timestamp UTC."""
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "run_id": self._run_id,
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        """Fecha o arquivo."""
        with self._lock:
            self._handle.close()

    def __enter__(self) -> AuditLog:
        """Entrada do context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Saída do context manager."""
        self.close()
