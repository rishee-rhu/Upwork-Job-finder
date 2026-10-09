import base64
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from findjobs.web import State, make_handler

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    st = State(tmp_path / "ws")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", st
    srv.shutdown()


def call(base, path, body=None, host=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Host": host} if host else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_secrets_masked_and_host_checked(ui):
    base, st = ui
    call(base, "/api/settings", {"apify_token": "apify_api_SECRET9999", "apify_actor": "a~b"})
    _, s = call(base, "/api/settings")
    assert s["apify_token"] == "••••9999" and s["apify_actor"] == "a~b"
    call(base, "/api/settings", {"apify_token": s["apify_token"]})  # masked echo doesn't overwrite
    assert st.settings()["apify_token"] == "apify_api_SECRET9999"
    assert call(base, "/api/settings", host="evil.example")[0] == 403


def test_run_then_judgments_rerun(ui):
    base, st = ui
    assert call(base, "/api/profile/example", {"name": "profile.somya.json"})[0] == 200
    data = base64.b64encode((ROOT / "examples" / "jobs.sample.json").read_bytes()).decode()
    call(base, "/api/upload", {"name": "jobs.sample.json", "data": data})

    def wait():
        for _ in range(100):
            _, s = call(base, "/api/status")
            if not s["task"] and s["finished_at"]:
                return s
            time.sleep(0.1)
        raise AssertionError("task never finished")

    opts = {"use_apify": False, "no_verify": True, "show_unverified": True, "job_files": ["jobs.sample.json"]}
    assert call(base, "/api/run", opts)[1]["started"]
    s = wait()
    assert s["error"] is None and s["outputs"]["judge_requests.json"]

    j = base64.b64encode((ROOT / "examples" / "judgments.sample.json").read_bytes()).decode()
    call(base, "/api/upload", {"name": "judgments.json", "data": j, "kind": "judgments"})
    st.finished_at = None
    call(base, "/api/run", {"use_apify": False, "no_verify": True, "show_unverified": True,
                            "reuse_verified": True, "use_judgments": True})
    s = wait()
    assert s["summary"]["unverified"] == 2 and not s["outputs"]["judge_requests.json"]


def test_apify_without_token_rejected(ui):
    base, _ = ui
    call(base, "/api/profile/example", {"name": "profile.somya.json"})
    code, body = call(base, "/api/run", {"use_apify": True})
    assert code == 400 and "Apify" in body
