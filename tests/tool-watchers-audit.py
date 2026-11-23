#!/usr/bin/env python3
"""Offline watchdog tests with real JSONL/SQLite and a recorded tmux boundary."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ToolWatchersAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-tool-watch-")
        self.world = Path(self.tmp.name)
        (self.world / "bin").mkdir()
        (self.world / "alive").touch()
        self.tmux = self.world / "bin/tmux"
        self.tmux.write_text('''#!/bin/bash
case "$1" in
 display-message) [ ! -f "$AUDIT_WORLD/alive" ] || printf '%%1\\n' ;;
 capture-pane) printf 'ctrl+p commands\\n' ;;
 send-keys) python3 - "$@" <<'SNAP'
import json,os,sys
from pathlib import Path
with (Path(os.environ["AUDIT_WORLD"])/"sent").open("a") as fh:
 fh.write(json.dumps(sys.argv[1:])+"\\n")
SNAP
 ;;
esac
''')
        self.tmux.chmod(0o755)
        self.process = None

    def tearDown(self):
        (self.world / "alive").unlink(missing_ok=True)
        if self.process:
            try:
                self.process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.communicate(timeout=3)
        self.tmp.cleanup()

    def append(self, tool, error, seq):
        if tool == "claude":
            record = {"type":"assistant", "isApiErrorMessage":True, "message":{"content":[{"type":"text", "text":error}]}}
        elif tool == "pi":
            record = {"type":"message", "message":{"role":"assistant", "stopReason":"error", "errorMessage":error}}
        else:
            with sqlite3.connect(self.world / "opencode.db") as conn:
                conn.execute("INSERT INTO session_message VALUES ('s','assistant',?,?)", (seq, json.dumps({"error":{"message":error}})))
            return
        with (self.world / "rollout.jsonl").open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def sent(self):
        path = self.world / "sent"
        return path.read_text().splitlines() if path.exists() else []

    def wait_count(self, count):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            if len(self.sent()) == count:
                return
            if self.process.poll() is not None:
                break
            time.sleep(.025)
        self.assertEqual(len(self.sent()), count, (self.world / "codexc-watch.log").read_text() if (self.world / "codexc-watch.log").exists() else "no log")

    def exercise(self, tool):
        if tool == "opencode":
            with sqlite3.connect(self.world / "opencode.db") as conn:
                conn.execute("CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)")
        self.append(tool, "Too Many Requests", 1)
        script = r'''
set -u
SCRIPT_DIR="$AUDIT_ROOT"
TRANSIENT_RE='Too Many Requests|server error|timed out'
BLOCK_RE='usage limit|subscription|upgrade to|plan limit'
CODEXC_POLL=0.02
CODEXC_COOLDOWN=0
CODEXC_MAX_CONTINUES=2
CODEXC_MESSAGE=continue
CODEXC_NOTIFY=0
source "$SCRIPT_DIR/ck-watch-tools.sh"
watch_and_run_tool "$AUDIT_TOOL" "$$" '%1'
'''
        config = dict(os.environ, PATH=str(self.world / "bin")+":"+os.environ["PATH"],
                      AUDIT_WORLD=str(self.world), AUDIT_ROOT=str(ROOT), AUDIT_TOOL=tool,
                      CODEX_HOME=str(self.world), CODEXC_LOG_DIR=str(self.world), OPENCODE_DATA_DIR=str(self.world),
                      CODEXC_LOOP_ROLLOUT="s" if tool == "opencode" else str(self.world / "rollout.jsonl"))
        self.process = subprocess.Popen(["bash", "-c", script, str(ROOT / "codexc")], env=config,
                                        cwd=self.world, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        until = time.monotonic() + 10
        while time.monotonic() < until:
            logfile = self.world / "codexc-watch.log"
            if logfile.exists() and "watcher armed" in logfile.read_text():
                break
            time.sleep(.025)
        else:
            self.fail("watcher did not finish initialization")
        self.assertEqual(self.sent(), [], "historical errors must not trigger retry")
        self.append(tool, "server error", 2)
        self.wait_count(2)
        time.sleep(.2)
        self.assertEqual(len(self.sent()), 2, "same error must be consumed once")
        self.append(tool, "usage limit: Too Many Requests", 3)
        time.sleep(.25)
        self.assertEqual(len(self.sent()), 2, "quota blocklist must beat transient match")
        self.append(tool, "timed out", 4)
        self.wait_count(4)
        self.append(tool, "server error", 5)
        stdout, stderr = self.process.communicate(timeout=10)
        self.assertEqual(self.process.returncode, 0, stdout+stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(len(self.sent()), 4, "retry limit must stop further sends")
        text_send = json.loads(self.sent()[0])
        self.assertEqual(text_send[-2:], ["--", "continue"])

    def test_claude_watchdog(self):
        self.exercise("claude")

    def test_pi_watchdog(self):
        self.exercise("pi")

    def test_opencode_watchdog(self):
        self.exercise("opencode")

    def opencode_snapshot(self, messages):
        with sqlite3.connect(self.world / 'opencode.db') as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)')
            connection.execute('DELETE FROM session_message')
            connection.executemany('INSERT INTO session_message VALUES (?,?,?,?)',
                                   [('s', kind, sequence, json.dumps(data)) for kind, sequence, data in messages])
        result = subprocess.run(['bash', '-c', 'source "$1/ck-watch-tools.sh"; ck_tool_snapshot opencode s',
                                 'snapshot', str(ROOT)], capture_output=True, text=True, timeout=10,
                                env=dict(os.environ, OPENCODE_DIR=str(self.world)))
        self.assertEqual(result.returncode, 0, result.stderr)
        state, token, encoded = result.stdout.rstrip('\n').split('\t')
        return state, token, base64.b64decode(encoded).decode()

    def test_opencode_idle_retains_completed_answer_and_event_identity(self):
        message = ('assistant', 7, {'finish': 'stop', 'content': [{'type': 'text', 'text': 'finished'}]})
        before = self.opencode_snapshot([message])
        after = self.opencode_snapshot([message, ('idle', 11, {'outcome': 'succeeded'})])
        self.assertEqual(after, before)
        self.assertEqual((after[0], after[2]), ('clean', 'finished'))

    def test_opencode_failed_idle_retains_provider_error(self):
        message = ('assistant', 7, {'finish': 'error', 'error': {'data': {'statusCode': 429}}})
        before = self.opencode_snapshot([message])
        after = self.opencode_snapshot([message, ('idle', 11, {'outcome': 'failed'})])
        self.assertEqual(after, before)
        self.assertEqual(after[0], 'error')
        self.assertIn('Too Many Requests', after[2])

    def test_opencode_idle_does_not_replay_stale_or_unfinished_answers(self):
        completed = ('assistant', 7, {'finish': 'stop', 'content': [{'type': 'text', 'text': 'old'}]})
        cases = [
            [completed, ('user', 12, {'text': 'new turn'})],
            [completed, ('user', 12, {}), ('idle', 15, {'outcome': 'succeeded'})],
            [completed, ('idle', 15, {'outcome': 'failed'})],
            [completed, ('idle', 15, {'outcome': 'cancelled'})],
            [completed, ('idle', 15, [])],
            [completed, ('assistant', 12, {'content': []}), ('idle', 15, {'outcome': 'succeeded'})],
            [completed, ('tool', 12, {}), ('idle', 15, {'outcome': 'succeeded'})],
        ]
        for messages in cases:
            with self.subTest(messages=messages):
                state, _token, text = self.opencode_snapshot(messages)
                self.assertEqual((state, text), ('none', ''))


if __name__ == "__main__":
    unittest.main(verbosity=2)
