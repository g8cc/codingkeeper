#!/usr/bin/env python3
"""Behavioral regressions for TUI freshness and daily resume (no APIs/tmux server)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LoopDailyAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-loop-audit-")
        self.world = Path(self.tmp.name)
        (self.world / ".codingkeeper").mkdir()
        (self.world / "sessions").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def shell(self, script, body, **env):
        path = ROOT / script
        source = path.read_text()
        marker = "# ---- dispatch" if script == "codexc-loop" else '\ncase "${1:-run}" in'
        source = source.rsplit(marker, 1)[0]
        config = dict(os.environ, CODEX_HOME=str(self.world), CODEXC_LOOP_NOTIFY="0",
                      CODEXC_NOTIFY="0", CODEXC_LOOP_IDLE="0", CODEXC_BANNER="0")
        config.update(env)
        run = subprocess.run(["bash", "-c", source + "\n" + body, str(path)],
                             cwd=self.world, env=config, capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        return run.stdout.strip()

    def write_rollout(self, records):
        path = self.world / "rollout.jsonl"
        path.write_text("".join(json.dumps(x) + "\n" for x in records))
        return path

    @staticmethod
    def done(text="TASK_RESULT: DONE"):
        return {"payload": {"type": "task_complete", "last_agent_message": text}}

    def test_empty_baseline_is_single_number(self):
        self.write_rollout([])
        self.assertEqual(self.shell("codexc-loop", 'terminal_count rollout.jsonl'), "0")

    def test_codex_new_turn_cannot_reuse_previous_completion(self):
        self.write_rollout([self.done(), {"payload": {"type": "task_started"}}])
        self.assertEqual(self.shell("codexc-loop", 'turn_status rollout.jsonl .codingkeeper/msg'), "none")

    def test_codex_aborted_turn_is_error(self):
        self.write_rollout([self.done(), {"payload": {"type": "turn_aborted"}}])
        self.assertEqual(self.shell("codexc-loop", 'turn_status rollout.jsonl .codingkeeper/msg'), "error")

    def test_claude_tool_call_is_not_clean_completion(self):
        self.write_rollout([
            {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}},
            {"type": "user", "message": {"content": "fix"}},
            {"type": "assistant", "message": {"stop_reason": "tool_use", "content": [{"type": "text", "text": "I will fix"}, {"type": "tool_use"}]}}
        ])
        self.assertEqual(self.shell("codexc-loop", 'turn_status_claude rollout.jsonl .codingkeeper/msg'), "none")

    def test_claude_sidechain_does_not_refresh_old_completion(self):
        first = {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}}
        path = self.write_rollout([first])
        baseline = path.stat().st_size
        with path.open("a") as fh:
            fh.write(json.dumps(dict(first, isSidechain=True)) + "\n")
        self.assertEqual(self.shell("codexc-loop", 'turn_status_claude rollout.jsonl .codingkeeper/msg >/dev/null; cat .codingkeeper/msg.tok'), str(baseline))

    def test_pi_tool_call_is_not_clean_completion(self):
        self.write_rollout([
            {"type": "message", "message": {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "TASK_RESULT: DONE"}]}},
            {"type": "message", "message": {"role": "assistant", "stopReason": "toolUse", "content": []}}
        ])
        self.assertEqual(self.shell("codexc-loop", 'turn_status_pi rollout.jsonl .codingkeeper/msg'), "none")

    def test_fast_completion_is_accepted(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() { iterations=$((iterations+1)); [ "$iterations" -lt 8 ]; }
feed_msg() { printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl; }
gate_run() { return 0; }
review_run() { printf 0; }
run_driver audit
cat .codingkeeper/journal 2>/dev/null || true
''')
        self.assertIn("accepted after", output)

    def test_refeed_requires_new_completion(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() {
 iterations=$((iterations+1))
 if [ "$iterations" = 2 ]; then printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl; fi
 [ "$iterations" -lt 12 ]
}
feeds=0
feed_msg() {
 feeds=$((feeds+1))
 if [ "$feeds" -gt 1 ]; then printf '%s\n' '{"payload":{"type":"token_count"}}' >> rollout.jsonl; fi
}
gate_run() { return 0; }
review_run() {
 if [ ! -e .codingkeeper/reviewed ]; then touch .codingkeeper/reviewed; printf 1; else printf 0; fi
}
review_tail() { printf bug; }
run_driver audit
if [ -f .codingkeeper/journal ]; then cat .codingkeeper/journal; fi
''')
        self.assertNotIn("accepted after", output)

    def paused_validation(self, phase, pause, replacement=None, banner="1"):
        project = self.world / (phase + '-' + pause + '-' + (replacement or 'unchanged'))
        state = project / '.codingkeeper'
        state.mkdir(parents=True)
        (project / '.gitignore').write_text('.codingkeeper/\n')
        subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True, timeout=10)
        (state / 'queue.md').write_text('## ready\n- [ ] task\n')
        (state / 'rollout.jsonl').write_text('')
        completion = (json.dumps(self.done()) + '\n').encode()
        (state / 'completion').write_bytes(completion)
        if replacement:
            event = json.dumps({'payload': {'type': replacement}}).encode()
            (state / 'replacement').write_bytes(event + b' ' * (len(completion) - len(event) - 1) + b'\n')
            self.assertEqual((state / 'replacement').stat().st_size, len(completion))
        output = self.shell('codexc-loop', r'''
cd "$AUDIT_PROJECT" || exit 1
notify() { :; }
register_project() { :; }
sleep() { :; }
tmux() { return 0; }
pane_idle() { return 0; }
find_rollout() { printf '%s' "$PWD/.codingkeeper/rollout.jsonl"; }
iterations=0
date() {
    if [ "$1" = +%s ]; then printf '%s\n' "$((100 + iterations * 30))"; else command date "$@"; fi
}
pane_alive() {
    iterations=$((iterations + 1))
    if [ "$AUDIT_PAUSE" = manual ] && [ "$iterations" = 4 ]; then rm -f .codingkeeper/loop.halt; fi
    [ "$iterations" -lt 10 ]
}
ck_run_check() {
    if [ -e .codingkeeper/loop.halt ]; then CK_WINDOW_REASON=manual_stop; return 125; fi
    if [ -e .codingkeeper/cancelled ] && [ ! -e .codingkeeper/waited ]; then
        case "$AUDIT_PAUSE" in
            window|interaction)
                touch .codingkeeper/waited
                CK_WINDOW_REASON=outside_window
                [ "$AUDIT_PAUSE" != interaction ] || CK_WINDOW_REASON=user_interactive
                CK_WINDOW_NEXT_OPEN=9999999999
                return 125
                ;;
        esac
    fi
    return 0
}
feed_msg() {
    printf 'feed\n' >> .codingkeeper/feeds
    cat .codingkeeper/completion >> .codingkeeper/rollout.jsonl
}
validation_stage() {
    printf '%s\n' "$1" >> .codingkeeper/stages
    : > "$2"
    if [ "$1" = "$AUDIT_PHASE" ]; then
        if [ ! -e .codingkeeper/cancelled ]; then
            touch .codingkeeper/cancelled
            if [ -f .codingkeeper/replacement ]; then mv .codingkeeper/replacement .codingkeeper/rollout.jsonl; fi
            if [ "$AUDIT_PAUSE" = manual ]; then
                printf 'operator pause\n' > .codingkeeper/.halt
                mv .codingkeeper/.halt .codingkeeper/loop.halt
            fi
            [ "$1" != review ] || printf window-closed
            return 125
        fi
        status_touch
        cat .codingkeeper/status.json >> .codingkeeper/observations.jsonl
        printf '\n' >> .codingkeeper/observations.jsonl
    fi
    if [ "$1" = review ]; then printf 'BUGS: 0\n' > "$2"; printf 0; fi
    return 0
}
gate_run() { validation_stage gate "$1"; }
review_run() { validation_stage review "$2"; }
run_driver audit
turn_status .codingkeeper/rollout.jsonl .codingkeeper/actual
''', AUDIT_PROJECT=str(project), AUDIT_PHASE=phase, AUDIT_PAUSE=pause,
            HOME=str(self.world), CODEXC_LOG_DIR=str(self.world / 'logs'),
            CODEXC_ACTIVE_WINDOW='', CODEXC_TOOL='codex', CODEXC_BANNER=banner,
            CODEXC_REQUIRE_GATE='0', CODEXC_REVIEW_PASS='2', CODEXC_REVIEW_ROUNDS='2',
            CODEXC_REVIEW_PARSE_RETRIES='0', CODEXC_LOOP_STALL='300', CODEXC_TURN_TIMEOUT='3600')
        return state, output

    def test_validation_resume_rechecks_equal_size_completion_replacement(self):
        for phase in ('gate', 'review'):
            for replacement, outcome in (('turn_aborted', 'error'), ('task_started', 'none')):
                with self.subTest(phase=phase, replacement=replacement):
                    state, actual = self.paused_validation(phase, 'none', replacement)
                    self.assertEqual(actual, outcome)
                    self.assertIn('- [ ] task', (state / 'queue.md').read_text())
                    self.assertFalse((state / 'journal').exists())
                    self.assertEqual(list((state / 'evidence').glob('*/accepted.json')), [])
                    self.assertTrue((state / 'loop.halt').exists())
                    self.assertEqual((state / 'feeds').read_text(), 'feed\n')
                    self.assertEqual((state / 'stages').read_text().splitlines().count(phase), 1)

    def test_validation_resume_restores_stage_status_and_heartbeat(self):
        for phase, pause, banner in (('gate', 'window', '1'), ('review', 'window', '1'),
                                     ('review', 'manual', '1'), ('gate', 'interaction', '0')):
            with self.subTest(phase=phase, pause=pause, banner=banner):
                state, actual = self.paused_validation(phase, pause, banner=banner)
                self.assertEqual(actual, 'clean')
                self.assertIn('- [x] task', (state / 'queue.md').read_text())
                self.assertFalse((state / 'loop.halt').exists())
                self.assertEqual(len(list((state / 'evidence').glob('*/accepted.json'))), 1)
                self.assertEqual((state / 'feeds').read_text(), 'feed\n')
                observations = [json.loads(line) for line in (state / 'observations.jsonl').read_text().splitlines()]
                self.assertTrue(observations)
                for status in observations:
                    self.assertTrue(status['active'], status)
                    self.assertEqual(status['phase'], phase, status)
                    self.assertEqual(status['next_run_at'], 0, status)
                    self.assertGreater(status['started_at'], 0, status)
                    self.assertFalse(status['parked'], status)

    def test_discovery_does_not_drop_older_active_project(self):
        for i in range(20):
            path = self.world / "sessions" / (str(i) + ".jsonl")
            path.write_text(json.dumps({"payload": {"type": "session_meta", "cwd": str(self.world) if i == 0 else "/another/" + str(i)}}) + "\n")
            os.utime(path, (100 + i, 100 + i))
        output = self.shell("codexc-loop", 'tmux() { printf "%s" "$PWD"; }; find_rollout audit')
        self.assertEqual(output, str(self.world / "sessions/0.jsonl"))

    def test_daily_error_completion_is_rescue_candidate(self):
        self.write_rollout([{"payload": {"type": "task_complete", "error": {"message": "stream disconnected"}}}])
        encoded = __import__("base64").b64encode(str(self.world / "rollout.jsonl").encode()).decode()
        self.assertEqual(self.shell("codexc-daily", 'last_turn_state "$AUDIT_ROLLOUT"', AUDIT_ROLLOUT=encoded), "died")

    def test_daily_malformed_rollout_is_unknown(self):
        self.write_rollout([{"payload": ["malformed"]}, None])
        encoded = __import__("base64").b64encode(str(self.world / "rollout.jsonl").encode()).decode()
        self.assertEqual(self.shell("codexc-daily", 'last_turn_state "$AUDIT_ROLLOUT"', AUDIT_ROLLOUT=encoded), "died")

    def test_opencode_sparse_sequences_use_sequence_baseline(self):
        import sqlite3
        with sqlite3.connect(self.world / "opencode.db") as db:
            db.execute("CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)")
            db.execute("INSERT INTO session_message VALUES ('s','assistant',100,'{}')")
        self.assertEqual(self.shell("codexc-loop", 'terminal_count s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world)), "100")

    def test_opencode_database_path_with_uri_characters(self):
        import sqlite3
        for dirname in ('data?mode=other', 'data#fragment', 'data % 中文'):
            with self.subTest(dirname=dirname):
                folder = self.world / dirname
                folder.mkdir()
                with sqlite3.connect(folder / 'opencode.db') as db:
                    db.execute('CREATE TABLE session_v2 (id TEXT, directory TEXT, time_updated INTEGER)')
                    db.execute('INSERT INTO session_v2 VALUES (?,?,?)', ('s', str(self.world), 1))
                    db.execute('CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)')
                    db.execute('INSERT INTO session_message VALUES (?,?,?,?)',
                               ('s', 'assistant', 7, json.dumps(dict(finish='stop', content=[dict(type='text', text='TASK_RESULT: DONE')]))))
                env = dict(CODEXC_TOOL='opencode', OPENCODE_DATA_DIR=str(folder))
                self.assertEqual(self.shell('codexc-loop', 'opencode_active_session "$PWD"', **env), 's')
                self.assertEqual(self.shell('codexc-loop', 'turn_status_opencode s .codingkeeper/msg', **env), 'clean')
                self.assertEqual((self.world / '.codingkeeper/msg').read_text(), 'TASK_RESULT: DONE')

    def test_opencode_in_place_stream_completion_changes_cache_key(self):
        import sqlite3
        path = self.world / "opencode.db"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)")
            db.execute("INSERT INTO session_message VALUES ('s','assistant',1,'{}')")
        before = self.shell("codexc-loop", 'rollout_size s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world))
        with sqlite3.connect(path) as db:
            db.execute('UPDATE session_message SET data=?', (json.dumps({"finish":"stop"}),))
        after = self.shell("codexc-loop", 'rollout_size s', CODEXC_TOOL="opencode", OPENCODE_DATA_DIR=str(self.world))
        self.assertNotEqual(before, after)

    def test_opencode_new_user_or_invalid_idle_does_not_replay_previous_completion(self):
        import sqlite3
        cases = [('user', {}), ('idle', {'outcome': 'cancelled'}), ('idle', {'outcome': 'failed'})]
        with sqlite3.connect(self.world / 'opencode.db') as connection:
            connection.execute('CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)')
        for kind, payload in cases:
            with self.subTest(kind=kind, payload=payload):
                with sqlite3.connect(self.world / 'opencode.db') as connection:
                    connection.execute('DELETE FROM session_message')
                    connection.execute('INSERT INTO session_message VALUES (?,?,?,?)',
                                       ('s', 'assistant', 7, json.dumps({'finish': 'stop', 'content': [{'type': 'text', 'text': 'old'}]})))
                    connection.execute('INSERT INTO session_message VALUES (?,?,?,?)', ('s', kind, 12, json.dumps(payload)))
                output = self.world / '.codingkeeper/msg'
                output.unlink(missing_ok=True)
                self.assertEqual(self.shell('codexc-loop', 'turn_status_opencode s .codingkeeper/msg',
                                            CODEXC_TOOL='opencode', OPENCODE_DATA_DIR=str(self.world)), 'none')
                self.assertFalse(output.exists())

    def test_opencode_successful_idle_preserves_answer_and_assistant_sequence(self):
        import sqlite3
        with sqlite3.connect(self.world / 'opencode.db') as connection:
            connection.execute('CREATE TABLE session_message (session_id TEXT, type TEXT, seq INTEGER, data TEXT)')
            connection.execute('INSERT INTO session_message VALUES (?,?,?,?)',
                               ('s', 'assistant', 7, json.dumps({'finish': 'stop', 'content': [{'type': 'text', 'text': 'TASK_RESULT: DONE'}]})))
            connection.execute('INSERT INTO session_message VALUES (?,?,?,?)', ('s', 'idle', 11, json.dumps({'outcome': 'succeeded'})))
        self.assertEqual(self.shell('codexc-loop', 'turn_status_opencode s .codingkeeper/msg',
                                    CODEXC_TOOL='opencode', OPENCODE_DATA_DIR=str(self.world)), 'clean')
        self.assertEqual((self.world / '.codingkeeper/msg').read_text(), 'TASK_RESULT: DONE')
        self.assertEqual((self.world / '.codingkeeper/msg.tok').read_text(), '7')

    def daily_stub(self, command="codex", tool="codex"):
        return self.shell("codexc-daily", r'''
notify() { :; }
sleep() { :; }
latest_rollout() { printf ignored; }
latest_cwd() { printf '%s.' "$PWD"; }
last_turn_state() { printf died; }
resolve_session_name() { printf audit; }
send_text() { printf SENT; }
tmux() {
 case "$*" in
  *'#{session_path}'*|*'#{pane_current_path}'*) printf '%s' "$PWD" ;;
  *'#{pane_id}'*) printf '%%1' ;;
  *'#{pane_current_command}'*) printf '%s' "$AUDIT_COMMAND" ;;
  *'@codexc_tool'*) printf '%s' "$AUDIT_TOOL" ;;
  *) return 0 ;;
 esac
}
run_now
''', CODEXC_DAILY_IDLE="0", AUDIT_COMMAND=command, AUDIT_TOOL=tool)

    def test_daily_never_types_into_shell(self):
        self.assertNotIn("SENT", self.daily_stub(command="bash"))

    def test_daily_never_types_into_other_tool(self):
        self.assertNotIn("SENT", self.daily_stub(tool="claude"))

    def test_daily_can_resume_verified_codex(self):
        self.assertIn("SENT", self.daily_stub())

    def test_long_turn_can_finish_after_stall_threshold(self):
        self.write_rollout([])
        (self.world / ".codingkeeper/queue.md").write_text("## ready\n- [ ] task\n")
        (self.world / "clock").write_text("100")
        output = self.shell("codexc-loop", r'''
notify() { :; }
banner_set() { :; }
sleep() { :; }
date() { if [ "$1" = +%s ]; then cat clock; else command date "$@"; fi; }
pane_idle() { [ "$iterations" != 2 ]; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() {
 iterations=$((iterations+1))
 case "$iterations" in
  2) printf 106 > clock; printf '%s\n' '{"payload":{"type":"token_count"}}' >> rollout.jsonl ;;
  3) printf 112 > clock; printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> rollout.jsonl ;;
 esac
 [ "$iterations" -lt 9 ]
}
feed_msg() { :; }
gate_run() { return 0; }
review_run() { printf 0; }
run_driver audit
cat .codingkeeper/journal 2>/dev/null || true
''', CODEXC_LOOP_STALL="5", CODEXC_TURN_TIMEOUT="30")
        self.assertIn("accepted after", output)

    def provider_timeline(self, steps, tasks=('task',), **environment):
        self.write_rollout([])
        state = self.world / '.codingkeeper'
        (state / 'queue.md').write_text('## ready\n' + ''.join('- [ ] ' + task + '\n' for task in tasks))
        (state / 'timeline.json').write_text(json.dumps(steps))
        binaries = self.world / 'bin'
        binaries.mkdir(exist_ok=True)
        tmux = binaries / 'tmux'
        tmux.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
if sys.argv[1] == 'show-option':
    print({'@codexc_owner': os.environ['AUDIT_DRIVER_PID'],
           '@codexc_tool': os.environ['CODEXC_TOOL'],
           '@codexc_project': str(Path.cwd().resolve())}.get(sys.argv[-1], ''))
elif sys.argv[1] == 'capture-pane':
    print('esc to interrupt' if Path('.codingkeeper/busy').exists() else 'ctrl+p commands')
''')
        tmux.chmod(0o755)
        (self.world / 'timeline.py').write_text('''import json, os, sys, time
from pathlib import Path
state = Path('.codingkeeper')
steps = json.loads((state / 'timeline.json').read_text())
position = int(sys.argv[1]) - 1
if position:
    with (state / 'observations.jsonl').open('a') as output:
        status = json.loads((state / 'status.json').read_text()) if (state / 'status.json').exists() else {}
        output.write(json.dumps({'at': steps[position - 1]['at'], 'halt': (state / 'loop.halt').exists(),
                                 'status': status}) + '\\n')
if position == len(steps):
    raise SystemExit(1)
step = steps[position]
(state / 'clock').write_text(str(step['at']))
record = dict(tool=os.environ['CODEXC_TOOL'], pane='%1', owner=sys.argv[2], pid=int(sys.argv[2]),
              project=str(Path.cwd().resolve()), generation=os.environ['CK_PROVIDER_GENERATION'],
              phase='waiting_provider' if step.get('wait') else 'active', heartbeat=time.time(),
              source=str(Path('rollout.jsonl').resolve()))
fault = step.get('fault')
if fault == 'stale': record['heartbeat'] -= 60
if fault == 'generation': record['generation'] = 'b' * 32
if fault == 'owner': record['owner'] = '1'
if fault == 'source': record['source'] += '.foreign'
if fault == 'dead': record['pid'] = 1
if fault == 'busy': (state / 'busy').touch()
else: (state / 'busy').unlink(missing_ok=True)
temporary = state / '.control'
temporary.write_text(json.dumps(record))
temporary.replace(state / 'provider-supervisor-1.json')
if fault == 'manual':
    temporary.write_text('operator pause')
    temporary.replace(state / 'loop.halt')
if step.get('complete'):
    with Path('rollout.jsonl').open('a') as output:
        output.write(json.dumps({'payload': {'type': 'task_complete', 'last_agent_message': 'TASK_RESULT: DONE'}}) + '\\n')
''')
        config = dict(HOME=str(self.world), CODEXC_LOG_DIR=str(self.world / 'logs'),
                      PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                      CODEXC_TOOL='codex', CK_PROVIDER_GENERATION='a' * 32,
                      CODEXC_REQUIRE_GATE='0', CODEXC_ACTIVE_WINDOW='',
                      CODEXC_LOOP_STALL='300', CODEXC_TURN_TIMEOUT='10')
        config.update(environment)
        self.shell('codexc-loop', r'''
export AUDIT_DRIVER_PID=$$
sleep() { :; }
date() { if [ "$1" = +%s ]; then cat .codingkeeper/clock; else command date "$@"; fi; }
find_rollout() { printf '%s' "$PWD/rollout.jsonl"; }
iterations=0
pane_alive() {
    iterations=$((iterations+1))
    command python3 timeline.py "$iterations" "$$"
}
feed_msg() { printf 'feed\n' >> .codingkeeper/feeds; }
gate_run() { return 0; }
review_run() { printf 0; }
run_driver '%1'
''', **config)
        return [json.loads(line) for line in (state / 'observations.jsonl').read_text().splitlines()]

    def test_provider_wait_preserves_remaining_turn_budget_across_repeated_pauses(self):
        observations = self.provider_timeline([
            {'at': 100}, {'at': 104, 'wait': True}, {'at': 130, 'wait': True}, {'at': 131},
            {'at': 133, 'wait': True}, {'at': 180, 'wait': True}, {'at': 182}, {'at': 183}])
        self.assertFalse(any(row['halt'] for row in observations[:-1]), observations)
        self.assertTrue(observations[-1]['halt'], 'real execution must still reach its original timeout budget')
        self.assertTrue(observations[3]['status']['active'], 'recovery must clear the waiting display')
        self.assertNotEqual(observations[3]['status']['phase'], 'waiting_provider')
        self.assertEqual((self.world / '.codingkeeper/feeds').read_text(), 'feed\n')
        self.assertFalse((self.world / '.codingkeeper/journal').exists())

    def test_provider_wait_can_resume_and_accept_the_original_task(self):
        observations = self.provider_timeline([
            {'at': 100}, {'at': 104, 'wait': True}, {'at': 160, 'wait': True},
            {'at': 161, 'complete': True}, {'at': 161}, {'at': 161}])
        self.assertFalse(any(row['halt'] for row in observations), observations)
        self.assertIn('- [x] task', (self.world / '.codingkeeper/queue.md').read_text())
        self.assertEqual((self.world / '.codingkeeper/journal').read_text().count('receipt='), 1)
        self.assertEqual((self.world / '.codingkeeper/feeds').read_text(), 'feed\n')

    def test_invalid_provider_wait_does_not_hide_turn_timeout(self):
        for fault in ('stale', 'generation', 'owner', 'source', 'dead', 'busy'):
            with self.subTest(fault=fault):
                (self.world / '.codingkeeper/loop.halt').unlink(missing_ok=True)
                (self.world / '.codingkeeper/observations.jsonl').unlink(missing_ok=True)
                observations = self.provider_timeline([
                    {'at': 100}, {'at': 104, 'wait': True}, {'at': 130, 'wait': True},
                    {'at': 160, 'wait': True, 'fault': fault}])
                self.assertFalse(any(row['halt'] for row in observations[:-1]), observations)
                self.assertTrue(observations[-1]['halt'], observations)

    def test_provider_wait_cannot_override_manual_halt(self):
        observations = self.provider_timeline([
            {'at': 100}, {'at': 104, 'wait': True}, {'at': 160, 'wait': True},
            {'at': 161, 'wait': True, 'fault': 'manual'}])
        self.assertFalse(any(row['halt'] for row in observations[:-1]), observations)
        self.assertTrue(observations[-1]['halt'])
        self.assertEqual((self.world / '.codingkeeper/loop.halt').read_text(), 'operator pause')

    def test_late_provider_wait_cannot_reset_exhausted_execution_budget(self):
        observations = self.provider_timeline([{'at': 100}, {'at': 111, 'wait': True}])
        self.assertTrue(observations[-1]['halt'])

    def test_provider_wait_credit_does_not_extend_the_next_task(self):
        observations = self.provider_timeline([
            {'at': 100}, {'at': 104, 'wait': True}, {'at': 160, 'wait': True},
            {'at': 161, 'complete': True}, {'at': 161}, {'at': 162}, {'at': 172}],
            tasks=('task', 'next task'))
        self.assertFalse(any(row['halt'] for row in observations[:-1]), observations)
        self.assertTrue(observations[-1]['halt'])
        self.assertIn('- [x] task\n- [ ] next task', (self.world / '.codingkeeper/queue.md').read_text())
        self.assertEqual((self.world / '.codingkeeper/journal').read_text().count('receipt='), 1)
        self.assertEqual((self.world / '.codingkeeper/feeds').read_text(), 'feed\nfeed\n')


if __name__ == "__main__":
    unittest.main(verbosity=2)
