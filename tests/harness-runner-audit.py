#!/usr/bin/env python3
"""Exercise the public harness using a disposable repository and fake audits."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def test_ci_uses_a_macos_runner_without_retired_image_labels(self):
        workflow = (ROOT / '.github/workflows/harness.yml').read_text()
        labels = re.findall(r'^\s+runs-on:\s*["\']?([^\s"\']+)', workflow, re.M)
        self.assertTrue(labels, 'CI must select a macOS runner')
        for label in labels:
            self.assertTrue(label.startswith('macos-'), label)
            self.assertNotRegex(label, r'^macos-(?:10(?:\.\d+)?|11|12|13|14)(?:-|$)')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-runner-audit-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'tests').mkdir()
        for name in ('run-all', 'harness.py'):
            source = ROOT / 'tests' / name
            if source.exists():
                shutil.copy2(source, self.root / 'tests' / name)
        # Keep every historical suite green, then inject an undiscovered failure.
        for source in (ROOT / 'tests').glob('*-audit.py'):
            (self.root / 'tests' / source.name).write_text('raise SystemExit(0)\n')
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir()
        self.env = dict(os.environ, CK_TEST_ISOLATED='1',
                        CK_TEST_ARTIFACTS=str(self.artifacts))
        for name in ('CK_TEST_PLAN', 'CK_TEST_REPORT', 'CK_TEST_SUITES', 'CK_TEST_STRICT_SKIPS'):
            self.env.pop(name, None)

    def run_harness(self, *args, isolated=True):
        env = dict(self.env)
        if not isolated:
            env.pop('CK_TEST_ISOLATED', None)
        return subprocess.run(['bash', str(self.root / 'tests/run-all'), *args],
                              cwd=self.root, env=env, text=True, capture_output=True,
                              timeout=30)

    def test_new_audit_is_discovered_and_its_failure_blocks_the_gate(self):
        probe = self.root / 'tests/zz-injected-audit.py'
        probe.write_text('print("INJECTED_FAILURE")\nraise SystemExit(23)\n')
        result = self.run_harness('audit')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('INJECTED_FAILURE', result.stdout)
        report = json.loads((self.artifacts / 'report.json').read_text())
        failed = [row for row in report['results'] if row['exit_code'] == 23]
        self.assertEqual([row['name'] for row in failed], ['audit zz-injected'])
        self.assertEqual(report['status'], 'failed')

    def test_list_needs_no_tmux_or_artifact_directory(self):
        result = self.run_harness('--list', '--json', isolated=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        inventory = json.loads(result.stdout)
        self.assertIn('harness-runner', inventory['audits'])
        self.assertIn('docs', inventory['stages'])
        self.assertFalse(list(self.artifacts.iterdir()))

    def test_named_suite_runs_only_the_requested_audit(self):
        (self.root / 'tests/zz-injected-audit.py').write_text('raise SystemExit(23)\n')
        result = self.run_harness('--suite', 'harness-runner')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.artifacts / 'report.json').read_text())
        self.assertEqual([row['name'] for row in report['results']], ['audit harness-runner'])

    def test_skip_is_visible_and_strict_mode_fails(self):
        (self.root / 'tests/harness-runner-audit.py').write_text('print("SKIP: fixture capability unavailable")\n')
        for flags, expected in (([], 0), (['--strict-skips'], 1)):
            with self.subTest(flags=flags):
                result = self.run_harness('--suite', 'harness-runner', *flags)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                report = json.loads((self.artifacts / 'report.json').read_text())
                self.assertEqual(report['results'][0]['status'], 'pass_with_skips')
                self.assertEqual(report['status'], 'failed' if expected else 'passed_with_skips')

    def test_invalid_selector_fails_before_execution(self):
        for args in (['typo'], ['--suite', 'missing'], ['--profile', 'full', 'unit'],
                     ['audit', 'audit'], ['--json']):
            with self.subTest(args=args):
                result = self.run_harness(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(list(self.artifacts.iterdir()))

    def test_report_cannot_overwrite_repository_source(self):
        source = self.root / 'tests/harness-runner-audit.py'
        before = source.read_bytes()
        result = self.run_harness('--suite', 'harness-runner', '--report', str(source))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(source.read_bytes(), before)

    def test_report_path_is_resolved_before_private_home_changes(self):
        report = self.root / '.codingkeeper' / 'test report.json'
        result = self.run_harness('--suite', 'harness-runner', '--report', str(report))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(report.read_text())['status'], 'passed')

    def test_missing_result_cannot_be_reported_as_success(self):
        result = subprocess.run([sys.executable, str(self.root / 'tests/harness.py'),
                                 '__start', 'unit'], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([sys.executable, str(self.root / 'tests/harness.py'),
                                 '__finish', '0'], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.artifacts / 'report.json').read_text())
        self.assertEqual(report['missing_checks'], ['unit (loop)', 'unit (headless)'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
