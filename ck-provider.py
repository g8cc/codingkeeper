#!/usr/bin/env python3
"""Read effective provider identity without logging credentials or making requests.

Snapshot fingerprints contain connection settings only.  Invalid/unsupported
configurations disable automatic recovery, but never prevent a normal launch.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

LIMIT = 4 * 1024 * 1024
TOOLS = ('codex', 'claude', 'pi', 'opencode', 'zcode', 'dsh')
CONFIG_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError,
                 RecursionError, StopIteration, subprocess.SubprocessError)
_CAPABILITIES = {}
CONNECTION_KEYS = {'base_url', 'baseUrl', 'baseURL', 'endpoint', 'url', 'apiKey',
                   'api_key', 'apiKeyEnv', 'api', 'wire_api', 'env_key',
                   'http_headers', 'env_http_headers', 'headers', 'requires_openai_auth',
                   'experimental_bearer_token', 'type', 'access', 'npm'}


def _read(path, optional=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        if optional:
            return ''
        raise
    with os.fdopen(fd, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('configuration is not a regular file')
        data = source.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('configuration is too large')
    return data.decode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate configuration key')
        result[key] = value
    return result


def _json(path, optional=False):
    text = _read(path, optional)
    if not text and optional:
        return {}
    # JSONC is used by OpenCode. Strip comments only outside string literals.
    text = re.sub(r'("(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\r\n]*)',
                  lambda m: m[0] if m[0].startswith('"') else ' ', text)
    text = re.sub(r'("(?:\\.|[^"\\])*"|,\s*[}\]])',
                  lambda m: m[0] if m[0].startswith('"') else m[0][1:], text)
    value = json.loads(text, object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError('configuration must be an object')
    return value


def _yaml(path, optional=False):
    text = _read(path, optional)
    if not text and optional:
        return {}
    try:
        return json.loads(text, object_pairs_hook=_unique)
    except json.JSONDecodeError:
        pass
    # Use the tool's existing parser, never install a YAML dependency or execute
    # configuration strings. Only parsed JSON crosses this subprocess boundary.
    binary = shutil.which(os.environ.get('DSH_BIN', 'dsh'))
    if not binary:
        raise ValueError('dsh YAML parser unavailable')
    package = Path(binary).resolve().parent.parent / 'package.json'
    script = ("const {createRequire}=require('module');"
              "const r=createRequire(process.argv[1]);let s='';"
              "process.stdin.setEncoding('utf8');process.stdin.on('data',x=>s+=x);"
              "process.stdin.on('end',()=>{try{process.stdout.write(JSON.stringify(r('yaml').parse(s)))}"
              "catch{process.exit(2)}})")
    result = subprocess.run(['node', '-e', script, str(package)], input=text,
                            capture_output=True, text=True, timeout=5)
    if result.returncode or len(result.stdout) > LIMIT:
        raise ValueError('invalid YAML configuration')
    return json.loads(result.stdout, object_pairs_hook=_unique)


def _merge(left, right):
    result = dict(left)
    for key, value in right.items():
        result[key] = _merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else value
    return result


def _args(argv):
    result = list(argv)
    if result and not result[0].startswith('-') and Path(result[0]).name in TOOLS:
        result = result[1:]
    return result


def _option(argv, *names):
    value = None
    for index, arg in enumerate(argv):
        if arg in names:
            if index + 1 >= len(argv):
                raise ValueError('missing option value')
            value = argv[index + 1]
        elif any(arg.startswith(name + '=') for name in names):
            value = arg.split('=', 1)[1]
    return value


def _references(value, env):
    if isinstance(value, dict):
        return {k: _references(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_references(v, env) for v in value]
    if isinstance(value, str):
        match = re.fullmatch(r'\{env:([^}]+)\}|\$\{([^}]+)\}', value)
        if match:
            return env.get(match[1] or match[2], '')
    return value


def _connection(value):
    return {key: val for key, val in value.items() if key in CONNECTION_KEYS}


def _codex(cwd, argv, env):
    if '--remote' in argv or '--oss' in argv or any(arg.startswith('--remote=') for arg in argv):
        raise ValueError('remote and local model runtimes cannot be reconfigured here')
    home = Path(env.get('CODEX_HOME') or env.get('CODEXC_HOME') or Path.home() / '.codex')
    data = tomllib.loads(_read(home / 'config.toml'))
    project = cwd / '.codex/config.toml'
    if project.is_file():
        data = _merge(data, tomllib.loads(_read(project)))
    profile = _option(argv, '-p', '--profile') or data.get('profile')
    if profile:
        external = home / (profile + '.config.toml')
        values = tomllib.loads(_read(external)) if external.is_file() else data.get('profiles', {}).get(profile)
        if not isinstance(values, dict):
            raise ValueError('unknown Codex profile')
        data = _merge(data, values)
    for index, arg in enumerate(argv):
        if arg in ('-c', '--config'):
            if index + 1 >= len(argv):
                raise ValueError('missing config override')
            override = argv[index + 1]
        elif arg.startswith(('--config=', '-c=')):
            override = arg.split('=', 1)[1]
        elif arg.startswith('-c') and not arg.startswith('--') and len(arg) > 2:
            override = arg[2:]
        else:
            continue
        try:
            values = tomllib.loads(override)
        except tomllib.TOMLDecodeError:
            key, value = override.split('=', 1)
            values = tomllib.loads(key + '=' + json.dumps(value))
        data = _merge(data, values)
    model = _option(argv, '-m', '--model') or data.get('model')
    name = data.get('model_provider', 'openai')
    provider = data.get('model_providers', {}).get(name, {})
    if not isinstance(provider, dict) or (name != 'openai' and not provider):
        raise ValueError('selected Codex provider is missing')
    settings = _connection(provider)
    key = provider.get('env_key')
    if key:
        settings['credential'] = env.get(key, '')
    elif provider.get('experimental_bearer_token'):
        settings['credential'] = provider['experimental_bearer_token']
    else:
        auth = _json(home / 'auth.json', optional=True)
        settings['credential'] = auth.get('OPENAI_API_KEY') or env.get('OPENAI_API_KEY') or auth.get('tokens')
        if auth.get('OPENAI_API_KEY'):
            env['OPENAI_API_KEY'] = auth['OPENAI_API_KEY']
    settings['env_header_values'] = {k: env.get(v, '') for k, v in provider.get('env_http_headers', {}).items()}
    return {'provider': name, 'model': model, 'connection': settings}, env


def _claude(cwd, argv, env):
    home = Path(env.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    data = {}
    found = False
    sources = _option(argv, '--setting-sources')
    if sources and sources != 'user,project,local':
        raise ValueError('custom Claude setting sources are not supported')
    for path in (home / 'settings.json', cwd / '.claude/settings.json', cwd / '.claude/settings.local.json'):
        if path.exists():
            data = _merge(data, _json(path)); found = True
    extra = _option(argv, '--settings')
    if extra:
        parsed = json.loads(extra) if extra.lstrip().startswith('{') else _json(Path(extra))
        data = _merge(data, parsed); found = True
    settings_env = data.get('env', {})
    if not isinstance(settings_env, dict) or not all(isinstance(v, (str, int, float, bool)) for v in settings_env.values()):
        raise ValueError('invalid Claude environment')
    # A switcher may replace token auth with API-key auth. Do not retain the
    # previous process's competing credential alongside the file's new one.
    auth_keys = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_OAUTH_TOKEN')
    if any(key in settings_env for key in auth_keys):
        for key in auth_keys:
            if key not in settings_env:
                env.pop(key, None)
    env.update({key: str(value) for key, value in settings_env.items()})
    relevant = {key: value for key, value in env.items()
                if key.startswith('ANTHROPIC_') or key in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY', 'AWS_REGION', 'AWS_PROFILE')}
    if not found and not relevant:
        raise ValueError('Claude provider configuration is absent')
    return {'provider': relevant, 'model': _option(argv, '--model') or data.get('model'),
            'apiKeyHelper': data.get('apiKeyHelper')}, env


def _pi_value(value, env):
    if not isinstance(value, str) or value.startswith('!'):
        raise ValueError('Pi dynamic credential cannot be inspected')

    def expand(match):
        token = match[0]
        if token in ('$$', '$!'):
            return token[1:]
        name = token[2:-1] if token.startswith('${') else token[1:]
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            return token
        resolved = env.get(name)
        if not isinstance(resolved, str) or not resolved:
            raise ValueError('Pi credential environment is missing')
        return resolved

    return re.sub(r'\$(?:[$!]|\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*)', expand, value)


def _pi(cwd, argv, env):
    home = Path(env.get('PI_CODING_AGENT_DIR') or env.get('PI_DIR') or Path.home() / '.pi/agent')
    data = _json(home / 'settings.json')
    project = cwd / '.pi/settings.json'
    if project.exists():
        data = _merge(data, _json(project))
    name = _option(argv, '--provider') or data.get('defaultProvider')
    model = _option(argv, '--model') or data.get('defaultModel')
    if not name or not model:
        raise ValueError('Pi provider/model is not selected')
    if '/' in model and not _option(argv, '--provider'):
        name, model = model.split('/', 1)
    providers = _json(home / 'models.json', optional=True).get('providers', {})
    entry = providers.get(name, {})
    auth = _json(home / 'auth.json', optional=True).get(name, {})
    settings = _connection(entry)
    settings.pop('apiKey', None)
    key = _option(argv, '--api-key')
    credential_env = env
    if key:
        settings['credential'] = key
    elif auth:
        credential_env = dict(env)
        stored_env = auth.get('env', {})
        if not isinstance(stored_env, dict) or not all(isinstance(value, str) for value in stored_env.values()):
            raise ValueError('invalid Pi credential environment')
        credential_env.update({name: value for name, value in stored_env.items() if value})
        if auth.get('type') == 'api_key':
            settings['credential'] = _pi_value(auth.get('key'), credential_env)
        elif auth.get('type') == 'oauth':
            settings['credential'] = auth
        else:
            raise ValueError('unknown Pi credential type')
    elif 'apiKey' in entry:
        settings['credential'] = _pi_value(entry['apiKey'], env)
    else:
        # Built-in providers resolve these names. Include only the selected one.
        key_name = {'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY','google':'GEMINI_API_KEY',
                    'deepseek':'DEEPSEEK_API_KEY','openrouter':'OPENROUTER_API_KEY','groq':'GROQ_API_KEY',
                    'xai':'XAI_API_KEY','zai':'ZAI_API_KEY'}.get(name)
        if not key_name or not env.get(key_name):
            raise ValueError('Pi provider credentials are not inspectable')
        settings['credential'] = env[key_name]
    if 'headers' in settings:
        settings['headers'] = {name: _pi_value(value, credential_env)
                               for name, value in settings['headers'].items()}
    return {'provider': name, 'model': model, 'connection': settings}, env


def _opencode(cwd, argv, env):
    if '--server' in argv or any(arg.startswith('--server=') for arg in argv):
        raise ValueError('remote OpenCode server cannot be reconfigured here')
    config_home = Path(env.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'opencode'
    data = {}
    for parent in (config_home, cwd):
        for name in ('opencode.json', 'opencode.jsonc'):
            path = parent / name
            if path.exists():
                data = _merge(data, _json(path))
    if env.get('OPENCODE_CONFIG'):
        data = _merge(data, _json(Path(env['OPENCODE_CONFIG'])))
    if env.get('OPENCODE_CONFIG_CONTENT'):
        data = _merge(data, json.loads(env['OPENCODE_CONFIG_CONTENT'], object_pairs_hook=_unique))
    model = _option(argv, '-m', '--model') or data.get('model')
    if not isinstance(model, str) or '/' not in model:
        raise ValueError('OpenCode provider/model is not selected')
    name, model_id = model.split('/', 1)
    entry = data.get('provider', {}).get(name, {})
    if not isinstance(entry, dict):
        raise ValueError('invalid OpenCode provider')
    options = _references(_connection(entry.get('options', {})), env)
    auth_home = Path(env.get('OPENCODE_DATA_DIR') or Path(env.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode')
    auth = _json(auth_home / 'auth.json', optional=True).get(name)
    return {'provider': name, 'model': model_id, 'options': options, 'npm': entry.get('npm'),
            'credential': auth}, env


def _zcode(cwd, argv, env):
    base = Path(env.get('ZCODE_DATA_BASE_DIR') or Path.home())
    path = Path(env.get('ZCODE_PERSONAL_PROVIDER_CONFIG_FILE') or base / '.zcode/v2/provider_config.json')
    data = _json(path).get('config', {})
    order = data.get('providerOrder', [])
    if not isinstance(order, list) or not order:
        raise ValueError('ZCode provider order is missing')
    rules = data.get('providerConfigRules', {}).get('providerRules', [])
    choice = data.get('defaultModelSelection')
    if choice is not None:
        if not isinstance(choice, dict):
            raise ValueError('invalid ZCode default model selection')
        name, model = choice.get('providerId'), choice.get('modelId')
        if not isinstance(name, str) or not isinstance(model, str) or not name or not model:
            raise ValueError('invalid ZCode default model selection')
        if not isinstance(choice.get('options', {}), dict):
            raise ValueError('invalid ZCode default model options')
    elif len(order) == 1:
        name, model = order[0], None
    else:
        raise ValueError('ZCode default selection is ambiguous')
    selected = next((r.get('config') for r in rules if isinstance(r, dict) and r.get('providerId') == name), None)
    if not isinstance(selected, dict):
        raise ValueError('ZCode selected provider is missing')
    models = selected.get('modelOrder') or selected.get('personalModelIds')
    if not isinstance(models, list) or not models:
        raise ValueError('ZCode model is not selected')
    if model is None:
        if len(models) != 1:
            raise ValueError('ZCode default model is ambiguous')
        model = models[0]
    if not isinstance(model, str) or not model:
        raise ValueError('invalid ZCode model')
    # The current ZCode CLI has no --model flag and restores a resumed session's
    # selection. Its worker uses this non-secret value for a local /model
    # command before the task; a configured default alone does not switch it.
    if env.get('CODEXC_PROVIDER_RELOADING') == '1':
        env['CODEXC_ZCODE_MODEL_SELECTION'] = json.dumps({'providerId': name, 'modelId': model,
                                                        **({'options': choice['options']} if isinstance(choice, dict) and choice.get('options') else {})}, separators=(',', ':'))
    else:
        env.pop('CODEXC_ZCODE_MODEL_SELECTION', None)
    model_rules = [r for r in data.get('modelConfigRules', {}).get('providerModelRules', [])
                   if isinstance(r, dict) and r.get('providerId') == name and r.get('modelId') == model]
    return {'provider': name, 'model': model, 'modelOptions': (choice or {}).get('options', {}),
            'connection': _connection(selected), 'modelRules': model_rules}, env


def _dsh(cwd, argv, env):
    home = Path(env.get('DSH_HOME') or Path.home() / '.dsh')
    data = _yaml(home / 'settings.yaml', optional=True)
    if not isinstance(data, dict):
        raise ValueError('invalid dsh settings')
    profile = _option(argv, '--profile') or env.get('DSH_PROFILE', 'headless')
    profile_path = home / 'profiles' / profile / 'cordis.patch.yml'
    roots = []
    manifest = _json(profile_path.with_name('package.json'), optional=True)
    bundles = manifest.get('dsh', {}).get('profile', {}).get('bundles', [])
    if not isinstance(bundles, list):
        raise ValueError('invalid dsh bundles')
    binary = shutil.which(env.get('DSH_BIN', 'dsh'))
    if bundles and not binary:
        raise ValueError('dsh bundle configuration cannot be inspected')
    package = Path(binary).resolve().parent.parent if binary else None
    for bundle in bundles:
        if not isinstance(bundle, str) or not re.fullmatch(r'@?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?', bundle):
            raise ValueError('dsh bundle path cannot be inspected')
        roots.append(package / 'node_modules' / bundle / 'cordis.patch.yml')
    roots.extend(path for path in (profile_path, home / 'cordis.patch.yml') if path.exists())
    for index, arg in enumerate(argv):
        if arg == '--':
            break
        if arg == '--patch':
            if index + 1 >= len(argv):
                raise ValueError('missing dsh patch path')
            roots.append(cwd / argv[index + 1])
        elif arg.startswith('--patch='):
            roots.append(cwd / arg.split('=', 1)[1])

    def entries(tree):
        if not isinstance(tree, list):
            raise ValueError('invalid dsh profile')
        for entry in tree:
            if not isinstance(entry, dict):
                raise ValueError('invalid dsh profile row')
            yield entry
            if 'insert' in entry:
                yield from entries(entry['insert'])

    disabled = {}
    for path in roots:
        for entry in entries(_yaml(path)):
            name = entry.get('id')
            if name not in ('llm-pi-ai', 'agent-default-model', 'credentials'):
                continue
            if 'disabled' in entry:
                disabled[name] = entry['disabled']
            if 'config' in entry:
                data[name] = entry['config']
    if any(value is not False for value in disabled.values()):
        raise ValueError('dsh provider selection is disabled or dynamic')
    if any(not isinstance(data.get(name, {}), dict)
           for name in ('llm-pi-ai', 'agent-default-model', 'credentials')):
        raise ValueError('dynamic dsh provider configuration')
    if any(key in data.get('credentials', {}) for key in ('path', 'dshHome')):
        raise ValueError('custom dsh credential store cannot be inspected')
    default = data.get('agent-default-model', {})
    llm = data.get('llm-pi-ai', {})
    model = _option(argv, '--model') or default.get('model') or llm.get('defaultModel') or llm.get('model')
    providers = llm.get('providers', {})
    if not isinstance(providers, dict) or not providers:
        raise ValueError('dsh providers are absent')
    if default.get('provider') and model:
        name = default['provider']
    elif isinstance(model, str) and '/' in model:
        name, model = model.split('/', 1)
    elif len(providers) == 1:
        name = next(iter(providers))
        models = providers[name].get('models') or []
        model = model or (models[0].get('id') if models and isinstance(models[0], dict) else None)
    else:
        raise ValueError('dsh active provider is ambiguous')
    entry = providers.get(name)
    if not isinstance(entry, dict) or not model:
        raise ValueError('dsh selected provider/model is missing')
    credentials = _yaml(home / '.credentials.yaml', optional=True)
    refs = credentials.get('refs', {}) if isinstance(credentials, dict) else {}
    key = entry.get('apiKeyEnv')
    if isinstance(key, str) and isinstance(refs.get(key), str):
        env[key] = refs[key]
    settings = _connection(entry)
    if key:
        settings['credential'] = env.get(key, '')
    return {'provider': name, 'model': model, 'connection': settings}, env


def _effective(tool, cwd=None, argv=()):
    if tool not in TOOLS:
        raise ValueError('unsupported tool')
    return globals()['_' + tool](Path(cwd or os.getcwd()).resolve(), _args(argv), dict(os.environ))


def snapshot(tool, cwd=None, argv=()):
    result = {'tool': tool, 'configured': False, 'recoverable': False, 'fingerprint': ''}
    try:
        data, _env = _effective(tool, cwd, argv)
        result.update(configured=True, recoverable=True, fingerprint=hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest())
    except CONFIG_ERRORS:
        pass
    return result


def launch_environment(tool, cwd=None, argv=()):
    try:
        return _effective(tool, cwd, argv)[1]
    except CONFIG_ERRORS:
        return dict(os.environ)


def initial_command(tool, original_command, cwd):
    """Make Codex honor effective config even when first restoring an old thread.

    Derive launch arguments only; retain the caller's original argv so future
    configuration changes are not mistaken for a user-pinned provider/model.
    """
    command = list(original_command)
    if tool != 'codex' or not command:
        return command
    try:
        current, _env = _effective(tool, cwd, command[1:])
        name, model = current['provider'], current.get('model')
        if not isinstance(name, str) or not name or (model is not None and not isinstance(model, str)):
            return command
        options = ['-c', 'model_provider=' + json.dumps(name)]
        if model:
            options += ['--model', model]
        return command[:1] + options + command[1:]
    except CONFIG_ERRORS:
        return command


def error_is_missing_provider(text):
    return bool(re.search(r'\bProviderModelNotFoundError\b|\b(?:Provider|Model)NotFound\b|'
                          r'\b(?:provider|model)-not-found\b|\bunknown\s+(?:provider|model)\s*[:=]|'
                          r'\b(?:provider|model)(?:\s+[\w./:-]+){0,3}\s+(?:is\s+)?(?:not\s+(?:found|configured)|unavailable)\b|'
                          r'\b(?:provider|model)\s+not\s+found\s*:', str(text), re.I))


def error_is_provider(text):
    return bool(re.search(r'\b(?:401|402|403|429|500|502|503|504)\b|quota|usage.limit|rate.limit|'
                          r'too.many.requests|exceeded.retry.limit|insufficient.(?:credit|balance|fund)|'
                          r'(?:invalid|expired).{0,20}(?:api.?key|token)|api.?key.{0,20}(?:invalid|expired)|'
                          r'unauthori[sz]ed|authentication|ECONNRESET|ECONNREFUSED|ENOTFOUND|'
                          r'connection|network|fetch.failed|timed.out|timeout|bad.gateway|'
                          r'service.unavailable|at.capacity|overloaded|额度|配额|余额不足|令牌.*(?:过期|失效)',
                          str(text), re.I) or error_is_missing_provider(text))


def _session(tool, source, cwd):
    project = os.path.realpath(cwd)
    if tool == 'opencode':
        if not isinstance(source, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', source):
            raise ValueError('invalid OpenCode session identity')
        directory = Path(os.environ.get('OPENCODE_DATA_DIR') or Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode')
        with closing(sqlite3.connect((directory / 'opencode.db').resolve().as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT directory FROM session_v2 WHERE id=?', (source,)).fetchall()
        if len(rows) != 1 or os.path.realpath(rows[0][0]) != project:
            raise ValueError('OpenCode session is missing or belongs to another project')
        return source
    fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('session source is not a regular file')
        lines = []
        for _ in range(12):
            line = stream.readline(65537)
            if not line or len(line) > 65536:
                break
            lines.append(line)
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if tool == 'codex':
            if event.get('type') != 'session_meta':
                continue
            record = event.get('payload', {})
            if not isinstance(record, dict):
                raise ValueError('invalid Codex session metadata')
            origin = record.get('source')
            if ((isinstance(origin, dict) and 'subagent' in origin)
                    or (isinstance(origin, str) and origin.lower().startswith('subagent'))):
                raise ValueError('subagent cannot replace a main conversation')
            sid = record.get('id'); owner = record.get('cwd')
        elif tool == 'claude':
            if event.get('isSidechain'):
                raise ValueError('sidechain cannot replace a main conversation')
            sid = event.get('sessionId'); owner = event.get('cwd')
        elif tool == 'pi':
            if event.get('type') != 'session':
                continue
            sid = event.get('id'); owner = event.get('cwd')
        else:
            raise ValueError('headless sessions use their existing adapters')
        if not sid or not owner:
            continue
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', sid):
            raise ValueError('invalid session identity')
        if not isinstance(owner, str) or os.path.realpath(owner) != project:
            raise ValueError('session belongs to another project')
        return str(Path(source).resolve()) if tool == 'pi' else sid
    raise ValueError('session ownership cannot be verified')


def _kept_options(tool, argv):
    common = {'--model', '-m', '--settings', '--setting-sources', '--permission-mode', '--effort',
              '--system-prompt', '--append-system-prompt', '--thinking', '--provider', '--api-key',
              '--tools', '--exclude-tools', '--extension', '-e', '--skill', '--prompt-template',
              '--theme', '--mcp-config', '--add-dir', '--sandbox', '-s', '--ask-for-approval', '-a',
              '--config', '--profile', '-p', '--agent', '--agents', '--allowedTools', '--disallowedTools',
              '--system-prompt-file', '--append-system-prompt-file', '--mode'}
    booleans = {'--dangerously-bypass-approvals-and-sandbox','--approve-for-me','--dangerously-skip-permissions',
                '--allow-dangerously-skip-permissions','--auto','--search','--no-alt-screen','--no-daemon',
                '--standalone','--offline','--approve','--no-approve','--no-extensions','--no-skills',
                '--no-context-files','--no-themes','--no-prompt-templates','--no-tools','--no-builtin-tools',
                '--verbose','--strict-config'}
    valued = {'--resume', '-r', '--session', '--session-id'}
    switches = {'--continue', '--last', '--all', '--include-non-interactive'}
    kept = []
    index = 0
    args = list(argv)
    if tool == 'codex':
        common.add('-c')
    else:
        switches.add('-c')
        common.discard('-p')
        common.discard('--profile')
        common.discard('-s')
    if tool == 'opencode':
        valued.add('-s')
        valued.add('--prompt')
    elif tool == 'pi':
        common.discard('-a')
        booleans.add('-a')
        common.add('-t')
    while index < len(args):
        arg = args[index]
        if tool == 'codex' and arg.startswith('-c') and not arg.startswith('--') and len(arg) > 2:
            # Clap accepts -c=KEY=VALUE and -cKEY=VALUE as well as -c VALUE.
            kept += ['-c', arg[2:].removeprefix('=')]
            index += 1
            continue
        if arg in ('resume', 'fork'):
            # The old identity and positional prompt are intentionally discarded.
            index += 1
            if index < len(args) and not args[index].startswith('-'):
                index += 1
            continue
        name = arg.split('=', 1)[0]
        if name in valued:
            index += 1 if '=' in arg else 2
        elif name in switches:
            index += 1
        elif name in common:
            kept.append(arg)
            if '=' not in arg:
                if index + 1 >= len(args):
                    raise ValueError('missing original option value')
                kept.append(args[index + 1]); index += 1
            index += 1
        elif arg in booleans:
            kept.append(arg); index += 1
        elif arg.startswith('-'):
            raise ValueError('cannot safely preserve original option')
        else:
            # Initial prompts are not replayed as new requests.
            index += 1
    return kept


def verify_resume_capability(tool, original_command):
    """Check local native resume support before the running process is stopped."""
    if not original_command:
        raise ValueError('original command is missing')
    executable = shutil.which(original_command[0])
    if executable is None:
        raise ValueError('tool executable is unavailable')
    path = Path(executable).resolve()
    info = path.stat()
    key = (tool, str(path), info.st_mtime_ns, info.st_size)
    if key not in _CAPABILITIES:
        command = [str(path)] + (['resume', '--help'] if tool == 'codex' else ['--help'])
        try:
            help_text = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True, timeout=3).stdout
            required = {'codex': ('--no-daemon', 'resume'), 'claude': ('--resume',),
                        'pi': ('--session',), 'opencode': ('--standalone', '--session')}[tool]
            _CAPABILITIES[key] = all(flag in help_text for flag in required)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            _CAPABILITIES[key] = False
    if not _CAPABILITIES[key]:
        raise ValueError('installed tool does not expose safe private-session resume')


def resume_command(tool, source, original_command, cwd):
    if not original_command:
        raise ValueError('original command is missing')
    try:
        sid = _session(tool, source, cwd)
    except CONFIG_ERRORS + (sqlite3.Error,):
        raise ValueError('session identity or project ownership cannot be verified') from None
    verify_resume_capability(tool, original_command)
    options = _kept_options(tool, original_command[1:])
    command = [original_command[0]] + options
    if tool == 'codex':
        try:
            current, _env = _effective(tool, cwd, options)
            command += ['-c', 'model_provider=' + json.dumps(current['provider'])]
            if current.get('model'):
                command += ['--model', current['model']]
        except CONFIG_ERRORS:
            pass
        if '--no-daemon' not in command:
            command.append('--no-daemon')
        command += ['resume', sid, 'continue']
    elif tool == 'claude':
        try:
            current, _env = _effective(tool, cwd, options)
            if current.get('model'):
                command += ['--model', current['model']]
        except CONFIG_ERRORS:
            pass
        command += ['--resume', sid, 'continue']
    elif tool == 'pi':
        command += ['--session', sid]
        # Pi otherwise restores the old session's model before its global default.
        try:
            config, _env = _effective(tool, cwd, options)
            command += ['--provider', config['provider'], '--model', config['model']]
        except (OSError, ValueError, TypeError):
            pass
        command.append('continue')
    elif tool == 'opencode':
        if '--standalone' not in command:
            command.append('--standalone')
        command += ['--session', sid, '--prompt', 'continue']
    else:
        raise ValueError('headless sessions use their existing adapters')
    return command


def _native_output(command, cwd=None, env=None, timeout=12):
    """Bound local native API output/time and reap only its private process group."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=cwd, env=env, start_new_session=True)
    chunks, sizes = [], {'stdout': 0, 'stderr': 0}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('native provider configuration command timed out')
                for key, _mask in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    sizes[key.data] += len(data)
                    if sizes[key.data] > LIMIT:
                        raise ValueError('native provider configuration output exceeded limit')
                    if key.data == 'stdout':
                        chunks.append(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or process.wait(timeout=remaining):
                raise ValueError('native provider configuration command failed')
        return b''.join(chunks)
    finally:
        # Popen created this group. Never signal the supervisor/terminal group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin may reject signals to an already dead, zombie-only group.
            result = subprocess.run(['ps', '-axo', 'pgid=,stat='], capture_output=True,
                                    text=True, timeout=3, check=True)
            if any(len(fields) == 2 and fields[0] == str(process.pid) and not fields[1].startswith('Z')
                   for fields in (row.split() for row in result.stdout.splitlines())):
                raise
        process.wait()
        process.stdout.close()
        process.stderr.close()


def _opencode_current(sid, cwd):
    directory = Path(os.environ.get('OPENCODE_DATA_DIR') or
                     Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'opencode')
    with closing(sqlite3.connect((directory / 'opencode.db').resolve().as_uri() + '?mode=ro',
                                uri=True, timeout=3)) as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(session_v2)')}
        query = 'SELECT directory,model' + (',path' if 'path' in columns else '') + ' FROM session_v2 WHERE id=?'
        rows = db.execute(query, (sid,)).fetchall()
    if (len(rows) != 1 or any(not isinstance(path, str) or os.path.realpath(path) != os.path.realpath(cwd)
            for path in (rows[0][0], rows[0][2] if len(rows[0]) > 2 and rows[0][2] is not None else rows[0][0]))):
        raise ValueError('OpenCode recovery session ownership cannot be verified')
    raw = rows[0][1]
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError('invalid persisted OpenCode model')
    current = json.loads(raw)
    if not isinstance(current, dict):
        raise ValueError('invalid persisted OpenCode model')
    return current


def prepare_resume(tool, source, original_command, cwd):
    """Apply OpenCode's latest model with its native local API before TUI exit."""
    if tool != 'opencode':
        return
    try:
        sid = _session(tool, source, cwd)
        current = _opencode_current(sid, cwd)
        config, env = _effective(tool, cwd, original_command[1:])
        desired = {'providerID': config['provider'], 'id': config['model']}
        if not all(isinstance(value, str) and value and len(value) <= 512
                   and not re.search(r'[\s\x00-\x1f\x7f]', value) for value in desired.values()):
            raise ValueError('invalid OpenCode configured model')
        def selected():
            value = _opencode_current(sid, cwd)
            return value is not None and all(value.get(key) == val for key, val in desired.items())
        if current is not None and all(current.get(key) == val for key, val in desired.items()):
            return
        verify_resume_capability(tool, original_command)
        command = [original_command[0], 'api', '--standalone']
        help_text = _native_output([original_command[0], 'api', '--help'], cwd=cwd, env=env).decode('utf-8', 'replace')
        if not all(flag in help_text for flag in ('--standalone', '--param', '--data')):
            raise ValueError('installed OpenCode local API is not supported')
        schema = json.loads(_native_output(command + ['GET', '/openapi.json'], cwd=cwd, env=env))
        operation = schema.get('paths', {}).get('/api/session/{sessionID}/model', {}).get('post', {})
        if operation.get('operationId') != 'session.switchModel':
            raise ValueError('installed OpenCode model switch is not supported')
        _native_output(command + ['session.switchModel', '--param', 'sessionID=' + sid, '--data',
                       json.dumps({'model': desired}, separators=(',', ':'))], cwd=cwd, env=env)
        if not selected():
            raise ValueError('OpenCode model switch was not persisted to the original session')
    except CONFIG_ERRORS + (sqlite3.Error,):
        raise ValueError('OpenCode provider recovery could not be verified; original session preserved') from None


def _zcode_helper():
    spec = importlib.util.spec_from_file_location('ck_zcode_provider_session',
            Path(__file__).resolve().with_name('ck-zcode-session.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def _zcode_current(sid, cwd):
    if not isinstance(sid, str) or not re.fullmatch(r'sess_[A-Za-z0-9_-]{1,200}', sid):
        raise ValueError('invalid ZCode recovery session')
    db_path = Path(os.environ.get('ZCODE_SESSION_DB') or Path.home() / '.zcode/cli/db/db.sqlite').resolve()
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        rows = db.execute('SELECT directory,path FROM session WHERE id=?', (sid,)).fetchall()
        if len(rows) != 1 or any(not isinstance(path, str) or os.path.realpath(path) != os.path.realpath(cwd)
                                for path in (rows[0][0], rows[0][1] if rows[0][1] is not None else rows[0][0])):
            raise ValueError('ZCode recovery session does not belong to this project')
        found = db.execute("SELECT data FROM session_entry WHERE session_id=? AND type='runtime/model_selection' ORDER BY time_updated DESC,id DESC LIMIT 1", (sid,)).fetchone()
    if not found:
        return None
    record = json.loads(found[0])
    if not isinstance(record, dict):
        raise ValueError('invalid persisted ZCode model selection')
    current = record.get('modelSelection') or record
    if (not isinstance(current, dict) or not isinstance(current.get('options', {}), dict)
            or not all(isinstance(current.get(key), str) and current[key] for key in ('providerId', 'modelId'))):
        raise ValueError('invalid persisted ZCode model selection')
    return current


def _zcode_matches(current, choice):
    return (current is not None and current.get('providerId') == choice['providerId']
            and current.get('modelId') == choice['modelId']
            and all(current.get('options', {}).get(key) == value for key, value in choice.get('options', {}).items()))


def needs_reload(tool, cwd=None):
    """Only a verified durable session/default difference authorizes recovery."""
    if tool != 'zcode':
        return False
    cwd = Path(cwd or os.getcwd()).resolve()
    config, _env = _effective(tool, cwd)
    path = Path(os.environ.get('ZCODE_SESSION_FILE') or cwd / '.codingkeeper/zcode-session-id')
    helper = _zcode_helper()
    sid = helper.saved(path) or helper.saved(Path(str(path) + '.retry'))
    if not sid:
        return False
    current = _zcode_current(sid, cwd)
    choice = {'providerId': config['provider'], 'modelId': config['model'], 'options': config['modelOptions']}
    return current is not None and not _zcode_matches(current, choice)


def prepare_zcode_session(sid, cjs, mode):
    """Apply a new default through ZCode's native local command, then verify it.

    A resumed CLI deliberately ignores configuredDefaultModelSelection. The
    /model command updates runtime/model_selection without a model request.
    Read-only DB verification prevents a failed command from silently running
    the task on the old provider. Only the native CLI persists the selection.
    """
    raw = os.environ.get('CODEXC_ZCODE_MODEL_SELECTION')
    if not raw:
        return
    choice = json.loads(raw)
    if not isinstance(choice, dict) or not re.fullmatch(r'sess_[A-Za-z0-9_-]{1,200}', sid):
        raise ValueError('ZCode recovery selection cannot be verified')
    if not isinstance(choice.get('options', {}), dict):
        raise ValueError('invalid ZCode recovery options')
    name, model = choice.get('providerId'), choice.get('modelId')
    if not all(isinstance(value, str) and value and len(value) <= 512 and not re.search(r'[\s\x00-\x1f\x7f]', value)
               for value in (name, model)):
        raise ValueError('ZCode recovery model cannot be verified')
    def selected():
        return _zcode_matches(_zcode_current(sid, os.getcwd()), choice)

    if selected():
        return
    value = name + '/' + model
    effort = choice.get('options', {}).get('reasoningLevel')
    if effort:
        if not isinstance(effort, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', effort):
            raise ValueError('invalid ZCode reasoning selection')
        value += '$' + effort
    helper = _zcode_helper()
    command = ['node', cjs, '--resume', sid, '--prompt', '/model ' + value,
               '--cwd', os.getcwd(), '--mode', mode, '--no-color', '--json', '--output-format', 'stream-json']
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                 env=helper.cli_environment(cjs), timeout=45)
        if process.returncode or os.fstat(output.fileno()).st_size > LIMIT:
            raise ValueError('ZCode native model switch failed; task was not sent')
        output.seek(0)
        records = helper.records(output.read(LIMIT))
    final = [item for item in records if isinstance(item, dict) and item.get('type') in (None, 'result') and 'sessionId' in item]
    if (not final or any(item.get('sessionId') != sid for item in final)
            or not isinstance(final[-1].get('response'), str)
            or not final[-1]['response'].startswith('Model switched to ')
            or not selected()):
        raise ValueError('ZCode model switch was not persisted to the original session; task was not sent')


def main(argv):
    if len(argv) == 2 and argv[0] == 'needs-reload':
        return 0 if needs_reload(argv[1]) else 1
    if len(argv) == 2 and argv[0] == 'fingerprint':
        result = snapshot(argv[1])
        if not result['recoverable']:
            return 1
        print(result['fingerprint'])
        return 0
    if len(argv) == 2 and argv[0] == 'error':
        fd = os.open(argv[1], os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return 1
            stream.seek(max(0, os.fstat(stream.fileno()).st_size - 65536))
            text = stream.read(65536).decode('utf-8', 'replace')
        return 0 if error_is_provider(text) else 1
    if len(argv) > 3 and argv[0] == 'exec' and argv[2] == '--':
        command = argv[3:]
        os.execvpe(command[0], command, launch_environment(argv[1], argv=command))
    if len(argv) == 4 and argv[0] == 'prepare-zcode':
        prepare_zcode_session(*argv[1:])
        return 0
    raise ValueError('invalid provider helper arguments')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except CONFIG_ERRORS + (sqlite3.Error,):
        # Configuration parsing can include credentials in library exceptions.
        print('codingkeeper: provider configuration or session cannot be verified', file=sys.stderr)
        sys.exit(1)
