import unittest
from io import BytesIO
from unittest.mock import patch

from babymind.research import (
    github_repository,
    github_search,
    license_policy,
    _PinnedHTTPSHandler,
    _SafeRedirectHandler,
    _SearchRedirectHandler,
    _destination,
    _validate_public_url,
    fetch_page,
    search_web,
)


class ResearchTests(unittest.TestCase):
    def test_destination_rejects_non_http_and_credentials(self):
        self.assertEqual(_destination("javascript:alert(1)"), "")
        self.assertEqual(_destination("https://user:pass@example.com"), "")
        self.assertEqual(_destination("https://[malformed"), "")
        self.assertEqual(_destination("https://duckduckgo.com/l/?uddg=https%3A%2F%2F%5Bmalformed"), "")

    def test_destination_unwraps_duckduckgo_redirect(self):
        self.assertEqual(
            _destination("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx"),
            "https://example.com/x",
        )

    def test_query_validation(self):
        with self.assertRaises(ValueError):
            search_web("")
        with self.assertRaises(ValueError):
            search_web("valid", 11)

    @patch("babymind.research.build_opener")
    def test_search_parses_result_titles_and_snippets(self, mocked):
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def geturl(self): return "https://html.duckduckgo.com/html/?q=test"
        mocked.return_value.open.return_value = Response(
            b'<a class="result__a" href="https://example.com">Example title</a>'
            b'<td class="result__snippet">Useful summary</td>'
        )
        results = search_web("test")
        self.assertEqual(results[0]["title"], "Example title")
        self.assertEqual(results[0]["url"], "https://example.com")
        self.assertEqual(results[0]["snippet"], "Useful summary")

    def test_public_url_validation_blocks_local_and_non_web_addresses(self):
        for url in ("http://127.0.0.1/", "http://192.168.1.1/", "file:///etc/passwd", "https://user:pass@example.com/", "https://example.com:80/", "http://example.com:443/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_url(url)

    @patch("babymind.research.socket.getaddrinfo")
    def test_public_url_validation_blocks_private_dns_results(self, getaddrinfo):
        getaddrinfo.return_value = [(None, None, None, None, ("10.0.0.5", 443))]
        with self.assertRaisesRegex(ValueError, "private"):
            _validate_public_url("https://example.test/")

    def test_pinned_https_handler_uses_supported_python_tls_arguments(self):
        handler = _PinnedHTTPSHandler()
        with patch.object(handler, "do_open", return_value="ok") as do_open:
            self.assertEqual(handler.https_open(object()), "ok")
        self.assertIn("context", do_open.call_args.kwargs)
        self.assertNotIn("check_hostname", do_open.call_args.kwargs)

    def test_search_redirect_rejects_other_hosts_before_following(self):
        handler = _SearchRedirectHandler()
        request = type("RequestStub", (), {"full_url": "https://html.duckduckgo.com/html/"})()
        for url in ("http://127.0.0.1/", "https://example.com/", "https://user@html.duckduckgo.com/",
                    "https://html.duckduckgo.com:8443/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "Found", {}, url)

    def test_redirect_handler_rejects_private_redirect_target(self):
        handler = _SafeRedirectHandler()
        request = type("RequestStub", (), {"full_url": "https://public.example/"})()
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/admin")

    @patch("babymind.research.build_opener")
    @patch("babymind.research._validate_public_url")
    def test_page_reader_extracts_text_without_scripts_navigation_or_forms(self, validate, build):
        class Headers:
            def get_content_type(self): return "text/html"
            def get_content_charset(self): return "utf-8"
        class Response(BytesIO):
            headers = Headers()
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def geturl(self): return "https://example.com/article"
        class Opener:
            def open(self, request, timeout):
                self.timeout = timeout
                return Response(
                    b"<html><head><title>Useful article</title><script>ignore secret</script></head>"
                    b"<body><nav>navigation</nav><h1>Heading</h1><p>Readable paragraph.</p>"
                    b"<form>password form</form></body></html>"
                )
        opener = Opener()
        build.return_value = opener
        result = fetch_page("https://example.com/article")
        self.assertEqual(result["title"], "Useful article")
        self.assertIn("Readable paragraph.", result["text"])
        self.assertNotIn("ignore secret", result["text"])
        self.assertNotIn("navigation", result["text"])
        self.assertNotIn("password form", result["text"])
        self.assertEqual(opener.timeout, 12)
        self.assertTrue(validate.call_count >= 2)

    @patch("babymind.research.build_opener")
    @patch("babymind.research._validate_public_url")
    def test_page_reader_rejects_non_text_content(self, validate, build):
        class Headers:
            def get_content_type(self): return "image/png"
            def get_content_charset(self): return "utf-8"
        class Response(BytesIO):
            headers = Headers()
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def geturl(self): return "https://example.com/image.png"
        class Opener:
            def open(self, request, timeout): return Response(b"image")
        build.return_value = Opener()
        with self.assertRaisesRegex(ValueError, "HTML and plain-text"):
            fetch_page("https://example.com/image.png")


class GitHubResearchTests(unittest.TestCase):
    def test_licence_policy_classifies_common_licences(self) -> None:
        self.assertTrue(license_policy("MIT")["allowed"])
        self.assertTrue(license_policy("Apache-2.0")["allowed"])
        self.assertFalse(license_policy("GPL-3.0")["allowed"])
        self.assertFalse(license_policy(None)["allowed"])
        self.assertFalse(license_policy("Weird-1.0")["allowed"])

    def test_search_summarises_results_with_licence_policy(self) -> None:
        payload = {"items": [{
            "full_name": "example/tool", "html_url": "https://github.com/example/tool",
            "description": "A tool", "stargazers_count": 42, "pushed_at": "2026-01-01T00:00:00Z",
            "archived": False, "license": {"spdx_id": "MIT"},
        }]}
        with patch("babymind.research._github_json", return_value=payload) as mocked:
            results = github_search("local llm", limit=3)
        self.assertIn("search/repositories", mocked.call_args[0][0])
        self.assertEqual(results[0]["name"], "example/tool")
        self.assertTrue(results[0]["license"]["allowed"])

    def test_search_limits_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            github_search("x", limit=50)
        with self.assertRaises(ValueError):
            github_search("   ", limit=3)

    def test_repository_metadata_is_read_only(self) -> None:
        payload = {
            "full_name": "example/tool", "html_url": "https://github.com/example/tool",
            "description": "A tool", "stargazers_count": 10, "forks_count": 2,
            "open_issues_count": 3, "pushed_at": "2026-01-01T00:00:00Z", "archived": False,
            "default_branch": "main", "license": {"spdx_id": "GPL-3.0"},
        }
        with patch("babymind.research._github_json", return_value=payload):
            repo = github_repository("example", "tool")
        self.assertEqual(repo["default_branch"], "main")
        self.assertFalse(repo["license"]["allowed"])
        self.assertIn("Metadata only", repo["notice"])

    def test_repository_names_are_validated(self) -> None:
        for owner, repo in (("../../etc", "passwd"), ("ok", "bad name"), ("", "x")):
            with self.subTest(owner=owner, repo=repo), self.assertRaises(ValueError):
                github_repository(owner, repo)

    def test_github_rate_limit_is_reported_clearly(self) -> None:
        from urllib.error import HTTPError

        error = HTTPError("https://api.github.com", 403, "Forbidden", {}, None)
        with patch("babymind.research.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "rate limit"):
                github_repository("example", "tool")


if __name__ == "__main__":
    unittest.main()
