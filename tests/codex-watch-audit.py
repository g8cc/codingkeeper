#!/usr/bin/env python3
"""Codex main-session discovery with newer subagent rollouts; no model calls."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WATCH = (ROOT / 'codexc').read_text().split('# ---- internal: standalone watcher entry')[0]
LOOP = (ROOT / 'codexc-loop').read_text().split('# ---- dispatch')[0]


class CodexDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-codex-watch-')
        self.addCleanup(self.tmp.cleanup)
        self.world = Path(self.tmp.name).resolve()
        self.home = self.world / 'home'
        self.sessions = self.home / 'sessions/2026/11/16'
        self.sessions.mkdir(parents=True)
        self.parent = self.rollout('parent', 'vscode', 1)
        self.child = self.rollout('child', {'subagent': {'thread_spawn': {
            'parent_thread_id': 'parent', 'depth': 1, 'agent_path': '/root/review'}}}, 2)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('CODEXC_', 'CODEX_', 'TMUX'))}
        self.env.update(HOME=str(self.home), CODEX_HOME=str(self.home),
                        CODEXC_NOTIFY='0', CODEXC_LOOP_NOTIFY='0')
        self.process = None
        self.output = None

    def tearDown(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
            if self.output is not None:
                self.output.close()

    def rollout(self, name, source, seconds, cwd=None):
        path = self.sessions / (name + '.jsonl')
        payload = {'id': name, 'cwd': str(cwd or self.world), 'source': source}
        path.write_text(json.dumps({'type': 'session_meta', 'payload': payload}) + '\n')
        stamp = time.time() - 20 + seconds
        os.utime(path, (stamp, stamp))
        return path

    def discover(self, lane, open_files=()):
        # All external process/tmux probes are fixtures, never the user server.
        files = '\n'.join('n' + str(path) for path in open_files)
        stub = ('\ntmux() { case "$*" in *pane_current_path*) printf %s "$PWD";; '
                '*) printf 999999999;; esac; }\n'
                'pgrep() { :; }\n'
                'lsof() { printf "%s\\n" ' + shlex.quote(files) + '; }\n')
        source = WATCH if lane == 'watcher' else LOOP
        function = 'watcher_find_rollout' if lane == 'watcher' else 'find_rollout'
        result = subprocess.run(['bash', '-c', source + stub + function + ' "%1"; :',
                                 str(ROOT / ('codexc' if lane == 'watcher' else 'codexc-loop'))],
                                cwd=self.world, env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_watcher_directory_fallback_ignores_newer_subagent(self):
        self.assertEqual(self.discover('watcher'), str(self.parent))

    def test_watcher_open_files_ignore_newer_subagent(self):
        self.assertEqual(self.discover('watcher', [self.parent, self.child]), str(self.parent))

    def test_loop_ignores_newer_subagent(self):
        self.assertEqual(self.discover('loop'), str(self.parent))

    def test_open_files_from_other_project_cannot_win(self):
        other = self.rollout('other', 'cli', 3, cwd=self.world / 'other')
        self.assertEqual(self.discover('watcher', [other, self.child]), str(self.parent))

    def test_child_only_never_becomes_the_main_thread(self):
        self.parent.unlink()
        for lane in ('watcher', 'loop'):
            with self.subTest(lane=lane):
                self.assertEqual(self.discover(lane, [self.child]), '')

    def test_legacy_header_and_symlinked_cwd_still_match(self):
        alias = self.world / 'project-alias'
        alias.symlink_to(self.world, target_is_directory=True)
        self.parent.write_text(json.dumps({'payload': {'cwd': str(alias)}}) + '\n')
        for lane in ('watcher', 'loop'):
            with self.subTest(lane=lane):
                self.assertEqual(self.discover(lane), str(self.parent))

    def test_bad_header_fifo_symlink_and_outside_candidate_are_ignored(self):
        (self.sessions / 'broken.jsonl').write_text('{not json\n')
        os.mkfifo(self.sessions / 'fifo.jsonl')
        (self.sessions / 'link.jsonl').symlink_to(self.parent)
        outside = self.world / 'outside.jsonl'
        outside.write_text(self.parent.read_text())
        self.assertEqual(self.discover('watcher', [outside, self.sessions / 'fifo.jsonl',
                                                 self.sessions / 'link.jsonl']), str(self.parent))
        self.assertEqual(self.discover('loop'), str(self.parent))

    def test_old_root_stays_available_to_loop_but_not_activity_fallback(self):
        old = time.time() - 600
        os.utime(self.parent, (old, old))
        self.assertEqual(self.discover('loop'), str(self.parent))
        self.assertEqual(self.discover('watcher'), '')

    def wait_for(self, predicate, message, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.process is not None and self.process.poll() is not None:
                break
            time.sleep(.025)
        log = self.world / 'watch.log'
        output = self.world / 'process.log'
        self.fail(message + '\n' + (log.read_text() if log.exists() else '') + '\n' +
                  (output.read_text() if output.exists() else ''))

    def append(self, path, payload):
        with path.open('a') as output:
            output.write(json.dumps({'type': 'event_msg', 'payload': payload}) + '\n')

    def sent(self):
        path = self.world / 'sent'
        return path.read_text().splitlines() if path.exists() else []

    def start_watcher(self):
        # Keep history to prove that starting the watcher does not replay errors.
        self.append(self.parent, {'type': 'task_complete', 'error': {'message': '429 Too Many Requests'}})
        # Appending the historical event changes parent mtime; restore the
        # incident's child-is-newer ordering before the watcher first binds.
        os.utime(self.child, (time.time() + 2, time.time() + 2))
        script = WATCH + r'''
CODEXC_POLL=1
CODEXC_COOLDOWN=0
CODEXC_MAX_CONTINUES=1
WATCHLOG="$PWD/watch.log"
touch alive
kill() { [ -f alive ]; }
pgrep() { :; }
lsof() { :; }
sleep() { command sleep .04; }
tmux() {
    case "$1" in
        display-message) printf '%%1\n' ;;
        capture-pane) printf 'Ask Codex to do anything\n' ;;
        send-keys) printf '%s\n' "$*" >> sent ;;
    esac
}
write_status() { printf '%s\n' "$1" >> statuses; }
watch_and_run "$$" '%1'
'''
        self.output = (self.world / 'process.log').open('w')
        self.process = subprocess.Popen(['bash', '-c', script, str(ROOT / 'codexc')],
                                        cwd=self.world, env=self.env, stdout=self.output,
                                        stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_for(lambda: (self.world / 'statuses').exists(), 'watcher did not reach its first heartbeat')
        time.sleep(.12)
        self.assertEqual(self.sent(), [], 'historical failures must not replay')

    def test_parent_429_continues_once_while_subagent_is_newer_and_quota_does_not(self):
        self.start_watcher()
        self.append(self.child, {'type': 'task_complete', 'last_agent_message': 'CHILD_COMPLETION'})
        self.append(self.parent, {'type': 'task_complete', 'error': {'message':
            'exceeded retry limit, last status: 429 Too Many Requests'}})
        os.utime(self.child, (time.time() + 2, time.time() + 2))
        self.wait_for(lambda: len(self.sent()) == 2, 'main 429 was not continued')
        self.assertIn('-l -- continue', self.sent()[0])
        self.assertTrue(self.sent()[1].endswith(' Enter'))
        time.sleep(.2)
        self.assertEqual(len(self.sent()), 2, 'one terminal error must send only once')
        self.assertNotIn('CHILD_COMPLETION', (self.world / 'statuses').read_text())
        self.append(self.parent, {'type': 'task_complete', 'error': {'message':
            'usage limit: 429 Too Many Requests'}})
        self.wait_for(lambda: 'usage limit' in (self.world / 'watch.log').read_text(),
                      'quota terminal event was not consumed')
        time.sleep(.15)
        self.assertEqual(len(self.sent()), 2, 'quota must never send continue')
        self.append(self.parent, {'type': 'task_complete', 'error': {'message': 'server error'}})
        self.process.wait(timeout=5)
        self.assertIn('reached max continues (1)', (self.world / 'watch.log').read_text())
        self.assertEqual(len(self.sent()), 2, 'retry ceiling must still apply')


if __name__ == '__main__':
    unittest.main(verbosity=2)
