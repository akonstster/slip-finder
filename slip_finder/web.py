"""Локальный HTTP-сервер: страница поиска и JSON API."""
import json
import logging
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import __version__, config
from .indexer import Indexer
from .store import Store

log = logging.getLogger(__name__)

SEARCH_LIMIT = 200


def _static_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return base / "slip_finder" / "static"


def period_bounds(period: str, now: datetime | None = None) -> tuple[int | None, int | None]:
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "all":
        return None, None
    if period == "yesterday":
        return int((today - timedelta(days=1)).timestamp()), int(today.timestamp())
    days = int(period) if period.isdigit() else 1
    return int((today - timedelta(days=days - 1)).timestamp()), None


def make_handler(store: Store, indexer: Indexer, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            # Защита от DNS rebinding: чужой домен, указывающий на 127.0.0.1
            if self.headers.get("Host") in allowed_hosts:
                return True
            self._send(403, b"forbidden", "text/plain")
            return False

        def _status(self) -> dict:
            return {**store.stats(), "logs_dir": str(indexer.logs_dir),
                    "logs_dir_ok": indexer.logs_dir.is_dir(),
                    "last_scan_ts": indexer.last_scan_ts, "version": __version__}

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/":
                body = (_static_dir() / "index.html").read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
            elif url.path == "/api/search":
                ts_from, ts_to = period_bounds(qs.get("period", "1"))
                results = store.search(qs.get("q", ""), ts_from, ts_to, limit=SEARCH_LIMIT + 1)
                self._json({"results": results[:SEARCH_LIMIT],
                            "truncated": len(results) > SEARCH_LIMIT})
            elif url.path == "/api/status":
                self._json(self._status())
            elif url.path == "/api/settings":
                self._json({"logs_dir": str(indexer.logs_dir)})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._host_ok():
                return
            # Только JSON: кросс-доменный JSON-POST браузер без CORS не отправит
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._send(415, b"json only", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json({"error": "Некорректный запрос"}, 400)
                return

            url = urlparse(self.path)
            if url.path == "/api/scan":
                n = indexer.scan()
                self._json({"scanned": n, **self._status()})
            elif url.path == "/api/settings":
                raw = str(data.get("logs_dir", "")).strip().strip('"')
                path = Path(raw)
                if not raw or not path.is_dir():
                    self._json({"error": f"Папка не найдена: {raw}"}, 400)
                    return
                settings = config.load()
                settings["logs_dir"] = str(path)
                config.save(settings)
                indexer.set_logs_dir(path)
                log.info("Папка логов изменена: %s", path)
                n = indexer.scan()
                self._json({"scanned": n, **self._status()})
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


class _Server(ThreadingHTTPServer):
    # На Windows SO_REUSEADDR даёт второму экземпляру занять тот же порт
    allow_reuse_address = False
    daemon_threads = True


def make_server(store: Store, indexer: Indexer, port: int) -> ThreadingHTTPServer:
    # Только localhost: коды авторизации не должны быть видны из сети магазина
    server = _Server(("127.0.0.1", port), BaseHTTPRequestHandler)
    # Порт 0 (тесты) становится известен только после bind
    server.RequestHandlerClass = make_handler(store, indexer, server.server_address[1])
    return server
