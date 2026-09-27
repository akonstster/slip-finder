import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from slip_finder import config
from slip_finder.indexer import Indexer
from slip_finder.store import Store
from slip_finder.web import make_server

FIXTURES = Path(__file__).parent / "fixtures"
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    empty = tmp_path / "empty"
    empty.mkdir()
    store = Store(tmp_path / "t.db")
    indexer = Indexer(store, empty)
    server = make_server(store, indexer, 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", indexer, tmp_path
    server.shutdown()
    server.server_close()


def call(url, body=None, ctype="application/json", host=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    if body is not None:
        req.add_header("Content-Type", ctype)
    if host:
        req.add_header("Host", host)
    try:
        with NO_PROXY.open(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_scan_picks_up_new_file(app):
    base, indexer, tmp = app
    logs = tmp / "empty"
    status, data = call(base + "/api/scan", {})
    assert status == 200 and data["scanned"] == 0 and data["count"] == 0

    shutil.copy(FIXTURES / "260115093425.log", logs)
    status, data = call(base + "/api/scan", {})
    assert data["scanned"] == 1 and data["count"] == 1 and data["last_scan_ts"]


def test_settings_change_logs_dir(app):
    base, indexer, tmp = app
    status, data = call(base + "/api/settings", {"logs_dir": str(FIXTURES)})
    assert status == 200 and data["scanned"] == 11
    assert indexer.logs_dir == FIXTURES
    saved = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
    assert saved["logs_dir"] == str(FIXTURES)
    assert call(base + "/api/settings")[1]["logs_dir"] == str(FIXTURES)


def test_settings_rejects_missing_dir(app):
    base, indexer, tmp = app
    status, data = call(base + "/api/settings", {"logs_dir": str(tmp / "nope")})
    assert status == 400 and "не найдена" in json.loads(data)["error"]
    assert not (tmp / "settings.json").exists()


def test_post_requires_json(app):
    base, *_ = app
    status, _ = call(base + "/api/scan", {}, ctype="text/plain")
    assert status == 415


def test_foreign_host_rejected(app):
    base, *_ = app
    status, _ = call(base + "/api/status", host="evil.example:80")
    assert status == 403
