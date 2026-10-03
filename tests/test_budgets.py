import dataclasses
import unittest
from globdelta import Limits, compare_policies, explain_path, parse_policy
from globdelta.budget import Budget, LimitExceeded
from globdelta.nfa import Matcher, compile_policy

class BudgetTests(unittest.TestCase):
    def test_parser_allocation_limits_at_boundary(self):
        for field, threshold in [('input_bytes',1),('line_bytes',1),('rules',1),('ast_items',2)]:
            for value in (threshold-1,threshold,threshold+1):
                result=parse_policy(b'a',Limits(**{field:value}))
                self.assertEqual(result.policy is not None,value>=threshold,(field,value,result))
                if value<threshold:self.assertIsNotNone(result.stop)

    def test_nfa_state_and_edge_boundaries(self):
        p=parse_policy(b'/a').policy
        for field,threshold in [('nfa_states',3),('nfa_edges',2)]:
            for value in (threshold-1,threshold,threshold+1):
                b=Budget(Limits(**{field:value}))
                if value<threshold:
                    with self.assertRaises(LimitExceeded):compile_policy(p,b)
                else:compile_policy(p,b)

    def test_diagnostics_limit_is_resource_failure(self):
        self.assertIsNotNone(parse_policy(b'[',Limits(diagnostics=0)).stop)
        result=explain_path(b'',b'.git',Limits(diagnostics=0))
        self.assertEqual(result.result,'inconclusive')
        self.assertEqual(result.stop.limit.name,'diagnostics')

    def test_api_internal_failure_returns_error(self):
        from unittest.mock import patch
        with patch('globdelta.api.search',side_effect=AssertionError('sentinel')):
            report=compare_policies(b'',b'')
        self.assertEqual(report.result,'error')
        self.assertEqual(report.stop.reason,'error')
        self.assertFalse(report.assessment_complete)
        self.assertEqual(report.newly_ignored.status,'unknown')

    def test_checked_budget_configuration(self):
        for kw in ({'rules':-1},{'rules':True},{'work':2**63},{'report_bytes':8191}):
            with self.assertRaises(ValueError):Limits(**kw)

    def test_all_input_buffers_are_reserved_before_first_parse(self):
        limit=3*Limits().report_bytes+10002
        r=compare_policies(b'abc',b'x'*10000,Limits(payload_bytes=limit))
        self.assertEqual(r.stop.reason,'limit')
        self.assertEqual(r.stop.limit.phase,'input_buffers')

    def test_query_buffer_is_accounted_before_analysis(self):
        r=explain_path(b'',b'a'*1000,Limits(payload_bytes=3*Limits().report_bytes+999))
        self.assertEqual(r.stop.reason,'limit')
        self.assertEqual(r.stop.limit.phase,'input_buffers')

    def test_report_transient_reserve_is_precharged(self):
        r=compare_policies(b'',b'',Limits(payload_bytes=2*Limits().report_bytes))
        self.assertEqual(r.stop.reason,'limit')
        self.assertEqual(r.stop.limit.phase,'report_reserve')

    def test_failed_report_reserve_uses_small_emergency_envelope(self):
        from globdelta.report import to_json
        r=explain_path(b'',b'a'*1_100_000,Limits(payload_bytes=0))
        self.assertEqual(r.stop.limit.name,'payload_bytes')
        self.assertEqual(r.stop.limit.phase,'report_reserve')
        self.assertEqual(r.query,b'')
        self.assertLessEqual(len(to_json(r)),8192)
        self.assertTrue(any('omitted' in d.message for d in r.diagnostics))

    def test_payload_failure_never_claims_equivalence(self):
        r=compare_policies(b'',b'',Limits(payload_bytes=0))
        self.assertEqual(r.result,'inconclusive')
        self.assertEqual(r.stop.limit.name,'payload_bytes')
        self.assertFalse(r.graph_exhausted)

if __name__=='__main__':unittest.main()
