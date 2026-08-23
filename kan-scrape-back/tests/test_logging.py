import logging
import re
from pathlib import Path

from app.core import config
from app.core.logging import configure_logging


def _reset_root_logger() -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()


def test_configure_logging_writes_level_time_and_logger_name(tmp_path: Path) -> None:
    _reset_root_logger()
    log_path = tmp_path / "nested" / "app.log"
    configure_logging(config.Settings(log_file=str(log_path), debug=False))

    logging.getLogger("app.services.stt").info("hello from test")
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = log_path.read_text(encoding="utf-8")
    assert "INFO" in text
    assert "app.services.stt" in text
    assert "hello from test" in text
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)


def test_configure_logging_skips_file_when_unset() -> None:
    _reset_root_logger()
    configure_logging(config.Settings(log_file=None, debug=False))

    kinds = {type(handler).__name__ for handler in logging.getLogger().handlers}
    assert "StreamHandler" in kinds
    assert not any("FileHandler" in name for name in kinds)
