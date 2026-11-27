# ADR-0012: Importing decks from deck-site links

**Status:** Accepted (2026-11-14)

## Context

Players keep their decks on deck sites. Typing a deck in, or exporting and pasting it, was the only way to get it into the app. The core must stay free of I/O (NFR-07). A future web app would also turn any "fetch this URL" feature into a server-side request forgery (SSRF) risk.

Checked against the live sites on 2026-11-14:
- **Archidekt** serves public decks as JSON at `https://archidekt.com/api/decks/<id>/`, with no authentication.
- **Moxfield** answers every non-browser request with HTTP 403 bot protection. Its API is only for applications it has approved.

## Decision

- Add a separate package, **`mtgcalc_online`**, using only the standard library, with three single-purpose modules:
  - `http.get_json`: one guarded GET (user agent, timeout, size cap, friendly errors, cause chained, DEBUG logging).
  - `archidekt.to_deck`: a pure JSON → `Deck` conversion.
  - `sources`: a registry of `Source(name, link pattern, api_url, to_deck, help)`, `recognize`, and `fetch_deck(link, get=...)`.
- **Only recognized deck links are fetched**, and only from the site's own API (`https`). Anything else is rejected before any request is made.
- **Moxfield is recognized but not fetched.** The app explains Moxfield's own *Export → Copy as plain text*, which the existing parser already reads, tags included. We do not impersonate a browser to get past its bot protection.
- **One explicit import step in the GUI.** *Import* downloads once, on a worker thread, and writes the deck into the decklist box via the new `mtgcalc.format_decklist`. The player sees and can edit exactly what was imported. Answering questions never touches the network.
- `format_decklist` writes tags as `#tags` (hyphenating spaces), so that tags such as "sideboard" are never read back as sections.
- Layering contracts: `mtgcalc` must not import `mtgcalc_online` or `mtgcalc_gui`, and `mtgcalc_online` must not import `mtgcalc_gui`.

## Consequences

- Archidekt decks import in one step. Moxfield users get clear two-click instructions instead of a cryptic failure.
- Tests need no internet:
  - the converter runs on trimmed real responses;
  - the HTTP layer runs against a local server;
  - the GUI runs with an injected fetch.
  - An opt-in `-m network` test detects format changes on the site. *(Removed 2026-11-25: Archidekt began refusing requests from GitHub's CI servers with HTTP 403. Format changes are now caught only by the saved-response tests.)*
- Adding a site means one module with a link pattern, `api_url` and `to_deck`, plus a `Source` entry.
