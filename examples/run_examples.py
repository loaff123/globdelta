#!/usr/bin/env python3
"""Check complete example workflows against an installed GlobDelta command.

Development helper only: the production package never invokes subprocesses.
Expected results are checked, not presented as already captured transcripts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--globdelta', default='globdelta', help='Installed CLI executable')
    args = parser.parse_args()

    def run(*arguments, status):
        proc = subprocess.run([args.globdelta, *map(str, arguments), '--format', 'json'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=False, text=True)
        if proc.returncode != status:
            raise AssertionError(f'{arguments!r}: expected exit {status}, got '
                                 f'{proc.returncode}; stderr={proc.stderr!r}; '
                                 f'stdout={proc.stdout!r}')
        report = json.loads(proc.stdout)
        assert report['profile']['id'] == 'git-root-ascii-v1', report
        return report

    def diff(name, before, after, witness):
        report = run('diff', HERE / before, HERE / after, status=0 if witness is None else 1)
        assert report['assessment_complete'] is True, report
        assert report['graph_exhausted'] is True, report
        assert report['directions']['newly_included']['status'] == 'absent', report
        newly = report['directions']['newly_ignored']
        if witness is None:
            assert report['result'] == 'equivalent', report
            assert newly == {'status': 'absent'}, report
        else:
            assert report['result'] == 'different', report
            assert newly['status'] == 'found', report
            found = newly['witness']
            assert found['path'] == witness, found
            assert found['byte_length'] == len(witness.encode('ascii')), found
            assert found['minimality'] == 'shortest-shortlex', found
            assert found['before']['ignored'] is False, found
            assert found['after']['ignored'] is True, found
        print(f'{name}: {report["result"]}; newly ignored={witness!r}; newly included=absent')
        return report

    ancestor = diff('ancestor', 'ancestor/before.gitignore', 'ancestor/after.gitignore',
                    'build/keep.txt')
    explanation = ancestor['directions']['newly_ignored']['witness']['after']
    assert explanation['basis'] == 'blocked_ancestor', explanation
    assert explanation['first_blocked_ancestor'] == {'prefix_end': 5, 'winning_rule_id': 1}
    assert explanation['terminal_matches']['effective'] is False, explanation
    diff('order', 'order/before.gitignore', 'order/after.gitignore', 'keep.log')
    diff('cache equivalence', 'cache/before.gitignore', 'cache/after.gitignore', None)
    diff('cache file-type contrast', 'cache/directories-only.gitignore',
         'cache/before.gitignore', 'cache')

    checks = [
        ('ancestor/before.gitignore', 'build/keep.txt', False),
        ('ancestor/after.gitignore', 'build/keep.txt', True),
        ('ancestor/before.gitignore', 'build/drop.txt', True),
        ('ancestor/after.gitignore', 'build/drop.txt', True),
        ('ancestor/before.gitignore', 'build', False),
        ('ancestor/after.gitignore', 'build', False),
        ('ancestor/before.gitignore', 'x/build/keep.txt', False),
        ('ancestor/after.gitignore', 'x/build/keep.txt', False),
        ('order/before.gitignore', 'keep.log', False),
        ('order/after.gitignore', 'keep.log', True),
        ('order/before.gitignore', 'other.log', True),
        ('order/after.gitignore', 'other.log', True),
        ('order/before.gitignore', 'notes.txt', False),
        ('order/after.gitignore', 'notes.txt', False),
        ('cache/directories-only.gitignore', 'cache', False),
        ('cache/before.gitignore', 'cache', True),
        ('cache/after.gitignore', 'cache', True),
        ('cache/before.gitignore', 'src/cache', True),
        ('cache/after.gitignore', 'src/cache', True),
        ('cache/before.gitignore', 'cache/item', True),
        ('cache/after.gitignore', 'cache/item', True),
        ('cache/before.gitignore', 'cachex', False),
        ('cache/after.gitignore', 'cachex', False),
    ]
    for policy, path, ignored in checks:
        report = run('explain', HERE / policy, path, status=0)
        assert report['result'] == 'explained', report
        assert report['assessment_complete'] is True, report
        assert report['explanation']['ignored'] is ignored, report
    print(f'explain: {len(checks)} expected regular-file decisions checked')

    with tempfile.TemporaryDirectory(prefix='globdelta-example-report-') as tmp:
        output = Path(tmp) / 'report.json'
        proc = subprocess.run([args.globdelta, 'diff',
            str(HERE / 'cache/before.gitignore'), str(HERE / 'cache/after.gitignore'),
            '--format', 'json', '--output', str(output)], check=False, capture_output=True)
        assert proc.returncode == 0, proc
        assert json.loads(output.read_text())['result'] == 'equivalent'
        original = output.read_bytes()
        refused = subprocess.run([args.globdelta, 'diff',
            str(HERE / 'cache/before.gitignore'), str(HERE / 'cache/after.gitignore'),
            '--format', 'json', '--output', str(output)], check=False, capture_output=True)
        assert refused.returncode == 5, refused
        assert output.read_bytes() == original
    print('output: fresh JSON created; existing destination refused unchanged')


if __name__ == '__main__':
    main()
