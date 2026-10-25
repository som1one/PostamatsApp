"""Логи бэкенда пишутся в файл, который переживает выкладку.

2026-10-24 не удалось узнать даже дату брони, стёртой выкладкой: INFO-логи
приложения не писались никуда, а лог контейнера пропадал вместе с ним.
"""

import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core import logging_setup


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = logging.getLogger()
        self.saved_handlers = list(self.root.handlers)
        self.saved_level = self.root.level
        self.uvicorn_saved = {
            name: list(logging.getLogger(name).handlers) for name in ("uvicorn", "uvicorn.access")
        }
        self.root.handlers = []
        self.tmp = Path(tempfile.mkdtemp(prefix="logs-"))

    def tearDown(self):
        for handler in self.root.handlers:
            if handler not in self.saved_handlers:
                handler.close()
        self.root.handlers = self.saved_handlers
        self.root.setLevel(self.saved_level)
        for name, handlers in self.uvicorn_saved.items():
            logging.getLogger(name).handlers = handlers
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _log_text(self) -> str:
        for handler in self.root.handlers:
            handler.flush()
        return (self.tmp / logging_setup.LOG_FILE_NAME).read_text(encoding="utf-8")

    def test_app_and_access_logs_go_to_the_file(self):
        with patch.dict(os.environ, {"LOG_DIR": str(self.tmp)}):
            logging_setup.configure_logging()
            logging_setup.configure_logging()  # повторный вызов ничего не удваивает

        logging.getLogger("backend.routers.reservation").info("Reservation R1 created: pickup_at=2026-10-24")
        logging.getLogger("uvicorn.access").info('"POST /reservations HTTP/1.1" 200')

        text = self._log_text()
        self.assertEqual(text.count("Reservation R1 created: pickup_at=2026-10-24"), 1)
        self.assertIn("POST /reservations", text)
        file_handlers = [h for h in self.root.handlers if h.name == "postamats-file"]
        self.assertEqual(len(file_handlers), 1)
        self.assertEqual(file_handlers[0].maxBytes, 10 * 1024 * 1024)

    def test_without_log_dir_nothing_is_written_and_warnings_still_reach_stderr(self):
        with patch.dict(os.environ, {"LOG_DIR": ""}):
            logging_setup.configure_logging()

        self.assertFalse((self.tmp / logging_setup.LOG_FILE_NAME).exists())
        stream_handlers = [h for h in self.root.handlers if isinstance(h, logging.StreamHandler)]
        self.assertEqual(len(stream_handlers), 1)
        self.assertEqual(stream_handlers[0].level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
