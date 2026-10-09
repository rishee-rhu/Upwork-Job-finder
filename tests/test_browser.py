"""Drives the real Playwright verifier against a local fake of Upwork's job pages."""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("playwright")

from findjobs.models import Job  # noqa: E402
from findjobs.verify import BrowserVerifier, PageState  # noqa: E402

from .test_verify import OPEN_PAGE  # noqa: E402

PAGES = {
    "/jobs/~01aaaaaaaaaaaaaaaa": OPEN_PAGE,
    "/jobs/~01bbbbbbbbbbbbbbbb": "Access denied. This job is private. Only freelancers invited by client can view this job.",
    "/jobs/~01cccccccccccccccc": "This job is no longer available.",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/jobs/~01dddddddddddddddd":
            self.send_response(302)
            self.send_header("Location", "/nx/search/jobs/")
            self.end_headers()
            return
        body = PAGES.get(self.path, "Find work Apply now")
        html = f"<html><head><title>Upwork</title></head><body><pre>{body}</pre></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _chromium():
    for p in (os.environ.get("FINDJOBS_CHROMIUM"), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
        if p and os.path.exists(p):
            return p
    return None


def test_browser_verifier_states(server):
    try:
        v = BrowserVerifier(executable_path=_chromium())
    except Exception as e:  # no browser installed
        pytest.skip(str(e))
    try:
        def check(path, title=""):
            return v.check(Job(url=server + path, title=title)).state

        assert check("/jobs/~01aaaaaaaaaaaaaaaa", "Healthcare Appointment Setter") == PageState.OK
        assert check("/jobs/~01bbbbbbbbbbbbbbbb") == PageState.PRIVATE
        assert check("/jobs/~01cccccccccccccccc") == PageState.UNAVAILABLE
        assert check("/jobs/~01dddddddddddddddd") == PageState.REDIRECTED
    finally:
        v.close()
