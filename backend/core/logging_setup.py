"""Куда пишутся логи бэкенда.

Раньше логирование не настраивалось вовсе: INFO-строки приложения
(«Auto-confirmed paid reservation…», «Expired N reservations») не попадали
никуда, а то, что попадало в лог контейнера, пропадало при каждой выкладке
вместе с пересозданным контейнером. 2026-10-24 из-за этого не удалось
узнать даже дату брони, которую стёрла выкладка.

Если задан ``LOG_DIR`` (на проде — том Docker ``backend_logs``), всё от
INFO и выше, включая access-лог uvicorn, пишется в ``LOG_DIR/backend.log``
с ротацией: 10 МБ × 6 файлов, не больше 60 МБ на диске. В stderr, как и
раньше, идут только предупреждения и ошибки — лог контейнера не растёт.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "backend.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_NAME = "postamats-file"


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "name", None) == _HANDLER_NAME for handler in root.handlers):
        return

    if not root.handlers:
        # То же, что раньше давал «последний шанс» logging: предупреждения
        # и ошибки в stderr. Без явного хендлера он отключился бы.
        stderr = logging.StreamHandler()
        stderr.setLevel(logging.WARNING)
        stderr.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stderr)

    log_dir = os.environ.get("LOG_DIR", "").strip()
    if not log_dir:
        return
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            Path(log_dir) / LOG_FILE_NAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        # Без файла логов бэкенд всё равно должен подняться.
        logging.getLogger(__name__).exception("Cannot write logs to %s", log_dir)
        return
    file_handler.name = _HANDLER_NAME
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)
    # Логгеры uvicorn не передают записи корню — подключаем файл к ним явно.
    for name in ("uvicorn", "uvicorn.access"):
        logging.getLogger(name).addHandler(file_handler)
