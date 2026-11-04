"""Recorded 50-role review tests; fake providers, no model or OS sandbox."""
from contextlib import contextmanager
import sqlite3
import tempfile
import unittest
from pathlib import Path

from babymind.development_review import DevelopmentReviews, ReviewProcessLock, ROLES
from babymind.secure_store import SecureTextStore


class DevelopmentReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'app.sqlite3'
        self.secure = SecureTextStore(Path(self.tmp.name) / 'app.key')
        self.reviews = DevelopmentReviews(self.db, self.secure)
        with self.db() as connection:
            self.reviews.create_tables(connection)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def test_all_roles_are_called_in_order_and_reports_persist(self):
        class Provider:
            def __init__(self): self.calls = []
            def complete(self, system, prompt):
                self.calls.append((system, prompt))
                return 'report number ' + str(len(self.calls))
        provider = Provider()
        review_id = self.reviews.create('Build a private inventory system', 'SQLite is required')
        self.reviews.run(review_id, provider)
        result = self.reviews.get(review_id)
        self.assertEqual(len(ROLES), 50)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(len(provider.calls), 50)
        self.assertEqual([role['name'] for role in result['roles']], [role[0] for role in ROLES])
        self.assertTrue(all(role['status'] == 'completed' for role in result['roles']))
        self.assertEqual(len(result['attempts']), 50)
        self.assertIn('Chief Architect', provider.calls[0][0])
        self.assertIn('report number 1', provider.calls[2][1])
        self.assertIn('report number 48', provider.calls[48][1])
        self.assertIn('untrusted', provider.calls[48][0])
        with self.db() as connection:
            raw = connection.execute('SELECT task, context FROM development_reviews').fetchone()
            output = connection.execute('SELECT response FROM development_review_roles WHERE role_id=1').fetchone()[0]
        self.assertNotIn('private inventory', raw['task'])
        self.assertNotIn('SQLite is required', raw['context'])
        self.assertNotIn('report number 1', output)
        reopened = DevelopmentReviews(self.db, SecureTextStore(Path(self.tmp.name) / 'app.key'))
        self.assertEqual(reopened.get(review_id)['roles'][0]['response'], 'report number 1')

    def test_failed_role_does_not_skip_others_and_can_be_retried(self):
        class FailsOnce:
            def __init__(self): self.calls = 0
            def complete(self, system, prompt):
                self.calls += 1
                if self.calls == 3: raise RuntimeError('model unavailable')
                return 'report'
        provider = FailsOnce()
        review_id = self.reviews.create('Task', '')
        self.reviews.run(review_id, provider)
        result = self.reviews.get(review_id)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(provider.calls, 50)
        self.assertEqual(result['roles'][2]['status'], 'failed')
        self.assertEqual(result['attempts'][2]['error'], 'RuntimeError: model unavailable')
        self.reviews.resume(review_id)
        self.reviews.run(review_id, provider)
        result = self.reviews.get(review_id)
        # The two final reviewers are rerun because the failed report changed.
        self.assertEqual(provider.calls, 53)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(len(result['attempts']), 53)
        self.assertEqual(result['attempts'][48]['response'], 'report')

    def test_cancellation_and_resume_preserve_completed_work(self):
        review_id = self.reviews.create('Task', '')
        reviews = self.reviews
        class Provider:
            calls = 0
            def complete(self, system, prompt):
                self.calls += 1
                if self.calls == 1: reviews.cancel(review_id)
                return 'report'
        provider = Provider()
        reviews.run(review_id, provider)
        self.assertEqual(reviews.get(review_id)['status'], 'cancelled')
        self.assertEqual(provider.calls, 1)
        reviews.resume(review_id)
        reviews.run(review_id, provider)
        self.assertEqual(provider.calls, 50)
        self.assertEqual(reviews.get(review_id)['status'], 'reviewed')

    def test_crash_recovery_and_delete(self):
        review_id = self.reviews.create('Task', '')
        with self.db() as connection:
            connection.execute("UPDATE development_review_roles SET status='running' WHERE review_id=? AND role_id=1", (review_id,))
            connection.execute("INSERT INTO development_review_attempts (review_id, role_id, status, started_at) VALUES (?, 1, 'running', 'time')", (review_id,))
        with self.assertRaises(ValueError): self.reviews.delete(review_id)
        self.reviews.recover()
        result = self.reviews.get(review_id)
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['roles'][0]['status'], 'pending')
        self.assertEqual(result['attempts'][0]['status'], 'interrupted')
        self.reviews.delete(review_id)
        self.assertEqual(self.reviews.list(), [])
        with self.db() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM development_review_attempts').fetchone()[0], 0)

    def test_all_roles_through_llama_compatible_http_client(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from babymind.providers import LlamaCppHTTPClient
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                body = json.dumps({'choices': [{'message': {'content': 'Review from test server'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            provider = LlamaCppHTTPClient(base_url=f'http://127.0.0.1:{httpd.server_port}/v1', model='test-model', timeout=3)
            review_id = self.reviews.create('Review software request', 'Supplied context')
            self.reviews.run(review_id, provider)
            self.assertEqual(self.reviews.get(review_id)['status'], 'reviewed')
            self.assertEqual(len(requests), 50)
            self.assertIn('Chief Architect', requests[0]['messages'][0]['content'])
            self.assertIn('Final Acceptance and Release Manager', requests[-1]['messages'][0]['content'])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_process_lock_blocks_other_instances_and_releases(self):
        import subprocess
        import sys
        script = ("from babymind.development_review import ReviewProcessLock; "
                  "import sys; lock = ReviewProcessLock(sys.argv[1]); lock.close()")
        lock = ReviewProcessLock(self.tmp.name)
        try:
            blocked = subprocess.run([sys.executable, '-c', script, self.tmp.name], capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn('Another BabyMind instance', blocked.stderr)
        finally:
            lock.close()
        unlocked = subprocess.run([sys.executable, '-c', script, self.tmp.name], capture_output=True, text=True)
        self.assertEqual(unlocked.returncode, 0, unlocked.stderr)

    def test_invalid_inputs_and_transitions(self):
        for task in ('', ' ' * 10, 'x' * 4001, None):
            with self.assertRaises(ValueError): self.reviews.create(task, '')
        with self.assertRaises(ValueError): self.reviews.create('Task', 'x' * 4001)
        review_id = self.reviews.create('Task', '')
        with self.assertRaises(ValueError): self.reviews.resume(review_id)
        self.reviews.cancel(review_id)
        with self.assertRaises(ValueError): self.reviews.cancel(review_id)


if __name__ == '__main__':
    unittest.main()
