#!/usr/bin/env python3
"""自动化会话零堆积的源头卫生: 探测/审核不留行, 清扫覆盖全部自动化标题, worker 能自愈死链。"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class SessionHygieneAudit(unittest.TestCase):
    def read(self, name):
        return (REPO / name).read_text(encoding='utf-8')

    def test_review_lane_deletes_its_session_rows(self):
        source = self.read('codexc-review-leaf')
        self.assertIn('drop_session_rows', source)
        self.assertIn('tasks-index', source,
                      'sidebar task shells must be deleted alongside session rows')
        self.assertNotIn("'--no-history'", source,
                         'zcode 0.17.1 has no such option; it fails the whole review')

    def test_watchdog_probe_deletes_its_session_row(self):
        source = self.read('burn-watch.sh')
        probe = [line for line in source.splitlines() if '--prompt replyOK' in line]
        self.assertEqual(len(probe), 1, 'probe invocation must stay unique')
        self.assertNotIn('--no-history', probe[0],
                         'zcode 0.17.1 has no such option; the probe would always fail')
        self.assertIn("DELETE FROM session WHERE id='$psid'", source)
        self.assertIn("DELETE FROM tasks WHERE task_id='$psid'", source,
                      'probe shell in the sidebar tasks-index must go too')
        self.assertIn('tasks-index', source.split('cleanup_probe_sessions')[1],
                      'hourly sweep must also cover the sidebar tasks-index')

    def test_watchdog_sweep_covers_every_automated_title(self):
        sweep = self.read('burn-watch.sh')
        for pattern in ("'replyOK'", "'Reply with exactly: OK'", 'Review the single leaf%',
                        '你是独立%', '[codexc-headless]%'):
            self.assertIn(pattern, sweep, f'sweep must cover {pattern}')

    def test_worker_self_heals_dead_resume_chains(self):
        worker = self.read('codexc-zcode-worker')
        call = 'heal "$ZCODE_SESSION_FILE" "$sid"'
        self.assertEqual(worker.count(call), 2,
                         'both failure paths (rc!=0 and unparseable) must heal')
        self.assertIn(call, worker.split('CK_ERROR_CLASS: $cls')[0],
                      'rc!=0 failure path must heal before exit')

    def test_zcode_resume_binds_the_saved_conversation_to_current_project(self):
        source = self.read('ck-zcode-session.py')
        select = source.split("if action == 'select':", 1)[1].split("if action == 'capture':", 1)[0]
        self.assertIn('verify_directory(sid)', select,
                      'a saved or retry session must be checked before the CLI can resume it')
        check = source.split('def verify_directory(sid):', 1)[1].split('\n\ndef heal', 1)[0]
        self.assertIn("SELECT directory, path FROM session", check)
        self.assertIn("Path(directory).resolve() != Path.cwd().resolve()", check,
                      'persisted executor cwd is part of the session ownership check')
        self.assertIn("'?mode=ro'", check,
                      'ownership verification must not mutate the session database')


if __name__ == '__main__':
    unittest.main()
