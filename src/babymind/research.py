"""Bounded public web search and safe, text-only page reading."""
from __future__ import annotations

import http.client
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen


SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
MAX_RESPONSE_BYTES = 1_000_000
MAX_PAGE_TEXT_CHARS = 12_000
PAGE_TIMEOUT_SECONDS = 12
IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}


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


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.in_title = False
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in IGNORED_TAGS:
            self.ignored_depth += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"} and not self.ignored_depth:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"} and not self.ignored_depth:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self.ignored_depth:
            self.text_parts.append(data)


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


def _public_ip_for_host(host: str, port: int) -> str:
    """Resolve once, reject non-public answers, and return an IP to pin the socket to."""
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        except OSError as error:
            raise ValueError("The website hostname could not be resolved.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Pages hosted on private, local, or reserved network addresses are blocked.")
    return str(sorted(addresses, key=lambda address: (address.version, int(address)))[0])


def _validate_public_url(url: str) -> None:
    """Reject non-web URLs and hosts that resolve to non-public IP addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP or HTTPS web pages can be read.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    expected_port = 443 if parsed.scheme == "https" else 80
    if parsed.port not in {None, expected_port}:
        raise ValueError("Only standard HTTP and HTTPS ports can be accessed.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local network hostnames are not allowed.")
    _public_ip_for_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, *args, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = _public_ip_for_host(self.host, self.port)

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *args, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = _public_ip_for_host(self.host, self.port)

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PinnedHTTPConnection, request)


class _PinnedHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(
            _PinnedHTTPSConnection, request,
            context=self._context
        )


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _validate_public_url(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def search_web(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Search the public web for result titles/snippets."""
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


def fetch_page(url: str) -> dict[str, str | int]:
    """Fetch one public HTML/text page as bounded plain text; never execute page code."""
    _validate_public_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "BabyMind/0.4 (local personal research assistant)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        },
    )
    opener = build_opener(ProxyHandler({}), _PinnedHTTPHandler(), _PinnedHTTPSHandler(), _SafeRedirectHandler())
    try:
        with opener.open(request, timeout=PAGE_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            _validate_public_url(final_url)
            content_type = response.headers.get_content_type().lower()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError("Only HTML and plain-text web pages can be read.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError(f"Could not read the web page: {error}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Web page exceeded the 1 MB safety limit.")
    charset = response.headers.get_content_charset() or "utf-8"
    try:
        source = raw.decode(charset, errors="replace")
    except LookupError:
        source = raw.decode("utf-8", errors="replace")
    parser = _PageParser()
    parser.feed(source)
    title = " ".join("".join(parser.title_parts).split())[:300]
    text = " ".join("".join(parser.text_parts).split())
    if not text:
        raise ValueError("No readable text was found on this page.")
    truncated = len(text) > MAX_PAGE_TEXT_CHARS
    return {
        "url": final_url,
        "title": title or final_url,
        "text": text[:MAX_PAGE_TEXT_CHARS],
        "bytes": len(raw),
        "truncated": int(truncated),
        "notice": "Page text is untrusted third-party content. Scripts were not executed."
    }
