"""The HTTP helper against a local throwaway server (real sockets, no internet)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mtgcalc_online import DeckFetchError
from mtgcalc_online.http import USER_AGENT, get_json

ROUTES: dict[str, tuple[int, bytes]] = {
    "/ok": (200, b'{"name": "deck", "cards": []}'),
    "/missing": (404, b'{"error": "Deck not found."}'),
    "/private": (403, b"<html>blocked</html>"),
    "/busy": (429, b""),
    "/broken": (503, b""),
    "/teapot": (418, b""),
    "/html": (200, b"<html>not json</html>"),
    "/huge": (200, b"[" + b"1," * 1000 + b"1]"),
}
SEEN_AGENTS: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        SEEN_AGENTS.append(self.headers.get("User-Agent", ""))
        status, body = ROUTES.get(self.path, (404, b""))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_json_is_decoded_and_identifies_itself(server: str) -> None:
    assert get_json(f"{server}/ok") == {"name": "deck", "cards": []}
    assert SEEN_AGENTS[-1] == USER_AGENT and "mtgcalc" in USER_AGENT


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/missing", "not found"),
        ("/private", "refused"),
        ("/busy", "Wait a minute"),
        ("/broken", "Try again later"),
        ("/teapot", "HTTP 418"),
        ("/html", "not a deck"),
    ],
)
def test_failures_become_friendly_errors_with_the_cause_kept(
    server: str, path: str, message: str
) -> None:
    with pytest.raises(DeckFetchError, match=message) as info:
        get_json(f"{server}{path}")
    assert info.value.__cause__ is not None  # the original error, for debugging


def test_oversized_responses_are_refused(server: str) -> None:
    with pytest.raises(DeckFetchError, match="far more data"):
        get_json(f"{server}/huge", max_bytes=100)


def test_unreachable_host() -> None:
    with pytest.raises(DeckFetchError, match="internet connection"):
        get_json("http://127.0.0.1:9/", timeout=2)
