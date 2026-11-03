import unittest
from unittest.mock import patch
from io import BytesIO

from babymind.research import _destination, search_web


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


if __name__ == "__main__":
    unittest.main()
