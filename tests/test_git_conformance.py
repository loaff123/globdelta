"""Independent real-file Git oracle and reproducible finite conformance campaigns."""
from __future__ import annotations

import importlib
import os
import hashlib
import json
from pathlib import Path
import unittest
import tempfile


class GitOracleContractTests(unittest.TestCase):
    def oracle_module(self):
        try:
            return importlib.import_module('tests.git_oracle')
        except ModuleNotFoundError:
            self.fail('Missing independent actual-file Git oracle')

    def test_verbose_negation_does_not_mean_ignored(self):
        module = self.oracle_module()
        with module.GitOracle() as oracle:
            result = oracle.check(b'a\n!a\n', [b'a'])[b'a']
            self.assertFalse(result.ignored)
            self.assertEqual(result.pattern, b'!a')
            self.assertEqual(result.verbose_returncode, 0)
            self.assertEqual(result.quiet_returncode, 1)
            self.assertEqual(result.actual_type, 'regular-file')

    def test_actual_file_directory_collisions_are_batched(self):
        module = self.oracle_module()
        with module.GitOracle() as oracle:
            result = oracle.check(b'a/\n', [b'a', b'a/b', b'a/b/c'])
            self.assertEqual({p: r.ignored for p, r in result.items()},
                             {b'a': False, b'a/b': True, b'a/b/c': True})

    def test_policy_file_and_nested_policy_names_are_protected(self):
        module = self.oracle_module()
        with module.GitOracle() as oracle:
            policy = b'.gitignore\n'
            result = oracle.check(policy, [b'.gitignore', b'a/.gitignore', b'a/.gitignore/x'])
            self.assertTrue(all(r.ignored for r in result.values()))
            self.assertEqual((oracle.repo / '.gitignore').read_bytes(), policy)
            with self.assertRaises(ValueError):
                oracle.check(policy, [b'.git/config'])
            with self.assertRaises(ValueError):
                oracle.check(policy, [b'.gitignore/x'])

    def test_colon_and_terminal_spaces_use_nul_framing(self):
        module = self.oracle_module()
        with module.GitOracle() as oracle:
            result = oracle.check(b':a\nfoo\\ \n', [b':a', b'foo ', b'foo'])
            self.assertEqual([result[p].ignored for p in [b':a', b'foo ', b'foo']],
                             [True, True, False])

    def test_hostile_inherited_git_environment_is_scrubbed(self):
        module = self.oracle_module()
        keys = {'GIT_DIR': '/definitely/not/a/repository',
                'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.ignoreCase',
                'GIT_CONFIG_VALUE_0': 'true', 'GIT_WORK_TREE': '/bad',
                'GIT_INDEX_FILE': '/bad/index', 'GIT_CONFIG_PARAMETERS': "'core.ignoreCase=true'"}
        previous = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update(keys)
            with module.GitOracle() as oracle:
                result = oracle.check(b'a\n', [b'a', b'A'])
                self.assertTrue(result[b'a'].ignored)
                self.assertFalse(result[b'A'].ignored)
                self.assertEqual(oracle.environment['LC_ALL'], 'C')
                self.assertNotIn('GIT_DIR', oracle.environment)
                self.assertNotIn('GIT_INDEX_FILE', oracle.environment)
                self.assertEqual(oracle.command('ls-files').stdout, b'')
        finally:
            for k, value in previous.items():
                if value is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = value

    def test_oversized_abstract_path_is_explicitly_unvalidated(self):
        module = self.oracle_module()
        with module.GitOracle() as oracle:
            with self.assertRaisesRegex(module.UnmaterializablePath, 'Unvalidated'):
                oracle.check(b'*\n', [b'a' * 4096])
            self.assertEqual(oracle.queries, 0)

    def test_runtime_metadata_identifies_git_and_isolation(self):
        module = self.oracle_module()
        self.assertTrue(hasattr(module.GitOracle, 'metadata'), 'Missing auditable oracle environment')
        with module.GitOracle() as oracle:
            metadata = oracle.metadata()
            self.assertEqual(metadata['executable'], oracle.executable)
            self.assertEqual(metadata['version'], oracle.version)
            self.assertEqual(metadata['environment']['LC_ALL'], 'C')
            self.assertEqual(metadata['environment']['GIT_CONFIG_NOSYSTEM'], '1')
            self.assertIn('core.ignoreCase=false', metadata['config'])
            self.assertEqual(metadata['actual_target_type'], 'regular-file')

    def test_optional_evidence_ledger_records_raw_bytes_and_decisions(self):
        module = self.oracle_module()
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / 'evidence.jsonl'
            self.assertTrue(hasattr(module.GitOracle, 'record'), 'Missing full oracle evidence ledger')
            with module.GitOracle(ledger=ledger) as oracle:
                oracle.check(b'a\n!b\n', [b'a', b'b'])
            records = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(records[0]['kind'], 'environment')
            answers = [r for r in records if r['kind'] == 'query']
            self.assertEqual(len(answers), 2)
            self.assertEqual([r['ignored'] for r in answers], [True, False])
            self.assertEqual([r['path_hex'] for r in answers], ['61', '62'])
            self.assertTrue(all(r['policy_hex'] == b'a\n!b\n'.hex() for r in answers))
            self.assertTrue(all(r['actual_type'] == 'regular-file' for r in answers))
            self.assertTrue(all(r['quiet_returncode'] in (0, 1) for r in answers))

    def test_missing_git_is_failure_not_skip(self):
        module = self.oracle_module()
        with self.assertRaises(module.GitOracleError):
            module.GitOracle(executable='/definitely/no/git')

    def test_each_witness_is_checked_in_both_policies(self):
        module = self.oracle_module()
        self.assertTrue(hasattr(module.GitOracle, 'verify_witness'), 'Missing two-policy witness replay')
        with module.GitOracle() as oracle:
            self.assertEqual(oracle.verify_witness(b'', b'a\n', b'a', 'newly_ignored'), (False, True))
            self.assertEqual(oracle.verify_witness(b'a\n', b'', b'a', 'newly_included'), (True, False))
            with self.assertRaises(module.GitOracleError):
                oracle.verify_witness(b'a\n', b'', b'a', 'newly_ignored')
            self.assertEqual(oracle.queries, 6)

    def test_malformed_verbose_framing_is_a_failure(self):
        module = self.oracle_module()
        for value in [b'', b'a\x00b\x00c\x00', b'a\x00b\x00c\x00d', b'\x00\x00\x00./wrong\x00']:
            with self.subTest(value=value), self.assertRaises(module.GitOracleError):
                module.parse_verbose(value, (b'a',))


FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'design_cases.json'
FIXTURE_DIGEST = 'e35789bfdb1e13c41b6bc2e15df14f31f697440dc9db2a22eb4f1fff19103f52'


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def engine_api(test):
    try:
        from globdelta.parse import parse_policy
        from globdelta.reference import evaluate
        from globdelta.budget import Budget, Limits
    except ModuleNotFoundError:
        test.fail('Missing parser/reference API for mandatory conformance')
    return parse_policy, evaluate, Budget, Limits


class ArchivedGitEvidenceTests(unittest.TestCase):
    def test_fixture_counts_and_integrity(self):
        self.assertEqual(hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(), FIXTURE_DIGEST)
        fixture = load_fixture()
        self.assertEqual(fixture['profile'], 'git-root-ascii-v1')
        self.assertEqual(len(fixture['cases']), 506)
        self.assertEqual(sum(len(c['queries']) for c in fixture['cases']), 27399)
        self.assertEqual(sum(c['accepted'] for c in fixture['cases']), 400)
        self.assertEqual(sum(not c['accepted'] for c in fixture['cases']), 106)
        self.assertEqual(sum(len(c['queries']) for c in fixture['cases'] if c['accepted']), 17790)
        for case in fixture['cases']:
            self.assertEqual(case['accepted'], case['rejection'] is None)
        self.assertEqual(fixture['saved_git_version'], 'git version 2.52.0')

    def test_saved_boolean_decisions_replay_in_fresh_git(self):
        from tests.git_oracle import GitOracle
        with GitOracle() as oracle:
            for case in load_fixture()['cases']:
                policy = bytes.fromhex(case['policy_hex'])
                result = oracle.check(policy, [p.encode('ascii') for p, _ in case['queries']])
                for path, ignored in case['queries']:
                    with self.subTest(campaign=case['campaign'], case=case['id'], path=path):
                        self.assertEqual(result[path.encode('ascii')].ignored, ignored,
                                         f'Git={oracle.version}; policy_hex={case["policy_hex"]}')
            print('ORACLE environment=' + json.dumps(oracle.metadata(), sort_keys=True), flush=True)
            print(f'ORACLE archived Git={oracle.version}; queries={oracle.queries}; '
                  f'fixture_sha256={FIXTURE_DIGEST}', flush=True)
            self.assertEqual(oracle.queries, 27399)

    def test_profile_classifications_and_saved_decisions(self):
        parse_policy, evaluate, Budget, Limits = engine_api(self)
        for case in load_fixture()['cases']:
            raw = bytes.fromhex(case['policy_hex'])
            with self.subTest(campaign=case['campaign'], case=case['id'], raw=raw):
                parsed = parse_policy(raw, Limits())
                self.assertIsNone(parsed.stop)
                if not case['accepted']:
                    self.assertIsNone(parsed.policy, f'Unsupported grammar accepted: {case["rejection"]}')
                    self.assertTrue(parsed.diagnostics)
                else:
                    self.assertFalse(parsed.diagnostics)
                    self.assertIsNotNone(parsed.policy)
                    for path, ignored in case['queries']:
                        explanation = evaluate(parsed.policy, path.encode('ascii'), Budget(Limits()))
                        self.assertEqual(explanation.ignored, ignored,
                                         f'path={path!r}, policy_hex={case["policy_hex"]}')


