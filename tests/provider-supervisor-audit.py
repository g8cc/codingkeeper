#!/usr/bin/env python3
"""Provider handoff through private fake CLIs and tmux; never calls a model."""
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fixture_processes import live_processes, wait_watchers_exited

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / 'ck-tool-supervisor.py'
SESSION = '21a1e211-6de4-7b12-a07f-217fd0c2cef4'
SECRET = 'PROVIDER_TEST_SECRET_DO_NOT_LOG'
ORIGINAL_PROMPT = 'original task must not be replayed'


class ProviderSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SUPERVISOR.is_file(), 'provider supervisor is missing')
        self.temporary = tempfile.TemporaryDirectory(prefix='ck-provider-supervisor-')
        self.addCleanup(self.temporary.cleanup)
        self.world = Path(self.temporary.name).resolve()
        self.project = self.world / 'project'
        self.home = self.world / 'home'
        self.bin = self.world / 'bin'
        for directory in (self.project, self.home, self.bin, self.project / '.codingkeeper'):
            directory.mkdir(parents=True, exist_ok=True)
        self.owner = str(os.getpid())
        self.generation = 'a' * 32
        self.environment = {k: v for k, v in os.environ.items()
                            if not k.startswith(('CODEX', 'CODEXC', 'CK_PROVIDER', 'TMUX',
                                                 'ANTHROPIC', 'OPENAI', 'OPENCODE', 'PI_',
                                                 'CLAUDE', 'DSH', 'ZCODE', 'XDG_'))}
        self.environment.update(HOME=str(self.home), CODEX_HOME=str(self.home / '.codex'),
                                CLAUDE_CONFIG_DIR=str(self.home / '.claude'),
                                PI_DIR=str(self.home / '.pi/agent'),
                                PI_CODING_AGENT_DIR=str(self.home / '.pi/agent'),
                                OPENCODE_DATA_DIR=str(self.home / '.opencode'),
                                XDG_CONFIG_HOME=str(self.home / '.config'),
                                PATH=str(self.bin) + ':' + os.environ['PATH'],
                                CK_PROVIDER_GENERATION=self.generation,
                                CODEXC_PROVIDER_POLL='0.05', CODEXC_PROVIDER_MAX_RESTARTS='2',
                                CODEXC_PROVIDER_RECOVERY='1',
                                CODEXC_NOTIFY='0', CODEXC_LOG_DIR=str(self.world / 'logs'),
                                AUDIT_WORLD=str(self.world), AUDIT_PROJECT=str(self.project),
                                AUDIT_OWNER=self.owner, AUDIT_TOOL='codex')
        self.process = None
        self.output = None
        self.mock_tmux()
        self.mock_cli()

    def tearDown(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            # Only PIDs published by our own fake CLI can be cleaned up here.
            for row in self.records():
                if row.get('kind') == 'start':
                    for key in ('pid', 'child'):
                        try:
                            os.kill(row[key], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            if self.output is not None:
                self.output.close()
            if self.process.stdin is not None:
                self.process.stdin.close()

    def mock_tmux(self):
        path = self.bin / 'tmux'
        path.write_text(r'''#!/usr/bin/env python3
import os,sys
from pathlib import Path
a=sys.argv[1:]; w=Path(os.environ['AUDIT_WORLD'])
if a[0] in ('show-option','show-options'):
 key=a[-1]
 values={'@codexc_owner':os.environ['AUDIT_OWNER'],'@codexc_tool':os.environ['AUDIT_TOOL'],
         '@codexc_project':os.environ['AUDIT_PROJECT']}
 if (w/'wrong-owner').exists(): values['@codexc_owner']='999999999'
 print(values.get(key,''))
elif a[0]=='display-message':
 print(os.environ['AUDIT_PROJECT'] if 'pane_current_path' in a[-1] else '%17')
elif a[0]=='capture-pane':
 print('esc to interrupt' if (w/'busy').exists() else 'Ask Codex to do anything\nctrl+p commands')
elif a[0]=='send-keys':
 with (w/'keys').open('a') as f: f.write(repr(a)+'\n')
''')
        path.chmod(0o755)

    def mock_cli(self):
        (self.world / 'child.py').write_text(r'''import os,signal,time
from pathlib import Path
p=Path(os.environ['AUDIT_WORLD'])/'child-stopped'
def stop(s,f):
 with p.open('a') as o:o.write(str(os.getpid())+'\n')
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
signal.signal(signal.SIGHUP,stop)
(p.parent/('child-ready-'+str(os.getpid()))).touch()
while True:time.sleep(.05)
''')
        code = r'''#!PYTHON
import json,os,signal,sqlite3,subprocess,sys,time
from pathlib import Path
w=Path(os.environ['AUDIT_WORLD'])
def record(row):
 with (w/'processes.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
if '--help' in sys.argv:
 record({'kind':'probe','argv':sys.argv[1:]})
 print('--no-daemon --standalone --resume --session --session-id --continue --param --data');sys.exit(0)
if len(sys.argv)>1 and sys.argv[1]=='api':
 if '/openapi.json' in sys.argv:
  print(json.dumps({'paths':{'/api/session/{sessionID}/model':{'post':{'operationId':'session.switchModel'}}}}))
  sys.exit(0)
 if 'session.switchModel' in sys.argv:
  sid=sys.argv[sys.argv.index('--param')+1].split('=',1)[1]
  model=json.loads(sys.argv[sys.argv.index('--data')+1])['model']
  directory=Path(os.environ.get('OPENCODE_DATA_DIR') or str(Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'opencode'))
  if not os.environ.get('AUDIT_API_NO_WRITE'):
   with sqlite3.connect(directory/'opencode.db') as db:
    db.execute('UPDATE session_v2 SET model=? WHERE id=?',(json.dumps(model),sid))
  record({'kind':'model-switch','session':sid,'model':model})
  sys.exit(0)
 sys.exit(2)
child=subprocess.Popen([sys.executable,str(w/'child.py')])
def stop(signum,frame):
 record({'kind':'stop','pid':os.getpid(),'signal':signum})
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
record({'kind':'start','pid':os.getpid(),'child':child.pid,'argv':sys.argv[1:]})
print('Ask Codex to do anything\nctrl+p commands',flush=True)
while True:
 if (w/'exit-cli').exists():
  child.terminate();child.wait(timeout=2);sys.exit(23)
 time.sleep(.025)
'''.replace('PYTHON', sys.executable)
        for tool in ('codex', 'claude', 'pi', 'opencode'):
            path = self.bin / tool
            path.write_text(code)
            path.chmod(0o755)

    def records(self):
        path = self.world / 'processes.jsonl'
        if not path.exists():
            return []
        rows = []
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass  # the fake process may still be appending its last line
        return rows

    def starts(self):
        return [row for row in self.records() if row.get('kind') == 'start']

    def wait_for(self, condition, explanation, timeout=7):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if condition():
                return
            if self.process is not None and self.process.poll() is not None:
                break
            time.sleep(.025)
        log = self.world / 'supervisor.log'
        self.fail(explanation + '\n' + (log.read_text() if log.exists() else '') +
                  '\nprocesses=' + repr(self.records()))

    def configure(self, tool='codex', endpoint='old'):
        self.tool = tool
        self.environment['AUDIT_TOOL'] = tool
        if tool == 'codex':
            path = self.home / '.codex/config.toml'
            text = ('model_provider="custom"\nmodel="test-model"\n'
                    '[model_providers.custom]\nname="custom"\nwire_api="responses"\n'
                    f'base_url="https://{endpoint}.invalid/v1"\nexperimental_bearer_token="{SECRET}"\n'
                    '[model_providers.pinned]\nname="pinned"\nwire_api="responses"\n'
                    'base_url="https://pinned.invalid/v1"\n')
        elif tool == 'claude':
            path = self.home / '.claude/settings.json'
            text = json.dumps({'model': 'test-model', 'env': {
                'ANTHROPIC_BASE_URL': f'https://{endpoint}.invalid', 'ANTHROPIC_AUTH_TOKEN': SECRET}})
        elif tool == 'pi':
            path = self.home / '.pi/agent/models.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.parent / 'settings.json').write_text(json.dumps({'defaultProvider': 'custom', 'defaultModel': 'test-model'}))
            text = json.dumps({'providers': {'custom': {'baseUrl': f'https://{endpoint}.invalid',
                               'apiKey': SECRET, 'models': [{'id': 'test-model'}]}}})
        else:
            path = self.home / '.config/opencode/opencode.json'
            text = json.dumps({'model': 'custom/test-model', 'provider': {'custom': {
                'options': {'baseURL': f'https://{endpoint}.invalid', 'apiKey': SECRET}}}})
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.new')
        temporary.write_text(text)
        temporary.replace(path)
        self.config = path
        return path

    def opencode_directory(self):
        return Path(self.environment.get('OPENCODE_DATA_DIR') or
                    str(Path(self.environment.get('XDG_DATA_HOME') or self.home / '.local/share') / 'opencode'))

    def source(self, tool='codex', project=None, child=False):
        project = project or self.project
        if tool == 'codex':
            path = self.home / '.codex/sessions/2026/11/16/rollout-main.jsonl'
            row = {'type': 'session_meta', 'payload': {'id': SESSION, 'cwd': str(project),
                   'source': {'subagent': {}} if child else 'cli'}}
        elif tool == 'claude':
            munged = str(project).replace('/', '-').replace('.', '-')
            path = self.home / '.claude/projects' / munged / 'session.jsonl'
            row = {'type': 'user', 'cwd': str(project), 'sessionId': SESSION,
                   'isSidechain': child, 'message': {'role': 'user', 'content': 'task'}}
        elif tool == 'pi':
            munged = '-' + str(project).replace('/', '-') + '-'
            path = self.home / '.pi/agent/sessions' / munged / 'session.jsonl'
            row = {'type': 'session', 'id': SESSION, 'cwd': str(project)}
        else:
            path = self.opencode_directory() / 'opencode.db'
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE IF NOT EXISTS session_v2 (id TEXT,directory TEXT,time_updated INTEGER,model TEXT)')
                conn.execute('CREATE TABLE IF NOT EXISTS session_message (session_id TEXT,type TEXT,seq INTEGER,data TEXT)')
                conn.execute('INSERT INTO session_v2 VALUES (?,?,?,?)',
                             (SESSION, str(project), 1, json.dumps({'providerID': 'persisted-old', 'id': 'old-model'})))
            self.session_source = SESSION
            return SESSION
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + '\n')
        self.session_source = str(path)
        return str(path)

    def start(self, tool='codex', args=()):
        self.configure(tool)
        self.source(tool)
        self.output = (self.world / 'supervisor.log').open('w')
        self.process = subprocess.Popen([sys.executable, str(SUPERVISOR), tool, '%17', self.owner,
                                         '--', str(self.bin / tool), *args, ORIGINAL_PROMPT],
                                        cwd=self.project, env=self.environment, stdout=self.output,
                                        stderr=subprocess.STDOUT, stdin=subprocess.PIPE, start_new_session=True)
        self.wait_for(lambda: len(self.starts()) == 1, 'initial CLI did not start')
        child_ready = self.world / ('child-ready-' + str(self.starts()[0]['child']))
        self.wait_for(child_ready.exists, 'CLI descendant did not install its signal handlers')

    def event(self, text='usage limit exhausted', source=None, token='event-1', state='error', **env):
        args = [sys.executable, str(SUPERVISOR), 'record', self.tool, '%17', self.owner,
                str(source or self.session_source), token, state]
        result = subprocess.run(args, cwd=self.project, env=dict(self.environment, **env), input=text,
                                text=True, capture_output=True, timeout=5)
        self.assertIn(result.returncode, (0, 75), result.stdout + result.stderr)
        return result

    def unchanged(self, count=1):
        time.sleep(.4)
        self.assertEqual(len(self.starts()), count, self.records())
        self.assertIsNone(self.process.poll(), (self.world / 'supervisor.log').read_text())

    def exercise_recovery(self, tool):
        self.start(tool)
        previous = self.starts()[0]
        self.event()
        self.unchanged()
        self.configure(tool, 'new')
        self.wait_for(lambda: len(self.starts()) == 2, tool + ' was not resumed on the new provider')
        args = self.starts()[1]['argv']
        self.assertIn(SESSION if tool != 'pi' else self.session_source, args)
        self.assertNotIn('--last', args)
        self.assertNotIn(ORIGINAL_PROMPT, args)
        self.assertIn('continue', args)
        if tool == 'codex':
            self.assertIn('--no-daemon', args)
        if tool == 'opencode':
            self.assertIn('--standalone', args)
            switched = [row for row in self.records() if row.get('kind') == 'model-switch']
            self.assertEqual(len(switched), 1)
            self.assertEqual(switched[0]['session'], SESSION)
            self.assertEqual(switched[0]['model'], {'providerID': 'custom', 'id': 'test-model'})
        self.wait_for(lambda: any(row.get('kind') == 'stop' and row['pid'] == previous['pid']
                                 for row in self.records()), 'old owned CLI was not stopped')
        stopped = self.world / 'child-stopped'
        self.wait_for(lambda: stopped.exists() and str(previous['child']) in stopped.read_text().splitlines(),
                      'old CLI descendant survived the provider handoff')
        self.unchanged(2)
        state = self.project / '.codingkeeper/provider-17.json'
        evidence = (self.world / 'supervisor.log').read_text() + (state.read_text() if state.exists() else '')
        self.assertNotIn(SECRET, evidence)

    def test_codex_exact_resume_and_owned_tree_replacement(self):
        self.exercise_recovery('codex')

    def test_claude_exact_resume_and_owned_tree_replacement(self):
        self.exercise_recovery('claude')

    def test_pi_exact_resume_and_owned_tree_replacement(self):
        self.exercise_recovery('pi')

    def test_opencode_exact_resume_and_owned_tree_replacement(self):
        self.exercise_recovery('opencode')

    def test_unchanged_quota_and_unrelated_failure_never_restart(self):
        self.start()
        self.event()
        self.unchanged()
        self.event('compiler error in application source', token='event-2')
        self.configure(endpoint='new')
        self.unchanged()

    def test_invalid_config_preserves_live_cli_until_fixed(self):
        self.start()
        self.event()
        self.config.write_text('model_provider = [ invalid')
        self.unchanged()
        self.configure(endpoint='fixed')
        self.wait_for(lambda: len(self.starts()) == 2, 'valid new provider was not retried after a partial write')

    def test_explicit_provider_override_neither_restarts_nor_suppresses_continue(self):
        self.start(args=('-c', 'model_provider="pinned"'))
        self.configure(endpoint='new')
        result = self.event()
        self.assertEqual(result.returncode, 0, 'pinned provider incorrectly suppressed the existing watcher')
        self.unchanged()

    def test_explicit_model_still_allows_endpoint_recovery(self):
        self.start(args=('-m', 'chosen-model'))
        self.event()
        self.configure(endpoint='new')
        self.wait_for(lambda: len(self.starts()) == 2, 'a fixed model incorrectly pinned the old endpoint')
        args = self.starts()[1]['argv']
        self.assertIn('chosen-model', args)
        self.assertIn(SESSION, args)

    def test_malformed_session_header_keeps_original_cli_alive(self):
        self.start()
        Path(self.session_source).write_text(json.dumps({'type': 'session_meta', 'payload': []}) + '\n')
        self.event()
        self.configure(endpoint='new')
        self.unchanged()

    def test_corrupt_opencode_session_database_keeps_original_cli_alive(self):
        self.start('opencode')
        (self.opencode_directory() / 'opencode.db').write_text('not a sqlite database')
        self.event()
        self.configure('opencode', 'new')
        self.unchanged()

    def test_codex_subagent_cannot_replace_original_conversation(self):
        self.start()
        self.source(child=True)
        self.event()
        self.configure(endpoint='new')
        self.unchanged()

    def test_busy_pane_and_manual_halt_defer_handoff(self):
        self.start()
        (self.world / 'busy').touch()
        self.event()
        self.configure(endpoint='new')
        self.unchanged()
        halt = self.project / '.codingkeeper/loop.halt'
        halt.write_text('manual stop')
        (self.world / 'busy').unlink()
        self.unchanged()
        halt.unlink()
        self.wait_for(lambda: len(self.starts()) == 2, 'idle authorized pane did not resume after manual hold cleared')

    def test_wrong_owner_generation_and_cross_project_are_rejected(self):
        self.start()
        self.configure(endpoint='new')
        self.event(CK_PROVIDER_GENERATION='b' * 32)
        self.unchanged()
        other = self.world / 'other-project'
        other.mkdir()
        self.event(source=self.source(project=other), token='event-2')
        self.unchanged()
        self.source()
        (self.world / 'wrong-owner').touch()
        self.event(token='event-3')
        self.unchanged()
        (self.world / 'wrong-owner').unlink()
        self.event(token='event-4')
        self.wait_for(lambda: len(self.starts()) == 2, 'valid owner/session handoff was not accepted')

    def test_restart_budget_and_consumed_event_prevent_ping_pong(self):
        self.environment['CODEXC_PROVIDER_MAX_RESTARTS'] = '1'
        self.start()
        self.event()
        self.configure(endpoint='second')
        self.wait_for(lambda: len(self.starts()) == 2, 'first changed provider was not resumed')
        self.configure(endpoint='third')
        self.unchanged(2)
        self.event('connection refused', token='event-2')
        self.unchanged(2)

    def test_unsent_draft_and_later_input_preserve_user_control(self):
        self.start()
        self.process.stdin.write(b'draft that must survive')
        self.process.stdin.flush()
        time.sleep(.1)
        self.event()
        self.configure(endpoint='new')
        self.unchanged()
        self.process.stdin.write(b'\x15')  # clear the unsent draft in the TUI
        self.process.stdin.flush()
        self.unchanged()  # typing after an error makes that error obsolete
        self.event(token='event-2')
        self.wait_for(lambda: len(self.starts()) == 2, 'a fresh error on an empty composer did not recover')

    def test_duplicate_error_cannot_overwrite_later_submitted_user_input(self):
        self.start()
        self.event()
        path = self.project / '.codingkeeper/provider-17.json'
        observed = json.loads(path.read_text())['observed_at']
        self.process.stdin.write(b'a new user task\r')
        self.process.stdin.flush()
        time.sleep(.1)
        self.configure(endpoint='new')
        self.event()  # the old watcher's cooldown republishes the same event
        self.assertEqual(json.loads(path.read_text())['observed_at'], observed)
        self.unchanged()
        self.event(token='event-2')
        self.wait_for(lambda: len(self.starts()) == 2, 'a new error after user input did not recover')

    def test_opencode_api_success_without_persisted_selection_keeps_original_cli(self):
        self.environment['AUDIT_API_NO_WRITE'] = '1'
        self.start('opencode')
        self.event()
        self.configure('opencode', 'new')
        attempts = lambda: [row for row in self.records() if row.get('kind') == 'model-switch']
        self.wait_for(lambda: len(attempts()) == 1, 'OpenCode did not attempt its native model switch')
        self.unchanged()
        self.assertEqual(len(attempts()), 1, 'failed native preflight repeated without a new event or configuration')
        self.event(token='event-2')
        self.wait_for(lambda: len(attempts()) == 2, 'a new provider error could not retry the local preflight')
        self.unchanged()
        self.assertEqual(len(attempts()), 2, 'fresh event caused unbounded local preflight retries')

    def test_natural_exit_returns_cli_status_without_restart(self):
        self.start()
        (self.world / 'exit-cli').touch()
        self.assertEqual(self.process.wait(timeout=5), 23)
        self.assertEqual(len(self.starts()), 1)

    def test_sigterm_reaps_owned_cli_and_descendant(self):
        self.start()
        first = self.starts()[0]
        self.process.terminate()
        self.process.wait(timeout=5)
        stopped = self.world / 'child-stopped'
        self.assertTrue(stopped.exists(), 'supervisor left its CLI child alive')
        self.assertIn(str(first['child']), stopped.read_text().splitlines())
        self.assert_owned_processes_stopped(first)

    def test_sigint_reaps_owned_cli_and_descendant(self):
        self.start()
        first = self.starts()[0]
        self.process.send_signal(signal.SIGINT)
        self.process.wait(timeout=5)
        stopped = self.world / 'child-stopped'
        self.assertTrue(stopped.exists(), 'interrupted supervisor left its CLI child alive')
        self.assertIn(str(first['child']), stopped.read_text().splitlines())
        self.assert_owned_processes_stopped(first)

    def assert_owned_processes_stopped(self, first):
        self.assertEqual(live_processes({first['pid'], first['child']}), {},
                         'owned CLI or descendant is still running')

    def test_owned_exit_check_rejects_ps_errors(self):
        first = {'pid': os.getpid(), 'child': os.getpid()}
        for returncode, diagnostic in ((2, ''), (1, 'cannot inspect processes'),
                                       (0, 'incomplete process listing'), (-signal.SIGKILL, '')):
            with self.subTest(returncode=returncode, diagnostic=diagnostic):
                result = subprocess.CompletedProcess(['ps'], returncode, 'Z\n', diagnostic)
                with patch('subprocess.run', return_value=result):
                    with self.assertRaises((AssertionError, RuntimeError)):
                        self.assert_owned_processes_stopped(first)

    def test_owned_exit_check_accepts_absence_and_rejects_live_process(self):
        first = {'pid': os.getpid(), 'child': os.getpid()}
        with self.assertRaises(AssertionError):
            self.assert_owned_processes_stopped(first)
        result = subprocess.CompletedProcess(['ps'], 1, '', '')
        with patch('subprocess.run', return_value=result):
            self.assert_owned_processes_stopped(first)

    def test_waiting_requires_current_live_owner_source_and_fresh_heartbeat(self):
        self.start()
        self.event()
        control_path = self.project / '.codingkeeper/provider-supervisor-17.json'
        def query(source=None, **env):
            return subprocess.run([sys.executable, str(SUPERVISOR), 'waiting', self.tool, '%17',
                                   self.owner, source or self.session_source], cwd=self.project,
                                  env=dict(self.environment, **env), text=True,
                                  capture_output=True, timeout=5).returncode
        self.wait_for(lambda: query() == 0, 'live provider wait was not exposed to the delivery loop')
        self.assertEqual(query(source='/other/session.jsonl'), 1)
        self.assertEqual(query(CK_PROVIDER_GENERATION='b' * 32), 1)
        os.kill(self.process.pid, signal.SIGSTOP)
        try:
            original = json.loads(control_path.read_text())
            for changes in ({'heartbeat': time.time() - 60}, {'generation': 'b' * 32},
                            {'pid': 999999999}, {'phase': 'active'}):
                control_path.write_text(json.dumps(dict(original, **changes)))
                self.assertEqual(query(), 1, changes)
            control_path.write_text(json.dumps(original))
            (self.world / 'wrong-owner').touch()
            self.assertEqual(query(), 1)
        finally:
            (self.world / 'wrong-owner').unlink(missing_ok=True)
            os.kill(self.process.pid, signal.SIGCONT)

    def test_sigint_reaps_slow_starting_owned_descendant(self):
        child = self.world / 'child.py'
        child.write_text('import time\ntime.sleep(1)\n' + child.read_text())
        self.test_sigint_reaps_owned_cli_and_descendant()

    def test_sigterm_reaps_slow_starting_owned_descendant(self):
        child = self.world / 'child.py'
        child.write_text('import time\ntime.sleep(1)\n' + child.read_text())
        self.test_sigterm_reaps_owned_cli_and_descendant()

    def append_terminal(self, tool, clean=False):
        if tool == 'codex':
            payload = {'type': 'task_complete'}
            payload.update({'last_agent_message': 'recovered task completed'} if clean else
                           {'error': {'message': 'usage limit exhausted'}})
            row = {'type': 'event_msg', 'payload': payload}
        elif tool == 'claude':
            row = {'type': 'assistant', 'sessionId': SESSION, 'cwd': str(self.project),
                   'message': {'stop_reason': 'end_turn', 'content': [{'type': 'text',
                               'text': 'recovered task completed' if clean else 'usage limit exhausted'}]}}
            if not clean:
                row.update(isApiErrorMessage=True, apiErrorStatus=429)
        elif tool == 'pi':
            row = {'type': 'message', 'message': {'role': 'assistant',
                   'stopReason': 'stop' if clean else 'error',
                   'errorMessage': '' if clean else 'usage limit exhausted',
                   'content': [{'type': 'text', 'text': 'recovered task completed' if clean else ''}]}}
        else:
            row = {'finish': 'stop', 'content': [{'type': 'text', 'text': 'recovered task completed'}]} if clean else {
                'error': {'message': 'usage limit exhausted'}}
            with sqlite3.connect(self.opencode_directory() / 'opencode.db') as conn:
                conn.execute('INSERT INTO session_message VALUES (?,?,?,?)',
                             (SESSION, 'assistant', 2 if clean else 1, json.dumps(row)))
            return
        with Path(self.session_source).open('a') as output:
            output.write(json.dumps(row) + '\n')

    def exercise_private_tmux(self, tool, alternate_home=False, loop_wait=False):
        real_tmux = shutil.which('tmux')
        if not real_tmux:
            self.skipTest('tmux unavailable')
        if alternate_home and tool == 'pi':
            self.environment.pop('PI_DIR', None)
        if alternate_home and tool == 'opencode':
            self.environment.pop('OPENCODE_DATA_DIR', None)
            self.environment['XDG_DATA_HOME'] = str(self.home / '.xdg-data')
        self.configure(tool)
        self.source(tool)
        socket_directory = tempfile.TemporaryDirectory(prefix='ck-provider-tmux-', dir='/private/tmp')
        self.addCleanup(socket_directory.cleanup)
        socket = str(Path(socket_directory.name) / 's')
        # This wrapper can only contact the newly-created private server.
        wrapper = self.bin / 'tmux'
        wrapper.write_text('#!/bin/bash\nexec ' + shlex.quote(real_tmux) + ' -S ' + shlex.quote(socket) + ' "$@"\n')
        wrapper.chmod(0o755)
        self.environment.update(TERM='xterm-256color', CODEXC_AUTO_YES='0', CODEXC_POLL='1',
                                CODEXC_COOLDOWN='0', CODEXC_NIGHT_IDLE='0', CODEXC_ACTIVE_WINDOW='')
        if loop_wait:
            self.environment.update(CODEXC_LOOP_STALL='5', CODEXC_LOOP_POLL='1', CODEXC_LOOP_IDLE='0',
                                    CODEXC_REQUIRE_GATE='0', CODEXC_LOOP_NOTIFY='0', CODEXC_TURN_TIMEOUT='10')
            (self.project / '.gitignore').write_text('.codingkeeper/\n')
            (self.project / 'base.txt').write_text('fixture baseline\n')
            git_env = dict(self.environment, GIT_AUTHOR_NAME='Provider Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                           GIT_COMMITTER_NAME='Provider Test', GIT_COMMITTER_EMAIL='test@example.invalid')
            for args in (('init', '-q'), ('add', '.gitignore', 'base.txt'), ('commit', '-qm', 'fixture baseline')):
                result = subprocess.run(['git', *args], cwd=self.project, env=git_env,
                                        text=True, capture_output=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stderr)
            (self.project / '.codingkeeper/queue.md').write_text('## ready\n- [ ] preserve this queued task\n\n## done\n')
        for name in ('TMUX', 'TMUX_PANE'):
            self.environment.pop(name, None)
        def tmux(*args):
            return subprocess.run([str(wrapper), *args], env=self.environment, text=True,
                                  capture_output=True, timeout=8)
        def wait_watchers():
            self.assertEqual(wait_watchers_exited(self.project), {},
                             'private watcher processes survived tmux shutdown')
        self.addCleanup(wait_watchers)
        self.addCleanup(lambda: tmux('kill-server'))
        bootstrap = tmux('-f', '/dev/null', 'new-session', '-d', '-s', 'anchor', 'sleep 60')
        self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
        master, slave = pty.openpty()
        self.output = (self.world / 'supervisor.log').open('w')
        self.process = subprocess.Popen([str(ROOT / 'codexc'), '-n', 'provider-audit', '-T', tool,
                                         *(['loop'] if loop_wait else ['--no-loop', ORIGINAL_PROMPT])], cwd=self.project,
                                        env=self.environment, stdin=slave, stdout=slave,
                                        stderr=slave, start_new_session=True)
        os.close(slave)
        try:
            self.wait_for(lambda: len(self.starts()) == 1, 'codexc did not start its private fake ' + tool)
            pane = tmux('display-message', '-p', '-t', '=provider-audit:', '#{pane_id}').stdout.strip()
            owner = tmux('show-option', '-p', '-v', '-t', pane, '@codexc_owner').stdout.strip()
            self.assertTrue(pane.startswith('%'), pane)
            watchlog = self.world / 'logs/codexc-watch.log'
            armed = 'main rollout' if tool == 'codex' else 'watcher armed'
            self.wait_for(lambda: watchlog.exists() and armed in watchlog.read_text(),
                          'real watcher did not bind its main ' + tool + ' session')
            if loop_wait:
                self.wait_for(lambda: 'task fed:' in watchlog.read_text(), 'delivery loop did not feed its queued task')
            else:
                self.configure(tool, 'new')
            self.append_terminal(tool)
            if loop_wait:
                state_path = self.project / '.codingkeeper/status.json'
                def waiting_status():
                    try:
                        return json.loads(state_path.read_text()).get('phase') == 'waiting_provider'
                    except (OSError, ValueError):
                        return False
                self.wait_for(waiting_status, 'delivery loop did not enter provider waiting')
                time.sleep(12)
                self.assertFalse((self.project / '.codingkeeper/loop.halt').exists(),
                                 'provider waiting incorrectly exhausted the stall or turn deadline')
                self.configure(tool, 'new')
            self.wait_for(lambda: len(self.starts()) == 2,
                          'watcher did not request automatic ' + tool + ' provider handoff', timeout=12)
            args = self.starts()[1]['argv']
            self.assertIn(SESSION if tool != 'pi' else self.session_source, args)
            self.assertIn('continue', args)
            self.assertNotIn(ORIGINAL_PROMPT, args)
            self.assertEqual(tmux('display-message', '-p', '-t', '=provider-audit:', '#{pane_id}').stdout.strip(), pane)
            self.assertEqual(tmux('show-option', '-p', '-v', '-t', pane, '@codexc_owner').stdout.strip(), owner)
            if tool == 'opencode':
                switched = [row for row in self.records() if row.get('kind') == 'model-switch']
                self.assertEqual(len(switched), 1)
                self.assertEqual(switched[0]['session'], SESSION)
                self.assertEqual(switched[0]['model'], {'providerID': 'custom', 'id': 'test-model'})
            if loop_wait:
                self.assertFalse((self.project / '.codingkeeper/loop.halt').exists())
                self.assertIn('- [ ] preserve this queued task', (self.project / '.codingkeeper/queue.md').read_text())
                return
            self.append_terminal(tool, clean=True)
            self.wait_for(lambda: '新 provider 完成回合' in tmux('capture-pane', '-p', '-t', pane).stdout,
                          'restored ' + tool + ' completion was not confirmed in the same user pane', timeout=10)
        except AssertionError as error:
            screen = tmux('capture-pane', '-p', '-t', '=provider-audit:')
            output = b''
            while select.select([master], [], [], 0)[0]:
                try:
                    part = os.read(master, 65536)
                except OSError:
                    break
                if not part:
                    break
                output += part
            raise AssertionError(str(error) + '\ntmux=' + screen.stdout + screen.stderr +
                                 '\nclient=' + output.decode('utf-8', 'replace')) from error
        finally:
            tmux('kill-server')
            os.close(master)
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            wait_watchers()

    def test_private_codex_watcher_handoff_and_recovery_confirmation(self):
        self.exercise_private_tmux('codex')

    def test_private_claude_watcher_handoff_and_recovery_confirmation(self):
        self.exercise_private_tmux('claude')

    def test_private_pi_watcher_handoff_and_recovery_confirmation(self):
        self.exercise_private_tmux('pi')

    def test_private_opencode_watcher_handoff_and_recovery_confirmation(self):
        self.exercise_private_tmux('opencode')

    def test_private_pi_native_agent_directory_handoff(self):
        self.exercise_private_tmux('pi', alternate_home=True)

    def test_private_opencode_xdg_data_directory_handoff(self):
        self.exercise_private_tmux('opencode', alternate_home=True)

    def test_private_handoff_waits_for_detached_status_writer(self):
        marker = self.world / 'status-writer.pid'
        wrapper = self.bin / 'python3'
        wrapper.write_text('#!' + sys.executable + '\n' + r'''
import os, signal, sys, time
from pathlib import Path
if len(sys.argv) > 3 and sys.argv[1] == '-' and sys.argv[3] == 'recovered task completed':
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (Path(os.environ['AUDIT_WORLD']) / 'status-writer.pid').write_text(str(os.getpid()))
    time.sleep(2)
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
''')
        wrapper.chmod(0o755)
        original_wait = self.wait_for

        def wait_for(condition, explanation, timeout=7):
            original_wait(condition, explanation, timeout)
            if explanation.startswith('restored opencode completion'):
                original_wait(marker.exists, 'delayed status writer did not start')

        self.wait_for = wait_for
        try:
            self.exercise_private_tmux('opencode', alternate_home=True)
            self.assertTrue(marker.exists())
            self.assertEqual(live_processes({int(marker.read_text())}), {},
                             'fixture returned while its detached status writer was still running')
        finally:
            if marker.exists():
                for process_id in live_processes({int(marker.read_text())}):
                    try:
                        os.kill(process_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_private_delivery_loop_waits_past_stall_and_turn_deadline_then_resumes_same_task(self):
        self.exercise_private_tmux('codex', loop_wait=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
