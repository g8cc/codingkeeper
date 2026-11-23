#!/usr/bin/env python3
"""Provider replacement keeps the exact headless task/session; no model calls."""
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HeadlessProviderAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ck-provider-hl-', dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.world = Path(self.tmp.name)
        self.state = self.world / '.codingkeeper'
        self.state.mkdir()
        self.home = self.world / 'home'
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('CODEXC_', 'CODEX_', 'ZCODE_', 'DSH_', 'TMUX'))}
        self.env.update(HOME=str(self.home), CODEXC_ACTIVE_WINDOW='', CODEXC_LOOP_NOTIFY='0',
                        CODEXC_NOTIFY='0', CODEXC_REQUIRE_GATE='0', CODEXC_LOOP_IDLE='0',
                        CODEXC_AUTO_RESUME='0', CODEXC_BANNER='0')
        self.a, self.b = 'a' * 64, 'b' * 64
        (self.world / 'provider').write_text(self.a)

    def shell(self, body, timeout=20, adapter_stubs=True):
        source = (ROOT / 'codexc-headless').read_text().rsplit('\ncase "${1:-}" in', 1)[0]
        source = '\n'.join('. ' + shlex.quote(str(ROOT / 'ck-common.sh'))
                           if line.startswith('. "$(dirname') else line for line in source.splitlines())
        # The adapter config parser has its own audit. Control only its public
        # fingerprint/error outputs here, while running real supervised workers.
        stubs = r'''
headless_provider_tool() { case "${CODEXC_HEADLESS_CMD:-}" in *zcode-worker*) printf zcode;; *dsh-worker*) printf dsh;; *) return 1;; esac; }
headless_provider_fingerprint() { cat provider; }
headless_provider_error() { grep -Eq 'CK_ERROR_CLASS: (auth|quota|transient)' "$1"; }
sleep() { command sleep .03; }
''' if adapter_stubs else '\nsleep() { command sleep .03; }\n'
        process = subprocess.Popen(['/bin/bash', '-c', source + '\n' + stubs + body],
                                   cwd=self.world, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise AssertionError('isolated provider fixture did not terminate') from None
        self.assertEqual(process.returncode, 0, out + err)
        return out

    def worker(self, tool='dsh', change=True, failure='quota', session=True):
        if session:
            (self.state / (tool + '-session-id')).write_text('exact-session\n')
        worker = self.world / ('fake-' + tool + '-worker')
        worker.write_text('#!/bin/bash\n' + r'''
n=$(cat calls 2>/dev/null || echo 0)
echo $((n+1)) > calls
cat >> prompts
printf '\n--turn--\n' >> prompts
cat .codingkeeper/''' + tool + r'''-session-id >> sessions 2>/dev/null || true
if [ "$n" = 0 ]; then
''' + ("printf '%s' '" + self.b + "' > provider\n" if change else '') +
                          '  printf "CK_ERROR_CLASS: ' + failure + '\\n"\n  exit 1\nfi\nprintf "TASK_RESULT: DONE\\n"\n')
        worker.chmod(0o755)
        return 'CODEXC_HEADLESS_CMD=' + shlex.quote(str(worker)) + '\n'

    def test_changed_provider_retries_same_prompt_and_exact_session_for_both_adapters(self):
        for tool in ('dsh', 'zcode'):
            with self.subTest(tool=tool):
                for name in ('calls', 'prompts', 'sessions'):
                    (self.world / name).unlink(missing_ok=True)
                (self.world / 'provider').write_text(self.a)
                out = self.shell(self.worker(tool) + r'''
headless_turn 'original task; preserve all context' .codingkeeper/out
printf 'rc=%s' "$?"
''')
                self.assertEqual(out, 'rc=0')
                self.assertEqual((self.world / 'calls').read_text().strip(), '2')
                self.assertEqual((self.world / 'sessions').read_text().splitlines(),
                                 ['exact-session', 'exact-session'])
                self.assertEqual((self.world / 'prompts').read_text().count('original task; preserve all context'), 2)

    def test_config_changed_after_failure_is_seen_without_restarting_runner(self):
        out = self.shell(self.worker(change=False, failure='auth') + r'''
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q waiting_provider .codingkeeper/status.json; then
        printf '%s' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > provider
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_unchanged_provider_never_retries_and_manual_halt_ends_wait(self):
        out = self.shell(self.worker(change=False) + r'''
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q waiting_provider .codingkeeper/status.json; then
        cp .codingkeeper/status.json waiting.json
        touch .codingkeeper/loop.halt
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=125')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')
        self.assertIn('waiting_provider', (self.world / 'waiting.json').read_text())

    def test_no_saved_session_never_creates_a_new_context_on_retry(self):
        out = self.shell(self.worker(session=False) + 'headless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')

    def test_unrelated_failure_does_not_restart_even_when_config_changes(self):
        out = self.shell(self.worker(failure='unknown') + 'headless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')

    def test_unknown_worker_failure_with_task_network_words_is_not_a_provider_error(self):
        for text in ('failed to edit network.py: task timeout\nCK_ERROR_CLASS: unknown\n',
                     'tests/test_network.py expected a connection timeout\n',
                     'CK_ERROR_CLASS: auth\nCK_ERROR_CLASS: unknown\n'):
            with self.subTest(text=text):
                (self.state / 'error').write_text(text)
                out = self.shell('headless_provider_error .codingkeeper/error; printf "rc=%s" "$?"\n',
                                 adapter_stubs=False)
                self.assertEqual(out, 'rc=1')

    def test_manual_halt_has_priority_over_new_config(self):
        setup = self.worker()
        worker = self.world / 'fake-dsh-worker'
        worker.write_text(worker.read_text().replace('  exit 1', '  touch .codingkeeper/loop.halt\n  exit 1'))
        out = self.shell(setup + 'headless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=125')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')

    def test_repeated_config_fingerprint_is_not_retried_again(self):
        setup = self.worker()
        worker = self.world / 'fake-dsh-worker'
        worker.write_text(worker.read_text().replace('printf "TASK_RESULT: DONE\\n"',
            "printf '%s' '" + self.a + "' > provider\nprintf 'CK_ERROR_CLASS: quota\\n'\nexit 1"))
        out = self.shell(setup + 'headless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_configuration_restart_budget_is_honored(self):
        setup = self.worker()
        worker = self.world / 'fake-dsh-worker'
        worker.write_text(worker.read_text().replace('printf "TASK_RESULT: DONE\\n"',
            "printf '%s' '" + 'c' * 64 + "' > provider\nprintf 'CK_ERROR_CLASS: quota\\n'\nexit 1"))
        out = self.shell(setup + 'CODEXC_PROVIDER_MAX_RESTARTS=1\nheadless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_transient_backoff_keeps_existing_bounded_same_provider_retry(self):
        out = self.shell(self.worker(change=False, failure='transient') + r'''
CODEXC_AUTO_RESUME=1
printf 1000 > clock
date() { if [ "$1" = +%s ]; then cat clock; else command date "$@"; fi; }
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q backoff .codingkeeper/status.json; then
        cat calls > calls-before-deadline
        printf 1601 > clock
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s;retries=%s' "$?" "${auto_resume:-0}"
''')
        self.assertEqual(out, 'rc=0;retries=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_config_change_interrupts_transient_backoff_before_retry_deadline(self):
        out = self.shell(self.worker(change=False, failure='transient') + r'''
CODEXC_AUTO_RESUME=1
date() { if [ "$1" = +%s ]; then printf 1000; else command date "$@"; fi; }
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q backoff .codingkeeper/status.json; then
        printf '%s' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > provider
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s;retries=%s' "$?" "${auto_resume:-0}"
''')
        self.assertEqual(out, 'rc=0;retries=0')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_same_provider_transient_retries_do_not_exceed_existing_budget(self):
        setup = self.worker(change=False, failure='transient')
        worker = self.world / 'fake-dsh-worker'
        worker.write_text(worker.read_text().replace('printf "TASK_RESULT: DONE\\n"',
                                                    "printf 'CK_ERROR_CLASS: transient\\n'\nexit 1"))
        out = self.shell(setup + r'''
CODEXC_AUTO_RESUME=2
printf 1000 > clock
date() { if [ "$1" = +%s ]; then cat clock; else command date "$@"; fi; }
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q backoff .codingkeeper/status.json; then
        printf '%s' "$(( $(cat clock) + 6000 ))" > clock
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s;retries=%s' "$?" "${auto_resume:-0}"
''')
        self.assertEqual(out, 'rc=1;retries=2')
        self.assertEqual((self.world / 'calls').read_text().strip(), '3')

    def test_disabled_recovery_preserves_original_failure(self):
        out = self.shell(self.worker() + 'CODEXC_PROVIDER_RECOVERY=0\nheadless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')

    def test_interaction_blocks_restart_until_user_releases_turn(self):
        out = self.shell(self.worker() + r'''
headless_provider_error() { touch block-recovery; grep -Eq 'CK_ERROR_CLASS: (auth|quota|transient)' "$1"; }
ck_interaction_check() { [ ! -f block-recovery ] || [ -f released ]; }
sleep() {
    if [ ! -f released ] && [ -f .codingkeeper/status.json ] && grep -q waiting_interaction .codingkeeper/status.json; then
        cat calls > calls-before-release
        touch released
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        self.assertEqual((self.world / 'calls-before-release').read_text().strip(), '1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_window_blocks_restart_until_it_opens(self):
        out = self.shell(self.worker() + r'''
headless_provider_error() { touch block-recovery; grep -Eq 'CK_ERROR_CLASS: (auth|quota|transient)' "$1"; }
ck_window_check() {
    if [ -f block-recovery ] && [ ! -f window-open ]; then
        CK_WINDOW_REASON=outside_window; CK_WINDOW_NEXT_OPEN=$(( $(date +%s) + 600 )); return 125
    fi
    CK_WINDOW_DEADLINE=0; return 0
}
sleep() {
    if [ ! -f window-open ] && [ -f .codingkeeper/status.json ] && grep -q waiting_window .codingkeeper/status.json; then
        cat calls > calls-before-open
        touch window-open
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        self.assertEqual((self.world / 'calls-before-open').read_text().strip(), '1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '2')

    def test_session_changed_during_wait_is_preserved_without_resuming_it(self):
        out = self.shell(self.worker(change=False) + r'''
sleep() {
    if [ -f .codingkeeper/status.json ] && grep -q waiting_provider .codingkeeper/status.json; then
        printf 'foreign-session\n' > .codingkeeper/dsh-session-id
        printf '%s' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > provider
    fi
    command sleep .03
}
headless_turn task .codingkeeper/out; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=1')
        self.assertEqual((self.world / 'calls').read_text().strip(), '1')
        self.assertEqual((self.state / 'dsh-session-id').read_text(), 'foreign-session\n')

    def test_quota_marker_for_old_provider_is_cleared_only_after_config_changes(self):
        (self.state / 'dsh-session-id').write_text('exact-session\n')
        out = self.shell("CODEXC_HEADLESS_CMD=fake-dsh-worker\n" +
            "printf 'v2 %s dsh %s\\n' \"$(( $(date +%s) + 600 ))\" '" + self.a + "' > .codingkeeper/quota-until\n" +
            "printf '%s' '" + self.b + "' > provider\n" + r'''
headless_wait_ready; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        self.assertFalse((self.state / 'quota-until').exists())

    def test_unchanged_bound_quota_marker_remains_and_no_request_runs(self):
        out = self.shell("CODEXC_HEADLESS_CMD=fake-dsh-worker\n" +
            "printf 'v2 %s dsh %s\\n' \"$(( $(date +%s) + 600 ))\" '" + self.a + "' > .codingkeeper/quota-until\n" + r'''
sleep() { cp .codingkeeper/status.json waiting.json; touch .codingkeeper/loop.halt; }
headless_wait_ready; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=1')
        self.assertTrue((self.state / 'quota-until').exists())
        self.assertIn('waiting_quota', (self.world / 'waiting.json').read_text())

    def test_invalid_new_config_never_clears_bound_quota(self):
        out = self.shell("CODEXC_HEADLESS_CMD=fake-dsh-worker\n" +
            "printf 'v2 %s dsh %s\\n' \"$(( $(date +%s) + 600 ))\" '" + self.a + "' > .codingkeeper/quota-until\n" + r'''
headless_provider_fingerprint() { return 1; }
sleep() { touch .codingkeeper/loop.halt; }
headless_wait_ready; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=1')
        self.assertTrue((self.state / 'quota-until').exists())

    def test_another_tools_quota_marker_is_never_cleared_by_provider_change(self):
        (self.state / 'dsh-session-id').write_text('exact-session\n')
        out = self.shell("CODEXC_HEADLESS_CMD=fake-dsh-worker\n" +
            "printf 'v2 %s zcode %s\\n' \"$(( $(date +%s) + 600 ))\" '" + self.a + "' > .codingkeeper/quota-until\n" +
            "printf '%s' '" + self.b + "' > provider\n" + r'''
sleep() { touch .codingkeeper/loop.halt; }
headless_wait_ready; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=1')
        self.assertTrue((self.state / 'quota-until').exists())

    def test_new_quota_markers_record_only_provider_identity_hash(self):
        out = self.shell("CK_PROVIDER_LAST_TOOL=dsh\nCK_PROVIDER_LAST_FINGERPRINT=" + self.a + r'''
headless_record_quota_until "$(( $(date +%s) + 600 ))"; printf 'rc=%s' "$?"
''')
        self.assertEqual(out, 'rc=0')
        parts = (self.state / 'quota-until').read_text().split()
        self.assertEqual([parts[0], *parts[2:]], ['v2', 'dsh', self.a])

    def test_only_exact_known_wrapper_with_no_shell_overrides_enables_recovery(self):
        wrapper = str(ROOT / 'codexc-dsh-worker')
        for command, expected in ((shlex.quote(wrapper), 'dsh:0'),
                                  ('KEY=stale ' + shlex.quote(wrapper), ':1'),
                                  (shlex.quote(wrapper) + ' --profile old', ':1'),
                                  ('printf fake-dsh-worker', ':1'),
                                  (str(self.world / 'unrelated-dsh-worker'), ':1')):
            with self.subTest(command=command):
                out = self.shell('CODEXC_HEADLESS_CMD=' + shlex.quote(command) +
                    '\nvalue="$(headless_provider_tool)"; rc=$?; printf "%s:%s" "$value" "$rc"\n',
                    adapter_stubs=False)
                self.assertEqual(out, expected)

    def test_real_dsh_adapter_reloads_credentials_and_keeps_exact_session(self):
        self.dsh_adapter_case(False)

    def test_real_dsh_adapter_honors_global_selection_patch_on_recovery(self):
        self.dsh_adapter_case(True)

    def dsh_adapter_case(self, global_patch):
        config = self.home / '.dsh'
        config.mkdir()
        settings = config / 'settings.yaml'
        llm = {'providers': {
            'p': {'baseURL': 'https://old.invalid', 'apiKeyEnv': 'FIXTURE_KEY', 'models': [{'id': 'm'}]},
            'other': {'baseURL': 'https://unused.invalid', 'models': [{'id': 'other'}]}}}
        if global_patch:
            (config / 'cordis.patch.yml').write_text(json.dumps([
                {'id':'agent-default-model', 'config':{'provider':'p', 'model':'m'}},
                {'id':'credentials', 'disabled':False}]))
        else:
            llm['defaultModel'] = 'p/m'
        settings.write_text(json.dumps({'llm-pi-ai':llm}))
        (config / '.credentials.yaml').write_text(json.dumps({'refs': {'FIXTURE_KEY': 'fixture-old'}}))
        (self.state / 'dsh-session-id').write_text('exact-session\n')
        binary = self.world / 'fake-dsh'
        binary.write_text('#!/usr/bin/env python3\n' + r'''
import json, os, sys
from pathlib import Path
root=Path.cwd(); cfg=Path.home()/'.dsh'
args=sys.argv[1:]; sid=args[args.index('--session-id')+1]
with (root/'cli-calls').open('a') as f: f.write(sid+' '+os.environ.get('FIXTURE_KEY','missing')+'\n')
sys.stdin.read()
print(json.dumps({'type':'session','sessionId':sid,'cwd':str(root)}), flush=True)
if os.environ.get('FIXTURE_KEY') == 'fixture-old':
    (cfg/'.credentials.yaml').write_text(json.dumps({'refs':{'FIXTURE_KEY':'fixture-new'}}))
    print(json.dumps({'type':'error','message':'quota exhausted'}), flush=True)
    sys.exit(1)
print(json.dumps({'type':'final','text':'TASK_RESULT: DONE'}))
print(json.dumps({'type':'status','phase':'turn_end','reason':{'kind':'completed'}}))
''')
        binary.chmod(0o755)
        self.env.update(DSH_BIN=str(binary), FIXTURE_KEY='inherited-stale')
        out = self.shell('CODEXC_HEADLESS_CMD=' + shlex.quote(str(ROOT / 'codexc-dsh-worker')) +
                         '\nheadless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n', adapter_stubs=False)
        self.assertEqual(out, 'rc=0')
        self.assertEqual((self.world / 'cli-calls').read_text().splitlines(),
                         ['exact-session fixture-old', 'exact-session fixture-new'])
        self.assertEqual((self.state / 'dsh-session-id').read_text(), 'exact-session\n')

    def zcode_case(self, before_start=False, recovery=True, healthy=False):
        config = self.home / '.zcode/v2'
        config.mkdir(parents=True)
        settings = config / 'provider_config.json'
        settings.write_text(json.dumps({'config': {'providerOrder': ['p', 'q'],
            'defaultModelSelection': {'providerId': 'p', 'modelId': 'm'}, 'providerConfigRules': {
            'providerRules': [{'providerId': 'p', 'config': {'api': {'baseUrl': 'https://old.invalid'},
                'access': {'apiKey': 'fixture-old'}, 'modelOrder': ['m']}},
                {'providerId': 'q', 'config': {'api': {'baseUrl': 'https://new.invalid'},
                'access': {'apiKey': 'fixture-new'}, 'modelOrder': ['m2']}}]}}}))
        sid = 'sess_exact-session'
        (self.state / 'zcode-session-id').write_text(sid + '\n')
        db = self.world / 'session.sqlite'
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE session(id text, directory text, path text)')
            conn.execute('INSERT INTO session VALUES(?,?,NULL)', (sid, str(self.world)))
            conn.execute('CREATE TABLE session_entry(id text, session_id text, type text, time_updated integer, data text)')
            conn.execute('INSERT INTO session_entry VALUES(?,?,?,0,?)',
                         ('selection', sid, 'runtime/model_selection',
                          json.dumps({'modelSelection': {'providerId': 'p', 'modelId': 'm'}})))
        cjs = self.world / 'fake.cjs'
        cjs.touch()
        binary = self.world / 'bin'
        binary.mkdir()
        node = binary / 'node'
        node.write_text('#!/usr/bin/env python3\n' + r'''
import json, os, sqlite3, sys
from pathlib import Path
root=Path.cwd(); cfg=Path.home()/'.zcode/v2/provider_config.json'
data=json.loads(cfg.read_text())
args=sys.argv[1:]; sid=args[args.index('--resume')+1]
prompt=args[args.index('--prompt')+1]
if prompt.startswith('/model '):
    name,model=prompt.removeprefix('/model ').split('/',1)
    with sqlite3.connect(os.environ['ZCODE_SESSION_DB']) as conn:
        conn.execute('UPDATE session_entry SET data=? WHERE session_id=?',
                     (json.dumps({'modelSelection':{'providerId':name,'modelId':model}}),sid))
    with (root/'cli-model-switches').open('a') as f: f.write(sid+' '+name+'/'+model+'\n')
    print(json.dumps({'type':'result','sessionId':sid,'response':'Model switched to '+name+'/'+model+' (high).'}))
    sys.exit(0)
with sqlite3.connect(os.environ['ZCODE_SESSION_DB']) as conn:
    selected=json.loads(conn.execute('SELECT data FROM session_entry WHERE session_id=?',(sid,)).fetchone()[0])['modelSelection']
entry=next(rule['config'] for rule in data['config']['providerConfigRules']['providerRules']
           if rule['providerId']==selected['providerId'])
with (root/'cli-calls').open('a') as f: f.write(sid+' '+entry['api']['baseUrl']+'\n')
print(json.dumps({'type':'turn.started','sessionId':sid}), flush=True)
if os.environ.get('FIXTURE_HEALTHY') == '1':
    print(json.dumps({'type':'result','sessionId':sid,'response':'TASK_RESULT: DONE'})); sys.exit(0)
if entry['api']['baseUrl'] == 'https://old.invalid':
    data['config']['defaultModelSelection']={'providerId':'q','modelId':'m2'}
    cfg.write_text(json.dumps(data)); print('network unavailable',file=sys.stderr); sys.exit(1)
print(json.dumps({'type':'result','sessionId':sid,'response':'TASK_RESULT: DONE'}))
''')
        node.chmod(0o755)
        self.env.update(PATH=str(binary) + os.pathsep + self.env['PATH'],
                        ZCODE_CJS=str(cjs), ZCODE_SESSION_DB=str(db),
                        CODEXC_PROVIDER_RECOVERY='1' if recovery else '0',
                        FIXTURE_HEALTHY='1' if healthy else '0')
        if before_start:
            data = json.loads(settings.read_text())
            data['config']['defaultModelSelection'] = {'providerId': 'q', 'modelId': 'm2'}
            settings.write_text(json.dumps(data))
        out = self.shell('CODEXC_HEADLESS_CMD=' + shlex.quote(str(ROOT / 'codexc-zcode-worker')) +
                         '\nheadless_turn task .codingkeeper/out; printf "rc=%s" "$?"\n', adapter_stubs=False)
        if healthy or not recovery:
            self.assertEqual(out, 'rc=0' if healthy else 'rc=1')
            self.assertEqual((self.world / 'cli-calls').read_text().splitlines(), [sid + ' https://old.invalid'])
            self.assertFalse((self.world / 'cli-model-switches').exists())
            return
        self.assertEqual(out, 'rc=0')
        self.assertEqual((self.world / 'cli-calls').read_text().splitlines(),
                         [sid + ' https://old.invalid', sid + ' https://new.invalid'])
        self.assertEqual((self.world / 'cli-model-switches').read_text().splitlines(), [sid + ' q/m2'])
        self.assertEqual((self.state / 'zcode-session-id').read_text(), sid + '\n')

    def test_real_zcode_adapter_reloads_provider_and_keeps_exact_session(self):
        self.zcode_case()

    def test_zcode_default_changed_before_turn_still_recovers_pinned_failed_session(self):
        self.zcode_case(before_start=True)

    def test_healthy_zcode_session_keeps_explicit_provider_when_default_changes(self):
        self.zcode_case(before_start=True, healthy=True)

    def test_disabling_recovery_never_switches_zcode_saved_provider(self):
        self.zcode_case(before_start=True, recovery=False)

    def test_gate_and_review_repairs_keep_their_phase_and_accept_once_after_recovery(self):
        (self.state / 'queue.md').write_text('## ready\n- [ ] original queued task\n')
        (self.state / 'dsh-session-id').write_text('exact-session\n')
        (self.world / '.gitignore').write_text('.codingkeeper/\nhome/\nprovider\n')
        worker = self.world / 'fake-dsh-worker'
        worker.write_text('#!/bin/bash\n' + r'''
n=$(cat .codingkeeper/calls 2>/dev/null || echo 0); n=$((n+1))
echo "$n" > .codingkeeper/calls
cat > ".codingkeeper/prompt-$n"
cat .codingkeeper/dsh-session-id >> .codingkeeper/sessions
if [ "$n" = 2 ]; then
    printf '%s' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > provider
    printf 'CK_ERROR_CLASS: quota\n'; exit 1
fi
if [ "$n" = 4 ]; then
    printf '%s' 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc' > provider
    printf 'CK_ERROR_CLASS: auth\n'; exit 1
fi
printf 'TASK_RESULT: DONE\n'
''')
        worker.chmod(0o755)
        for command in (['git', 'init', '-q'], ['git', 'add', '.'],
                        ['git', '-c', 'user.name=Audit', '-c', 'user.email=a@example.invalid',
                         'commit', '-qm', 'fixture']):
            subprocess.run(command, cwd=self.world, env=self.env, check=True, capture_output=True)
        out = self.shell('CODEXC_HEADLESS_CMD=' + shlex.quote(str(worker)) + r'''
CODEXC_REVIEW_PARALLEL=0
register_project() { :; }
notify() { :; }
gate_run() {
    local n
    n=$(cat .codingkeeper/gates 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > .codingkeeper/gates
    : > "$1"
    [ "$n" -gt 1 ]
}
review_run() {
    local n
    n=$(cat .codingkeeper/reviews 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > .codingkeeper/reviews
    : > "$2"
    if [ "$n" = 1 ]; then printf 1; else printf 0; fi
}
sleep() {
    if [ -f .codingkeeper/journal ]; then touch .codingkeeper/loop.halt; fi
    command sleep .03
}
run_runner
printf finished
''', timeout=40)
        self.assertEqual(out, 'finished')
        self.assertEqual((self.state / 'calls').read_text().strip(), '5')
        self.assertEqual((self.state / 'prompt-2').read_text(), (self.state / 'prompt-3').read_text())
        self.assertEqual((self.state / 'prompt-4').read_text(), (self.state / 'prompt-5').read_text())
        self.assertIn('gate 未通过', (self.state / 'prompt-2').read_text())
        self.assertIn('独立审查发现问题', (self.state / 'prompt-4').read_text())
        self.assertEqual((self.state / 'sessions').read_text().splitlines(), ['exact-session'] * 5)
        self.assertEqual(len(list((self.state / 'evidence').glob('*/accepted.json'))), 1)
        self.assertEqual((self.state / 'journal').read_text().count('accepted after'), 1)
        self.assertIn('- [x] original queued task', (self.state / 'queue.md').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
