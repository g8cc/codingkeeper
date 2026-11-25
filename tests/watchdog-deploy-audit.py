#!/usr/bin/env python3
"""Watchdog deploy regressions: midnight re-exec lock survival + launchd runtime copy.

2026-11-10 双故障回归锁:
1. 翻日 exec 曾放在 patrol_once 内, 而巡逻以 9>&- 运行 — exec 出的新实例
   fstat(9) 报 EBADF, "missing lock" 自杀, 看门狗零点必死。
2. plist 曾直指 ~/Documents 下的脚本, launchd 拉起的 bash 被 TCC 内核拒绝
   (System Policy deny file-read-data), KeepAlive 三连拒后任务被移除,
   看门狗静默死亡 15 小时。探针证实 launchd 进程对 ~/Documents 一律 DENIED。
"""
import os
import plistlib
import json
import signal
import shutil

os.environ['CODEXC_FLEET_TEMP_FILTER'] = '0'  # fixture 舰队建在临时根下 — 服务端过滤会让位
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fixture_processes import live_processes

ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parents[1]))
HOME = Path.home()


class WatchdogDeployAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix='ck-watchdog-deploy-',
            dir=os.environ.get('CK_TEST_TMP') or tempfile.gettempdir())
        self.world = Path(self.tmp.name)
        self.home = self.world / 'home'
        (self.home / '.codingkeeper').mkdir(parents=True, exist_ok=True)
        self.flock = self.home / '.codingkeeper' / 'watchdog.lock.flock'
        self.flock.touch()
        self.processes = []

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        self.tmp.cleanup()

    def plist_args(self, path):
        with open(path, 'rb') as fh:
            return plistlib.load(fh)['ProgramArguments']

    def test_fixture_worlds_are_unique_and_cleanup_preserves_other_run(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='ck-watchdog-isolation-') as base:
            with patch.dict(os.environ, {'CK_TEST_TMP': base}):
                first = WatchdogDeployAudit('test_daily_plist_script_outside_documents')
                second = WatchdogDeployAudit('test_daily_plist_script_outside_documents')
                first.setUp(); second.setUp()
                marker = second.world / 'other-run-marker'
                marker.write_text('preserve')
                try:
                    self.assertNotEqual(first.world, second.world)
                    first.tearDown()
                    self.assertEqual(marker.read_text(), 'preserve')
                finally:
                    first.tearDown(); second.tearDown()

    # ---- 静态断言 (可移植) ----

    def test_packaging_plist_script_outside_documents(self):
        args = self.plist_args(ROOT / 'packaging' / 'com.codingkeeper.watchdog.plist')
        self.assertEqual(args[0], '/bin/bash', args)
        self.assertNotIn('/Documents/', args[1],
                         'launchd 拉起的进程读不了 ~/Documents (TCC) — 运行位必须在 Documents 外')
        self.assertTrue(args[1].endswith('/.codingkeeper/bin/burn-watch.sh'),
                        '运行位应指向 ~/.codingkeeper/bin/ 副本')
        self.assertEqual(args[2], 'run')

    def test_daily_plist_script_outside_documents(self):
        # com.codexc.daily 同病: 2026-11-02 起从未跑成过 (日志五条 Operation not permitted)
        args = self.plist_args(ROOT / 'packaging' / 'com.codexc.daily.plist')
        self.assertNotIn('/Documents/', args[0],
                         'daily 脚本运行位必须在 Documents 外 (TCC)')
        self.assertTrue(args[0].endswith('/.codingkeeper/bin/codexc-daily'), args)

    def test_install_script_covers_deploy_steps(self):
        script = (ROOT / 'packaging' / 'install-watchdog.sh').read_text()
        for needle in ('atomic_copy "$repo/burn-watch.sh"', 'atomic_copy "$repo/codexc-daily"',
                       'atomic_copy "$repo/ck-watchdog-alive.sh"', 'launchctl bootout', 'launchctl bootstrap'):
            self.assertIn(needle, script)

    def test_watchdog_alive_checker_is_fda_free(self):
        """守夜员必须只碰 Documents 之外的东西, 否则 launchd 无 FDA 时它也瞎。"""
        src = (ROOT / 'ck-watchdog-alive.sh').read_text()
        self.assertNotIn('/Documents/', src, '守夜员不得依赖 Documents (TCC)')
        self.assertIn('watchdog.heartbeat', src)
        self.assertIn('-lt 900', src, '心跳 15 分钟陈旧阈值')
        self.assertIn('-lt 3600', src, '告警每小时去重')
        args = self.plist_args(ROOT / 'packaging' / 'com.codingkeeper.watchdog-alive.plist')
        self.assertNotIn('/Documents/', args[1])
        self.assertTrue(args[1].endswith('/.codingkeeper/bin/ck-watchdog-alive.sh'))

    # ---- 守夜员行为回归 (此前仅静态断言 — 舰队全盲的最后告警线必须真跑过) ----

    def run_alive_checker(self, heartbeat_age):
        (self.home / '.codingkeeper').mkdir(parents=True, exist_ok=True)
        heartbeat = self.home / '.codingkeeper' / 'watchdog.heartbeat'
        if heartbeat.exists():
            heartbeat.unlink()
        if heartbeat_age is not None:
            heartbeat.write_text(str(int(time.time()) - heartbeat_age))
        fake_bin = self.world / 'alive-fake-bin'
        fake_bin.mkdir(parents=True, exist_ok=True)
        osascript = fake_bin / 'osascript'
        osascript.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$ALIVE_NOTIFY_LOG"\n')
        osascript.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home),
                   PATH=str(fake_bin) + os.pathsep + os.environ['PATH'],
                   ALIVE_NOTIFY_LOG=str(self.world / 'notify.log'))
        result = subprocess.run([str(ROOT / 'ck-watchdog-alive.sh')], env=env,
                                capture_output=True, text=True, timeout=30)
        alerts = self.home / '.codingkeeper' / 'burn-ALERTS.txt'
        notify = self.world / 'notify.log'
        return (result,
                alerts.read_text() if alerts.exists() else '',
                notify.read_text() if notify.exists() else '')

    def test_alive_checker_silent_on_fresh_heartbeat(self):
        result, alerts, notify = self.run_alive_checker(heartbeat_age=60)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(alerts, '', '新鲜心跳不得告警')
        self.assertEqual(notify, '')

    def test_alive_checker_alerts_on_stale_heartbeat(self):
        result, alerts, notify = self.run_alive_checker(heartbeat_age=2000)
        self.assertEqual(result.returncode, 0)
        self.assertIn('心跳陈旧', alerts, '陈旧心跳必须 ALERTS 留档')
        self.assertIn('display notification', notify, '陈旧心跳必须系统通知')

    def test_alive_checker_dedups_within_the_hour(self):
        self.run_alive_checker(heartbeat_age=2000)
        _, alerts, _ = self.run_alive_checker(heartbeat_age=2000)
        self.assertEqual(alerts.count('心跳陈旧'), 1, '每小时去重: 同日重复陈旧只留档一次')

    def test_alive_checker_alerts_on_missing_heartbeat(self):
        # 心跳缺失 = 看门狗从未巡逻 (launchd bootstrap 失败族, 2026-11-09 事故
        # 形态: job 被 KeepAlive 三连拒移除后无人值守) — 必须告警, 不得当新鲜
        result, alerts, _ = self.run_alive_checker(heartbeat_age=None)
        self.assertIn('心跳陈旧', alerts, '缺失的心跳必须告警 — fail-open 静默不可接受')

    def test_burn_watch_refreshes_runtime_copy(self):
        src = (ROOT / 'burn-watch.sh').read_text()
        self.assertIn('$HOME/.codingkeeper/bin/burn-watch.sh', src)
        self.assertIn('cmp -s', src, '运行位自愈刷新缺失')

    def test_watch_dir_falls_back_to_repo_from_bin_copy(self):
        # 副本目录没有 ck-window.py: WATCH_DIR 必须回退仓库真源, 否则
        # watch_window_open 对一切炉子 125, 巡逻全盲 (2026-11-10 首次从
        # bin 副本启动时发现, soul2soul/wechatflow 停转未被复燃)
        src = (ROOT / 'burn-watch.sh').read_text()
        self.assertIn('$WATCH_DIR/ck-window.py', src)
        self.assertIn('bw_repo_dir', src)

    def registry_scan(self, entries, temp_filter=None):
        source = (ROOT / 'burn-watch.sh').read_text().split('\ncase "${1:-}" in\n')[0]
        library = self.world / 'watch-library.sh'
        library.write_text(source)
        (self.home / '.codingkeeper/projects').write_text('\n'.join(map(str, entries)) + '\n')
        alerts = self.home / '.codingkeeper/burn-ALERTS.txt'
        alerts.unlink(missing_ok=True)
        env = dict(os.environ, HOME=str(self.home), BURN_WATCH_NOTIFY='0')
        env.pop('CODEXC_FLEET_TEMP_FILTER', None)
        if temp_filter is not None:
            env['CODEXC_FLEET_TEMP_FILTER'] = temp_filter
        result = subprocess.run(['/bin/bash', '-c', '. "$1"\nfleet_trace_registry\nfleet_furnaces',
                                 'registry-audit', str(library)], cwd=self.world, env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines(), alerts.read_text() if alerts.exists() else ''

    def registry_fixture_entries(self):
        missing = self.world / 'deleted-furnace'
        noqueue = self.world / 'noqueue-furnace'
        spaced = self.world / 'space furnace'
        incomplete = self.world / 'incomplete-furnace'
        complete = self.world / 'complete-furnace'
        for project in (noqueue, spaced, incomplete, complete):
            (project / '.codingkeeper').mkdir(parents=True)
        for project in (incomplete, complete):
            (project / '.codingkeeper/queue.md').touch()
        for name in ('gate.sh', 'review-leaf.sh'):
            (complete / '.codingkeeper' / name).touch()
        return [project.resolve() for project in (missing, noqueue, spaced, incomplete, complete)]

    def test_temporary_registry_entries_do_not_alert_when_incomplete(self):
        entries = self.registry_fixture_entries()
        entries.extend(Path(prefix) / self.world.name / 'deleted-furnace'
                       for prefix in ('/tmp', '/private/tmp', '/var/tmp', '/private/var/tmp',
                                      '/var/folders', '/private/var/folders'))
        for temp_filter in (None, '1'):
            with self.subTest(temp_filter=temp_filter):
                furnaces, alerts = self.registry_scan(entries, temp_filter)
                self.assertEqual(furnaces, [])
                self.assertEqual(alerts, '', 'filtered temporary registry entries must remain silent')

    def test_registry_temp_filter_override_preserves_diagnostics(self):
        entries = self.registry_fixture_entries()
        furnaces, alerts = self.registry_scan(entries, '0')
        self.assertEqual(furnaces, [str(entries[-1])])
        for diagnostic in ('目录不存在', '缺 queue.md', '含空白', 'scaffold 缺件'):
            self.assertIn(diagnostic, alerts)

    def test_registry_filter_preserves_similarly_named_roots(self):
        entries = [Path(prefix + '-projects') / (self.world.name + prefix.replace('/', '-'))
                   for prefix in ('/tmp', '/private/tmp', '/var/tmp', '/private/var/tmp',
                                  '/var/folders', '/private/var/folders')]
        furnaces, alerts = self.registry_scan(entries)
        self.assertEqual(furnaces, [])
        for entry in entries:
            self.assertIn(str(entry), alerts)

    def test_furnace_gate_propagates_pytest_result(self):
        project = self.world / 'python project'
        project.mkdir()
        env = dict(os.environ, HOME=str(self.home))
        subprocess.run([str(ROOT / 'ck-init-furnace'), str(project)], env=env,
                       capture_output=True, text=True, check=True, timeout=15)
        (project / 'pytest.ini').touch()
        (project / 'pytest.py').write_text(
            'import os, sys\n'
            'print(os.environ["CK_TEST_PYTEST_DIAGNOSTIC"], file=sys.stderr)\n'
            'code = int(os.environ["CK_TEST_PYTEST_EXIT"])\n'
            'raise SystemExit(0 if code == 1 and "--collect-only" in sys.argv else code)\n')
        gate = project / '.codingkeeper' / 'gate.sh'
        for code, diagnostic in ((2, 'collection error'), (5, 'no tests collected'),
                                 (1, 'assertion failed'), (0, 'test passed')):
            with self.subTest(code=code):
                gate_env = dict(env, CK_TEST_PYTEST_EXIT=str(code), CK_TEST_PYTEST_DIAGNOSTIC=diagnostic)
                result = subprocess.run([str(gate)], cwd=self.world, env=gate_env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual('[gate] OK' in result.stdout, code == 0)

    def test_ck_init_furnace_scaffolds_and_registers(self):
        """生成器: 三件套 + 注册登记, 幂等 (重跑不炸不重复登记)。"""
        with tempfile.TemporaryDirectory(prefix='ck-init-furnace-', dir='/private/tmp') as tmp:
            home = Path(tmp) / 'home'
            (home / '.codingkeeper').mkdir(parents=True)
            proj = Path(tmp) / 'projA'
            proj.mkdir()
            env = {**os.environ, 'HOME': str(home)}
            run = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj)],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            ck = proj / '.codingkeeper'
            for f in ('queue.md', 'gate.sh', 'review-leaf.sh'):
                self.assertTrue((ck / f).exists(), f'missing {f}')
            self.assertIn('- [ ] 通读本仓库', (ck / 'queue.md').read_text())
            self.assertIn('渐进式', (ck / 'gate.sh').read_text())
            self.assertIn('codexc-review-leaf', (ck / 'review-leaf.sh').read_text())
            reg = home / '.codingkeeper' / 'projects'
            self.assertEqual(reg.read_text().strip().splitlines(), [str(proj)])
            run2 = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj), 'true'],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(run2.returncode, 0, run2.stderr)
            self.assertEqual(reg.read_text().strip().splitlines(), [str(proj)],
                             '重复登记 = 炉队重复巡逻')
            # 幂等语义: 已存在的 gate 不被指定命令覆盖
            self.assertIn('渐进式', (ck / 'gate.sh').read_text())
            proj_b = Path(tmp) / 'projB'
            proj_b.mkdir()
            run3 = subprocess.run(['bash', str(ROOT / 'ck-init-furnace'), str(proj_b), 'true'],
                                  env=env, capture_output=True, text=True)
            self.assertEqual(run3.returncode, 0, run3.stderr)
            self.assertIn('true', (proj_b / '.codingkeeper' / 'gate.sh').read_text(),
                          '全新项目走指定命令路径')

    def test_furnace_registration_preserves_comments_and_concurrent_projects(self):
        (self.home / '.codingkeeper/projects').write_text('# intentionally disabled\n')
        projects = [self.world / ('project-' + str(i)) for i in range(6)]
        children = []
        for project in projects:
            project.mkdir()
            children.append(subprocess.Popen(['/bin/bash', str(ROOT / 'ck-init-furnace'), str(project), 'true'],
                                             env={**os.environ, 'HOME': str(self.home)},
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for child in children:
            out, err = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, err)
        lines = (self.home / '.codingkeeper/projects').read_text().splitlines()
        self.assertEqual(lines[0], '# intentionally disabled')
        self.assertEqual(set(lines[1:]), {str(project.resolve()) for project in projects})

    def test_midnight_exec_lives_outside_patrol(self):
        lines = (ROOT / 'burn-watch.sh').read_text().splitlines()
        exec_lines = [i for i, l in enumerate(lines) if 'exec /bin/bash "$0" __locked-run' in l]
        self.assertEqual(len(exec_lines), 1, f'翻日 exec 应恰好一处: {exec_lines}')
        loop_lines = [i for i, l in enumerate(lines) if l.strip() == 'while :; do']
        self.assertTrue(loop_lines, '主循环缺失')
        self.assertGreater(exec_lines[0], loop_lines[0],
                           '翻日 exec 必须在主循环 (fd 9 开启) 内, patrol_once 里 fd 9 已关 — 会 missing lock 自杀')

    # ---- 机器态断言 (部署过的机器上不得漂移) ----

    def deployed_fixture(self):
        sources = sorted({ROOT / 'burn-watch.sh', ROOT / 'codexc-daily',
                          *ROOT.glob('ck-*.py'), *ROOT.glob('ck-*.sh')})
        runtime = self.home / '.codingkeeper' / 'bin'
        runtime.mkdir(parents=True, exist_ok=True)
        for source in sources:
            shutil.copy2(source, runtime / source.name)
        agents = self.home / 'Library' / 'LaunchAgents'
        agents.mkdir(parents=True, exist_ok=True)
        plists = []
        for label in ('com.codingkeeper.watchdog', 'com.codexc.daily',
                      'com.codingkeeper.watchdog-alive'):
            source = ROOT / 'packaging' / (label + '.plist')
            value = plistlib.loads(source.read_bytes().replace(
                b'/Users/wardonguo', str(self.home).encode()))
            installed = agents / source.name
            installed.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
            plists.append(installed)
        return [runtime / source.name for source in sources], plists

    def installed_probe(self, method):
        result = unittest.TestResult()
        with patch.dict(globals(), HOME=self.home):
            WatchdogDeployAudit(method).run(result)
        return result

    def assert_probe_failed(self, result, name):
        self.assertFalse(result.skipped, name)
        self.assertEqual(len(result.failures), 1, name)
        self.assertFalse(result.errors, name)

    def deployment_present(self):
        runtime = HOME / '.codingkeeper' / 'bin'
        sources = {ROOT / 'burn-watch.sh', ROOT / 'codexc-daily',
                   *ROOT.glob('ck-*.py'), *ROOT.glob('ck-*.sh')}
        paths = [runtime / source.name for source in sources]
        paths.extend(HOME / 'Library' / 'LaunchAgents' / (label + '.plist')
                     for label in ('com.codingkeeper.watchdog', 'com.codexc.daily',
                                   'com.codingkeeper.watchdog-alive'))
        return any(path.exists() or path.is_symlink() for path in paths)

    def test_runtime_probe_checks_every_installed_file(self):
        installed_files, _ = self.deployed_fixture()
        method = 'test_runtime_copy_matches_repo_if_present'
        self.assertTrue(self.installed_probe(method).wasSuccessful())
        for installed in installed_files:
            original = installed.read_bytes()
            for damage in ('stale', 'missing'):
                with self.subTest(file=installed.name, damage=damage):
                    try:
                        if damage == 'stale':
                            installed.write_bytes(b'stale runtime\n')
                        else:
                            installed.unlink()
                        self.assert_probe_failed(self.installed_probe(method), installed.name)
                    finally:
                        installed.write_bytes(original)

    def test_runtime_probe_rejects_partial_install_without_main_script(self):
        runtime = self.home / '.codingkeeper' / 'bin'
        runtime.mkdir()
        shutil.copy2(ROOT / 'ck-provider.py', runtime / 'ck-provider.py')
        result = self.installed_probe('test_runtime_copy_matches_repo_if_present')
        self.assert_probe_failed(result, 'partial runtime')

    def test_installed_probes_skip_only_when_not_deployed(self):
        for method in ('test_runtime_copy_matches_repo_if_present',
                       'test_installed_plist_matches_packaging_if_present'):
            with self.subTest(method=method):
                result = self.installed_probe(method)
                self.assertEqual(len(result.skipped), 1)
                self.assertTrue(result.wasSuccessful())

    def test_installed_probes_reject_entire_missing_component(self):
        for missing in ('runtime', 'plists'):
            with self.subTest(missing=missing):
                runtime, plists = self.deployed_fixture()
                targets = runtime if missing == 'runtime' else plists
                for target in targets:
                    target.unlink()
                method = ('test_runtime_copy_matches_repo_if_present' if missing == 'runtime'
                          else 'test_installed_plist_matches_packaging_if_present')
                self.assert_probe_failed(self.installed_probe(method), missing)

    def test_plist_probe_accepts_relocated_home_and_binary_format(self):
        self.deployed_fixture()
        result = self.installed_probe('test_installed_plist_matches_packaging_if_present')
        self.assertFalse(result.skipped)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])

    def test_plist_probe_checks_all_jobs_and_partial_installation(self):
        _, installed_files = self.deployed_fixture()
        for installed in installed_files:
            original = installed.read_bytes()
            for damage in ('stale', 'missing'):
                with self.subTest(file=installed.name, damage=damage):
                    try:
                        if damage == 'stale':
                            value = plistlib.loads(original)
                            value['ProgramArguments'] = ['/old/runtime']
                            installed.write_bytes(plistlib.dumps(value))
                        else:
                            installed.unlink()
                        result = self.installed_probe('test_installed_plist_matches_packaging_if_present')
                        self.assert_probe_failed(result, installed.name)
                    finally:
                        installed.write_bytes(original)

    def test_runtime_copy_matches_repo_if_present(self):
        sources = sorted({ROOT / 'burn-watch.sh', ROOT / 'codexc-daily',
                          *ROOT.glob('ck-*.py'), *ROOT.glob('ck-*.sh')})
        runtime = HOME / '.codingkeeper' / 'bin'
        targets = [runtime / source.name for source in sources]
        if not self.deployment_present():
            self.skipTest('运行位尚未部署 (packaging/install-watchdog.sh)')
        for source, target in zip(sources, targets):
            self.assertTrue(target.is_file(), f'{target.name} 运行副本缺失或非普通文件')
            self.assertTrue(target.read_bytes() == source.read_bytes(),
                            f'{target.name} 运行副本与仓库漂移 — 按发布流程同步安装')

    def test_installed_plist_matches_packaging_if_present(self):
        labels = ('com.codingkeeper.watchdog', 'com.codexc.daily',
                  'com.codingkeeper.watchdog-alive')
        agents = HOME / 'Library' / 'LaunchAgents'
        installed = [agents / (label + '.plist') for label in labels]
        if not self.deployment_present():
            self.skipTest('launchd 作业尚未安装 (packaging/install-watchdog.sh)')

        def relocate(value):
            if isinstance(value, str):
                return value.replace('/Users/wardonguo', str(HOME))
            if isinstance(value, list):
                return [relocate(item) for item in value]
            if isinstance(value, dict):
                return {key: relocate(item) for key, item in value.items()}
            return value

        for installed_path in installed:
            self.assertTrue(installed_path.is_file(), f'{installed_path.name} 安装不完整')
            source = ROOT / 'packaging' / installed_path.name
            self.assertEqual(plistlib.loads(installed_path.read_bytes()),
                             relocate(plistlib.loads(source.read_bytes())),
                             f'{installed_path.name} 与 packaging 源漂移 — 按发布流程同步安装')

    # ---- 进程级回归: __locked-run 在 fd 9 开启 (未持锁) 时必须存活 ----

    def test_revived_runner_fixture_cleans_up_on_success_and_failure(self):
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        self.processes.append(other)
        for inject_failure in (False, True):
            with self.subTest(inject_failure=inject_failure):
                fixture = WatchdogDeployAudit('test_real_revived_runner_does_not_inherit_watchdog_lock_descriptors')
                fixture.setUp()
                record = fixture.world / 'runner-fds.json'
                runner_pid = None
                try:
                    try:
                        if inject_failure:
                            with patch.object(fixture, 'assertEqual', side_effect=AssertionError('injected fixture failure')):
                                with self.assertRaisesRegex(AssertionError, 'injected fixture failure'):
                                    fixture.test_real_revived_runner_does_not_inherit_watchdog_lock_descriptors()
                        else:
                            fixture.test_real_revived_runner_does_not_inherit_watchdog_lock_descriptors()
                    finally:
                        if record.exists():
                            runner_pid = json.loads(record.read_text())['pid']
                        fixture.tearDown()
                    self.assertIsNotNone(runner_pid, 'fixture must publish its fake runner PID')
                    self.assertEqual(live_processes({runner_pid}), {},
                                     'detached fake runner survived fixture cleanup')
                    self.assertIsNone(other.poll(), 'cleanup must preserve another fixture')
                finally:
                    if runner_pid is not None and live_processes({runner_pid}):
                        try:
                            os.kill(runner_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_real_revived_runner_does_not_inherit_watchdog_lock_descriptors(self):
        project = self.world / 'real-revive'
        state = project / '.codingkeeper'
        state.mkdir(parents=True)
        for name in ('queue.md', 'gate.sh', 'review-leaf.sh'):
            (state / name).touch()
        (self.home / '.codingkeeper/projects').write_text(str(project.resolve()) + '\n')
        bindir = self.world / 'fd-bin'
        bindir.mkdir()
        record = self.world / 'runner-fds.json'
        fake = bindir / 'zcodec'
        fake.write_text('#!' + sys.executable + '\n' +
                        'import json,os,time\nfrom pathlib import Path\n'
                        'fds=[]\n'
                        'for fd in range(9,13):\n'
                        '    try: os.fstat(fd); fds.append(fd)\n'
                        '    except OSError: pass\n'
                        'record=Path(os.environ["FD_RECORD"])\n'
                        'temporary=record.with_suffix(".tmp")\n'
                        'temporary.write_text(json.dumps({"pid":os.getpid(),"fds":fds}))\n'
                        'temporary.replace(record)\n'
                        'time.sleep(60)\n')
        fake.chmod(0o755)
        env = {**os.environ, 'HOME': str(self.home), 'PATH': str(bindir) + ':' + os.environ['PATH'],
               'CODEXC_ACTIVE_WINDOW': '', 'BURN_WATCH_NOTIFY': '0', 'FD_RECORD': str(record)}
        process = subprocess.Popen([str(ROOT / 'burn-watch.sh'), 'run'], cwd=project, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        self.processes.append(process)
        try:
            # This includes watchdog initialization and the first patrol,
            # separate from the descriptor ownership assertions below.
            until = time.monotonic() + 60
            while time.monotonic() < until and process.poll() is None:
                if record.exists():
                    break
                time.sleep(.05)
            alert = self.home / '.codingkeeper/burn-ALERTS.txt'
            detail = alert.read_text(errors='replace')[-2000:] if alert.is_file() else ''
            self.assertTrue(record.exists(),
                            'real nohup must launch the fake runner (watchdog rc=' +
                            str(process.poll()) + '): ' + detail)
            result = json.loads(record.read_text())
            self.assertEqual(result['fds'], [], 'runner must not inherit fd 9 or Bash save slots 10–12')
            process.terminate()
            process.wait(timeout=5)
            # The long-lived runner must not retain the kernel lock after its
            # watchdog dies; a new independent process must acquire it now.
            check = subprocess.run([sys.executable, '-c',
                                    'import fcntl,sys; f=open(sys.argv[1],"a+"); '
                                    'fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)',
                                    str(self.flock)], capture_output=True, text=True, timeout=5)
            self.assertEqual(check.returncode, 0, check.stderr)
        finally:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=5)
            if record.exists():
                runner_pid = json.loads(record.read_text())['pid']
                if type(runner_pid) is not int or runner_pid <= 1:
                    raise ValueError('fixture must record its fake runner PID')
                try:
                    os.kill(runner_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                survivors = live_processes({runner_pid})
                while survivors and time.monotonic() < deadline:
                    time.sleep(.05)
                    survivors = live_processes({runner_pid})
                self.assertFalse(survivors, 'detached fake runner survived cleanup')

    def test_locked_run_survives_with_open_fd9(self):
        env = dict(os.environ, HOME=str(self.home))
        script = ROOT / 'burn-watch.sh'
        errfile = self.home / 'watchdog-stderr.log'
        # stderr 走文件而非 PIPE: 活实例与其子进程握着管道写端, stderr.read()
        # 永远等不到 EOF (且 assert 的 msg 参数是无条件求值), 套件会挂死
        with open(errfile, 'wb') as ef:
            proc = subprocess.Popen(
                ['/bin/bash', '-c',
                 f'exec 9<"{self.flock}"; exec /bin/bash "{script}" __locked-run'],
                env=env, stdout=subprocess.DEVNULL, stderr=ef)
        self.processes.append(proc)
        time.sleep(4)
        self.assertIsNone(proc.poll(),
                          '__locked-run 退出: ' + errfile.read_text(errors='replace'))
        heartbeat = self.home / '.codingkeeper' / 'watchdog.heartbeat'
        self.assertTrue(heartbeat.exists(), '存活实例应写心跳')


if __name__ == '__main__':
    unittest.main()
