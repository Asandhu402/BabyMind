"""Exercise model streaming against a real local HTTP server and fixture bytes."""
import hashlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from babymind import first_run


class ModelDownloadHTTPTests(unittest.TestCase):
    def test_stream_and_verify_from_http_server(self):
        payload = b"BabyMind fixture - not a real model" * 1000
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'model.gguf'
                progress = []
                with patch.object(first_run, 'MODEL_URL', f'http://127.0.0.1:{server.server_address[1]}/model'), \
                     patch.object(first_run, 'MODEL_SHA256', hashlib.sha256(payload).hexdigest()), \
                     patch.object(first_run.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 9_000_000_000})()):
                    first_run._download_model(target, lambda done, total: progress.append((done, total)))
                    first_run._ensure_model(target)
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(progress[-1], (len(payload), len(payload)))
        finally:
            server.shutdown()
            server.server_close()

    def test_rejects_oversized_download_before_publishing(self):
        import io
        class Response(io.BytesIO):
            headers = {'Content-Length': '99'}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.gguf'
            with patch.object(first_run, 'MAX_MODEL_DOWNLOAD_BYTES', 10), \
                 patch.object(first_run.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 9_000_000_000})()), \
                 patch.object(first_run.urllib.request, 'urlopen', return_value=Response(b'x' * 99)):
                with self.assertRaisesRegex(RuntimeError, 'size limit'):
                    first_run._download_model(target)
            self.assertEqual(list(Path(folder).iterdir()), [])
