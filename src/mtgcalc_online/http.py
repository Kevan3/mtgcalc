"""One small, guarded HTTP GET for JSON (standard library only).

Every failure becomes a :class:`DeckFetchError` with a message a player can act on; the
original exception is chained for debugging. Requests and their outcome are logged at
DEBUG level on the ``mtgcalc_online`` logger.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from mtgcalc import __version__
from mtgcalc_online.errors import DeckFetchError

log = logging.getLogger("mtgcalc_online")

USER_AGENT = f"mtgcalc/{__version__} (deck import)"
TIMEOUT_SECONDS = 15.0
MAX_BYTES = 5_000_000  # a 100-card deck is ~100 kB; anything far larger is not a deck


def get_json(url: str, *, timeout: float = TIMEOUT_SECONDS, max_bytes: int = MAX_BYTES) -> Any:
    """GET ``url`` and decode the JSON body.

    Raises:
        DeckFetchError: offline / unreachable, HTTP error, oversized or non-JSON response.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    log.debug("GET %s", url)
    try:
        # Safe to open: callers only pass https URLs built from a recognized deck link.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        log.debug("GET %s -> HTTP %s", url, e.code)
        raise DeckFetchError(_http_message(e.code)) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.debug("GET %s failed: %r", url, e)
        raise DeckFetchError(
            "Could not reach the website. Check your internet connection and try again."
        ) from e
    log.debug("GET %s -> %d bytes", url, len(body))
    if len(body) > max_bytes:
        raise DeckFetchError("The website sent far more data than a deck; import cancelled.")
    try:
        return json.loads(body)
    except ValueError as e:
        raise DeckFetchError("The website sent something that is not a deck.") from e


def _http_message(status: int) -> str:
    if status == 404:
        return "Deck not found. Check the link, and make sure the deck is public."
    if status in (401, 403):
        return "The website refused the request (the deck may be private)."
    if status == 429:
        return "The website is limiting requests. Wait a minute and try again."
    if status >= 500:
        return "The website is having problems right now. Try again later."
    return f"The website answered with an error (HTTP {status})."
