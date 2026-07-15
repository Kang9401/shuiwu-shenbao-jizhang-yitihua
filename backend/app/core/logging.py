from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import settings


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "name", "") == "taxworkbench-file" for handler in root.handlers):
        return
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            settings.log_dir / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        logging.getLogger(__name__).warning("日志目录不可写，将仅使用控制台日志：%s", settings.log_dir)
        return
    handler.name = "taxworkbench-file"
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
