import dataclasses
import unittest

from globdelta.budget import Budget, Limits
from globdelta.parse import parse_policy
from globdelta.reference import evaluate, valid_path


class ParseReferenceTests(unittest.TestCase):
    def parsed(self, raw):
        result = parse_policy(raw)
        self.assertIsNotNone(result.policy, result)
        return result.policy

    def decision(self, raw, path):
        return evaluate(self.parsed(raw), path, Budget(Limits())).ignored

    def test_empty_and_exact_raw_hash(self):
        import hashlib
        raw = b'# comment\r\n\r\nfoo\r\n!bar'
        p = self.parsed(raw)
        self.assertEqual(p.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual([r.span.line for r in p.rules], [3, 4])
        self.assertEqual(p.rules[0].span.byte_start, 13)
        self.assertEqual(p.rules[0].span.byte_end, 16)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.raw_size = 9
        self.assertFalse(self.decision(b'', b'a'))

    def test_missing_body_span_is_consistently_zero_width(self):
        for raw in (b'!', b'/', b'!/', b'!\n', b'!/\r\n'):
            span = parse_policy(raw).diagnostics[0].location
            self.assertEqual(span.column_end_exclusive - span.column_start, span.byte_end - span.byte_start)
            self.assertEqual(span.byte_end, span.byte_start)

    def test_byte_rejections_even_comments(self):
        for raw, offset in [(b'#\t', 1), (b'\xef\xbb\xbf', 0), (b'a\rb', 1), (b'a\r', 1), (b'#\x7f', 1), (b'\x00', 0)]:
            r = parse_policy(raw)
            self.assertIsNone(r.policy, raw)
            self.assertEqual(r.diagnostics[0].location.byte_start, offset)

    def test_grammar_rejections_and_first_spans(self):
        for raw, offset in [(b'!',1),(b'/',1),(b'a//b',2),(b'a\\/b',1),(b'a**b',1),(b'***',0),(b'a\\',1),(b'[abc',0),(b'[]',0),(b'[z-a]',2),(b'[a-b-c]',4),(b'[--a]',2),(b'[a-\\]]',2),(b'[[:alpha:]]',1)]:
            r=parse_policy(raw)
            self.assertIsNone(r.policy, raw)
            self.assertEqual(r.diagnostics[0].location.byte_start,offset,raw)

    def test_markers_spaces_and_escape_parity(self):
        cases=[(b'\\#x',b'#x'),(b'\\!x',b'!x'),(b' x ',b' x'),(b'foo\\  ',b'foo '),(b'foo\\\\ ',b'foo\\'),(b'foo \\ ',b'foo  '),(b'!!x\n',b'!x')]
        for raw,path in cases:
            self.assertEqual(self.decision(raw,path),not raw.startswith(b'!'),(raw,path))
        self.assertFalse(self.decision(b'# [ malformed', b'#'))
        self.assertTrue(self.decision(b'!#x\n#x',b'#x') is False)

    def test_class_baseline(self):
        cases=[(b'[abc]',b'b'),(b'[a-zA-Z0-9]',b'Z'),(b'[!ab]',b'c'),(b'[^ab]',b'c'),(b'[]a]',b']'),(b'[-ab]',b'-'),(b'[ab-]',b'-'),(b'[\\[\\]]',b'['),(b'[\\-]',b'-'),(b'[9-A]',b':'),(b'[**]',b'*')]
        for raw,path in cases:
            self.assertTrue(self.decision(raw,path),(raw,path))
            self.assertFalse(self.decision(raw,b'xx'),raw)

    def test_directory_order_and_blocking(self):
        cases=[(b'*\n!a/',b'a',True),(b'*\n!a/',b'a/b',True),(b'foo/\n!foo/bar',b'foo/bar',True),(b'foo/\n!foo\n!foo/bar',b'foo/bar',False),(b'/build/*\n!/build/keep.txt',b'build/keep.txt',False),(b'/build/\n!/build/keep.txt',b'build/keep.txt',True),(b'a\n!ab',b'ab',False)]
        for raw,path,want in cases:self.assertEqual(self.decision(raw,path),want,(raw,path))
        e=evaluate(self.parsed(b'/build/\n!/build/keep.txt'),b'build/keep.txt',Budget(Limits()))
        self.assertEqual(e.basis,'blocked_ancestor')
        self.assertEqual(e.first_blocked_ancestor.prefix_end,5)
        self.assertEqual(e.winning_rule_id,1)

    def test_globstar_direct_and_basename(self):
        for raw,path,want in [(b'a/**/b',b'a/b',True),(b'a/**/**/b',b'a/x/y/b',True),(b'a/**',b'a',False),(b'a/**/',b'a/b',False),(b'a/**/',b'a/b/c',True),(b'foo/',b'x/foo/a',True),(b'/foo/',b'x/foo/a',False),(b'cache',b'x/cache',True),(b'**/cache',b'x/cache',True)]:
            self.assertEqual(self.decision(raw,path),want,(raw,path))

    def test_valid_paths(self):
        for path in [b' ',b':',b'\\',b'.gitx',b'.gitignore',b'a/.gitignore',b'a/.gitignore/x']:
            self.assertTrue(valid_path(path),path)
        for path in [b'',b'.',b'..',b'.git',b'a/.git/x',b'.gitignore/x',b'/a',b'a/',b'a//b',b'\x7f']:
            self.assertFalse(valid_path(path),path)

    def test_reference_charges_before_path_validation(self):
        from globdelta.budget import LimitExceeded
        with self.assertRaises(LimitExceeded):
            evaluate(self.parsed(b''), b'a' * 1000 + b'/..', Budget(Limits(reference_work=0)))

    def test_reference_charges_prefix_copy_work(self):
        from globdelta.budget import LimitExceeded
        path = b'a/' * 99 + b'a'
        with self.assertRaises(LimitExceeded):
            evaluate(self.parsed(b''), path, Budget(Limits(reference_work=len(path), explanation_steps=0)))

    def test_parser_caps_are_inconclusive(self):
        for kw,raw in [({'input_bytes':0},b'a'),({'line_bytes':0},b'a'),({'rules':0},b'a'),({'ast_items':0},b'a')]:
            r=parse_policy(raw,Limits(**kw))
            self.assertIsNone(r.policy)
            self.assertIsNotNone(r.stop)
            self.assertEqual(r.diagnostics,())

if __name__=='__main__':unittest.main()