class GeneratedGitCampaignTests(unittest.TestCase):
    def test_mismatch_shrinker_reduces_policy_and_path(self):
        import tests.git_campaigns as campaigns
        self.assertTrue(hasattr(campaigns, 'shrink_mismatch'), 'Missing automatic mismatch reduction')
        raw, path = campaigns.shrink_mismatch(
            b'irrelevant\na*\nextra\n', b'foo/a/tail',
            lambda policy, path: b'a*' in policy and b'a' in path)
        self.assertEqual(raw, b'a*')
        self.assertEqual(path, b'a')

    def test_campaign_identity_and_counts(self):
        from tests.git_campaigns import (finite_campaign, random_campaign, invalid_campaign,
                                        campaign_digest, invalid_digest)
        finite, random, invalid = finite_campaign(), random_campaign(), invalid_campaign()
        self.assertEqual(len(finite), 157)
        self.assertEqual(sum(len(paths) for _, paths in finite), 6594)
        self.assertEqual(campaign_digest(finite), '583f7078141d4dc6773855b80d4c59559d588cc78ef0bd9ff4b7dfa2c05d1997')
        self.assertEqual(len(random), 80)
        self.assertEqual(sum(len(paths) for _, paths in random), 2560)
        self.assertEqual(campaign_digest(random), '193d03e088fe797323c9fca7b3280b9620c78ce22af8a60851bc3839396f5847')
        self.assertEqual(len(invalid), 256)
        self.assertEqual(invalid_digest(invalid), '62459b1f904db4de7b1c247fb4af0f06f9887bfe043aa71c7c50a5f10eb5f152')

    def verify_campaign(self, name, records, seed=None):
        from tests.git_oracle import GitOracle
        from tests.git_campaigns import campaign_digest
        parse_policy, evaluate, Budget, Limits = engine_api(self)
        decisions_digest = hashlib.sha256()
        with GitOracle() as oracle:
            for index, (raw, paths) in enumerate(records):
                with self.subTest(campaign=name, seed=seed, index=index, raw=raw):
                    parsed = parse_policy(raw, Limits())
                    self.assertIsNone(parsed.stop)
                    self.assertFalse(parsed.diagnostics)
                    self.assertIsNotNone(parsed.policy, 'Generated accepted AST was rejected')
                    results = oracle.check(raw, paths)
                    for path in paths:
                        for data in (raw, path, bytes([results[path].ignored])):
                            decisions_digest.update(len(data).to_bytes(8, 'big'))
                            decisions_digest.update(data)
                        explanation = evaluate(parsed.policy, path, Budget(Limits()))
                        if explanation.ignored != results[path].ignored:
                            from tests.git_campaigns import shrink_mismatch
                            def reproduces(candidate_policy, candidate_path):
                                parsed_candidate = parse_policy(candidate_policy, Limits())
                                if parsed_candidate.policy is None:
                                    return False
                                candidate_result = evaluate(parsed_candidate.policy, candidate_path, Budget(Limits()))
                                return candidate_result.ignored != oracle.check(candidate_policy, [candidate_path])[candidate_path].ignored
                            small_policy, small_path = shrink_mismatch(raw, path, reproduces)
                            self.fail(f'policy_hex={raw.hex()}; path_hex={path.hex()}; Git={oracle.version}; '
                                      f'reduced_policy_hex={small_policy.hex()}; reduced_path_hex={small_path.hex()}')
            expected_digests = {'finite': '2bbaeb34d3ad15417e77b99861762ae122c96e37c974c126a5fbb61d3f61addd',
                                'random': '1460f57abda4da73a08b29c55e24c964e95a44e2dbcf30316eba4d4f2eaa0363'}
            self.assertEqual(decisions_digest.hexdigest(), expected_digests[name])
            print(f'ORACLE {name}: seed={seed}; policies={len(records)}; queries={oracle.queries}; '
                  f'input_sha256={campaign_digest(records)}; decisions_sha256={decisions_digest.hexdigest()}', flush=True)

    def test_exhaustive_reduced_alphabet_ordered_policies(self):
        from tests.git_campaigns import finite_campaign
        self.verify_campaign('finite', finite_campaign())

    def test_random_accepted_ast_with_raw_grammar_variations(self):
        from tests.git_campaigns import random_campaign, RANDOM_SEED
        self.verify_campaign('random', random_campaign(), RANDOM_SEED)

    def test_invalid_fuzz_is_rejected_stably(self):
        from tests.git_campaigns import invalid_campaign, INVALID_SEED, invalid_digest
        parse_policy, _, _, Limits = engine_api(self)
        policies = invalid_campaign()
        for index, raw in enumerate(policies):
            with self.subTest(seed=INVALID_SEED, index=index, raw=raw):
                first = parse_policy(raw, Limits())
                second = parse_policy(raw, Limits())
                self.assertIsNone(first.policy)
                self.assertIsNone(first.stop)
                self.assertTrue(first.diagnostics)
                self.assertEqual(first, second)
        print(f'ORACLE invalid: seed={INVALID_SEED}; cases={len(policies)}; '
              f'input_sha256={invalid_digest(policies)}', flush=True)


