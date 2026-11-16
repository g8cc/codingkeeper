#!/usr/bin/env python3
"""Keep a TUI and its exact session alive across an explicit provider change."""
import argparse
import errno
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty


def provider():
    spec = importlib.util.spec_from_file_location('ck_provider', Path(__file__).with_name('ck-provider.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state_path(pane, control=False):
    if not re.fullmatch(r'%[0-9]+', pane):
        raise ValueError('invalid pane')
    directory = Path.cwd() / '.codingkeeper'
    if directory.is_symlink():
        raise ValueError('state directory cannot be a symlink')
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / (('provider-supervisor-' if control else 'provider-') + pane[1:] + '.json')


def atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.provider-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as source:
            data = json.loads(source.read(65537))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def identity(tool, pane, owner):
    generation = os.environ.get('CK_PROVIDER_GENERATION', '')
    if tool not in ('codex', 'claude', 'pi', 'opencode') or not owner.isdigit() or int(owner) <= 1:
        raise ValueError('invalid provider recovery owner/tool')
    if not re.fullmatch('[a-f0-9]{32}', generation):
        raise ValueError('invalid provider recovery generation')
    return dict(tool=tool, pane=pane, owner=owner, project=os.path.realpath('.'), generation=generation)


def matches(record, expected):
    return all(record.get(k) == v for k, v in expected.items())


def waiting(tool, pane, owner, source):
    expected = identity(tool, pane, owner)
    control = read_state(state_path(pane, True))
    if not matches(control, expected) or control.get('phase') not in ('waiting_provider', 'restarting') or control.get('source') != source:
        return 1
    heartbeat = control.get('heartbeat', 0)
    pid = control.get('pid')
    if not isinstance(heartbeat, (int, float)) or not 0 <= time.time() - heartbeat <= 15 or not isinstance(pid, int) or pid <= 1:
        return 1
    try:
        os.kill(pid, 0)
    except OSError:
        return 1
    return 0 if pane_ready(expected) else 1


def number(name, fallback, lower, upper, integer=False):
    try:
        value = float(os.environ.get(name, str(fallback)))
        if not lower <= value <= upper:
            raise ValueError
        return int(value) if integer else value
    except (ValueError, OverflowError):
        return fallback


def record_event(tool, pane, owner, source, event, state):
    expected = identity(tool, pane, owner)
    control = read_state(state_path(pane, True))
    if not matches(control, expected):
        return 0  # No supervisor: preserve the existing watcher protocol.
    if state not in ('error', 'clear', 'clean'):
        raise ValueError('invalid provider event')
    module = provider()
    if state == 'error' and not module.error_is_provider(sys.stdin.read(32768)):
        state = 'clear'
    if state == 'error' and control.get('handled_source') == source and control.get('handled_event') == event:
        return 75
    data = dict(expected, source=source, event=event, state=state, observed_at=time.time())
    previous = read_state(state_path(pane))
    if matches(previous, expected) and all(previous.get(key) == data[key] for key in ('source', 'event', 'state')):
        data['observed_at'] = previous.get('observed_at', data['observed_at'])
    atomic(state_path(pane), data)
    if state == 'error':
        snapshot = module.snapshot(tool, cwd=expected['project'])
        if control.get('recoverable') and snapshot.get('configured') and snapshot.get('fingerprint') != control.get('disk_fingerprint'):
            # Only the supervisor knows the original CLI's in-memory overrides.
            # Wait for its acknowledgement, never infer eligibility from the
            # default config when the CLI pinned a different provider.
            deadline = time.monotonic() + min(number('CODEXC_PROVIDER_POLL', 2, .05, 60) + .5, 3)
            while time.monotonic() < deadline:
                latest = read_state(state_path(pane, True))
                if not matches(latest, expected):
                    break
                if latest.get('handled_source') == source and latest.get('handled_event') == event:
                    return 75
                time.sleep(.025)
    return 0


def pane_ready(expected):
    try:
        os.kill(int(expected['owner']), 0)
        for option, value in (('@codexc_owner', expected['owner']),
                              ('@codexc_tool', expected['tool']),
                              ('@codexc_project', expected['project'])):
            result = subprocess.run(['tmux', 'show-option', '-p', '-v', '-t', expected['pane'], option],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode or result.stdout.strip() != value:
                return False
        screen = subprocess.run(['tmux', 'capture-pane', '-p', '-t', expected['pane']],
                                capture_output=True, text=True, timeout=2)
        if screen.returncode:
            return False
        text = screen.stdout.lower()
        if expected['tool'] == 'opencode':
            return 'ctrl+p commands' in text
        return 'to interrupt' not in text
    except (OSError, subprocess.SubprocessError):
        return False


def spawn(command, env):
    child, master = pty.fork()
    if child == 0:
        try:
            os.execvpe(command[0], command, env)
        except OSError:
            os.write(2, b'CodingKeeper: cannot start configured tool\n')
            os._exit(127)
    return child, master


def stop(child):
    # pty.fork created this session/group. Never signal a PID from state files.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            # Darwin can reject a final KILL when only zombie members remain.
            groups = subprocess.run(['ps', '-axo', 'pgid=,stat='], capture_output=True,
                                    text=True, timeout=3, check=True)
            if any(len(parts := row.split()) == 2 and parts[0] == str(child) and not parts[1].startswith('Z')
                   for row in groups.stdout.splitlines()):
                raise
            break
        if sig == signal.SIGTERM:
            time.sleep(.15)
            try:
                os.waitpid(child, os.WNOHANG)
            except ChildProcessError:
                pass
    try:
        os.waitpid(child, 0)
    except ChildProcessError:
        pass


def resize(master):
    try:
        size = fcntl.ioctl(0, termios.TIOCGWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)
    except OSError:
        pass


def emit(message):
    os.write(1, ('\r\n[CodingKeeper] ' + message + '\r\n').encode())


def supervise(tool, pane, owner, command):
    expected = identity(tool, pane, owner)
    module = provider()
    baseline = module.snapshot(tool, cwd=expected['project'], argv=command)
    fingerprint = baseline.get('fingerprint', '')
    seen = {fingerprint} if fingerprint else set()
    path, control_path = state_path(pane), state_path(pane, True)
    # Do not persist argv: it may contain an explicit key or inline env config.
    control = dict(expected, fingerprint=fingerprint, recoverable=baseline.get('recoverable', True), pid=os.getpid(),
                   phase='active', heartbeat=time.time(),
                   disk_fingerprint=module.snapshot(tool, cwd=expected['project']).get('fingerprint'))
    atomic(control_path, control)
    started_at = time.time()
    atomic(path, dict(expected, state='clear', event='started', observed_at=started_at))
    launch_command = module.initial_command(tool, command, expected['project'])
    child, master = spawn(launch_command, dict(os.environ, **module.launch_environment(tool, cwd=expected['project'], argv=launch_command)))
    original_command = list(command)
    terminal = termios.tcgetattr(0) if os.isatty(0) else None
    requested_stop = [0]
    def shutdown(signum, _frame):
        requested_stop[0] = signum
    previous = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    previous[signal.SIGWINCH] = signal.signal(signal.SIGWINCH, lambda *_: resize(master))
    try:
        if terminal:
            tty.setraw(0)
        resize(master)
        poll = number('CODEXC_PROVIDER_POLL', 2, .05, 60)
        budget = number('CODEXC_PROVIDER_MAX_RESTARTS', 2, 0, 10, integer=True)
        if os.environ.get('CODEXC_PROVIDER_RECOVERY', '1').lower() in ('0', 'off', 'false', 'no'):
            budget = 0
        restarts, next_check, last_input, pending = 0, 0, 0., bytearray()
        input_open, output_open, recovering = True, True, False
        notice = ''
        preparations = {}
        while True:
            if requested_stop[0]:
                return 128 + requested_stop[0]
            exited, status = os.waitpid(child, os.WNOHANG)
            if exited:
                # Preserve the final output before returning the CLI's status.
                while output_open:
                    ready, _, _ = select.select([master], [], [], 0)
                    if not ready:
                        break
                    try:
                        output = os.read(master, 65536)
                    except OSError:
                        break
                    if not output:
                        break
                    os.write(1, output)
                return os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)
            readers = ([master] if output_open else []) + ([0] if input_open else [])
            ready, _, _ = select.select(readers, [], [], .05)
            if 0 in ready:
                data = os.read(0, 65536)
                if data:
                    last_input = time.time()
                    for value in data:
                        if value in (3, 10, 13, 21):
                            pending.clear()
                        elif value in (8, 127):
                            if pending:
                                pending.pop()
                        elif len(pending) < 65536:
                            pending.append(value)
                    os.write(master, data)
                else:
                    input_open = False
            if master in ready:
                try:
                    data = os.read(master, 65536)
                    if data:
                        os.write(1, data)
                    else:
                        output_open = False
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    output_open = False
            if time.monotonic() < next_check:
                continue
            next_check = time.monotonic() + poll
            try:
                os.kill(int(owner), 0)
            except ProcessLookupError:
                return 143
            event = read_state(path)
            control.update(phase='active', heartbeat=time.time(), source='')
            if matches(event, expected) and event.get('state') == 'error' and baseline.get('configured') and restarts < budget:
                control.update(phase='waiting_provider', source=event.get('source', ''))
            atomic(control_path, control)
            if not matches(event, expected):
                continue
            if event.get('state') == 'clean' and recovering:
                emit('原会话已通过新 provider 完成回合。')
                recovering = False
                restarts = 0
                seen = {control['fingerprint']}
                notice = ''
            if event.get('state') == 'error' and restarts >= budget and budget > 0 and notice != 'limit':
                emit('自动切换已达上限，原会话已保留，请检查当前 provider。')
                notice = 'limit'
            if event.get('state') != 'error' or restarts >= budget:
                continue
            if baseline.get('configured') and not notice:
                emit('上游不可用；更新有效 provider 配置后将自动续接原会话。')
                notice = 'waiting'
            observed = event.get('observed_at', 0)
            if not isinstance(observed, (int, float)) or observed < started_at or observed > time.time() + 1:
                continue
            current = module.snapshot(tool, cwd=expected['project'], argv=original_command)
            updated = current.get('fingerprint')
            if not baseline.get('configured') or not current.get('configured') or not current.get('recoverable', True) or not updated or updated in seen:
                continue
            try:
                resumed = module.resume_command(tool, event.get('source', ''), original_command, expected['project'])
                launch_env = dict(os.environ, **module.launch_environment(tool, cwd=expected['project'], argv=resumed))
            except (OSError, ValueError, TypeError, sqlite3.Error):
                if notice != 'unsupported':
                    emit('当前工具或会话暂无法安全自动续接，原会话已保留。')
                    notice = 'unsupported'
                continue  # Keep the original TUI when continuity is uncertain.
            control.update(handled_source=event.get('source'), handled_event=event.get('event'))
            atomic(control_path, control)
            if pending or observed < last_input or Path('.codingkeeper/loop.halt').exists():
                continue
            # Recheck after validating config and session; UI/user input wins.
            if not pane_ready(expected) or read_state(path) != event or select.select([0] if input_open else [], [], [], 0)[0]:
                continue
            if module.snapshot(tool, cwd=expected['project'], argv=original_command).get('fingerprint') != updated:
                continue
            executable = Path(shutil.which(original_command[0]) or original_command[0])
            try:
                info = executable.stat()
                preparation = (event.get('source'), event.get('event'), updated,
                               str(executable.resolve()), info.st_mtime_ns, info.st_size)
            except OSError:
                continue
            if preparation not in preparations:
                # Local CLI capability/model selection calls are bounded but
                # can outlast one loop poll. Keep the supervised wait fresh.
                heartbeat_stop = threading.Event()
                def heartbeat():
                    while not heartbeat_stop.wait(2):
                        try:
                            atomic(control_path, dict(control, heartbeat=time.time()))
                        except OSError:
                            return
                heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
                heartbeat_thread.start()
                try:
                    module.prepare_resume(tool, event.get('source', ''), original_command, expected['project'])
                    preparations[preparation] = True
                except (OSError, ValueError, TypeError, sqlite3.Error, subprocess.SubprocessError):
                    preparations[preparation] = False
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join(timeout=1)
            if not preparations[preparation]:
                if notice != 'unsupported':
                    emit('原会话尚未确认使用新 provider，已保留当前会话。')
                    notice = 'unsupported'
                continue
            if not pane_ready(expected) or read_state(path) != event or select.select([0] if input_open else [], [], [], 0)[0]:
                continue
            if requested_stop[0] or module.snapshot(tool, cwd=expected['project'], argv=original_command).get('fingerprint') != updated:
                continue
            emit('检测到 provider 配置已更新，正在恢复原会话…')
            control['phase'] = 'restarting'
            atomic(control_path, control)
            stop(child)
            os.close(master)
            restarts += 1
            seen.add(updated)
            control['fingerprint'] = updated
            control['disk_fingerprint'] = module.snapshot(tool, cwd=expected['project']).get('fingerprint')
            atomic(control_path, control)
            atomic(path, dict(expected, state='clear', event='restart', observed_at=time.time()))
            child, master = spawn(resumed, launch_env)
            output_open = True
            resize(master)
            recovering = True
    finally:
        stop(child)
        os.close(master)
        if terminal:
            termios.tcsetattr(0, termios.TCSADRAIN, terminal)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        for state in (path, control_path):
            if matches(read_state(state), expected):
                state.unlink(missing_ok=True)


def main():
    if sys.argv[1:2] == ['waiting']:
        if len(sys.argv) != 6:
            raise ValueError('waiting requires tool pane owner source')
        return waiting(*sys.argv[2:])
    if sys.argv[1:2] == ['record']:
        if len(sys.argv) != 8:
            raise ValueError('record requires tool pane owner source event state')
        return record_event(*sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool')
    parser.add_argument('pane')
    parser.add_argument('owner')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        raise ValueError('tool command required')
    return supervise(args.tool, args.pane, args.owner, command)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        print('CodingKeeper: provider recovery could not be initialized; session state preserved', file=sys.stderr)
        sys.exit(1)
