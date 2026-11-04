"""Public GitHub research: request limits, pinned blobs and failure cases."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from babymind import github_research as github

COMMIT = '1' * 40
CONTENT = b'hello from repository\n'
BLOB = hashlib.sha1(b'blob ' + str(len(CONTENT)).encode() + b'\0' + CONTENT).hexdigest()


def tree_entry(mode='100644', sha=BLOB, size=len(CONTENT), path='src/test.py'):
    return {'path': path, 'type': 'blob', 'mode': mode, 'sha': sha, 'size': size}


def api_data(path, params=None):
    if path == f'/repos/owner/repo/commits/{COMMIT}': return {'sha': COMMIT}
    if path == f'/repos/owner/repo/git/trees/{COMMIT}': return {'tree': [tree_entry()], 'truncated': False}
    if path == f'/repos/owner/repo/git/blobs/{BLOB}':
        return {'encoding': 'base64', 'content': base64.b64encode(CONTENT).decode(), 'sha': BLOB, 'size': len(CONTENT)}
    raise AssertionError(path)


class GitHubResearchTests(unittest.TestCase):
    def test_search_filters_private_and_invalid_results(self):
        response = {'items': [
            {'full_name': 'owner/repo', 'private': False, 'description': 'Tool', 'license': {'spdx_id': 'MIT'}, 'stargazers_count': 5},
            {'full_name': 'owner/private', 'private': True},
            {'full_name': '../bad', 'private': False},
        ], 'incomplete_results': True}
        with patch.object(github, '_request', return_value=response) as request:
            result = github.search_repositories('local tool', 5)
        self.assertEqual([x['repo'] for x in result['results']], ['repo'])
        self.assertTrue(result['incomplete'])
        self.assertIn('do not establish', result['notice'])
        self.assertEqual(request.call_args.args[0], '/search/repositories')

    def test_invalid_parameters_are_rejected_before_network(self):
        with patch.object(github, '_request') as request:
            for owner, repo in [('../private', 'x'), ('x', 'foo/bar'), ('evil.com@x', 'x'), ('', 'x')]:
                with self.subTest(owner=owner, repo=repo), self.assertRaises(ValueError):
                    github.inspect_repository(owner, repo)
            for path in ['../secret', '/absolute', 'x//y', 'x/../y', 'x\\secret', 'x\0y']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    github.read_file('owner', 'repo', COMMIT, path)
            with self.assertRaises(ValueError): github.read_file('owner', 'repo', 'main', 'README')
            with self.assertRaises(ValueError): github.search_repositories('query', True)
            request.assert_not_called()

    def test_inspect_pins_head_and_filters_symlinks_and_submodules(self):
        def response(path, params=None):
            if path == '/repos/owner/repo': return {'private': False, 'license': {'spdx_id': 'MIT'}}
            if path == '/repos/owner/repo/commits/HEAD': return {'sha': COMMIT}
            return {'tree': [tree_entry(), tree_entry('120000', path='link'), {'type':'commit','path':'submodule'}, tree_entry(path='../bad')]}
        with patch.object(github, '_request', side_effect=response):
            info = github.inspect_repository('owner', 'repo')
        self.assertEqual(info['commit'], COMMIT)
        self.assertEqual(info['files'], [{'path':'src/test.py', 'size':len(CONTENT)}])
        self.assertEqual(info['license'], 'MIT')

    def test_read_pinned_regular_file_checks_blob_integrity(self):
        with patch.object(github, '_request', side_effect=api_data):
            result = github.read_file('owner', 'repo', COMMIT, 'src/test.py')
        self.assertEqual(result['text'], CONTENT.decode())
        self.assertEqual(result['blob'], BLOB)
        self.assertEqual(result['commit'], COMMIT)

    def test_rejects_symlink_truncated_tree_and_modified_blob(self):
        for variant in ('symlink', 'truncated', 'wrong_hash'):
            def response(path, params=None):
                data = api_data(path, params)
                if '/git/trees/' in path:
                    if variant == 'symlink': data['tree'][0]['mode'] = '120000'
                    if variant == 'truncated': data['truncated'] = True
                if '/git/blobs/' in path and variant == 'wrong_hash': data['sha'] = '2' * 40
                return data
            with self.subTest(variant=variant), patch.object(github, '_request', side_effect=response):
                with self.assertRaises((ValueError, RuntimeError)):
                    github.read_file('owner', 'repo', COMMIT, 'src/test.py')

    def test_request_is_fixed_host_uses_no_token_and_disallows_redirects(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return Response(b'{"items": []}')
        opener = Opener()
        with patch.object(github, 'build_opener', return_value=opener) as build:
            result = github.search_repositories('safe', 2)
        self.assertEqual(result['results'], [])
        self.assertTrue(opener.request.full_url.startswith('https://api.github.com/search/repositories?'))
        self.assertFalse(opener.request.has_header('Authorization'))
        self.assertIsInstance(build.call_args.args[0], github._NoRedirect)
        self.assertIsNone(github._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1'))

    def test_request_limits_and_github_errors(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        with patch.object(github, 'build_opener') as builder:
            builder.return_value.open.return_value = Response(b'X' * (github.MAX_API_BYTES + 1))
            with self.assertRaisesRegex(ValueError, '2 MB'): github.search_repositories('query')
            builder.return_value.open.side_effect = HTTPError('https://api.github.com', 403, 'Forbidden', {}, None)
            with self.assertRaisesRegex(RuntimeError, 'rate limit'): github.search_repositories('query')


if __name__ == '__main__':
    unittest.main()