class ComparisonWitnessGitTests(unittest.TestCase):
    def test_generated_policy_pairs_verify_every_found_witness(self):
        from globdelta.search import search
        from globdelta.api import compare_policies
        from tests.git_oracle import GitOracle
        from tests.git_campaigns import finite_campaign, random_campaign, campaign_digest, RANDOM_SEED
        parse_policy, _, Budget, Limits = engine_api(self)
        finite = [raw for raw, _ in finite_campaign()]
        random = [raw for raw, _ in random_campaign()]
        # Adjacent cyclic pairing includes every generated policy as both a
        # before and an after. This is 237 comparisons, not all possible pairs.
        pairs = [(name, items[i], items[(i + 1) % len(items)])
                 for name, items in [('finite', finite), ('random', random)]
                 for i in range(len(items))]
        self.assertEqual(len(pairs), 237)
        input_digest = campaign_digest((a, (b,)) for _, a, b in pairs)
        self.assertEqual(input_digest, '8f07a2051b9e88d1904ee83a9c5dee9721d82822d9f200bf8556f2b78e36b4fc')
        decision_digest = hashlib.sha256()
        counts = {'comparisons': 0, 'witnesses': 0, 'found': 0, 'absent': 0, 'unknown': 0}
        # Resource bounds control effort, not semantic path depth or length.
        limits = Limits(product_states=1500, transitions=150000, work=500000)
        with GitOracle() as oracle:
            for index, (name, before, after) in enumerate(pairs):
                with self.subTest(campaign=name, index=index, before=before, after=after):
                    parsed_before, parsed_after = parse_policy(before), parse_policy(after)
                    self.assertIsNotNone(parsed_before.policy)
                    self.assertIsNotNone(parsed_after.policy)
                    result = search(parsed_before.policy, parsed_after.policy, Budget(limits))
                    api_result = compare_policies(before, after, limits)
                    self.assertNotIn(api_result.result, ('error', 'unsupported'))
                    self.assertIsNone(result.error)
                    counts['comparisons'] += 1
                    for direction_name in ('newly_ignored', 'newly_included'):
                        direction = getattr(result, direction_name)
                        api_direction = getattr(api_result, direction_name)
                        self.assertEqual(direction.status, api_direction.status)
                        self.assertEqual(direction.witness.path if direction.witness else None,
                                         api_direction.witness.path if api_direction.witness else None)
                        # The raw policies and path are now identical for both
                        # engine and API results, so one Git replay validates both.
                        counts[direction.status] += 1
                        for part in (before, after, direction_name.encode(), direction.status.encode()):
                            decision_digest.update(len(part).to_bytes(8, 'big'))
                            decision_digest.update(part)
                        if direction.status == 'found':
                            path = direction.witness.path
                            self.assertTrue(path)
                            oracle.verify_witness(before, after, path, direction_name)
                            counts['witnesses'] += 1
                            decision_digest.update(len(path).to_bytes(8, 'big'))
                            decision_digest.update(path)
                        else:
                            self.assertIsNone(direction.witness)
            self.assertEqual(oracle.queries, counts['witnesses'] * 2)
            self.assertEqual(counts, {'comparisons': 237, 'witnesses': 246, 'found': 246, 'absent': 228, 'unknown': 0})
            self.assertEqual(decision_digest.hexdigest(), '3cd230a4f51a55164de34e1f53016365e41a4aac5b63cb05177b1afa0b887e16')
            print('ORACLE witnesses: ' + json.dumps({**counts, 'git_queries': oracle.queries,
                  'random_seed': RANDOM_SEED, 'input_sha256': input_digest,
                  'decisions_sha256': decision_digest.hexdigest(),
                  'limits': {'product_states': 1500, 'transitions': 150000, 'work': 500000}},
                  sort_keys=True), flush=True)
    def test_three_public_api_workflows_against_git(self):
        from globdelta.api import compare_policies
        from tests.git_oracle import GitOracle
        examples = (
            (b'/build/*\n!/build/keep.txt\n', b'/build/\n!/build/keep.txt\n',
             'different', b'build/keep.txt'),
            (b'*.log\n!keep.log\n', b'!keep.log\n*.log\n', 'different', b'keep.log'),
            (b'cache\n', b'**/cache\n', 'equivalent', None),
            (b'cache/\n', b'cache\n', 'different', b'cache'),
        )
        with GitOracle() as oracle:
            for before, after, expected, witness in examples:
                report = compare_policies(before, after)
                self.assertEqual(report.result, expected)
                self.assertTrue(report.assessment_complete)
                self.assertEqual(report.newly_ignored.witness.path if witness else None, witness)
                self.assertEqual(report.newly_included.status, 'absent')
                for name in ('newly_ignored', 'newly_included'):
                    direction = getattr(report, name)
                    if direction.status == 'found':
                        oracle.verify_witness(before, after, direction.witness.path, name)


if __name__ == '__main__':
    unittest.main()
