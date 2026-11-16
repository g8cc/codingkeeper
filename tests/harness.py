#!/usr/bin/env python3
"""Harness planning and atomic reports; execution stays in the Bash 3.2 runner."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    'syntax': 'Bash syntax, Python compilation and Swift toolchain/typecheck',
    'watchdog': 'Watchdog selftests',
    'unit': 'Loop and headless embedded unit tests',
    'audit': 'Automatically discovered tests/*-audit.py regressions',
    'integration': 'Four parallel fake TUI worlds, then headless integration',
    'faultinjection': 'Process, timeout, stale-event and queue fault injection',
    'conformance': 'CLI, tmux and runtime invariants',
    'docs': 'Documentation links, navigation and repository contracts',
    'keys': 'Local binary/configuration inventory (report only)',
}
PROFILES = {'quick': ['syntax', 'unit', 'conformance', 'docs'], 'full': list(STAGES)}
INTEGRATION_TOOLS = ('codex', 'claude', 'pi', 'opencode')
SKIP = re.compile(r'^\s*SKIP:.*$|^OK \(skipped=\d+\)$|^.+ \.\.\. skipped .+$', re.M)


def audits():
    return sorted(p.name[:-len('-audit.py')] for p in (ROOT / 'tests').glob('*-audit.py'))


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def report_path():
    return Path(os.environ.get('CK_TEST_REPORT') or
                str(Path(os.environ['CK_TEST_ARTIFACTS']) / 'report.json'))


def expected_checks(stages, suites):
    checks = []
    for stage in stages:
        if stage == 'audit':
            checks.extend('audit ' + name for name in suites)
        elif stage == 'unit':
            checks.extend(('unit (loop)', 'unit (headless)'))
        elif stage == 'integration':
            checks.extend('integration ' + tool for tool in INTEGRATION_TOOLS)
            checks.append('integration headless')
        else:
            checks.append(stage)
    return checks


def initialize(stages):
    suites = os.environ.get('CK_TEST_SUITES', '').split() or audits()
    if 'audit' in stages and not suites:
        raise ValueError('audit stage cannot pass with zero discovered suites')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              capture_output=True, text=True)
    atomic_json(report_path(), {
        'schema_version': 1, 'status': 'running', 'started_at': now(),
        'repository': str(ROOT), 'revision': revision.stdout.strip() or None,
        'artifacts': os.environ['CK_TEST_ARTIFACTS'],
        'selected_stages': stages, 'audit_suites': suites if 'audit' in stages else [],
        'expected_checks': expected_checks(stages, suites), 'results': [],
        'strict_skips': os.environ.get('CK_TEST_STRICT_SKIPS') == '1',
    })


def record(stage, name, log, code, elapsed):
    path = report_path()
    data = json.loads(path.read_text())
    notices = [line.strip() for line in SKIP.findall(Path(log).read_text(errors='replace'))]
    status = ('fail' if code else 'report' if stage == 'keys' else
              'pass_with_skips' if notices else 'pass')
    data['results'].append({'stage': stage, 'name': name, 'status': status,
                            'exit_code': code, 'duration_seconds': elapsed,
                            'log': str(log), 'skip_notices': notices})
    atomic_json(path, data)
    return status


def finish(failed):
    path = report_path()
    data = json.loads(path.read_text())
    actual = [row['name'] for row in data['results']]
    missing = [name for name in data['expected_checks'] if name not in actual]
    skipped = any(row['skip_notices'] for row in data['results'])
    failed = failed or missing or any(row['exit_code'] for row in data['results'])
    if data['strict_skips'] and skipped:
        failed = True
        print('Strict coverage: skipped checks block this run.')
    data.update(status='failed' if failed else 'passed_with_skips' if skipped else 'passed',
                finished_at=now(), missing_checks=missing, exit_code=1 if failed else 0)
    atomic_json(path, data)
    if missing:
        print('Missing checks: ' + ', '.join(missing))
    if skipped:
        print('Coverage has SKIP notices; see report.json. Skipped checks are unverified.')
    print('Harness report: ' + str(path))
    return 1 if failed else 0


def parse_plan(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stages', nargs='*', help='stage subset; default: full profile')
    parser.add_argument('--profile', choices=PROFILES)
    parser.add_argument('--suite', action='append', default=[], metavar='NAME',
                        help='run a named audit; repeat to select several')
    parser.add_argument('--list', action='store_true', help='list stages, profiles and audits')
    parser.add_argument('--json', action='store_true', help='JSON inventory with --list')
    parser.add_argument('--report', type=Path, help='also retain the JSON report at this path')
    parser.add_argument('--keep-artifacts', action='store_true', help='retain successful run logs')
    parser.add_argument('--strict-skips', action='store_true', help='fail on reported coverage skips')
    args = parser.parse_args(argv)
    if args.json and not args.list:
        parser.error('--json requires --list')
    if sum((bool(args.stages), bool(args.profile), bool(args.suite))) > 1:
        parser.error('choose stages, --profile, or --suite; do not combine selectors')
    unknown = set(args.stages) - STAGES.keys()
    if unknown:
        parser.error('unknown stages: ' + ', '.join(sorted(unknown)))
    unknown = set(args.suite) - set(audits())
    if unknown:
        parser.error('unknown audits: ' + ', '.join(sorted(unknown)))
    if len(args.stages) != len(set(args.stages)):
        parser.error('duplicate stages are not allowed')
    if args.report:
        args.report = args.report.expanduser().resolve()
        # A report is generated output, never an excuse to overwrite source.
        try:
            relative = args.report.relative_to(ROOT)
        except ValueError:
            pass
        else:
            if relative.parts[0] != '.codingkeeper':
                parser.error('--report inside the repository must use .codingkeeper/')
        if args.report.exists() and not args.report.is_file():
            parser.error('--report must name a regular file')
    return args


def main(argv):
    # Private interface used by run-all; never evaluates shell text.
    if argv and argv[0].startswith('__'):
        command, *values = argv
        if command == '__start':
            initialize(values)
        elif command == '__audits':
            print('\n'.join(os.environ.get('CK_TEST_SUITES', '').split() or audits()))
        elif command == '__record':
            print(record(values[0], values[1], values[2], int(values[3]), int(values[4])))
        elif command == '__finish':
            return finish(int(values[0]))
        else:
            raise ValueError('unknown internal harness command')
        return 0
    args = parse_plan(argv)
    if args.list:
        inventory = {'stages': STAGES, 'profiles': PROFILES, 'audits': audits(),
                     'manual': ['tests/native-startup-smoke.py', 'tests/benchmark-status.py']}
        if args.json:
            print(json.dumps(inventory, indent=2))
        else:
            for name, description in STAGES.items():
                print(f'{name:16} {description}')
            for name, stages in PROFILES.items():
                print(f'profile {name}: ' + ' '.join(stages))
            print('audits: ' + ' '.join(audits()))
        return 0
    stages = args.stages or (['audit'] if args.suite else PROFILES[args.profile or 'full'])
    env = dict(os.environ)
    env.update(CK_TEST_PLAN='1', CK_TEST_SUITES=' '.join(dict.fromkeys(args.suite)),
               CK_TEST_KEEP_ARTIFACTS='1' if args.keep_artifacts else '0',
               CK_TEST_STRICT_SKIPS='1' if args.strict_skips else '0',
               CK_TEST_REPORT=str(args.report) if args.report else '')
    if env.get('CK_TEST_ISOLATED') == '1':
        os.execve('/bin/bash', ['bash', str(ROOT / 'tests/run-all'), *stages], env)
    os.execve(sys.executable, [sys.executable, str(ROOT / 'tests/isolate.py'), *stages], env)


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError) as error:
        print('harness error: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
