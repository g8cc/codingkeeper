#!/usr/bin/env python3
"""Provider changes and exact-session recovery; no provider requests."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ck_provider', ROOT / 'ck-provider.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
VERIFY_CAPABILITY = provider.verify_resume_capability


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ck-provider-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.env = patch.dict(os.environ, {'HOME': str(self.home)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        capability = patch.object(provider, 'verify_resume_capability')
        capability.start()
        self.addCleanup(capability.stop)

    def write(self, path, data):
        path = self.home / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return path

    def snap(self, tool, argv=()):
        result = provider.snapshot(tool, self.project, argv)
        self.assertTrue(result['configured'])
        self.assertTrue(result['recoverable'])
        self.assertRegex(result['fingerprint'], '^[a-f0-9]{64}$')
        return result['fingerprint']

    def codex(self, endpoint='https://old.example', extra=''):
        return self.write('.codex/config.toml', 'model_provider="custom"\nmodel="m"\n'
                          '[model_providers.custom]\nbase_url="' + endpoint + '"\n' + extra)

    def test_codex_connection_changes_but_trust_and_retries_do_not(self):
        self.codex()
        before = self.snap('codex')
        self.codex(extra='request_max_retries=9\n[projects."/tmp/p"]\ntrust_level="trusted"\n')
        self.assertEqual(self.snap('codex'), before)
        self.codex('https://new.example')
        self.assertNotEqual(self.snap('codex'), before)

    def test_codex_cli_provider_override_is_authoritative(self):
        self.codex()
        argv = ['-c', 'model_provider="custom"', '-c', 'model_providers.custom.base_url="https://pinned"']
        before = self.snap('codex', argv)
        self.codex('https://new.example')
        self.assertEqual(self.snap('codex', argv), before)

    def test_codex_attached_config_override_preserves_explicit_provider_pin(self):
        for flag in ('-c=', '--config=', '-c'):
            self.codex('https://default-old')
            path=self.home/'.codex/config.toml'
            path.write_text(path.read_text()+'[model_providers.pinned]\nbase_url="https://pinned"\n')
            argv=[flag+'model_provider="pinned"']
            before=self.snap('codex',argv)
            self.codex('https://default-new')
            path.write_text(path.read_text()+'[model_providers.pinned]\nbase_url="https://pinned"\n')
            self.assertEqual(before,self.snap('codex',argv),flag)
            session=self.write('pinned.jsonl',json.dumps({'type':'session_meta','payload':{
                'id':'pinned-session','cwd':str(self.project),'source':'cli'}})+'\n')
            command=provider.resume_command('codex',str(session),['codex']+argv,self.project)
            self.assertEqual(command[command.index('model_provider="pinned"')],'model_provider="pinned"')
            self.assertNotIn('model_provider="custom"',command)

    def test_codex_first_resume_explicitly_applies_current_config_without_changing_original(self):
        self.codex('https://new-provider')
        original=['codex','--sandbox','workspace-write','resume','old-session','continue']
        launch=provider.initial_command('codex',original,self.project)
        self.assertEqual(launch[:5],['codex','-c','model_provider="custom"','--model','m'])
        self.assertEqual(launch[5:],original[1:])
        self.assertEqual(original,['codex','--sandbox','workspace-write','resume','old-session','continue'])
        pinned=original[:1]+['-c=model_provider="pinned"','--model','explicit']+original[1:]
        path=self.home/'.codex/config.toml'
        path.write_text(path.read_text()+'[model_providers.pinned]\nbase_url="https://pinned"\n')
        self.assertEqual(provider.initial_command('codex',pinned,self.project)[:5],
                         ['codex','-c','model_provider="pinned"','--model','explicit'])
        for tool in ('claude','pi','opencode','zcode','dsh'):
            self.assertEqual(provider.initial_command(tool,original,self.project),original)
        path.write_text('broken=[')
        self.assertEqual(provider.initial_command('codex',original,self.project),original)

    def test_missing_broken_and_fifo_configs_fail_closed(self):
        for tool in ('codex', 'claude', 'pi', 'opencode', 'zcode', 'dsh'):
            self.assertFalse(provider.snapshot(tool, self.project)['recoverable'], tool)
        p = self.write('.codex/config.toml', 'model_provider=[')
        self.assertFalse(provider.snapshot('codex', self.project)['recoverable'])
        p.unlink()
        os.mkfifo(p)
        self.assertFalse(provider.snapshot('codex', self.project)['recoverable'])

    def test_claude_new_settings_refresh_inherited_provider_env(self):
        os.environ['ANTHROPIC_BASE_URL'] = 'https://old'
        os.environ['ANTHROPIC_AUTH_TOKEN'] = 'old-secret'
        self.write('.claude/settings.json', {'model':'sonnet','env':{
            'ANTHROPIC_BASE_URL':'https://new', 'ANTHROPIC_AUTH_TOKEN':'new-secret'}})
        before = self.snap('claude')
        env = provider.launch_environment('claude', self.project)
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'https://new')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'new-secret')
        self.assertNotIn('new-secret', json.dumps(provider.snapshot('claude', self.project)))
        self.write('.claude/settings.json', {'model':'sonnet','env':{
            'ANTHROPIC_BASE_URL':'https://new', 'ANTHROPIC_AUTH_TOKEN':'rotated-secret'}})
        self.assertNotEqual(self.snap('claude'), before)

    def test_pi_ignores_unselected_provider_changes_and_tracks_selected_key(self):
        self.write('.pi/agent/settings.json', {'defaultProvider':'p','defaultModel':'m'})
        models = {'providers':{'p':{'baseUrl':'https://one','apiKey':'key'},
                               'other':{'baseUrl':'https://two','apiKey':'unused'}}}
        self.write('.pi/agent/models.json', models)
        before = self.snap('pi')
        models['providers']['other']['apiKey'] = 'changed'
        self.write('.pi/agent/models.json', models)
        self.assertEqual(self.snap('pi'), before)
        models['providers']['p']['apiKey'] = 'changed'
        self.write('.pi/agent/models.json', models)
        self.assertNotEqual(self.snap('pi'), before)

    def test_opencode_tracks_selected_provider_options_only(self):
        config = {'model':'p/m','provider':{'p':{'options':{'baseURL':'https://p','apiKey':'key'}},
                                          'q':{'options':{'baseURL':'https://q'}}}}
        self.write('.config/opencode/opencode.json', config)
        before = self.snap('opencode')
        config['provider']['q']['options']['baseURL'] = 'https://new'
        config['permission'] = {'*':'allow'}
        self.write('.config/opencode/opencode.json', config)
        self.assertEqual(self.snap('opencode'), before)
        config['provider']['p']['options']['apiKey'] = 'rotated'
        self.write('.config/opencode/opencode.json', config)
        self.assertNotEqual(self.snap('opencode'), before)

    def test_zcode_personal_provider_order_and_selected_config(self):
        config = {'config':{'providerOrder':['p'], 'providerConfigRules':{'providerRules':[
            {'providerId':'p','config':{'api':{'baseUrl':'https://p'},'access':{'apiKey':'secret'},'modelOrder':['m']}}]}}}
        self.write('.zcode/v2/provider_config.json', config)
        before = self.snap('zcode')
        config['config']['providerConfigRules']['providerRules'][0]['config']['access']['apiKey']='rotated'
        self.write('.zcode/v2/provider_config.json', config)
        self.assertNotEqual(self.snap('zcode'), before)

    def test_dsh_effective_selected_model_and_credentials(self):
        self.write('.dsh/settings.yaml', {'llm-pi-ai':{'defaultModel':'p/m','providers':{
            'p':{'baseURL':'https://p','apiKeyEnv':'KEY','models':[{'id':'m'}]},
            'other':{'baseURL':'https://q'}}}})
        self.write('.dsh/.credentials.yaml', {'refs':{'KEY':'secret'}})
        before = self.snap('dsh')
        self.write('.dsh/.credentials.yaml', {'refs':{'KEY':'new-secret'}})
        self.assertNotEqual(self.snap('dsh'), before)
        self.assertEqual(provider.launch_environment('dsh', self.project)['KEY'], 'new-secret')

    def test_provider_errors_exclude_arbitrary_task_failures(self):
        for text in ('429 Too Many Requests', 'usage limit reached', '401 Unauthorized',
                     'API key invalid', 'ECONNRESET', 'connection refused', 'quota exhausted',
                     '余额不足', 'exceeded retry limit', 'Provider old is not configured',
                     'ProviderModelNotFoundError: providerID=old modelID=m',
                     'Unknown provider: removed', 'Model not found: old/m'):
            self.assertTrue(provider.error_is_provider(text), text)
        for text in ('tests failed', 'npm package not found', 'user cancelled', 'BLOCKED: decision needed',
                     'file not found: provider.json', 'model.py not found', 'unknown file model.py'):
            self.assertFalse(provider.error_is_provider(text), text)

    def test_codex_exact_main_resume_preserves_flags_and_drops_old_prompt(self):
        self.codex()
        path = self.write('main.jsonl', json.dumps({'type':'session_meta','payload':{
            'id':'01a1e211-6de4-7b12-a07f-217fd0c2cef4','cwd':str(self.project),'source':'cli'}})+'\n')
        command = provider.resume_command('codex', str(path), ['/tmp/bin/codex','--sandbox','workspace-write','old prompt'], self.project)
        self.assertEqual(command[0], '/tmp/bin/codex')
        self.assertIn('--no-daemon', command)
        self.assertIn('resume', command)
        self.assertNotIn('old prompt', command)
        self.assertIn('workspace-write', command)
        self.assertIn('01a1e211-6de4-7b12-a07f-217fd0c2cef4', command)
        meta = json.loads(path.read_text());meta['payload']['source']={'subagent':{}}
        path.write_text(json.dumps(meta)+'\n')
        with self.assertRaises(ValueError):
            provider.resume_command('codex', str(path), ['codex'], self.project)

    def test_claude_and_pi_exact_resume_reject_foreign_projects(self):
        for tool, record, flag in (
            ('claude',{'type':'user','cwd':str(self.project),'sessionId':'11111111-1111-4111-8111-111111111111'},'--resume'),
            ('pi',{'type':'session','cwd':str(self.project),'id':'11111111-1111-4111-8111-111111111111'},'--session')):
            path=self.write(tool+'.jsonl',json.dumps(record)+'\n')
            command=provider.resume_command(tool,str(path),[tool],self.project)
            self.assertIn(flag,command)
            record['cwd']=str(self.home/'other');path.write_text(json.dumps(record)+'\n')
            with self.assertRaises(ValueError):provider.resume_command(tool,str(path),[tool],self.project)

    def test_opencode_db_identity_is_checked_before_resume(self):
        path = self.home/'.local/share/opencode/opencode.db';path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE session_v2 (id TEXT,directory TEXT,time_updated INTEGER)')
            db.execute('INSERT INTO session_v2 VALUES (?,?,1)',('ses_one',str(self.project)))
            db.commit()
        command=provider.resume_command('opencode','ses_one',['opencode','--auto'],self.project)
        self.assertIn('--standalone',command)
        self.assertIn('--session',command)
        self.assertIn('ses_one',command)
        with self.assertRaises(ValueError):provider.resume_command('opencode','missing',['opencode'],self.project)
        command=provider.resume_command('opencode','ses_one',
            ['opencode','--auto','-s','old-id','--prompt','do not replay'],self.project)
        self.assertNotIn('old-id',command)
        self.assertNotIn('do not replay',command)
        self.assertEqual(command.count('--session'),1)
        self.assertEqual(command[-2:],['--prompt','continue'])

    def test_resume_last_is_replaced_with_verified_id_and_print_mode_is_refused(self):
        meta={'type':'session_meta','payload':{'id':'root','cwd':str(self.project),'source':'cli'}}
        path=self.write('resume.jsonl',json.dumps(meta)+'\n')
        command=provider.resume_command('codex',str(path),
            ['codex','-c','approval_policy="never"','-s','workspace-write','resume','--last','old task'],self.project)
        self.assertNotIn('--last',command)
        self.assertNotIn('old task',command)
        self.assertIn('approval_policy="never"',command)
        self.assertIn('workspace-write',command)
        self.assertEqual(command[-3:],['resume','root','continue'])
        for tool,record in [('claude',{'type':'user','sessionId':'root','cwd':str(self.project)}),
                            ('pi',{'type':'session','id':'root','cwd':str(self.project)})]:
            path=self.write(tool+'-print.jsonl',json.dumps(record)+'\n')
            with self.assertRaises(ValueError):
                provider.resume_command(tool,str(path),[tool,'-p','old task'],self.project)

    def test_jsonc_credentials_are_not_changed_by_comment_or_comma_stripping(self):
        self.write('.config/opencode/opencode.json', '''{
          // comment
          "model": "p/m", "provider": {"p": {"options": {
            "baseURL": "https://provider/path//value", "apiKey": "a,}b/*literal*/",},},},
        }''')
        data, _env = provider._effective('opencode', self.project)
        self.assertEqual(data['options']['apiKey'], 'a,}b/*literal*/')
        self.assertEqual(data['options']['baseURL'], 'https://provider/path//value')

    def test_malformed_config_shapes_fail_closed(self):
        for file, tool, data in (
                ('.claude/settings.json', 'claude', {'env':[]}),
                ('.pi/agent/settings.json', 'pi', {'defaultProvider':'p','defaultModel':'m'}),
                ('.config/opencode/opencode.json', 'opencode', {'model':'p/m','provider':[]})):
            self.write(file,data)
            if tool == 'pi':self.write('.pi/agent/models.json', {'providers':[]})
            self.assertFalse(provider.snapshot(tool,self.project)['recoverable'], tool)

    def test_large_session_uses_only_metadata_header_and_invalid_shape_is_rejected(self):
        meta={'type':'session_meta','payload':{'id':'root','cwd':str(self.project),'source':'cli'}}
        path=self.write('large.jsonl',json.dumps(meta)+'\n'+('x'*5*1024*1024))
        self.assertIn('root',provider.resume_command('codex',str(path),['codex'],self.project))
        path.write_text('{"type":"session_meta","payload":[]}\n')
        with self.assertRaises(ValueError):provider.resume_command('codex',str(path),['codex'],self.project)

    def test_zcode_multiple_providers_require_explicit_default(self):
        config={'config':{'providerOrder':['p','q'],'providerConfigRules':{'providerRules':[
            {'providerId':name,'config':{'api':{'baseUrl':'https://'+name},'access':{'apiKey':'secret'},'modelOrder':['m']}}
            for name in ('p','q')]}}}
        self.write('.zcode/v2/provider_config.json',config)
        self.assertFalse(provider.snapshot('zcode',self.project)['recoverable'])
        config['config']['defaultModelSelection']={'providerId':'q','modelId':'m'}
        self.write('.zcode/v2/provider_config.json',config)
        self.snap('zcode')
        self.assertNotIn('CODEXC_ZCODE_MODEL_SELECTION',provider.launch_environment('zcode',self.project))
        os.environ['CODEXC_PROVIDER_RELOADING']='1'
        env=provider.launch_environment('zcode',self.project)
        self.assertEqual(json.loads(env['CODEXC_ZCODE_MODEL_SELECTION']),{'providerId':'q','modelId':'m'})

    def test_native_capability_failure_is_closed_and_cached(self):
        executable=self.write('old-codex','#!/bin/sh\n')
        executable.chmod(0o700)
        with patch.object(provider.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'old help','')) as probe:
            for _ in range(2):
                with self.assertRaises(ValueError):VERIFY_CAPABILITY('codex',[str(executable)])
            self.assertEqual(probe.call_count,1)
        executable.write_text('#!/bin/sh\n# upgrade\n')
        with patch.object(provider.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'resume --no-daemon','')) as probe:
            VERIFY_CAPABILITY('codex',[str(executable)])
            self.assertEqual(probe.call_count,1)

    def zcode_selection_db(self):
        db_path=self.home/'zcode.sqlite'
        with closing(sqlite3.connect(db_path)) as db:
            db.executescript('CREATE TABLE session(id TEXT,directory TEXT,path TEXT);'
                             'CREATE TABLE session_entry(id TEXT,session_id TEXT,type TEXT,time_updated INT,data TEXT);')
            db.execute('INSERT INTO session VALUES (?,?,NULL)',('sess_test',str(self.project)))
            db.execute('INSERT INTO session_entry VALUES (?,?,?,?,?)',('one','sess_test','runtime/model_selection',1,
                json.dumps({'modelSelection':{'providerId':'old','modelId':'m'}})))
            db.commit()
        os.environ['ZCODE_SESSION_DB']=str(db_path)
        os.environ['CODEXC_ZCODE_MODEL_SELECTION']=json.dumps({'providerId':'new','modelId':'m'})
        return db_path

    def test_zcode_native_local_switch_must_persist_the_original_session_selection(self):
        db_path=self.zcode_selection_db()
        old_cwd=os.getcwd()
        self.addCleanup(os.chdir,old_cwd)
        os.chdir(self.project)
        def switch(command, **kwargs):
            self.assertEqual(command[command.index('--prompt')+1],'/model new/m')
            self.assertEqual(command[command.index('--resume')+1],'sess_test')
            with closing(sqlite3.connect(db_path)) as db:
                db.execute('UPDATE session_entry SET data=?,time_updated=2',
                    (json.dumps({'modelSelection':{'providerId':'new','modelId':'m'}}),))
                db.commit()
            kwargs['stdout'].write(json.dumps({'type':'result','sessionId':'sess_test','response':'Model switched to new/m (high).'}).encode())
            return subprocess.CompletedProcess(command,0)
        with patch.object(provider.subprocess,'run',side_effect=switch) as command:
            provider.prepare_zcode_session('sess_test','/tmp/zcode.cjs','yolo')
            self.assertEqual(command.call_count,1)
            # No repeated command when the durable session already uses it.
            provider.prepare_zcode_session('sess_test','/tmp/zcode.cjs','yolo')
            self.assertEqual(command.call_count,1)

    def test_zcode_claimed_model_switch_without_persistence_is_rejected(self):
        self.zcode_selection_db()
        old_cwd=os.getcwd()
        self.addCleanup(os.chdir,old_cwd)
        os.chdir(self.project)
        def switch(command, **kwargs):
            kwargs['stdout'].write(json.dumps({'type':'result','sessionId':'sess_test','response':'Model switched to new/m (high).'}).encode())
            return subprocess.CompletedProcess(command,0)
        with patch.object(provider.subprocess,'run',side_effect=switch):
            with self.assertRaises(ValueError):provider.prepare_zcode_session('sess_test','/tmp/zcode.cjs','yolo')

    def test_zcode_needs_reload_only_for_verified_saved_session_difference(self):
        db_path=self.zcode_selection_db()
        session=self.project/'.codingkeeper/zcode-session-id'
        session.parent.mkdir();session.write_text('sess_test\n')
        config={'config':{'providerOrder':['new'],'defaultModelSelection':{'providerId':'new','modelId':'m'},
            'providerConfigRules':{'providerRules':[{'providerId':'new','config':{
                'api':{'baseUrl':'https://new'},'access':{'apiKey':'secret'},'modelOrder':['m']}}]}}}
        self.write('.zcode/v2/provider_config.json',config)
        command=[sys.executable,str(ROOT/'ck-provider.py'),'needs-reload','zcode']
        def probe():return subprocess.run(command,cwd=self.project,capture_output=True,timeout=5)
        self.assertEqual(probe().returncode,0)
        session.rename(Path(str(session)+'.retry'))
        self.assertEqual(probe().returncode,0)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('UPDATE session_entry SET data=?',(json.dumps({'modelSelection':{'providerId':'new','modelId':'m'}}),))
            db.commit()
        self.assertEqual(probe().returncode,1)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('UPDATE session SET directory=?',(str(self.home/'foreign'),));db.commit()
        self.assertEqual(probe().returncode,1)
        self.assertNotIn(b'secret',probe().stderr)

    def test_opencode_native_model_switch_requires_schema_and_durable_same_session(self):
        self.write('.config/opencode/opencode.json',{'model':'new/m','provider':{'new':{'options':{'baseURL':'https://new'}}}})
        db_path=self.home/'.local/share/opencode/opencode.db';db_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('CREATE TABLE session_v2(id TEXT,directory TEXT,model TEXT)')
            db.execute('INSERT INTO session_v2 VALUES (?,?,?)',('ses_test',str(self.project),json.dumps({'providerID':'old','id':'m'})))
            db.commit()
        calls=[]
        def native(command,**kwargs):
            calls.append(command)
            if command[-1]=='--help':return b'--standalone --param --data'
            if command[-2:]==['GET','/openapi.json']:
                return json.dumps({'paths':{'/api/session/{sessionID}/model':{'post':{'operationId':'session.switchModel'}}}}).encode()
            self.assertIn('session.switchModel',command)
            self.assertIn('sessionID=ses_test',command)
            payload=json.loads(command[command.index('--data')+1])
            self.assertEqual(payload,{'model':{'providerID':'new','id':'m'}})
            self.assertEqual(Path(kwargs['cwd']),self.project)
            with closing(sqlite3.connect(db_path)) as db:
                db.execute('UPDATE session_v2 SET model=? WHERE id=?',(json.dumps(payload['model']),'ses_test'))
                db.commit()
            return b''
        with patch.object(provider,'_native_output',side_effect=native):
            provider.prepare_resume('opencode','ses_test',['opencode','--auto'],self.project)
        self.assertEqual(len(calls),3)
        with patch.object(provider,'_native_output',return_value=b'{}'):
            # Already persisted selection needs no further native command.
            provider.prepare_resume('opencode','ses_test',['opencode'],self.project)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('UPDATE session_v2 SET model=?',(json.dumps({'providerID':'old','id':'m'}),));db.commit()
        with patch.object(provider,'_native_output',return_value=b'{}') as native:
            with self.assertRaises(ValueError):provider.prepare_resume('opencode','ses_test',['opencode'],self.project)
            self.assertEqual(native.call_count,1)
        # A successful API exit without a durable selection update is rejected.
        def no_persist(command,**kwargs):
            if command[-1]=='--help':return b'--standalone --param --data'
            return json.dumps({'paths':{'/api/session/{sessionID}/model':{'post':{'operationId':'session.switchModel'}}}}).encode() if command[-1]=='/openapi.json' else b''
        with patch.object(provider,'_native_output',side_effect=no_persist):
            with self.assertRaises(ValueError):provider.prepare_resume('opencode','ses_test',['opencode'],self.project)

    def test_native_api_output_timeout_and_private_child_cleanup_are_bounded(self):
        pidfile=self.home/'native-child.pid'
        code=('import os,subprocess,sys;from pathlib import Path;'
              'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
              'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
              'Path(sys.argv[1]).write_text(str(child.pid));print("ok")')
        self.assertEqual(provider._native_output([sys.executable,'-c',code,str(pidfile)]),b'ok\n')
        result=subprocess.run(['/bin/ps','-p',pidfile.read_text(),'-o','stat='],capture_output=True,text=True,timeout=3)
        self.assertTrue(not result.stdout.strip() or result.stdout.strip().startswith('Z'),result.stdout)
        with self.assertRaises(ValueError):
            provider._native_output([sys.executable,'-c','import time;time.sleep(60)'],timeout=.1)
        with self.assertRaises(ValueError):
            provider._native_output([sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*5000000)'])

    def test_zcode_removed_provider_failure_is_classified_without_matching_missing_files(self):
        cjs=self.write('missing-provider.cjs','// fixture')
        binary=self.home/'missing-bin';binary.mkdir()
        (binary/'python3').symlink_to(sys.executable)
        fake=self.write('missing-bin/node','#!'+sys.executable+'\nimport os,sys\nprint(os.environ["FAKE_ERROR"],file=sys.stderr)\nsys.exit(1)\n')
        fake.chmod(0o700)
        os.environ.update(PATH=str(binary)+os.pathsep+os.defpath,ZCODE_CJS=str(cjs),
                          ZCODE_SESSION_FILE=str(self.project/'missing-session'))
        for error,expected in [('Provider old is not configured on this machine','auth'),
                               ('provider-not-found: Provider unavailable','auth'),
                               ('Model not found','auth'),('File not found: model.py','unknown')]:
            os.environ['FAKE_ERROR']=error
            result=subprocess.run(['/bin/bash',str(ROOT/'codexc-zcode-worker')],input='task',text=True,
                                  capture_output=True,cwd=self.project,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('CK_ERROR_CLASS: '+expected,result.stdout,error+'\n'+result.stdout+result.stderr)

    def test_zcode_worker_switches_model_then_runs_task_on_exact_same_session(self):
        self.zcode_selection_db()
        session=self.project/'session-id';session.write_text('sess_test\n')
        cjs=self.write('zcode.cjs','// fake CLI')
        binary=self.home/'bin';binary.mkdir()
        (binary/'python3').symlink_to(sys.executable)
        fake=self.write('bin/node','#!'+sys.executable+'\n'+'''import json,os,sqlite3,sys
from pathlib import Path
args=sys.argv[2:]
prompt=args[args.index('--prompt')+1]
sid=args[args.index('--resume')+1]
with open(os.environ['FAKE_CALLS'],'a') as f:f.write(json.dumps({'sid':sid,'prompt':prompt})+'\\n')
if prompt.startswith('/model '):
 if os.environ.get('FAKE_SWITCH_FAIL')=='1':
  response='Unable to switch model'
 else:
  db=sqlite3.connect(os.environ['ZCODE_SESSION_DB'])
  db.execute('UPDATE session_entry SET data=?,time_updated=2',(json.dumps({'modelSelection':{'providerId':'new','modelId':'m'}}),))
  db.commit();db.close()
  response='Model switched to new/m (high).'
else:response='TASK_RESULT: DONE'
print(json.dumps({'type':'result','sessionId':sid,'response':response}))
''')
        fake.chmod(0o700)
        os.environ.update(PATH=str(binary)+os.pathsep+os.defpath,ZCODE_CJS=str(cjs),ZCODE_SESSION_FILE=str(session),
                          FAKE_CALLS=str(self.home/'calls.jsonl'))
        result=subprocess.run(['/bin/bash',str(ROOT/'codexc-zcode-worker')],input='original task',text=True,
                              capture_output=True,cwd=self.project,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('TASK_RESULT: DONE',result.stdout)
        calls=[json.loads(line) for line in (self.home/'calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls,[{'sid':'sess_test','prompt':'/model new/m'},{'sid':'sess_test','prompt':'original task'}])
        self.assertEqual(session.read_text(),'sess_test\n')
        # A failed native switch must never feed the original task to the old provider.
        with closing(sqlite3.connect(os.environ['ZCODE_SESSION_DB'])) as db:
            db.execute('UPDATE session_entry SET data=?',(json.dumps({'modelSelection':{'providerId':'old','modelId':'m'}}),))
            db.commit()
        (self.home/'calls.jsonl').write_text('')
        os.environ['FAKE_SWITCH_FAIL']='1'
        result=subprocess.run(['/bin/bash',str(ROOT/'codexc-zcode-worker')],input='must stay queued',text=True,
                              capture_output=True,cwd=self.project,timeout=10)
        self.assertNotEqual(result.returncode,0)
        calls=[json.loads(line) for line in (self.home/'calls.jsonl').read_text().splitlines()]
        self.assertEqual(calls,[{'sid':'sess_test','prompt':'/model new/m'}])
        self.assertEqual(session.read_text(),'sess_test\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
