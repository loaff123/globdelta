"""Bounded reports and read-only CLI integration contract."""
import dataclasses
import hashlib
import importlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from globdelta.budget import Limits
from globdelta.model import (BlockedAncestor, Diagnostic, Direction, Explanation, Input,
                            LimitStop, Report, Rule, Span, Step, Stop, Witness)


def validate_schema_subset(value, schema, root):
    """The exact keywords used by report.schema.json, with no test dependency.

    Full Draft 2020-12 validation is additionally run in release verification.
    Unsupported schema keywords fail loudly rather than weakening validation.
    """
    supported = {'$schema','$id','title','$defs','$ref','type','const','enum','properties',
                 'required','additionalProperties','items','minItems','maxItems',
                 'uniqueItems','minimum','pattern','allOf','anyOf','oneOf','not','if','then'}
    assert not set(schema) - supported, set(schema) - supported
    if '$ref' in schema:
        target = root
        for part in schema['$ref'].split('/')[1:]:
            target = target[part]
        validate_schema_subset(value,target,root)
    kind = schema.get('type')
    if kind:
        matches = {'null': value is None, 'boolean': type(value) is bool,
                   'integer': type(value) is int, 'string': isinstance(value,str),
                   'object': isinstance(value,dict), 'array': isinstance(value,list)}
        assert matches[kind], (kind,value)
    if 'const' in schema:
        assert value == schema['const'] and (type(value) is bool) == (type(schema['const']) is bool)
    if 'enum' in schema:
        assert any(value == x and (type(value) is bool) == (type(x) is bool) for x in schema['enum'])
    if type(value) is int and 'minimum' in schema:
        assert value >= schema['minimum']
    if isinstance(value,str) and 'pattern' in schema:
        assert re.search(schema['pattern'],value)
    if isinstance(value,dict):
        assert set(schema.get('required',())) <= set(value)
        properties = schema.get('properties',{})
        for key,item in value.items():
            if key in properties:
                validate_schema_subset(item,properties[key],root)
            elif schema.get('additionalProperties') is False:
                raise AssertionError('unexpected property ' + key)
            elif isinstance(schema.get('additionalProperties'),dict):
                validate_schema_subset(item,schema['additionalProperties'],root)
    if isinstance(value,list):
        assert len(value) >= schema.get('minItems',0)
        assert len(value) <= schema.get('maxItems',len(value))
        if schema.get('uniqueItems'):
            assert len({json.dumps(x,sort_keys=True) for x in value}) == len(value)
        if 'items' in schema:
            for item in value:
                validate_schema_subset(item,schema['items'],root)
    def accepts(branch):
        try:
            validate_schema_subset(value,branch,root)
            return True
        except AssertionError:
            return False
    for branch in schema.get('allOf',()):
        validate_schema_subset(value,branch,root)
    if 'anyOf' in schema:
        assert any(accepts(branch) for branch in schema['anyOf'])
    if 'oneOf' in schema:
        assert sum(accepts(branch) for branch in schema['oneOf']) == 1
    if 'not' in schema:
        assert not accepts(schema['not'])
    if 'if' in schema and accepts(schema['if']):
        validate_schema_subset(value,schema.get('then',{}),root)


def report_module():
    try:
        return importlib.import_module('globdelta.report')
    except ImportError:
        return None


def empty_explanation(ignored=False):
    return Explanation(ignored, 'default', None, None, (), (), True, True, ())


def equivalent(limits=None):
    return Report('diff', tuple(Input(role, role, 0, True, hashlib.sha256(b'').hexdigest(), 0)
                              for role in ('before', 'after')),
                  'equivalent', True, True, limits or Limits(), (), Stop('exhausted'),
                  newly_ignored=Direction('absent'), newly_included=Direction('absent'))


