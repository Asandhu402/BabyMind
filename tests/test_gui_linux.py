"""Real Qt GUI smoke test, opt-in on a Linux host with desktop libraries.

Serves the actual BabyMind web assets from a local fixture HTTP server.
It does not start a model, the backend API, or production inference.
"""
import os
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@unittest.skipUnless(os.environ.get("BABYMIND_GUI_TEST") == "1", "requires a graphical Linux test host")
class LinuxGuiTests(unittest.TestCase):
    def test_qt_window_loads_local_app_and_blocks_external_navigation(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWidgets import QApplication
        from babymind.desktop import _create_window

        web = Path(__file__).resolve().parents[1] / "src" / "babymind" / "web"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import urlparse
                path = urlparse(self.path).path
                if path == "/":
                    file = web / "index.html"
                elif path.startswith("/assets/"):
                    file = web / Path(path).name
                else:
                    self.send_error(503, "Model and APIs are not part of this GUI smoke test")
                    return
                if not file.is_file():
                    self.send_error(404)
                    return
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                if file.suffix == ".js":
                    self.send_header("Content-Type", "application/javascript")
                elif file.suffix == ".css":
                    self.send_header("Content-Type", "text/css")
                else:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        app = QApplication.instance() or QApplication([])
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        view = _create_window(server.server_address[1])
        loaded = []
        view.loadFinished.connect(loaded.append)
        view.show()
        try:
            deadline = time.monotonic() + 30
            while not loaded and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            self.assertEqual(loaded, [True], "Qt failed to load the local fixture")
            self.assertEqual(view.title(), "BabyMind — Your intelligence, unified")
            dom = []
            view.page().runJavaScript("Boolean(document.querySelector('#newChat'))", dom.append)
            deadline = time.monotonic() + 5
            while not dom and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            self.assertEqual(dom, [True], "The real BabyMind interface was not rendered")
            self.assertFalse(view.page().acceptNavigationRequest(
                QUrl("https://example.com"), QWebEnginePage.NavigationType.NavigationTypeOther, True))
        finally:
            view.close()
            server.shutdown()
            server.server_close()
