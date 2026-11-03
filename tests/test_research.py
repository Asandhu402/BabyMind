import unittest
from io import BytesIO
from unittest.mock import patch

from babymind.research import (
    _SafeRedirectHandler,
    _destination,
    _validate_public_url,
    fetch_page,
    search_web,
)


class ResearchTests(unittest.TestCase):
    def test_destination_rejects_non_http_and_credentials(self):
        self.assertEqual(_destination("javascript:alert(1)"), "")
        self.assertEqual(_destination("https://user:pass@example.com"), "")

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

    @patch("babymind.research.urlopen")
    def test_search_parses_result_titles_and_snippets(self, mocked):
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def geturl(self): return "https://html.duckduckgo.com/html/?q=test"
        mocked.return_value = Response(
            b'<a class="result__a" href="https://example.com">Example title</a>'
            b'<td class="result__snippet">Useful summary</td>'
        )
        results = search_web("test")
        self.assertEqual(results[0]["title"], "Example title")
        self.assertEqual(results[0]["url"], "https://example.com")
        self.assertEqual(results[0]["snippet"], "Useful summary")

    def test_public_url_validation_blocks_local_and_non_web_addresses(self):
        for url in ("http://127.0.0.1/", "http://192.168.1.1/", "file:///etc/passwd", "https://user:pass@example.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_url(url)

    @patch("babymind.research.socket.getaddrinfo")
    def test_public_url_validation_blocks_private_dns_results(self, getaddrinfo):
        getaddrinfo.return_value = [(None, None, None, None, ("10.0.0.5", 443))]
        with self.assertRaisesRegex(ValueError, "private"):
            _validate_public_url("https://example.test/")

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


if __name__ == "__main__":
    unittest.main()
