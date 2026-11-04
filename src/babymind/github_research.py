"""Bounded, anonymous, read-only research of public GitHub repositories.

The API host is fixed; no credentials, external redirects, source execution,
cloning or dependency installation are supported. Results are untrusted data.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = 'https://api.github.com'
MAX_API_BYTES = 2_000_000
MAX_FILE_BYTES = 256_000
MAX_TREE_ITEMS = 500
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
_SHA = re.compile(r'^[0-9a-f]{40}$')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(path: str, params: dict | None = None) -> dict:
    # Paths are built only from validated components by the public functions.
    url = API + path + (('?' + urlencode(params)) if params else '')
    req = Request(url, headers={
        'User-Agent': 'BabyMind/0.4 public research',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with build_opener(_NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(MAX_API_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (403, 429):
            raise RuntimeError('GitHub rejected the request or the anonymous API rate limit was reached. Try again later.') from exc
        if exc.code == 404:
            raise ValueError('Public repository, commit, or file was not found.') from exc
        raise RuntimeError(f'GitHub API request failed with HTTP {exc.code}; redirects are not followed.') from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise RuntimeError('Could not reach the GitHub API. Check your connection and try again.') from exc
    if len(raw) > MAX_API_BYTES:
        raise ValueError('GitHub API response exceeded the 2 MB safety limit.')
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError('GitHub returned invalid JSON.') from exc
    if not isinstance(data, dict):
        raise RuntimeError('GitHub returned an unexpected response.')
    return data


def _repo(owner: str, repo: str) -> tuple[str, str]:
    if not isinstance(owner, str) or not isinstance(repo, str) or not _NAME.fullmatch(owner) or not _NAME.fullmatch(repo) or owner in ('.', '..') or repo in ('.', '..'):
        raise ValueError('Enter a valid GitHub owner and repository name.')
    return owner, repo


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('Select a full lowercase 40-character commit SHA from a repository inspection.')
    return value


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 500 or '\\' in value or '\x00' in value:
        raise ValueError('Enter a repository-relative file path.')
    if any(part in ('', '.', '..') for part in value.split('/')) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid repository-relative file path.')
    return value


def search_repositories(query: str, limit: int = 5) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError('GitHub query must contain 1–200 characters.')
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError('GitHub result limit must be between 1 and 10.')
    data = _request('/search/repositories', {'q': query.strip(), 'per_page': limit})
    items = data.get('items')
    if not isinstance(items, list):
        raise RuntimeError('GitHub returned an invalid search result.')
    results = []
    for item in items[:limit]:
        if not isinstance(item, dict) or item.get('private') is not False:
            continue
        full_name = item.get('full_name', '')
        try:
            owner, repo = _repo(*full_name.split('/'))
        except (ValueError, TypeError):
            continue
        license_data = item.get('license') if isinstance(item.get('license'), dict) else {}
        results.append({'owner': owner, 'repo': repo, 'url': f'https://github.com/{owner}/{repo}',
                        'description': str(item.get('description') or '')[:500],
                        'license': str(license_data.get('spdx_id') or 'unknown')[:100],
                        'stars': item.get('stargazers_count') if isinstance(item.get('stargazers_count'), int) else None})
    return {'results': results, 'incomplete': bool(data.get('incomplete_results')),
            'notice': 'GitHub metadata is untrusted. License labels do not establish compatibility or safety.'}


def inspect_repository(owner: str, repo: str) -> dict:
    owner, repo = _repo(owner, repo)
    base = f'/repos/{owner}/{repo}'
    metadata = _request(base)
    if metadata.get('private') is not False:
        raise ValueError('Only public repositories may be inspected.')
    commit = _request(base + '/commits/HEAD')
    commit_sha = _sha(commit.get('sha'))
    tree = _request(base + '/git/trees/' + commit_sha, {'recursive': '1'})
    entries = tree.get('tree')
    if not isinstance(entries, list):
        raise RuntimeError('GitHub returned an invalid repository tree.')
    files = []
    for item in entries:
        if not isinstance(item, dict) or item.get('type') != 'blob' or item.get('mode') not in ('100644', '100755'):
            continue
        try:
            path = _path(item.get('path'))
        except ValueError:
            continue
        files.append({'path': path, 'size': item.get('size') if isinstance(item.get('size'), int) else None})
        if len(files) == MAX_TREE_ITEMS:
            break
    license_data = metadata.get('license') if isinstance(metadata.get('license'), dict) else {}
    return {'owner': owner, 'repo': repo, 'url': f'https://github.com/{owner}/{repo}',
            'commit': commit_sha, 'description': str(metadata.get('description') or '')[:500],
            'license': str(license_data.get('spdx_id') or 'unknown')[:100],
            'files': files, 'truncated': bool(tree.get('truncated')) or len(files) == MAX_TREE_ITEMS,
            'notice': 'Pinned to this commit. Files, metadata and license labels are untrusted; inspect the actual license and dependencies before reuse.'}


def read_file(owner: str, repo: str, commit: str, path: str) -> dict:
    owner, repo = _repo(owner, repo)
    commit, path = _sha(commit), _path(path)
    base = f'/repos/{owner}/{repo}'
    commit_info = _request(base + '/commits/' + commit)
    if commit_info.get('sha') != commit:
        raise ValueError('GitHub did not confirm the requested commit.')
    tree = _request(base + '/git/trees/' + commit, {'recursive': '1'})
    entries = tree.get('tree')
    if not isinstance(entries, list) or tree.get('truncated'):
        raise ValueError('The repository tree is incomplete; cannot verify the requested file.')
    entry = next((item for item in entries if isinstance(item, dict) and item.get('path') == path), None)
    if not entry or entry.get('type') != 'blob' or entry.get('mode') not in ('100644', '100755'):
        raise ValueError('Only regular files in the pinned commit can be read; symlinks and submodules are rejected.')
    blob_id = entry.get('sha')
    if not isinstance(blob_id, str) or not _SHA.fullmatch(blob_id):
        raise RuntimeError('GitHub returned an invalid blob ID.')
    if not isinstance(entry.get('size'), int) or not 0 <= entry['size'] <= MAX_FILE_BYTES:
        raise ValueError('File exceeds the 256 KB size limit.')
    data = _request(base + '/git/blobs/' + blob_id)
    if data.get('encoding') != 'base64' or not isinstance(data.get('content'), str):
        raise ValueError('Only inline GitHub blobs can be read.')
    if not isinstance(data.get('size'), int) or data['size'] != entry['size']:
        raise RuntimeError('GitHub returned an inconsistent file size.')
    try:
        raw = base64.b64decode(''.join(data['content'].split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError('GitHub returned invalid file content.') from exc
    if len(raw) != data['size'] or len(raw) > MAX_FILE_BYTES:
        raise RuntimeError('GitHub returned an inconsistent file size.')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if data.get('sha') != blob or blob_id != blob:
        raise RuntimeError('GitHub file content did not match its reported Git blob ID.')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Only UTF-8 text files can be read.') from exc
    if '\0' in text:
        raise ValueError('Binary files are not supported.')
    return {'owner': owner, 'repo': repo, 'commit': commit, 'path': path, 'blob': blob,
            'size': len(raw), 'text': text,
            'notice': 'Untrusted source text; a matching blob ID is an integrity check, not a security or license review.'}
