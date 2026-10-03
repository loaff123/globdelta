import dataclasses
import unittest
from globdelta import Limits, compare_policies, explain_path, parse_policy

class APITests(unittest.TestCase):
    def test_result_invariants(self):
        for a,b,kw,expected in [(b'',b'',{},'equivalent'),(b'a',b'b',{},'different'),(b'',b'*',{'transitions':95},'different'),(b'',b'*',{'transitions':0},'inconclusive'),(b'a**b',b'',{},'unsupported')]:
            r=compare_policies(a,b,Limits(**kw))
            self.assertEqual(r.result,expected)
            states=(r.newly_ignored.status,r.newly_included.status)
            self.assertEqual(r.assessment_complete,all(x!='unknown' for x in states))
            self.assertEqual(r.result=='equivalent',states==('absent','absent'))
            self.assertEqual(r.result=='different','found' in states)
            with self.assertRaises(dataclasses.FrozenInstanceError):r.result='equivalent'

    def test_explain_and_scope_errors(self):
        r=explain_path(b'a/\n!a/b',b'a/b')
        self.assertEqual(r.result,'explained')
        self.assertTrue(r.explanation.ignored)
        self.assertTrue(r.assessment_complete)
        self.assertEqual(r.query,b'a/b')
        for path in (b'.git/x',b'.gitignore/x',b'a\x00'):
            r=explain_path(b'',path)
            self.assertEqual(r.result,'unsupported')
            self.assertEqual(r.diagnostics[0].location.role,'path')
        for path in (b'.gitignore',b'a/.gitignore/x'):
            self.assertEqual(explain_path(b'',path).result,'explained')

    def test_invalid_query_points_to_first_bad_component(self):
        for path, offset in [(b'ok/../x',3),(b'ok//x',3),(b'ok/.git/x',3),(b'ok/../x\x00',3),(b'ok/',2),(b'',0)]:
            r=explain_path(b'',path)
            self.assertEqual(r.diagnostics[0].location.byte_start,offset,path)
            self.assertEqual(r.diagnostics[0].location.column_start,offset+1,path)

    def test_input_metadata_hashes_and_incomplete(self):
        import hashlib
        r=compare_policies(b'a\r\n',b'a\n')
        self.assertEqual(r.inputs[0].sha256,hashlib.sha256(b'a\r\n').hexdigest())
        self.assertEqual(r.inputs[0].rule_count,1)
        r=compare_policies(b'ab',b'',Limits(input_bytes=1))
        self.assertEqual(r.result,'inconclusive')
        self.assertFalse(r.inputs[0].complete_read)
        self.assertIsNone(r.inputs[0].sha256)
        self.assertIsNone(r.inputs[0].rule_count)

    def test_trace_can_truncate_without_false_decision(self):
        r=explain_path(b'a/\n!a\n*/b',b'a/b',Limits(explanation_steps=0,explanation_matches=0))
        self.assertEqual(r.result,'explained')
        self.assertTrue(r.explanation.ignored)
        self.assertFalse(r.explanation.trace_complete)
        self.assertEqual(r.explanation.winning_rule_id,3)
        self.assertEqual([x.index for x in r.explanation.rule_table],[3])

if __name__=='__main__':unittest.main()
