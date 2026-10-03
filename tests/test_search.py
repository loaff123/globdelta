import dataclasses
import itertools
import unittest
from globdelta.budget import Budget, Limits
from globdelta.parse import parse_policy
from globdelta.reference import evaluate, valid_path
from globdelta.search import search
from tests.git_oracle import GitOracle

class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.git_oracle = GitOracle()

    @classmethod
    def tearDownClass(cls):
        cls.git_oracle.close()

    def compare(self,a,b,**kw):
        before, after = parse_policy(a), parse_policy(b)
        self.assertIsNotNone(before.policy)
        self.assertIsNotNone(after.policy)
        result = search(before.policy, after.policy, Budget(Limits(**kw)))
        for name in ('newly_ignored', 'newly_included'):
            direction = getattr(result, name)
            if direction.status == 'found':
                self.git_oracle.verify_witness(a, b, direction.witness.path, name)
        return result

    def test_ancestor_regression_shortest_witness(self):
        r=self.compare(b'/build/*\n!/build/keep.txt',b'/build/\n!/build/keep.txt')
        self.assertEqual(r.newly_ignored.witness.path,b'build/keep.txt')
        self.assertEqual(r.newly_included.status,'absent')
        self.assertTrue(r.graph_exhausted)
        self.assertEqual(r.newly_ignored.witness.after.first_blocked_ancestor.prefix_end,5)

    def test_two_directions_and_shortlex(self):
        r=self.compare(b'a',b'b')
        self.assertEqual(r.newly_ignored.witness.path,b'b')
        self.assertEqual(r.newly_included.witness.path,b'a')
        self.assertEqual(r.stop.reason,'both_witnesses_found')
        self.assertFalse(r.graph_exhausted)
        r=self.compare(b'',b'*')
        self.assertEqual(r.newly_ignored.witness.path,b' ')
        self.assertEqual(r.newly_included.status,'absent')

    def test_equivalence_is_graph_exhaustion(self):
        for a,b in [(b'',b''),(b'cache',b'**/cache'),(b'a',b'a\r\n#comment\n'),(b'a',b'a\na')]:
            r=self.compare(a,b)
            self.assertEqual((r.newly_ignored.status,r.newly_included.status),('absent','absent'),(a,b))
            self.assertTrue(r.graph_exhausted)

    def test_limit_never_means_absent(self):
        for kw in ({'product_states':0},{'transitions':0},{'nfa_states':0},{'subsets':0},{'work':0},{'witness_bytes':0},{'replay_work':0}):
            r=self.compare(b'',b'*',**kw)
            self.assertEqual(r.stop.reason,'limit',kw)
            self.assertFalse(r.graph_exhausted)
            self.assertNotIn('absent',(r.newly_ignored.status,r.newly_included.status),kw)

    def test_found_survives_later_limit(self):
        r=self.compare(b'',b'*',transitions=95)
        self.assertEqual(r.newly_ignored.status,'found')
        self.assertEqual(r.newly_ignored.witness.path,b' ')
        self.assertEqual(r.newly_included.status,'unknown')
        self.assertEqual(r.stop.reason,'limit')

    def test_replay_memory_limit_is_identified(self):
        r=self.compare(b'',b'*',replay_payload_bytes=64)
        self.assertEqual(r.stop.limit.name,'replay_payload_bytes')
        self.assertEqual(r.stop.limit.maximum,64)

    def test_forbidden_prefixes_never_latch(self):
        for raw in (b'.git',b'/.gitignore/'):
            r=self.compare(b'',raw)
            self.assertEqual(r.newly_ignored.status,'absent')
        r=self.compare(b'',b'/.gitignore')
        self.assertEqual(r.newly_ignored.witness.path,b'.gitignore')
        r=self.compare(b'',b'.gitx')
        self.assertEqual(r.newly_ignored.witness.path,b'.gitx')
        r=self.compare(b'a/\n!a/\n!a/b',b'')
        self.assertEqual(r.newly_included.status,'absent')

    def test_no_hidden_witness_length_language_cutoff(self):
        r=self.compare(b'a'*24,b'a'*24,witness_bytes=0)
        self.assertTrue(r.graph_exhausted)
        self.assertEqual(r.newly_ignored.status,'absent')
        r=self.compare(b'',b'a'*24,witness_bytes=23)
        self.assertEqual(r.stop.limit.name,'witness_bytes')
        self.assertEqual(r.newly_ignored.status,'unknown')

    def test_full_ascii_minimality_for_short_witnesses(self):
        alphabet=range(32,127)
        for a,b in [(b'a',b'b'),(b'[ ab]',b'[ ac]'),(b'/a',b'a'),(b'*\n!a/',b'*')]:
            r=self.compare(a,b)
            for direction in (r.newly_ignored,r.newly_included):
                if direction.status!='found' or len(direction.witness.path)>2:continue
                witness=direction.witness.path
                want=direction is r.newly_ignored
                pa,pb=parse_policy(a).policy,parse_policy(b).policy
                for n in range(1,len(witness)+1):
                    for values in itertools.product(alphabet,repeat=n):
                        path=bytes(values)
                        if path==witness:break
                        if not valid_path(path):continue
                        before=evaluate(pa,path,Budget(Limits())).ignored
                        after=evaluate(pb,path,Budget(Limits())).ignored
                        self.assertFalse((not before and after) if want else (before and not after),(a,b,path,witness))
                    else:continue
                    break

if __name__=='__main__':unittest.main()
