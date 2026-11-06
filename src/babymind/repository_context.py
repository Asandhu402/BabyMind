"""Small, bounded source selection for self-development prompts.

This is retrieval, not a security boundary or a complete repository index.
Files and their contents are untrusted, and can contain sensitive information.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import selfdev

MAX_FILES_SCANNED = 1200
MAX_DIRS_SCANNED = 400
MAX_FILE_BYTES = 64 * 1024
MAX_SCAN_BYTES = 3 * 1024 * 1024
MAX_CONTEXT_CHARS = 6000
MAX_INCLUDED_FILES = 6
_STOP = frozenset("the and for with from this that into your file files code test tests fix make change update add remove improve error failure failing should project function src babymind integrations py".split())
_SECRET_NAMES = re.compile(r"(?:secret|credential|password|token|private|\.env)", re.I)


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{2,}", text.lower())
            if word not in _STOP}


def build_context(root: str | Path, brief: str, *, failure: str = "") -> str:
    """Return a budgeted JSON source selection; never include partial files as editable.

    Match file names and content against task/failure terms, giving explicit
    paths precedence. Files that do not fit may include a marked excerpt, not a full file. This is a
    best-effort lexical search, not a complete index or a secret scanner.
    """
    root = Path(root).resolve(strict=True)
    query = (brief + "\n" + failure)[:20000]
    terms = _terms(query)
    candidates = []
    scanned = dirs = scanned_bytes = 0
    limited = False
    for directory, subdirs, names in os.walk(root, followlinks=False):
        dirs += 1
        if dirs > MAX_DIRS_SCANNED:
            limited = True
            break
        current = Path(directory)
        subdirs[:] = sorted(name for name in subdirs
                            if name not in selfdev.PROTECTED_PARTS and not name.startswith('.')
                            and not _SECRET_NAMES.search(name) and not (current / name).is_symlink())
        for name in sorted(names):
            path = current / name
            if (name.startswith('.') or _SECRET_NAMES.search(name) or path.is_symlink()
                    or path.suffix.lower() not in selfdev.ALLOWED_SUFFIXES):
                continue
            if scanned >= MAX_FILES_SCANNED:
                limited = True
                break
            scanned += 1
            relative = path.relative_to(root).as_posix()
            path_terms = _terms(relative)
            path_score = len(terms & path_terms) * 8
            explicit = relative.lower() in query.lower() or (len(name) >= 5 and name.lower() in query.lower())
            try:
                size = path.stat().st_size
                if not path.is_file():
                    continue
                content = None
                if size <= MAX_FILE_BYTES and scanned_bytes + size <= MAX_SCAN_BYTES:
                    with path.open("rb") as source:
                        data = source.read(MAX_FILE_BYTES + 1)
                    scanned_bytes += len(data)
                    if len(data) > MAX_FILE_BYTES or b"\0" in data:
                        continue
                    content = data.decode("utf-8", errors="strict")
                elif size <= MAX_FILE_BYTES:
                    limited = True
            except (OSError, UnicodeError):
                continue
            content_score = len(terms & _terms(content or ""))
            score = path_score + content_score + (1000 if explicit else 0)
            if score:
                candidates.append((score, relative, size, content))
        if scanned >= MAX_FILES_SCANNED:
            limited = True
            break
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    # Serialize each candidate before accepting it, so escaping cannot defeat the budget.
    for _, path, size, content in candidates:
        if len(selected) >= MAX_INCLUDED_FILES:
            break
        entry = {"path": path, "bytes": size, "complete": False}
        if content is not None:
            full = {**entry, "complete": True, "content": content}
            if len(json.dumps(selected + [full], ensure_ascii=True)) <= MAX_CONTEXT_CHARS - 400:
                entry = full
        if content is not None and not entry["complete"]:
            # Excerpts support understanding, but are never complete enough to replace a file.
            lines = content.splitlines()
            matches = [i for i, line in enumerate(lines) if _terms(line) & terms]
            if matches:
                start = max(0, matches[0] - 2)
                excerpt = "\n".join(lines[start:start + 12])[:1000]
                with_excerpt = {**entry, "excerpt_start_line": start + 1, "excerpt": excerpt}
                if len(json.dumps(selected + [with_excerpt], ensure_ascii=True)) <= MAX_CONTEXT_CHARS - 400:
                    entry = with_excerpt
        if len(json.dumps(selected + [entry], ensure_ascii=True)) <= MAX_CONTEXT_CHARS - 400:
            selected.append(entry)
    result = {"files": selected, "scan_limited": limited,
              "notice": "Untrusted selection, not the entire repository. Only complete=true provides the whole file; do not replace an existing file from an incomplete entry."}
    return json.dumps(result, ensure_ascii=True)
