"""Shortlex product BFS over complete finite semantic state, never paths."""
from dataclasses import dataclass, replace
from .budget import Budget, LimitExceeded
from .model import Direction, Policy, SearchResult, Stop, Witness
from .nfa import Matcher, compile_policy
from .reference import evaluate
from . import validity

BLOCKED = -1

@dataclass(frozen=True, slots=True)
class _Node:
    key: tuple[int, int, int]
    previous: int
    byte: int
    depth: int


def _advance(matcher: Matcher, identity: int, byte: int) -> int:
    if identity == BLOCKED:
        return BLOCKED
    if byte == 47 and matcher.ignored(identity, True):
        return BLOCKED
    return matcher.step(identity, byte)


def _ignored(matcher: Matcher, identity: int) -> bool:
    return identity == BLOCKED or matcher.ignored(identity, False)


def _path(nodes: list[_Node], index: int, replay: Budget) -> bytes:
    length = nodes[index].depth
    replay.check('witness_bytes', length, 'witness')
    replay.charge('replay_work', length, 'witness')
    replay.retain(length + 64, 'witness')
    with replay.scratch(length, 'witness'):
        output = bytearray(length)
        for position in range(length - 1, -1, -1):
            node = nodes[index]
            output[position] = node.byte
            index = node.previous
        return bytes(output)


def search(before: Policy, after: Policy, budget: Budget) -> SearchResult:
    directions = [Direction(), Direction()]
    replay = Budget(replace(budget.limits, payload_bytes=budget.limits.replay_payload_bytes))
    def result(reason: str, exhausted: bool = False, limit=None, error=None):
        return SearchResult(directions[0], directions[1], exhausted, Stop(reason, limit), error, replay.usage())
    try:
        # This reservation remains owned by the search. Main caches/work can
        # never consume the interpreter's independent replay capacity.
        budget.retain(budget.limits.replay_payload_bytes, 'replay_reserve')
        left = Matcher(compile_policy(before, budget, 'before'), budget)
        right = Matcher(compile_policy(after, budget, 'after'), budget)
        budget.charge('product_states', 1, 'search')
        budget.retain(192, 'product_state')
        initial = (left.start, right.start, validity.START)
        nodes = [_Node(initial, -1, 0, 0)]
        visited = {initial: 0}
        head = 0
        with budget.scratch(256, 'search_transition'):
            while head < len(nodes):
                node = nodes[head]
                a, b, valid = node.key
                if validity.terminal(valid):
                    ignored_a, ignored_b = _ignored(left, a), _ignored(right, b)
                    which = 0 if not ignored_a and ignored_b else 1 if ignored_a and not ignored_b else None
                    if which is not None and directions[which].status == 'unknown':
                        try:
                            path = _path(nodes, head, replay)
                            explain_before = evaluate(before, path, replay, 'replay_work')
                            explain_after = evaluate(after, path, replay, 'replay_work')
                            replay.retain(96, 'verified_witness')
                        except LimitExceeded as exc:
                            if exc.stop.name == 'payload_bytes':
                                raise LimitExceeded(replace(exc.stop, name='replay_payload_bytes')) from exc
                            raise
                        expected = (False, True) if which == 0 else (True, False)
                        if (explain_before.ignored, explain_after.ignored) != expected:
                            return result('error', error='Independent witness replay disagreed with product output')
                        directions[which] = Direction('found', Witness(path, explain_before, explain_after))
                        if all(d.status == 'found' for d in directions):
                            return result('both_witnesses_found')
                for byte in range(32, 127):
                    budget.charge('transitions', 1, 'search')
                    next_valid = validity.step(valid, byte)
                    if next_valid is None:
                        continue
                    next_key = (_advance(left, a, byte), _advance(right, b, byte), next_valid)
                    if next_key not in visited:
                        budget.charge('product_states', 1, 'search')
                        budget.retain(192, 'product_state')
                        visited[next_key] = len(nodes)
                        nodes.append(_Node(next_key, head, byte, node.depth + 1))
                head += 1
        directions = [Direction('absent') if d.status == 'unknown' else d for d in directions]
        return result('exhausted', exhausted=True)
    except LimitExceeded as exc:
        return result('limit', limit=exc.stop)
