#!/usr/bin/env python3
"""Offline documentation gate: local links, discoverability and entry contracts.

No network checks. Code fences are ignored; absolute machine paths and external
URLs are examples, not repository links. Historical evidence is checked for
link integrity, not rewritten to match current runtime defaults.
"""
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENTRY_DOCS = ('README.md', 'README.zh-CN.md', 'AGENTS.md', 'CONTRIBUTING.md',
              'tests/README.md', 'CHANGELOG.md')
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+["\'][^\n]*["\'])?\s*\)')
REFERENCE = re.compile(r'^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)', re.M)


def prose(text):
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return '\n'.join(lines)


def local_targets(path, root):
    text = prose(path.read_text())
    for match in list(LINK.finditer(text)) + list(REFERENCE.finditer(text)):
        target = match[1].strip('<>')
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith('/'):
            continue
        resolved = (path.parent / unquote(parsed.path)).resolve()
        yield target, resolved


def check(root=ROOT):
    root = root.resolve()
    errors = []
    documents = [root / name for name in ENTRY_DOCS]
    documents += sorted((root / 'docs').rglob('*.md'))
    for path in documents:
        if not path.is_file():
            errors.append(f'missing entry document: {path.relative_to(root)}')
            continue
        for label, target in local_targets(path, root):
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f'{path.relative_to(root)}: broken local link {label}')
    index = root / 'docs/README.md'
    if index.is_file():
        indexed = {target for _, target in local_targets(index, root)}
        for document in sorted((root / 'docs').glob('*.md')):
            if document != index and document.resolve() not in indexed:
                errors.append(f'docs/README.md: unindexed document {document.name}')
        for name in ('README.md', 'README.zh-CN.md', 'AGENTS.md', 'CONTRIBUTING.md', 'tests/README.md'):
            path = root / name
            if path.is_file() and index.resolve() not in {p for _, p in local_targets(path, root)}:
                errors.append(f'{name}: missing link to docs/README.md')
    else:
        errors.append('missing documentation index: docs/README.md')
    # These are executable policy contracts, not historical prose expectations.
    hook = root / '.githooks/pre-commit'
    if not hook.is_file() or not re.search(r'^exec .*tests/run-all["\s]+--profile full\s*$', hook.read_text(), re.M):
        errors.append('pre-commit must execute tests/run-all --profile full')
    return errors


if __name__ == '__main__':
    errors = check()
    for error in errors:
        print('FAIL: ' + error)
    if not errors:
        print('PASS: documentation links, index and full pre-commit contract')
    raise SystemExit(bool(errors))