class ReportTests(unittest.TestCase):
    def module(self):
        module = report_module()
        self.assertIsNotNone(module, 'bounded report module has not been implemented')
        return module

    def assertSchema(self, payload):
        schema = json.loads((Path(__file__).parents[1] / 'schemas/report.schema.json').read_text())
        validate_schema_subset(payload, schema, schema)

    def test_stable_versioned_complete_json(self):
        module = self.module()
        r = equivalent()
        encoded = module.to_json(r)
        payload = json.loads(encoded)
        self.assertEqual(list(payload), ['schema_version', 'tool', 'profile', 'command',
                         'inputs', 'result', 'assessment_complete', 'graph_exhausted',
                         'directions', 'limits', 'usage', 'stop', 'diagnostics'])
        self.assertEqual(payload['tool'], {'name':'GlobDelta', 'version':'0.1.0'})
        self.assertEqual(payload['profile']['id'], 'git-root-ascii-v1')
        self.assertEqual(set(payload['limits']), {f.name for f in dataclasses.fields(Limits)})
        self.assertEqual(module.to_json(r), encoded)
        self.assertEqual(module.exit_code(r), 0)
        self.assertSchema(payload)

    def test_resource_stop_takes_precedence_over_known_witness(self):
        module = self.module()
        w = Witness(b'a', empty_explanation(), empty_explanation(True))
        r = dataclasses.replace(equivalent(), result='different', assessment_complete=False,
                    graph_exhausted=False, newly_ignored=Direction('found', w),
                    newly_included=Direction(), stop=Stop('limit', LimitStop('work','search',1,1,1)))
        self.assertEqual(module.exit_code(r), 4)
        payload = json.loads(module.to_json(r))
        self.assertEqual(payload['directions']['newly_ignored']['witness']['path'], 'a')
        self.assertSchema(payload)

    def test_exit_codes_for_every_result(self):
        module = self.module()
        for result, code in [('unsupported',3), ('error',5), ('inconclusive',4)]:
            r = dataclasses.replace(equivalent(), result=result, assessment_complete=False,
                    graph_exhausted=False, newly_ignored=Direction(), newly_included=Direction(),
                    stop=Stop({'unsupported':'unsupported','error':'error','inconclusive':'limit'}[result]))
            self.assertEqual(module.exit_code(r),code)
        for ignored in (False, True):
            r = Report('explain', (equivalent().inputs[0],), 'explained', True, None,
                       Limits(), (), Stop('explained'), query=b'a', explanation=empty_explanation(ignored))
            self.assertEqual(module.exit_code(r),0)

    def test_optional_trace_shrinks_without_erasing_cause(self):
        module = self.module()
        rule = Rule(1, Span('policy',2,1,3,2,4), b'a/', False, True, False, ())
        exp = Explanation(True, 'blocked_ancestor', 1, BlockedAncestor(1,1), (rule,),
                   tuple(Step(i+1,'directory',(1,),1,True) for i in range(300)), True,False,())
        r = Report('explain', (Input('policy','p',5,True,hashlib.sha256(b'\na/\n').hexdigest(),1),),
                   'explained',True,None,Limits(report_bytes=8192),(),Stop('explained'),query=b'a/b',explanation=exp)
        fitted = module.finalize_report(r)
        self.assertEqual(fitted.result,'explained')
        self.assertFalse(fitted.explanation.trace_complete)
        self.assertEqual(fitted.explanation.winning_rule_id,1)
        payload = json.loads(module.to_json(fitted))
        self.assertLessEqual(len(module.to_json(fitted).encode()),8192)
        self.assertEqual(payload['explanation']['rule_table'][0]['line'],2)
        self.assertEqual(payload['explanation']['first_blocked_ancestor']['prefix_end'],1)
        self.assertSchema(payload)

    def test_mandatory_witness_overflow_returns_explicit_bounded_resource_envelope(self):
        module = self.module()
        witness = Witness(b'a'*20000, empty_explanation(), empty_explanation(True))
        r = dataclasses.replace(equivalent(Limits(report_bytes=8192)), result='different',
                    newly_ignored=Direction('found', witness))
        fitted = module.finalize_report(r)
        self.assertEqual(module.exit_code(fitted),4)
        self.assertFalse(fitted.assessment_complete)
        self.assertFalse(fitted.graph_exhausted)
        payload = json.loads(module.to_json(fitted))
        self.assertLessEqual(len(module.to_json(fitted).encode()),8192)
        self.assertEqual(payload['stop']['limit']['name'],'report_bytes')
        self.assertIn('known findings', ' '.join(x['message'] for x in payload['diagnostics']['items']))
        self.assertSchema(payload)

    def test_reserved_resource_diagnostic_survives_zero_diagnostic_limit(self):
        module = self.module()
        r = equivalent(Limits(report_bytes=8192,diagnostics=0))
        r = dataclasses.replace(r, inputs=(dataclasses.replace(r.inputs[0],label='a'*20000),r.inputs[1]))
        payload = json.loads(module.to_json(module.finalize_report(r)))
        self.assertTrue(payload['diagnostics']['items'])
        self.assertIn('known findings',payload['diagnostics']['items'][0]['message'])

    def test_all_status_combinations_validate_against_schema(self):
        module = self.module()
        from globdelta.api import compare_policies, explain_path
        reports = [compare_policies(b'',b''), compare_policies(b'a',b'b'),
                   compare_policies(b'',b'a'), compare_policies(b'a',b''),
                   compare_policies(b'',b'*',Limits(transitions=95)),
                   compare_policies(b'',b'*',Limits(transitions=0)),
                   compare_policies(b'a**b',b''), explain_path(b'a',b'a'),
                   explain_path(b'a',b'b'), explain_path(b'',b'.git/a'),
                   explain_path(b'a',b'a',Limits(reference_work=0))]
        for report in reports:
            self.assertSchema(json.loads(module.to_json(report)))
        malformed = json.loads(module.to_json(equivalent()))
        malformed['directions']['newly_ignored']['status']='unknown'
        with self.assertRaises(AssertionError):
            self.assertSchema(malformed)

    def test_huge_unicode_labels_are_bounded_and_disclosed(self):
        module = self.module()
        r = equivalent(Limits(report_bytes=8192))
        r = dataclasses.replace(r,inputs=(dataclasses.replace(r.inputs[0],label='\U0001f600'*20000),r.inputs[1]))
        result = module.finalize_report(r)
        self.assertEqual(module.exit_code(result),4)
        self.assertLessEqual(len(module.to_json(result).encode()),8192)
        self.assertSchema(json.loads(module.to_json(result)))
        self.assertEqual(result.inputs[0].sha256,r.inputs[0].sha256)

    def test_bounded_text_with_large_query_and_blocked_ancestor(self):
        module = self.module()
        from globdelta.api import explain_path
        r = explain_path(b'*/', b'a'*4094+b'/b', Limits(report_bytes=8192))
        encoded = module.to_text(r)
        self.assertLessEqual(len(encoded.encode('ascii')),8192)
        self.assertIn('first blocking ancestor',encoded)
        self.assertEqual(module.exit_code(r),0)

    def test_report_limit_counts_terminal_newline(self):
        module = self.module()
        result = module.to_json(equivalent())
        self.assertTrue(result.endswith('\n'))

    def test_text_escapes_labels_diagnostics_and_causal_rules(self):
        module = self.module()
        r = equivalent()
        r = dataclasses.replace(r,inputs=(dataclasses.replace(r.inputs[0],label='bad\x1b[31m\nname'),r.inputs[1]),
                                diagnostics=(Diagnostic('bad','message\r\x1b[2J'),))
        text = module.to_text(r)
        self.assertNotIn('\x1b',text)
        self.assertNotIn('\r',text)
        self.assertIn('\\u001b',text)
        self.assertIn('equivalent within git-root-ascii-v1',text)
        self.assertNotIn('bad\n',text)


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        try:
            from globdelta.cli import main
        except ImportError:
            self.fail('read-only CLI has not been implemented')
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):
            try: code=main(list(arguments))
            except SystemExit as e: code=e.code
        return code,out.getvalue(),err.getvalue()

    def test_version_and_invalid_limits(self):
        self.assertEqual(self.run_cli('--version')[:2],(0,'globdelta 0.1.0\n'))
        for assignment in ('unknown=1','work=-1','work=1.5','work','report_bytes=8191'):
            self.assertEqual(self.run_cli('diff','a','b','--limit',assignment)[0],2,assignment)

    def test_json_explain_and_hash_exact_raw_input(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; raw=b'build/\r\n!build/a\r\n'; p.write_bytes(raw)
            code,out,err=self.run_cli('explain',str(p),'build/a','--format','json')
            self.assertEqual(code,0,err)
            result=json.loads(out)
            self.assertEqual(result['result'],'explained')
            self.assertTrue(result['explanation']['ignored'])
            self.assertEqual(result['inputs'][0]['label'],str(p))
            self.assertEqual(result['inputs'][0]['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(p.read_bytes(),raw)

    def test_cli_retains_real_read_metadata_when_first_parse_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; q=Path(d)/'q'
            p.write_bytes(b'a**b'); q.write_bytes(b'valid\r\n')
            code,out,err=self.run_cli('diff',str(p),str(q),'--format','json')
            self.assertEqual(code,3,err)
            result=json.loads(out)
            self.assertTrue(result['inputs'][1]['complete_read'])
            self.assertEqual(result['inputs'][1]['raw_bytes_read'],7)
            self.assertEqual(result['inputs'][1]['sha256'],hashlib.sha256(b'valid\r\n').hexdigest())
            self.assertIsNone(result['inputs'][1]['rule_count'])

    def test_missing_input_emits_json_error_with_incomplete_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            code,out,err=self.run_cli('diff',str(Path(d)/'missing'),str(Path(d)/'other'),'--format','json')
            self.assertEqual(code,5,err)
            payload=json.loads(out)
            self.assertEqual(payload['result'],'error')
            self.assertFalse(payload['inputs'][0]['complete_read'])
            self.assertIsNone(payload['inputs'][0]['sha256'])
            self.assertEqual(len(payload['inputs']),2)

    def test_input_limit_is_resource_not_syntax_and_reads_only_sentinel(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; q=Path(d)/'q'; p.write_bytes(b'x'*100000); q.write_bytes(b'')
            code,out,err=self.run_cli('diff',str(p),str(q),'--format','json','--limit','input_bytes=5')
            self.assertEqual(code,4,err)
            data=json.loads(out)
            self.assertEqual(data['inputs'][0]['raw_bytes_read'],6)
            self.assertFalse(data['inputs'][0]['complete_read'])
            self.assertIsNone(data['inputs'][0]['sha256'])
            self.assertIsNone(data['inputs'][0]['rule_count'])
            self.assertEqual(data['stop']['limit']['name'],'before.input_bytes')

    def test_oversize_input_does_not_prefetch_beyond_the_single_sentinel(self):
        import builtins
        from unittest.mock import patch
        real_open = builtins.open
        positions = []
        class ObservedFile:
            def __init__(self,stream): self.stream=stream
            def __enter__(self): return self
            def read(self,size): return self.stream.read(size)
            def __exit__(self,*args):
                underlying=getattr(self.stream,'raw',self.stream)
                positions.append(underlying.tell())
                return self.stream.__exit__(*args)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'x'*100000)
            def observed_open(*args,**kwargs): return ObservedFile(real_open(*args,**kwargs))
            with patch('globdelta.cli.open',observed_open,create=True):
                code,out,err=self.run_cli('diff',str(p),str(p),'--format','json','--limit','input_bytes=5')
            self.assertEqual(code,4,err)
            self.assertEqual(positions,[6])

    def test_output_is_exclusive_and_never_overwrites_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=root/'p'; q=root/'q'; p.write_bytes(b''); q.write_bytes(b'')
            output=root/'report.json'
            code,out,err=self.run_cli('diff',str(p),str(q),'--format','json','--output',str(output))
            self.assertEqual(code,0,err)
            self.assertEqual(out,'')
            self.assertEqual(json.loads(output.read_text())['result'],'equivalent')
            original=output.read_bytes()
            code,out,err=self.run_cli('diff',str(p),str(q),'--format','json','--output',str(output))
            self.assertEqual(code,5)
            self.assertEqual(output.read_bytes(),original)
            self.assertEqual(json.loads(err)['result'],'error')
            for target in (p, root/'symlink', root/'hardlink'):
                if target.name=='symlink': target.symlink_to(p)
                if target.name=='hardlink': os.link(p,target)
                code,out,err=self.run_cli('diff',str(p),str(q),'--format','json','--output',str(target))
                self.assertEqual(code,5)
                self.assertEqual(p.read_bytes(),b'')

    def test_report_reserve_failure_uses_fixed_small_envelope_before_input_reads(self):
        code,out,err=self.run_cli('explain','missing-'+'p'*100000,'q'*1100000,
                                 '--format','json','--limit','payload_bytes=0','--limit','diagnostics=0')
        self.assertEqual(code,4,err)
        self.assertLessEqual(len(out.encode('ascii')),8192)
        result=json.loads(out)
        self.assertEqual(result['stop']['limit']['name'],'payload_bytes')
        self.assertEqual(result['stop']['limit']['phase'],'report_reserve')
        self.assertEqual(result['inputs'][0]['raw_bytes_read'],0)
        self.assertFalse(result['inputs'][0]['complete_read'])
        self.assertEqual(result['query']['path'],'')
        self.assertIn('omitted',result['diagnostics']['items'][0]['message'])

    def test_query_encoding_is_precharged_before_input_reads(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'')
            code,out,err=self.run_cli('explain',str(p),'q'*300,'--format','json',
                             '--limit','report_bytes=8192','--limit','payload_bytes=24676')
            self.assertEqual(code,4,err)
            result=json.loads(out)
            self.assertEqual(result['stop']['limit']['phase'],'query_encoding')
            self.assertEqual(result['inputs'][0]['raw_bytes_read'],0)
            self.assertEqual(result['query']['path'],'')

    def test_query_retention_is_charged_during_input_buffering(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'#'+b'x'*99)
            code,out,err=self.run_cli('explain',str(p),'q'*200,'--format','json',
                             '--limit','report_bytes=8192','--limit','payload_bytes=24876')
            self.assertEqual(code,4,err)
            result=json.loads(out)
            self.assertEqual(result['stop']['limit']['phase'],'input_read')
            self.assertLessEqual(result['inputs'][0]['raw_bytes_read'],33)

    def test_output_failure_keeps_io_error_when_original_query_cannot_fit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'')
            code,out,err=self.run_cli('explain',str(p),'a'*9000,'--format','json',
                             '--limit','report_bytes=8192','--limit','diagnostics=0','--output',str(p))
            self.assertEqual(code,5)
            self.assertEqual(out,'')
            result=json.loads(err)
            self.assertEqual(result['result'],'error')
            self.assertEqual(result['stop']['reason'],'error')
            self.assertEqual(result['diagnostics']['items'][0]['code'],'io_error')
            self.assertIn('omitted',result['diagnostics']['items'][0]['message'])
            self.assertLessEqual(len(err.encode('ascii')),8192)
            self.assertEqual(p.read_bytes(),b'')

    def test_exit_status_is_resolved_before_report_materialization(self):
        from globdelta import cli
        from unittest.mock import patch
        calls=[]
        original_exit,original_json=cli.exit_code,cli.to_json
        def measured_exit(report):
            calls.append('status')
            return original_exit(report)
        def measured_json(report):
            calls.append('render')
            return original_json(report)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'')
            with patch.object(cli,'exit_code',measured_exit),patch.object(cli,'to_json',measured_json):
                code,out,err=self.run_cli('diff',str(p),str(p),'--format','json')
            self.assertEqual(code,0,err)
            self.assertEqual(json.loads(out)['result'],'equivalent')
            self.assertEqual(calls,['status','render'])

    def test_argparse_diagnostics_escape_control_characters(self):
        code,out,err=self.run_cli('diff','a','b','evil\x1b[31m')
        self.assertEqual(code,2)
        self.assertNotIn('\x1b',err)
        self.assertIn('evil',err)

    def test_closed_stdout_pipe_returns_io_exit_without_shutdown_traceback(self):
        env=dict(os.environ); env['PYTHONPATH']=str(Path(__file__).parents[1]/'src')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p'; p.write_bytes(b'')
            reader,writer=os.pipe()
            os.close(reader)
            try:
                result=subprocess.run([sys.executable,'-m','globdelta','diff',str(p),str(p),
                              '--format','json'],stdout=writer,stderr=subprocess.PIPE,text=True,env=env)
            finally:
                os.close(writer)
            self.assertEqual(result.returncode,5,result.stderr)
            self.assertNotIn('Traceback',result.stderr)
            self.assertEqual(json.loads(result.stderr)['result'],'error')

    def test_module_invocation_and_runtime_import_safety(self):
        env=dict(os.environ); env['PYTHONPATH']=str(Path(__file__).parents[1]/'src')
        result=subprocess.run([sys.executable,'-m','globdelta','--version'],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'globdelta 0.1.0\n')
        probe='import globdelta.cli,sys; assert not any(x in sys.modules for x in ("subprocess","socket","urllib.request","http.client"))'
        checked=subprocess.run([sys.executable,'-c',probe],capture_output=True,text=True,env=env)
        self.assertEqual(checked.returncode,0,checked.stderr)


if __name__=='__main__': unittest.main()
