#!/usr/bin/env python3
"""notify 跨通道对等回归: 同声明 env (CODEXC_NOTIFY_GAP) 的语义不得漂移。

漂移实证 (2026-11-12 可维护性轮): codex 通道经 normalize_uint 把 gap 钳到
≤86400, ck-common 通道 (loop/headless/daily 共用) 只拒非数字 — gap=99999999
时 25h 前的上次弹窗: codex 通道送达、ck 通道静默压抑到 3 年后; 被压抑
通知只有 ck 通道写 WATCHLOG, codex 通道无痕。修复后两通道: 钳制一致 +
压抑留痕一致 (假 osascript 记录器全程零真弹窗)。
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CK_NOTIFY = """
CK_LANE=headless
WATCHLOG={watchlog!r}
HOME={home!r}
CODEXC_NOTIFY_GAP=99999999
CODEXC_LOOP_NOTIFY=1
{fn}
notify 'fleet notification: hello'
"""

CODEX_NOTIFY = """
WATCHLOG={watchlog!r}
HOME={home!r}
CODEXC_NOTIFY_GAP=99999999
CODEXC_NOTIFY=1
{normalize}
{fn}
notify 'fleet notification: hello'
"""


class NotifyParityAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-notify-parity-')
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'osascript').write_text(
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$OSA_LOG"\n')
        (self.bin / 'osascript').chmod(0o755)
        # The invalid huge gap falls back to 3s. Wall-clock calls can cross that
        # boundary under full-suite load, so keep the fixture clock explicit.
        (self.bin / 'date').write_text(
            '#!/bin/bash\n'
            'if [ "$#" = 1 ] && [ "$1" = +%s ]; then\n'
            '  printf "%s\\n" "$CK_NOTIFY_TEST_NOW"\n'
            'else\n  exec /bin/date "$@"\nfi\n')
        (self.bin / 'date').chmod(0o755)
        self.watchlog = self.root / 'watch.log'
        self.osa = self.root / 'osa.log'
        self.home = self.root / 'home'
        self.home.mkdir()
        # 上次弹窗 25h 前: 落在 86400 钳制之外、99999999 之内 — 漂移判别区
        self.notify_last = self.home / '.codingkeeper' / '.notify-last'
        self.notify_last.parent.mkdir(parents=True, exist_ok=True)
        self.now = 1700000000
        self.notify_last.write_text(str(self.now - 90000))
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        OSA_LOG=str(self.osa), CK_NOTIFY_TEST_NOW=str(self.now))

    def tearDown(self):
        self.tmp.cleanup()

    def run_lane(self, name, script):
        env = dict(self.env, HOME=str(self.home))
        return subprocess.run(['/bin/bash', '-c', script], env=env, text=True,
                              capture_output=True, timeout=30)

    def ck_script(self):
        fn = re.search(r'notify\(\) \{.*?\n\}', (REPO / 'ck-common.sh').read_text(), re.S).group(0)
        normalize = re.search(r'normalize_uint\(\) \{.*?\n\}', (REPO / 'ck-common.sh').read_text(), re.S).group(0)
        return 'CK_LANE=headless\n' + normalize + '\n' + CK_NOTIFY.format(watchlog=str(self.watchlog), home=str(self.home), fn=fn)

    def codex_script(self):
        src = (REPO / 'codexc').read_text()
        normalize = re.search(r'normalize_uint\(\) \{.*?\n\}', src, re.S).group(0)
        fn = re.search(r'notify\(\) \{.*?\n\}', src, re.S).group(0)
        return CODEX_NOTIFY.format(watchlog=str(self.watchlog), home=str(self.home),
                                   normalize=normalize, fn=fn)


    def test_gap_overflow_and_leading_zeroes_are_safe(self):
        for gap in ('9' * 80, '08', '0003'):
            for script in (self.ck_script, self.codex_script):
                with self.subTest(gap=gap, lane=script.__name__):
                    self.osa.unlink(missing_ok=True)
                    self.notify_last.write_text(str(self.now - 90000))
                    result = self.run_lane('lane', script().replace('99999999', gap))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn('integer expression', result.stderr)
                    self.assertNotIn('value too great for base', result.stderr)
                    self.assertEqual(len(self.delivered()), 1)

    def test_each_lane_independently_delivers_and_logs_suppression(self):
        for script in (self.ck_script, self.codex_script):
            with self.subTest(lane=script.__name__):
                self.osa.unlink(missing_ok=True)
                self.watchlog.unlink(missing_ok=True)
                self.notify_last.write_text(str(self.now - 90000))
                result = self.run_lane('lane', script())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.delivered()), 1)
                self.osa.unlink(missing_ok=True)
                self.watchlog.unlink(missing_ok=True)
                self.notify_last.write_text(str(self.now))
                result = self.run_lane('lane', script())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.delivered()), 0)
                self.assertIn('notification suppressed', self.watchlog.read_text())

    def delivered(self, result=None):
        # 假 osascript 把通知记录到 OSA_LOG (不占 stdout) — 从记录文件数送达
        osa = self.root / 'osa.log'
        return ([l for l in osa.read_text().splitlines() if 'display notification' in l]
                if osa.exists() else [])

    def reset_phase_state(self, notify_last_epoch):
        # 两通道共享 HOME (.notify-last) / OSA_LOG / WATCHLOG: 不按阶段重置,
        # 后跑的通道会读到前序通道的送达计数与压抑留痕 — 断言变假绿
        # (2026-11-15 审查: codex 通道完全不送达/不留痕时 test_huge_gap 与
        # test_suppression_parity 照样通过)。
        self.osa.unlink(missing_ok=True)
        self.watchlog.unlink(missing_ok=True)
        self.notify_last.write_text(str(notify_last_epoch))

    def test_huge_gap_is_clamped_on_both_lanes(self):
        # 漂移修复验证: gap=99999999 时两通道都钳制/回退 → 25h 前的上次弹窗
        # 照常送达 (修复前 ck 通道压抑到 3 年后, codex 通道送达 — 漂移)
        for lane, script in (('ck', self.ck_script), ('cx', self.codex_script)):
            self.reset_phase_state(self.now - 90000)
            result = self.run_lane(lane, script() + '\ntrue\n')
            self.assertEqual(len(self.delivered(result)), 1, f'{lane} 通道钳制/回退后应送达')

    def test_suppression_parity_on_both_lanes(self):
        # gap 内压抑 + 留痕对等 (两通道): 1s 前刚弹过 → 压抑 + WATCHLOG 留痕
        self.reset_phase_state(self.now - 1)
        result = self.run_lane('ck', self.ck_script() + '\ntrue\n')
        self.assertEqual(len(self.delivered(result)), 0, 'gap 内压抑 (ck 通道)')
        wl = self.watchlog.read_text()
        self.assertIn('notification suppressed', wl, 'ck 通道压抑必须留痕')
        self.reset_phase_state(self.now - 1)
        cx = self.run_lane('cx', self.codex_script() + '\ntrue\n')
        self.assertEqual(len(self.delivered(cx)), 0, 'gap 内压抑 (codex 通道)')
        cx_wl = self.watchlog.read_text()
        self.assertIn('notification suppressed', cx_wl, 'codex 通道压抑也必须留痕')

    def test_fallback_gap_has_deterministic_suppression_and_release_boundary(self):
        for script in (self.ck_script, self.codex_script):
            for elapsed, delivered in ((2, 0), (3, 1)):
                with self.subTest(lane=script.__name__, elapsed=elapsed):
                    self.osa.unlink(missing_ok=True)
                    self.notify_last.write_text(str(self.now - elapsed))
                    result = self.run_lane('boundary', script())
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(len(self.delivered()), delivered)


if __name__ == '__main__':
    unittest.main()
