"""Console + optional file logging for the API process."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core import config

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(settings: config.Settings) -> None:
    """Log to stderr and, when set, to ``settings.log_file``.

    Replaces existing root handlers so reload / tests do not stack duplicates.
    """
    level = logging.DEBUG if settings.debug else logging.INFO
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if not settings.log_file:
        return

    path = Path(settings.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
