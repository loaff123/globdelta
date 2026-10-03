import itertools
import unittest
from globdelta.budget import Budget, Limits
from globdelta.parse import parse_policy
from globdelta.reference import direct_match, valid_path
from globdelta.nfa import compile_policy, Matcher
from globdelta import validity

class NFATests(unittest.TestCase):
    def match(self, raw, path, cache=8192):
        p=parse_policy(raw).policy
        self.assertIsNotNone(p,raw)
        b=Budget(Limits(cache_entries=cache))
        m=Matcher(compile_policy(p,b),b)
        s=m.start
        for c in path:s=m.step(s,c)
        return p,m,s

    def test_direct_languages_exhaustive(self):
        patterns=[b'',b'a',b'*',b'?',b'[ab]',b'[^a]',b'\\*',b'**',b'/**',b'a/**',b'a/**/',b'a/**/b',b'**/a',b'a/**/**/b',b'*/a',b'foo/',b'/a',b'*\n!a/']
        paths=[bytes(v) for n in range(1,5) for v in itertools.product(b'ab/',repeat=n) if valid_path(bytes(v))]
        for raw in patterns:
            p=parse_policy(raw).policy
            b=Budget(Limits())
            m=Matcher(compile_policy(p,b),b)
            for path in paths:
                s=m.start
                for c in path:s=m.step(s,c)
                for directory in (False,True):
                    matching=[r for r in p.rules if (directory or not r.directory_only) and direct_match(r,tuple(path.split(b'/')),Budget(Limits()))]
                    expected=bool(matching and not matching[-1].include)
                    self.assertEqual(m.ignored(s,directory),expected,(raw,path,directory))

    def test_empty_class_mask_is_not_epsilon(self):
        raw = b'[!' + b''.join(b'\\' + bytes([c]) for c in range(32, 127) if c != 47) + b']'
        _, m, state = self.match(raw + b'a', b'a')
        self.assertFalse(m.ignored(state, False))

    def test_filter_type_before_order(self):
        _,m,s=self.match(b'*\n!a/',b'a')
        self.assertTrue(m.ignored(s,False))
        self.assertFalse(m.ignored(s,True))

    def test_cache_eviction_is_semantically_pure(self):
        for raw in (b'a/**/b\n!a/b',b'*\n!*/a',b'[ab]*'):
            for path in (b'a',b'a/b',b'x/a/z/b',b'bbaa'):
                values=[]
                for cap in (0,1,2,8192):
                    _,m,s=self.match(raw,path,cap)
                    values.append((m.ignored(s,False),m.ignored(s,True)))
                    self.assertLessEqual(len(m.cache),cap)
                self.assertEqual(len(set(values)),1)

    def test_nfa_limits_prevent_growth(self):
        from globdelta.budget import LimitExceeded
        for kw in ({'nfa_states':0},{'nfa_edges':0},{'subsets':0},{'work':0},{'payload_bytes':0}):
            with self.assertRaises(LimitExceeded):
                b=Budget(Limits(**kw));Matcher(compile_policy(parse_policy(b'a').policy,b),b)

class ValidityTests(unittest.TestCase):
    def accepted(self,path):
        s=validity.START
        for c in path:
            s=validity.step(s,c)
            if s is None:return False
        return validity.terminal(s)

    def test_validity_matches_reference_exhaustively(self):
        for n in range(6):
            for seq in itertools.product(b'.ag/',repeat=n):
                path=bytes(seq)
                self.assertEqual(self.accepted(path),valid_path(path),path)
        for p in (b'.git',b'.gitx',b'.gitignore',b'.gitignore/x',b'a/.gitignore/x',b'a/.git/x',b' ',b'\\',b':',b'a/..x'):
            self.assertEqual(self.accepted(p),valid_path(p),p)

    def test_state_set_finite_without_component_names(self):
        reachable={validity.START};todo=list(reachable)
        while todo:
            s=todo.pop()
            for c in range(32,127):
                t=validity.step(s,c)
                if t is not None and t not in reachable:reachable.add(t);todo.append(t)
        self.assertLessEqual(len(reachable),32)
        self.assertTrue(all(type(x) is int for x in reachable))

if __name__=='__main__':unittest.main()
