"""Deterministic campaign inputs independent of all production modules.

Random accepted policies originate as a tiny test-only AST. Rendering then varies
literal quoting, class notation, blank/comment lines, trailing spaces and physical
line endings. The AST never supplies expected decisions: real Git does.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import random

FINITE_VOCABULARY = (b'a', b'!a', b'b/', b'!b/', b'*', b'!a/', b'/a',
                     b'a/*', b'a/**', b'**/b', b'a/**/b', b'[ab]')
RANDOM_SEED = 0x6C0B2026
INVALID_SEED = 0xBAD52026
RANDOM_POLICY_COUNT = 80
RANDOM_PATH_COUNT = 32
INVALID_CASE_COUNT = 256


def finite_campaign():
    words = [bytes(c) for n in (1, 2) for c in product(b'ab', repeat=n)]
    paths = tuple(b'/'.join(parts) for depth in (1, 2) for parts in product(words, repeat=depth))
    policies = tuple(b''.join(line + b'\n' for line in lines)
                     for count in (0, 1, 2) for lines in product(FINITE_VOCABULARY, repeat=count))
    return tuple((policy, paths) for policy in policies)


@dataclass(frozen=True)
class TestAtom:
    kind: str
    value: bytes = b''


@dataclass(frozen=True)
class TestRule:
    # None denotes a whole-component globstar, otherwise a tuple of atoms.
    components: tuple
    include: bool
    rooted: bool
    directory: bool


# Raw variants and constructive samples, all inside the strict class baseline.
CLASS_VARIANTS = (
    ((b'[ab]', b'[ba]'), b'a'), ((b'[!ab]', b'[^ab]'), b'c'),
    ((b'[a-c]', b'[abc]'), b'b'), ((b'[]a]', b'[a\\]]'), b']'),
    ((b'[-ab]', b'[ab-]', b'[a\\-b]'), b'-'),
    ((b'[\\[\\]]', b'[\\]\\[]'), b'['), ((b'[9-A]',), b':'),
)


def _draw_rule(rng):
    components = []
    for _ in range(rng.randint(1, 3)):
        if rng.randrange(6) == 0:
            components.append(None)
            continue
        atoms = []
        for _ in range(rng.randint(1, 4)):
            kind = rng.choice(('literal', 'literal', 'literal', '?', '*', 'class'))
            if kind == '*' and atoms and atoms[-1].kind == '*':
                kind = '?'
            value = bytes([rng.choice(b'ab #!]?*[-\\09A')]) if kind == 'literal' else b''
            if kind == 'class':
                value = bytes([rng.randrange(len(CLASS_VARIANTS))])
            atoms.append(TestAtom(kind, value))
        components.append(tuple(atoms))
    return TestRule(tuple(components), bool(rng.randrange(2)),
                    bool(rng.randrange(2)), bool(rng.randrange(3) == 0))


def _render(rule, rng):
    components = []
    for component in rule.components:
        if component is None:
            components.append(b'**')
            continue
        raw = bytearray()
        for atom in component:
            if atom.kind == 'literal':
                byte = atom.value[0]
                if byte in b' #![]?*\\' or rng.randrange(3) == 0:
                    raw.append(92)
                raw.append(byte)
            elif atom.kind == 'class':
                raw.extend(rng.choice(CLASS_VARIANTS[atom.value[0]][0]))
            else:
                raw.extend(atom.kind.encode('ascii'))
        components.append(bytes(raw))
    return ((b'!' if rule.include else b'') + (b'/' if rule.rooted else b'') +
            b'/'.join(components) + (b'/' if rule.directory else b''))


def _sample(rule, rng):
    parts = []
    for component in rule.components:
        if component is None:
            parts.extend([b'b'] * rng.randint(0, 2))
            continue
        value = bytearray()
        for atom in component:
            if atom.kind == 'literal':
                value.extend(atom.value)
            elif atom.kind == 'class':
                value.extend(CLASS_VARIANTS[atom.value[0]][1])
            elif atom.kind == '?':
                value.append(rng.choice(b'ab'))
            else:
                value.extend(b'a' * rng.randrange(3))
        parts.append(bytes(value) or b'a')
    if not parts:
        parts.append(b'a')
    if rule.directory:
        parts.append(b'x')
    return b'/'.join(parts)


def random_campaign():
    rng = random.Random(RANDOM_SEED)
    records = []
    for _ in range(RANDOM_POLICY_COUNT):
        rules = tuple(_draw_rule(rng) for _ in range(rng.randint(1, 5)))
        rendered = []
        for rule in rules:
            if rng.randrange(4) == 0:
                rendered.append(b'# comment [ ** \\')
            if rng.randrange(4) == 0:
                rendered.append(b' ' * rng.randint(0, 3))
            rendered.append(_render(rule, rng) + b' ' * rng.randint(0, 2))
        terminator = rng.choice((b'\n', b'\r\n'))
        policy = terminator.join(rendered) + (terminator if rng.randrange(2) else b'')
        paths = set(_sample(rule, rng) for rule in rules)
        while len(paths) < RANDOM_PATH_COUNT:
            components = []
            for _ in range(rng.randint(1, 3)):
                components.append(bytes(rng.choice(b'ab .#!:*?[]\\-09A') for _ in range(rng.randint(1, 4))))
            if any(c in (b'.', b'..', b'.git') for c in components):
                continue
            paths.add(b'/'.join(components))
        records.append((policy, tuple(sorted(paths))))
    return tuple(records)


def invalid_campaign():
    rng = random.Random(INVALID_SEED)
    malformed = (b'a**b', b'***', b'a//b', b'a\\/b', b'[', b'[]',
                 b'[z-a]', b'[a-b-c]', b'[a-\\]]', b'[[:alpha:]]', b'!', b'/', b'a\\')
    invalid_bytes = bytes(i for i in range(256) if i not in range(32, 127) and i not in (10, 13))
    results = []
    for index in range(INVALID_CASE_COUNT):
        prefix = rng.choice((b'', b'# valid comment\n', b'a\n!a\n'))
        if index % 2:
            policy = prefix + rng.choice(malformed) + rng.choice((b'', b'\n', b'\r\n'))
        else:
            policy = prefix + rng.choice((b'# comment', b'a')) + bytes([rng.choice(invalid_bytes)]) + b'\n'
        results.append(policy)
    return tuple(results)


def campaign_digest(records):
    """Length-delimited raw bytes; path order is part of the campaign identity."""
    digest = sha256()
    for policy, paths in records:
        for item in (policy, *paths):
            digest.update(len(item).to_bytes(8, 'big'))
            digest.update(item)
        digest.update(b'\xff' * 8)
    return digest.hexdigest()


def invalid_digest(policies):
    return campaign_digest((policy, ()) for policy in policies)


def shrink_mismatch(policy: bytes, path: bytes, still_fails):
    """Greedy deletion reducer; predicates must reject unsupported candidates.

    Keep the failure while deleting whole policy lines, then policy bytes, then
    whole path components and individual path bytes. This promises a useful
    deletion-minimal reproduction, not a globally smallest semantic example.
    """
    from tests.git_oracle import _safe_path
    if not still_fails(policy, path):
        raise ValueError('The supplied case does not reproduce a mismatch')
    changed = True
    while changed:
        changed = False
        lines = policy.splitlines(keepends=True)
        proposals = [b''.join(lines[:i] + lines[i + 1:]) for i in range(len(lines))]
        proposals += [policy[:i] + policy[i + 1:] for i in range(len(policy))]
        for candidate in proposals:
            if still_fails(candidate, path):
                policy, changed = candidate, True
                break
        if changed:
            continue
        parts = path.split(b'/')
        proposals = [b'/'.join(parts[:i] + parts[i + 1:]) for i in range(len(parts))]
        proposals += [path[:i] + path[i + 1:] for i in range(len(path))]
        for candidate in proposals:
            try:
                _safe_path(candidate)
            except ValueError:
                continue
            if still_fails(policy, candidate):
                path, changed = candidate, True
                break
    return policy, path
