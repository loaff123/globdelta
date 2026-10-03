"""Independent iterative interpreter. This module never imports the automata.

All proper prefixes are evaluated as directories using the complete ordered
policy. The first ignored directory terminates effective traversal.
"""
from .budget import Budget
from .model import BlockedAncestor, Component, Explanation, Policy, Rule, Step


def invalid_path_offset(path: bytes) -> int | None:
    """First invalid byte/component start, without allocating component slices."""
    if not isinstance(path, bytes) or not path:
        return 0
    start = 0
    first = True
    for i, b in enumerate(path):
        if not 32 <= b <= 126:
            return i
        if b == 47:
            length = i - start
            forbidden = any(length == len(word) and path.startswith(word, start, i) for word in (b'.', b'..', b'.git'))
            root_policy = first and length == 10 and path.startswith(b'.gitignore', start, i)
            if not length:
                return i
            if forbidden or root_policy:
                return start
            first = False
            start = i + 1
    length = len(path) - start
    if not length:
        return len(path) - 1
    if any(length == len(word) and path.startswith(word, start) for word in (b'.', b'..', b'.git')):
        return start
    return None


def valid_path(path: bytes) -> bool:
    return invalid_path_offset(path) is None


def component_match(component: Component, word: bytes, budget: Budget, work: str = 'reference_work') -> bool:
    """Rolling atom/byte DP, independent of Thompson state construction."""
    if component.globstar:
        return True
    width = len(word) + 1
    budget.charge(work, width, 'reference_component_init')
    with budget.scratch(16 * width, 'reference_component'):
        previous = [False] * width
        previous[0] = True
        for atom in component.atoms:
            budget.charge(work, width, 'reference_component')
            current = [False] * width
            if atom.repeat:
                current[0] = previous[0]
                for j, byte in enumerate(word, 1):
                    current[j] = previous[j] or (current[j - 1] and bool(atom.mask & (1 << (byte - 32))))
            else:
                for j, byte in enumerate(word, 1):
                    current[j] = previous[j - 1] and bool(atom.mask & (1 << (byte - 32)))
            previous = current
        return previous[-1]


def direct_match(rule: Rule, components: tuple[bytes, ...], budget: Budget, work: str = 'reference_work') -> bool:
    if not components:
        return False
    if rule.basename:
        return component_match(rule.components[0], components[-1], budget, work)
    width = len(components) + 1
    budget.charge(work, width, 'reference_path_init')
    with budget.scratch(16 * width, 'reference_path'):
        previous = [False] * width
        previous[0] = True
        for i, component in enumerate(rule.components):
            budget.charge(work, width, 'reference_path')
            current = [False] * width
            if component.globstar:
                seen = False
                final = i == len(rule.components) - 1
                for j in range(width):
                    if not final:
                        seen = seen or previous[j]
                    current[j] = seen
                    if final:
                        seen = seen or previous[j]
            else:
                for j, word in enumerate(components):
                    if previous[j]:
                        current[j + 1] = component_match(component, word, budget, work)
            previous = current
        return previous[-1]


def evaluate(policy: Policy, path: bytes, budget: Budget, work: str = 'reference_work') -> Explanation:
    budget.check('witness_bytes', len(path), 'reference_input')
    budget.charge(work, len(path), 'reference_input')
    if not valid_path(path):
        raise ValueError('path is outside git-root-ascii-v1')
    with budget.scratch(32 * (len(path) + 1), 'reference_input'):
        components = tuple(path.split(b'/'))
        steps: list[Step] = []
        rule_ids: set[int] = set()
        trace_complete = True
        trace_matches = 0
        prefix_end = -1
        winner: Rule | None = None
        matches: tuple[int, ...] = ()
        for k, component in enumerate(components, 1):
            prefix_end += 1 + len(component)
            directory = k < len(components)
            matched: list[int] = []
            winner = None
            with budget.scratch(8 * k + 8 * len(policy.rules), 'reference_node'):
                budget.charge(work, k, 'reference_prefix')
                prefix = components[:k]
                for rule in policy.rules:
                    budget.charge(work, 1, 'reference_rule')
                    if (directory or not rule.directory_only) and direct_match(rule, prefix, budget, work):
                        winner = rule
                        if trace_complete:
                            matched.append(rule.index)
                ignored = winner is not None and not winner.include
                if trace_complete:
                    if len(steps) >= budget.limits.explanation_steps or trace_matches + len(matched) > budget.limits.explanation_matches:
                        trace_complete = False
                    else:
                        budget.retain(64 + 16 * len(matched), 'explanation_trace')
                        trace_matches += len(matched)
                        matches = tuple(matched)
                        rule_ids.update(matches)
                        steps.append(Step(prefix_end, 'directory' if directory else 'file', matches, winner.index if winner else None, ignored))
                if directory and ignored:
                    assert winner is not None
                    rule_ids.add(winner.index)
                    budget.retain(128 + 8 * len(rule_ids), 'explanation_cause')
                    return Explanation(True, 'blocked_ancestor', winner.index, BlockedAncestor(prefix_end, winner.index), tuple(r for r in policy.rules if r.index in rule_ids), tuple(steps), trace_complete, False, ())
        if winner:
            rule_ids.add(winner.index)
        budget.retain(128 + 8 * len(rule_ids), 'explanation_cause')
        return Explanation(bool(winner and not winner.include), 'direct_rule' if winner else 'default', winner.index if winner else None, None, tuple(r for r in policy.rules if r.index in rule_ids), tuple(steps), trace_complete, True, matches if trace_complete else ())
