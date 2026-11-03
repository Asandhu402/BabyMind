"""Bounded web-search discovery for BabyMind (no page execution or fetching)."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
MAX_RESPONSE_BYTES = 1_000_000


class _ResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._title: list[str] | None = None
        self._href = ""
        self._snippet: list[str] | None = None
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._title = []
            self._href = attrs.get("href") or ""
        elif "result__snippet" in classes:
            self._snippet = []
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._title is not None:
            title = " ".join("".join(self._title).split())
            url = _destination(self._href)
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._title = None
        if self._in_snippet and tag in {"a", "div", "td"}:
            self._in_snippet = False
            self._snippet = None

    def handle_data(self, data: str) -> None:
        if self._title is not None:
            self._title.append(data)
        if self._snippet is not None:
            self._snippet.append(data)
            if self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = " ".join("".join(self._snippet).split())[:600]


def _destination(raw: str) -> str:
    """Accept only ordinary HTTP(S) result destinations, never DDG redirect URLs."""
    parsed = urlparse(raw)
    if parsed.netloc.lower() == "duckduckgo.com" and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        dest = urlparse(target)
        if dest.scheme in {"http", "https"} and dest.hostname and not dest.username and not dest.password:
            return target
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
        return raw
    return ""


def search_web(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Search the public web for result titles/snippets; never fetch result pages."""
    clean = " ".join(str(query).split())
    if not clean or len(clean) > 500:
        raise ValueError("Research query must contain 1–500 characters.")
    if not 1 <= int(limit) <= 10:
        raise ValueError("Research result limit must be between 1 and 10.")
    request = Request(
        SEARCH_ENDPOINT + "?" + urlencode({"q": clean}),
        headers={"User-Agent": "BabyMind/0.4 (local personal research assistant)", "Accept": "text/html"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            if response.geturl().split("/", 3)[:3] != ["https:", "", "html.duckduckgo.com"]:
                raise RuntimeError("Search provider redirected to an unexpected host.")
            html = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception as error:
        raise RuntimeError(f"Web search failed: {error}") from error
    if len(html) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Search provider response exceeded the 1 MB safety limit.")
    parser = _ResultsParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.results:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique
