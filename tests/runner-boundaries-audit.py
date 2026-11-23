#!/usr/bin/env python3
"""Runner cancellation boundaries with private projects and offline workers."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest


ROOT = Path(os.environ.get('CK_AUDIT_SOURCE', Path(__file__).resolve().parents[1]))

TUI = r'''
notify() { :; }
register_project() { :; }
sleep() { :; }
tmux() { return 0; }
pane_idle() { return 0; }
gate_run() { : > "$1"; return 0; }
find_rollout() { printf '%s' "$PWD/.codingkeeper/rollout.jsonl"; }
iterations=0
pane_alive() {
    iterations=$((iterations + 1))
    [ "$iterations" -lt 15 ]
}
feed_msg() {
    printf '%s\n' "$2" >> .codingkeeper/feeds
    printf '%s\n' '{"payload":{"type":"task_complete","last_agent_message":"TASK_RESULT: DONE"}}' >> .codingkeeper/rollout.jsonl
}
review_run() {
    printf 'review\n' >> .codingkeeper/reviews
    printf 'BUGS: 0\n' > "$2"
    printf 0
}
'''

HEADLESS = r'''
notify() { :; }
register_project() { :; }
banner_set() { :; }
headless_wait_status() { printf '%s\n' "$2" >> .codingkeeper/wait-phases; }
fixture_step() {
    local count
    printf '%s\n' "$1" >> ".codingkeeper/$1"
    count=$(wc -l < ".codingkeeper/$1")
    [ "$count" -le 12 ] || exit 88
    FIXTURE_RESULT="$(printf '%s\n' "$2" | sed -n "${count// /}p")"
    FIXTURE_RESULT="${FIXTURE_RESULT:-$3}"
}
fixture_pause() {
    touch .codingkeeper/pause-pending
    if [ "${PAUSE_POLICY:-window}" = manual ]; then
        printf 'operator pause\n' > .codingkeeper/loop.halt
    fi
}
ck_window_check() {
    CK_WINDOW_NEXT_OPEN=0
    if [ -e .codingkeeper/pause-pending ]; then
        CK_WINDOW_REASON=outside_window
        [ "${PAUSE_POLICY:-window}" != invalid ] || CK_WINDOW_REASON=invalid_timezone
        return 125
    fi
    return 0
}
ck_interaction_check() {
    [ "${PAUSE_POLICY:-window}" != interaction ] || [ ! -e .codingkeeper/pause-pending ]
}
sleep() {
    if [ -e .codingkeeper/pause-pending ]; then
        rm .codingkeeper/pause-pending
        printf 'resumed\n' >> .codingkeeper/resumes
        if [ "${MUTATE_ON_PAUSE:-0}" = 1 ]; then printf 'changed while paused\n' > product.txt; fi
    elif [ -e .codingkeeper/journal ]; then
        exit 0
    fi
}
headless_turn() {
    printf '%s\n' "$1" >> .codingkeeper/prompts
    fixture_step workers "$WORKER_RESULTS" "${WORKER_DEFAULT:-done}"
    : > "$2"
    case "$FIXTURE_RESULT" in
        done) printf 'TASK_RESULT: DONE\n' > "$2" ;;
        125) fixture_pause; return 125 ;;
        *) return "$FIXTURE_RESULT" ;;
    esac
}
gate_run() {
    fixture_step gates "$GATE_RESULTS" 0
    printf 'gate result %s\n' "$FIXTURE_RESULT" > "$1"
    [ "$FIXTURE_RESULT" != 125 ] || fixture_pause
    return "$FIXTURE_RESULT"
}
review_run() {
    fixture_step reviews "$REVIEW_RESULTS" 0
    : > "$2"
    if [ "$FIXTURE_RESULT" = 125 ]; then fixture_pause; return 125; fi
    printf 'BUGS: %s\n' "$FIXTURE_RESULT" > "$2"
    printf '%s' "$FIXTURE_RESULT"
}
'''


class RunnerBoundariesAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-runner-boundaries-', dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        (self.world / 'home').mkdir()
        self.env = dict(PATH=os.environ['PATH'], HOME=str(self.world / 'home'),
                        CODEX_HOME=str(self.world / 'home/.codex'), TMPDIR=str(self.world),
                        CODEXC_ACTIVE_WINDOW='', CODEXC_LOOP_NOTIFY='0', CODEXC_NOTIFY='0',
                        CODEXC_LOOP_IDLE='0', CODEXC_AUTO_RESUME='0', CODEXC_BANNER='0',
                        CODEXC_REQUIRE_GATE='1', CODEXC_REVIEW_PASS='2',
                        CODEXC_REVIEW_ROUNDS='2', CODEXC_REVIEW_PARSE_RETRIES='0',
                        CODEXC_TURN_TIMEOUT='3600', CODEXC_LOOP_STALL='300',
                        CODEXC_HEADLESS_CMD='true', CODEXC_REVIEW_PARALLEL='0',
                        GIT_CONFIG_NOSYSTEM='1')
        subprocess.run(['git', 'init', '-q', str(self.world)], check=True,
                       env=self.env, capture_output=True, timeout=10)
        (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\n')
        (self.world / 'product.txt').write_text('original candidate\n')
        (self.state / 'queue.md').write_text('## ready\n- [ ] task\n')
        (self.state / 'gate.sh').write_text('#!/bin/bash\nexit 0\n')
        (self.state / 'rollout.jsonl').write_text('')

    def shell(self, body, script='codexc-loop', **environment):
        path = ROOT / script
        marker = '# ---- dispatch' if script == 'codexc-loop' else '\ncase "${1:-}" in'
        source = path.read_text().rsplit(marker, 1)[0]
        process = subprocess.Popen(['/bin/bash', '-c', source + '\n' + body, str(path)],
                                   cwd=self.world, env=self.env | environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=30)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        return stdout

    def trace(self, name):
        path = self.state / name
        return path.read_text().splitlines() if path.exists() else []

    def assert_accepted(self):
        self.assertIn('- [x] task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'loop.halt').exists())
        receipts = list((self.state / 'evidence').glob('*/accepted.json'))
        self.assertEqual(len(receipts), 1)

    def headless(self, workers='done', gates='0', reviews='0', body='', **environment):
        self.shell(HEADLESS + body + '\nrun_runner\n', script='codexc-headless',
                   WORKER_RESULTS=workers, GATE_RESULTS=gates, REVIEW_RESULTS=reviews,
                   **environment)

    def assert_parked(self, reason):
        self.assertTrue((self.state / 'loop.halt').exists(), 'runner accepted or exited without parking')
        self.assertIn(reason, (self.state / 'loop.halt').read_text())
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'journal').exists())

    def assert_main_worker_once(self):
        self.assertEqual(sum('队列任务:' in prompt for prompt in self.trace('prompts')), 1)

    def test_headless_gate_and_repair_resume_restore_running_status(self):
        self.shell(r'''
task=fixture
CK_TURN_TS=123
leaf_gate_run() {
    if [ ! -e .codingkeeper/interrupted ]; then touch .codingkeeper/interrupted; return 125; fi
    status_touch
    cp .codingkeeper/status.json .codingkeeper/gate-status.json
    return 0
}
headless_wait_ready() { headless_wait_status waiting waiting_window 999; }
leaf_verify() { return 0; }
headless_gate_run .codingkeeper/gate-result
rm .codingkeeper/interrupted
headless_turn() {
    if [ ! -e .codingkeeper/interrupted ]; then touch .codingkeeper/interrupted; return 125; fi
    status_touch
    cp .codingkeeper/status.json .codingkeeper/repair-status.json
    printf 'TASK_RESULT: DONE\n' > "$2"
}
headless_repair_turn repair .codingkeeper/repair-result gate
''', script='codexc-headless')
        for stage in ('gate', 'repair'):
            with self.subTest(stage=stage):
                status = json.loads((self.state / (stage + '-status.json')).read_text())
                self.assertTrue(status['active'], status)
                self.assertEqual(status['started_at'], 123)
                self.assertEqual(status['next_run_at'], 0)
                self.assertNotIn('waiting', status['phase'])

    def test_headless_post_review_gate_retries_worker_with_turn_budget(self):
        self.headless(workers='done\ndone\n42\ndone', gates='0\n1\n0', reviews='1\n0',
                      CODEXC_GATE_RETRIES='1', CODEXC_TURN_RETRIES='3', CODEXC_REVIEW_PASS='1')
        self.assert_accepted()
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 4)
        self.assertEqual(len(self.trace('gates')), 3)

    def test_headless_post_review_gate_enforces_smaller_turn_budget(self):
        self.headless(workers='done\ndone\n42', gates='0\n1', reviews='1', WORKER_DEFAULT='42',
                      CODEXC_GATE_RETRIES='3', CODEXC_TURN_RETRIES='1', CODEXC_REVIEW_PASS='1')
        self.assert_parked('gate fix turn failed')
        self.assertEqual(len(self.trace('workers')), 3)
        self.assertEqual(len(self.trace('gates')), 2)

    def test_headless_initial_gate_pause_keeps_task_and_worker(self):
        self.headless(gates='125\n0')
        self.assert_accepted()
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('gates')), 2)
        self.assertEqual(self.trace('resumes'), ['resumed'])

    def test_headless_repaired_gate_pause_keeps_repair_budget(self):
        self.headless(gates='1\n125\n0', CODEXC_GATE_RETRIES='1')
        self.assert_accepted()
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 2)
        self.assertEqual(len(self.trace('gates')), 3)

    def test_headless_review_fix_gate_pause_keeps_review_budget(self):
        self.headless(gates='0\n125\n0', reviews='1\n0', CODEXC_REVIEW_PASS='1',
                      CODEXC_REVIEW_ROUNDS='1')
        self.assert_parked('review rounds exhausted')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 2)
        self.assertEqual(len(self.trace('reviews')), 1)

    def test_headless_post_review_gate_pause_cannot_reset_review_budget(self):
        self.headless(gates='0\n1\n125\n0', reviews='1\n0', CODEXC_REVIEW_PASS='1',
                      CODEXC_GATE_RETRIES='1', CODEXC_REVIEW_ROUNDS='1')
        self.assert_parked('review rounds exhausted')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 3)
        self.assertEqual(len(self.trace('gates')), 4)
        self.assertEqual(len(self.trace('reviews')), 1)

    def test_headless_cancelled_review_preserves_zero_streak_and_budget(self):
        self.headless(reviews='0\n125\n0', PAUSE_POLICY='interaction')
        self.assert_accepted()
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('gates')), 1)
        self.assertEqual(len(self.trace('reviews')), 3)
        self.assertIn('waiting_interaction', self.trace('wait-phases'))

    def test_headless_cancelled_review_preserves_parse_budget(self):
        self.headless(reviews='parse-fail\n125\nparse-fail', CODEXC_REVIEW_PARSE_RETRIES='1',
                      CODEXC_REVIEW_ROUNDS='3')
        self.assert_parked('review output unparseable')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('reviews')), 3)

    def test_headless_parallel_review_pause_does_not_consume_budget(self):
        self.headless(CODEXC_REVIEW_PARALLEL='1', body=r'''
review_batch() {
    printf '%s\n' "$3" >> .codingkeeper/batches
    if [ ! -e .codingkeeper/batch-cancelled ]; then
        touch .codingkeeper/batch-cancelled
        fixture_pause
        return 125
    fi
    return 0
}
''')
        self.assert_accepted()
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('gates')), 1)
        self.assertEqual(self.trace('batches'), ['2', '2'])

    def test_headless_gate_repair_pause_preserves_failed_turns(self):
        self.headless(workers='done\n42\n125\n42', gates='1',
                      CODEXC_GATE_RETRIES='1', CODEXC_TURN_RETRIES='2')
        self.assert_parked('gate fix turn failed')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 4)
        self.assertEqual(len(self.trace('gates')), 1)

    def test_headless_review_repair_pause_preserves_failed_turns(self):
        self.headless(workers='done\n42\n125\n42', reviews='1', CODEXC_TURN_RETRIES='2')
        self.assert_parked('review fix turn failed')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 4)
        self.assertEqual(len(self.trace('reviews')), 1)

    def test_headless_post_review_gate_repair_pause_preserves_failed_turns(self):
        self.headless(workers='done\ndone\n42\n125\n42', gates='0\n1', reviews='1',
                      CODEXC_GATE_RETRIES='3', CODEXC_TURN_RETRIES='2')
        self.assert_parked('gate fix turn failed')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('workers')), 5)
        self.assertEqual(len(self.trace('reviews')), 1)
        self.assertEqual(len(self.trace('gates')), 2)

    def test_headless_manual_halt_during_gate_is_preserved(self):
        self.headless(gates='125', PAUSE_POLICY='manual')
        self.assert_parked('operator pause')
        self.assertEqual(len(self.trace('workers')), 1)
        self.assertEqual(self.trace('resumes'), [])

    def test_headless_manual_halt_during_review_is_preserved(self):
        self.headless(reviews='125', PAUSE_POLICY='manual')
        self.assert_parked('operator pause')
        self.assertEqual(len(self.trace('workers')), 1)
        self.assertEqual(self.trace('resumes'), [])

    def test_headless_invalid_policy_during_gate_stops(self):
        self.headless(gates='125', PAUSE_POLICY='invalid')
        self.assert_parked('invalid availability policy or quota state')
        self.assertEqual(len(self.trace('workers')), 1)

    def test_headless_review_pause_rejects_changed_candidate(self):
        self.headless(reviews='0\n125\n0', MUTATE_ON_PAUSE='1')
        self.assert_parked('review changed candidate')
        self.assert_main_worker_once()
        self.assertEqual(len(self.trace('gates')), 1)

    def test_tui_cancelled_gate_resumes_without_another_worker_turn(self):
        self.shell(TUI + r'''
gate_run() {
    printf 'gate\n' >> .codingkeeper/gates
    : > "$1"
    if [ ! -e .codingkeeper/gate-cancelled ]; then
        touch .codingkeeper/gate-cancelled
        return 125
    fi
    return 0
}
run_driver audit
''')
        self.assert_accepted()
        self.assertEqual(len(self.trace('feeds')), 1)
        self.assertEqual(len(self.trace('gates')), 2)
        self.assertEqual(len(self.trace('reviews')), 2)

    def test_tui_cancelled_review_preserves_parse_and_review_budgets(self):
        self.shell(TUI + r'''
review_run() {
    printf 'review\n' >> .codingkeeper/reviews
    : > "$2"
    if [ ! -e .codingkeeper/review-cancelled ]; then
        touch .codingkeeper/review-cancelled
        printf window-closed
        return 125
    fi
    printf 'BUGS: 0\n' > "$2"
    printf 0
}
run_driver audit
''')
        self.assert_accepted()
        self.assertEqual(len(self.trace('feeds')), 1)
        self.assertEqual(len(self.trace('reviews')), 3)

    def test_tui_cancelled_gate_resumes_after_a_long_closed_window(self):
        self.shell(TUI + r'''
date() {
    if [ "$1" = +%s ] && [ -e .codingkeeper/window-waited ]; then
        printf '%s\n' "$(( $(command date +%s) + 600 ))"
    else
        command date "$@"
    fi
}
ck_run_check() {
    if [ -e .codingkeeper/gate-cancelled ] && [ ! -e .codingkeeper/window-waited ]; then
        touch .codingkeeper/window-waited
        CK_WINDOW_REASON=outside_window
        return 125
    fi
    return 0
}
gate_run() {
    printf 'gate\n' >> .codingkeeper/gates
    : > "$1"
    if [ ! -e .codingkeeper/gate-cancelled ]; then
        touch .codingkeeper/gate-cancelled
        return 125
    fi
    return 0
}
run_driver audit
''')
        self.assert_accepted()
        self.assertEqual(len(self.trace('feeds')), 1)
        self.assertEqual(len(self.trace('gates')), 2)

    def test_tui_manual_halt_during_review_does_not_become_parse_failure(self):
        self.shell(TUI + r'''
review_run() {
    printf 'operator pause\n' > .codingkeeper/loop.halt
    : > "$2"
    printf window-closed
    return 125
}
run_driver audit
''')
        self.assertEqual((self.state / 'loop.halt').read_text(), 'operator pause\n')
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        log = (self.world / 'home/.codingkeeper/codexc-watch.log').read_text()
        self.assertNotIn('review output unparseable', log)
        self.assertFalse((self.state / 'journal').exists())

    def test_gate_process_exit_125_consumes_failure_budget(self):
        (self.state / 'gate.sh').write_text('#!/bin/bash\nprintf "gate\\n" >> .codingkeeper/gates\nexit 125\n')
        stubs = TUI.replace('gate_run() { : > "$1"; return 0; }\n', '')
        self.shell(stubs + r'''
sleep() {
    if [ "$1" != "$CODEXC_LOOP_POLL" ]; then command sleep "$@"; fi
}
run_driver audit
''', CODEXC_GATE_RETRIES='1')
        self.assertTrue((self.state / 'loop.halt').exists())
        self.assertEqual(len(self.trace('gates')), 2)
        self.assertEqual(len(self.trace('feeds')), 2)
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'journal').exists())

    def test_lost_completion_during_gate_cancellation_stops_explicitly(self):
        self.shell(TUI + r'''
gate_run() {
    : > "$1"
    : > .codingkeeper/rollout.jsonl
    return 125
}
run_driver audit
''')
        self.assertTrue((self.state / 'loop.halt').exists())
        self.assertEqual(len(self.trace('feeds')), 1)
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'journal').exists())

    def test_lost_completion_during_review_cancellation_stops_explicitly(self):
        self.shell(TUI + r'''
find_rollout() {
    if [ -f .codingkeeper/rollout.jsonl ]; then printf '%s' "$PWD/.codingkeeper/rollout.jsonl"; fi
}
review_run() {
    : > "$2"
    rm .codingkeeper/rollout.jsonl
    printf window-closed
    return 125
}
run_driver audit
''')
        self.assertTrue((self.state / 'loop.halt').exists())
        self.assertEqual(len(self.trace('feeds')), 1)
        self.assertIn('- [ ] task', (self.state / 'queue.md').read_text())
        self.assertFalse((self.state / 'journal').exists())

    def test_real_gate_exit_codes_do_not_impersonate_controller_signals(self):
        for exit_code, expected in ((0, 0), (42, 42), (125, 1), (126, 1)):
            with self.subTest(exit_code=exit_code):
                (self.state / 'gate.sh').write_text('#!/bin/bash\nexit ' + str(exit_code) + '\n')
                output = self.shell(r'''
trap loop_cleanup EXIT
gate_run .codingkeeper/gate-result
printf '%s\n' "$?"
''', script='codexc-headless')
                self.assertEqual(output.strip(), str(expected))
                if exit_code in (125, 126):
                    self.assertIn(str(exit_code), (self.state / 'gate-result').read_text())


if __name__ == '__main__':
    unittest.main()
