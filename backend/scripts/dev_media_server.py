"""Dev-медиасервер: отдаёт папку <корень проекта>/assets на :8010 под /assets/*.

Зачем: в dev MEDIA_PUBLIC_BASE_URL=http://127.0.0.1:8010/assets, обложки
товаров лежат в <корень>/assets/uploads/... Экспонируется ТОЛЬКО assets
(не корень проекта — там .env с секретами).

Запуск (из корня проекта):
    python backend/scripts/dev_media_server.py
"""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSETS_ROOT = str(Path(__file__).resolve().parents[2] / "assets")


class AssetsHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/assets/"):
            rel = path[len("/assets/"):]
        else:
            rel = path.lstrip("/")
        rel = os.path.normpath(rel)
        if rel.startswith("..") or os.path.isabs(rel):
            rel = ""
        return os.path.join(ASSETS_ROOT, rel)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        super().end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"dev media server on :8010 -> {ASSETS_ROOT}")
    ThreadingHTTPServer(("0.0.0.0", 8010), AssetsHandler).serve_forever()
