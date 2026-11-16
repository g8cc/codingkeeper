#!/usr/bin/env python3
"""Launch one detached watcher per pane without inherited command-substitution pipes."""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def main_codex_rollout(sessions, project, candidates=None, max_age=None):
    """Select a project-owned main thread; subagents share cwd with their parent."""
    sessions = Path(sessions).resolve()
    project = os.path.realpath(project)
    if candidates is None:
        candidates = (Path(current) / name
                      for current, _dirs, files in os.walk(sessions)
                      for name in files if name.endswith('.jsonl'))
    ranked = []
    for path in candidates:
        path = Path(path)
        try:
            if path.suffix != '.jsonl' or not path.resolve().is_relative_to(sessions):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if max_age is not None and time.time() - info.st_mtime > max_age:
                continue
            ranked.append((info.st_mtime_ns, str(path)))
        except OSError:
            continue
    for _stamp, path in sorted(ranked, reverse=True):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    continue
                for _ in range(5):
                    line = source.readline(65537)
                    if not line or len(line) > 65536:
                        break
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(record, dict) or record.get('type') not in (None, 'session_meta'):
                        continue
                    meta = record.get('payload')
                    if not isinstance(meta, dict):
                        continue
                    cwd, origin = meta.get('cwd'), meta.get('source')
                    if isinstance(origin, dict) and 'subagent' in origin:
                        break
                    if isinstance(origin, str) and origin.lower().startswith('subagent'):
                        break
                    if isinstance(cwd, str) and cwd and os.path.realpath(cwd) == project:
                        return path
        except OSError:
            continue
    return ''


def select_codex_rollout(argv):
    import argparse
    parser = argparse.ArgumentParser(description='Select a main Codex thread, never a subagent')
    parser.add_argument('sessions')
    parser.add_argument('project')
    parser.add_argument('--candidates', type=Path)
    parser.add_argument('--max-age', type=int)
    args = parser.parse_args(argv)
    candidates = args.candidates.read_text().splitlines() if args.candidates else None
    sys.stdout.write(main_codex_rollout(args.sessions, args.project, candidates, args.max_age))

def write_atomic(path, text):
    fd, name = tempfile.mkstemp(prefix='.watcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def launch(script, pane, owner, logfile):
    if not pane.startswith('%') or not pane[1:].isdigit() or not owner.isdigit() or int(owner) <= 1:
        raise ValueError('invalid watcher pane or owner')
    directory = Path('.codingkeeper')
    directory.mkdir(mode=0o700, exist_ok=True)
    state = directory / ('watcher-' + pane[1:] + '.json')
    fd = os.open(str(state) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('watcher launch is busy')
                time.sleep(.05)
        try:
            old = json.loads(state.read_text())
            pid = old.get('pid') if isinstance(old, dict) else None
            if isinstance(pid, int) and pid > 1 and old.get('owner') == owner:
                command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=3)
                expected = script + ' __watcher_run ' + pane + ' ' + owner
                if command.returncode == 0 and command.stdout.strip().endswith(expected):
                    return pid
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            pass
        # Never signal a PID read from project files. An obsolete watcher exits
        # when its owner/pane dies; metadata cannot be used to kill other tasks.
        with open(logfile, 'ab', buffering=0) as log:
            child = subprocess.Popen([script, '__watcher_run', pane, owner], stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        try:
            write_atomic(state, json.dumps({'pid':child.pid, 'owner':owner}))
            write_atomic(directory/'watcher.pid', str(child.pid)+'\n')
        except OSError:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
        return child.pid
    finally:
        os.close(fd)

if __name__ == '__main__':
    try:
        if sys.argv[1:2] == ['--codex-rollout']:
            select_codex_rollout(sys.argv[2:])
        else:
            print(launch(*sys.argv[1:]))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'codexc: cannot launch watcher: {error}', file=sys.stderr)
        sys.exit(1)
