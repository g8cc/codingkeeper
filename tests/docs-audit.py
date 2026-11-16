#!/usr/bin/env python3
"""Failure injection for the offline documentation gate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('docs_check', ROOT / 'tests/docs-check.py')
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-docs-audit-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/README.md').write_text('[Guide](GUIDE.md)\n')
        (self.root / 'docs/GUIDE.md').write_text('# Guide\n')
        for name in DOCS.ENTRY_DOCS:
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            link = '../docs/README.md' if '/' in name else 'docs/README.md'
            path.write_text(f'[Documentation]({link})\n')
        (self.root / '.githooks').mkdir()
        (self.root / '.githooks/pre-commit').write_text('exec "$root/tests/run-all" --profile full\n')

    def test_valid_documentation_passes(self):
        self.assertEqual(DOCS.check(self.root), [])

    def test_broken_links_fail_including_references_and_encoded_names(self):
        guide = self.root / 'docs/GUIDE.md'
        guide.write_text('[bad](missing.md)\n[bad2][id]\n[id]: missing%20file.md\n')
        errors = DOCS.check(self.root)
        self.assertTrue(any('missing.md' in error for error in errors), errors)
        self.assertTrue(any('missing%20file.md' in error for error in errors), errors)

    def test_unindexed_guide_and_missing_entry_link_fail(self):
        (self.root / 'docs/NEW.md').write_text('# New guide\n')
        (self.root / 'README.md').write_text('# Project\n')
        errors = DOCS.check(self.root)
        self.assertTrue(any('unindexed document NEW.md' in error for error in errors), errors)
        self.assertTrue(any('README.md: missing link' in error for error in errors), errors)

    def test_examples_external_links_and_anchors_are_not_fetched(self):
        (self.root / 'docs/GUIDE.md').write_text(
            '[web](https://example.invalid/missing) [section](#section)\n'
            '```md\n[example](not-a-real-file.md)\n```\n'
            '[file with spaces](<GUIDE.md>)\n')
        self.assertEqual(DOCS.check(self.root), [])

    def test_fast_hook_cannot_claim_full_submission_gate(self):
        (self.root / '.githooks/pre-commit').write_text('exec "$root/tests/run-all" syntax unit conformance\n')
        self.assertTrue(any('pre-commit' in error for error in DOCS.check(self.root)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
