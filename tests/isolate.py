#!/usr/bin/env python3
"""Run the harness with a private home and tmux socket, never the user's server."""
import os
import json
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
base = Path(tempfile.mkdtemp(prefix='ck-tests-', dir='/private/tmp'))
print(f'Test artifacts: {base}', flush=True)
env = {k:v for k,v in os.environ.items() if not k.startswith(('CODEXC_', 'CODEX_', 'TMUX', 'CK_TEST_'))}
# Only the validated planner's controls cross the environment reset.
for name in ('CK_TEST_PLAN', 'CK_TEST_SUITES', 'CK_TEST_KEEP_ARTIFACTS',
             'CK_TEST_STRICT_SKIPS', 'CK_TEST_REPORT'):
    if name in os.environ:
        env[name] = os.environ[name]
# Historical fake worlds are non-Git and use the single standing prompt.
# Strict entry/default and rotation tests explicitly select production behavior.
env.update(CK_TEST_ISOLATED='1', CK_TEST_ARTIFACTS=str(base), HOME=str(base/'home'), TMPDIR=str(base/'tmp')+'/',
           CODEX_HOME=str(base/'home/.codex'), CLAUDE_CONFIG_DIR=str(base/'home/.claude'),
           PI_DIR=str(base/'home/.pi'), OPENCODE_DATA_DIR=str(base/'home/.opencode'),
           CODEXC_ACTIVE_WINDOW='', CODEXC_LOOP_NOTIFY='0', CODEXC_NOTIFY='0', CODEXC_AUTO_RESUME='0', CODEXC_REVIEW_PARALLEL='0', CODEXC_PROMPT_ROTATION='0', CODEXC_REQUIRE_GATE='0',
           GIT_AUTHOR_NAME='Codexc Test', GIT_AUTHOR_EMAIL='codexc-test@example.invalid',
           GIT_COMMITTER_NAME='Codexc Test', GIT_COMMITTER_EMAIL='codexc-test@example.invalid',
           SWIFT_MODULECACHE_PATH=os.environ.get('CK_SWIFT_TEST_CACHE', str(base/'swift-cache')), CLANG_MODULE_CACHE_PATH=os.environ.get('CK_CLANG_TEST_CACHE', str(base/'clang-cache')))
for name in ['home/.codex/bin', 'tmp', 'bin']:
    (base/name).mkdir(parents=True, exist_ok=True)
shutil.copy2(root/'tmux.conf',base/'home/.tmux.conf')
(base/'home/.codex/bin/sync-prefix2.sh').symlink_to(root/'sync-prefix2.sh')
real_tmux = shutil.which('tmux')
if not real_tmux:
    sys.exit('tmux is required for the full harness')
wrapper = base/'bin/tmux'
wrapper.write_text('#!/bin/bash\nexec '+shlex.quote(real_tmux)+' -S '+shlex.quote(str(base/'tmux.sock'))+' "$@"\n')
wrapper.chmod(0o755)
# Tests publish status but must never display desktop notifications.
notify=base/'bin/osascript'; notify.write_text('#!/bin/bash\nexit 0\n'); notify.chmod(0o755)
env['PATH'] = str(base/'bin')+':'+str(root)+':'+env['PATH']
code=1
child=None
def interrupted(_signum, _frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, interrupted)
try:
    child=subprocess.Popen([str(root/'tests/run-all'),*sys.argv[1:]],env=env,start_new_session=True)
    code=child.wait()
except KeyboardInterrupt:
    code=130
finally:
    if child:
        # Each run owns this process group, including any orphaned fake workers.
        try: os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            child.poll()  # Reap the group leader before Darwin probes a zombie-only group.
            try: os.killpg(child.pid,0)
            except (ProcessLookupError, PermissionError): break
            time.sleep(.05)
        try: os.killpg(child.pid,signal.SIGKILL)
        except (ProcessLookupError, PermissionError): pass
        child.wait(timeout=3)
    cleanup_errors = []
    try:
        subprocess.run([str(wrapper),'kill-server'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL, timeout=5)
    except subprocess.TimeoutExpired:
        cleanup_errors.append('private tmux cleanup timed out after 5 seconds')
        if code == 0: code = 1
    except OSError as error:
        cleanup_errors.append('private tmux cleanup failed: ' + str(error))
        if code == 0: code = 1
    for error in cleanup_errors:
        print(error, file=sys.stderr)
    # The runner report is provisional until process/socket cleanup completes.
    report = Path(env.get('CK_TEST_REPORT') or str(base/'report.json'))
    if report.exists():
        try:
            data = json.loads(report.read_text())
            if data.get('status') == 'running' and code == 0:
                code = 1
            data.update(exit_code=code, cleanup_errors=cleanup_errors,
                        cleanup_complete=not cleanup_errors)
            if code:
                data['status'] = 'cancelled' if code == 130 else 'failed'
            fd, scratch = tempfile.mkstemp(prefix='.report-', dir=report.parent)
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump(data, output, indent=2, ensure_ascii=False)
                    output.write('\n')
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(scratch, report)
            finally:
                if os.path.exists(scratch): os.unlink(scratch)
        except (OSError, ValueError) as error:
            print('cannot finalize harness report: ' + str(error), file=sys.stderr)
            if code == 0: code = 1
    # Green runs remove their scratch world; failed runs keep stage logs on
    # disk because run-all's failure report points at "full log:" paths inside.
    if code == 0 and env.get('CK_TEST_KEEP_ARTIFACTS') != '1':
        shutil.rmtree(base, ignore_errors=True)
    else:
        label = 'test artifacts kept' if code == 0 else 'test artifacts kept for triage'
        print(f'{label}: {base}', file=sys.stderr)
sys.exit(code)
