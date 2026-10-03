"""Original tagged epsilon NFA and bounded lazy subset construction."""
from dataclasses import dataclass
from .budget import Budget
from .model import COMPONENT_MASK, Policy, Rule, SLASH_MASK

@dataclass(frozen=True, slots=True)
class NFA:
    consuming: tuple[tuple[tuple[int, int], ...], ...]
    epsilon: tuple[tuple[int, ...], ...]
    tags: tuple[tuple[Rule, ...], ...]
    scope: str


def compile_policy(policy: Policy, budget: Budget, scope: str = 'policy') -> NFA:
    consuming: list[list[tuple[int, int]]] = []
    epsilon: list[list[int]] = []
    tags: list[list[Rule]] = []
    def state() -> int:
        budget.charge('nfa_states', 1, 'compile', scope)
        budget.retain(96, 'compile')
        number = len(consuming)
        consuming.append([]); epsilon.append([]); tags.append([])
        return number
    def edge(source: int, target: int, mask: int | None = None) -> None:
        budget.charge('nfa_edges', 1, 'compile', scope)
        budget.retain(40, 'compile')
        if mask is not None:
            consuming[source].append((mask, target))
        else:
            epsilon[source].append(target)
    def any_prefix(cursor: int) -> int:
        # (C+/)*: the cursor is both entry and exit, with one branch per
        # complete nonempty component. It may coexist with the next atom.
        middle = state()
        edge(cursor, middle, COMPONENT_MASK)
        edge(middle, middle, COMPONENT_MASK)
        edge(middle, cursor, SLASH_MASK)
        return cursor
    start = state()
    for rule in policy.rules:
        cursor = state()
        edge(start, cursor)
        if rule.basename:
            any_prefix(cursor)
        for index, component in enumerate(rule.components):
            final = index == len(rule.components) - 1
            if component.globstar:
                if rule.basename:
                    edge(cursor, cursor, COMPONENT_MASK)
                elif final:
                    # C+(/C+)*. The entry cannot accept; each slash must be
                    # followed by a component byte before reaching the exit.
                    end = state()
                    edge(cursor, end, COMPONENT_MASK)
                    edge(end, end, COMPONENT_MASK)
                    edge(end, cursor, SLASH_MASK)
                    cursor = end
                else:
                    any_prefix(cursor)
            else:
                for atom in component.atoms:
                    if atom.repeat:
                        edge(cursor, cursor, atom.mask)
                    else:
                        end = state()
                        edge(cursor, end, atom.mask)
                        cursor = end
                if not final:
                    end = state()
                    edge(cursor, end, SLASH_MASK)
                    cursor = end
        budget.retain(8, 'compile')
        tags[cursor].append(rule)
    # Conversion temporarily coexists with the construction lists.
    with budget.scratch(24 * len(consuming) + 16 * sum(map(len, consuming)) + 8 * sum(map(len, epsilon)), 'compile_freeze'):
        return NFA(tuple(tuple(row) for row in consuming), tuple(tuple(row) for row in epsilon), tuple(tuple(row) for row in tags), scope)


class Matcher:
    """Interned subsets have permanent identities; only transitions evict."""
    def __init__(self, nfa: NFA, budget: Budget):
        self.nfa = nfa
        self.budget = budget
        self.width = 32 + (len(nfa.consuming) + 7) // 8
        self.subsets: list[int] = []
        self.ids: dict[int, int] = {}
        self.outputs: list[tuple[bool, bool]] = []
        self.cache: dict[tuple[int, int], int] = {}
        self.start = self._intern(self._closure(1))

    def _closure(self, seeds: int) -> int:
        with self.budget.scratch(5 * self.width, 'closure'):
            seen = seeds
            pending = seeds
            while pending:
                bit = pending & -pending
                pending ^= bit
                self.budget.charge('work', 1, 'closure')
                for target in self.nfa.epsilon[bit.bit_length() - 1]:
                    self.budget.charge('work', 1, 'closure_edge')
                    target_bit = 1 << target
                    if not seen & target_bit:
                        seen |= target_bit
                        pending |= target_bit
            return seen

    def _intern(self, subset: int) -> int:
        existing = self.ids.get(subset)
        if existing is not None:
            return existing
        self.budget.charge('subsets', 1, 'determinize', self.nfa.scope)
        self.budget.retain(self.width + 96, 'determinize')
        file_rule = directory_rule = None
        with self.budget.scratch(3 * self.width, 'determinize_outputs'):
            pending = subset
            while pending:
                bit = pending & -pending
                pending ^= bit
                self.budget.charge('work', 1, 'tag_scan')
                for rule in self.nfa.tags[bit.bit_length() - 1]:
                    self.budget.charge('work', 1, 'tag_scan')
                    if directory_rule is None or rule.index > directory_rule.index:
                        directory_rule = rule
                    if not rule.directory_only and (file_rule is None or rule.index > file_rule.index):
                        file_rule = rule
        number = len(self.subsets)
        self.subsets.append(subset)
        self.outputs.append((bool(file_rule and not file_rule.include), bool(directory_rule and not directory_rule.include)))
        self.ids[subset] = number
        return number

    def step(self, identity: int, byte: int) -> int:
        if not 32 <= byte <= 126:
            raise ValueError('matcher transitions require printable ASCII')
        key = (identity, byte)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        with self.budget.scratch(5 * self.width, 'transition'):
            pending = self.subsets[identity]
            seeds = 0
            mask = 1 << (byte - 32)
            while pending:
                bit = pending & -pending
                pending ^= bit
                self.budget.charge('work', 1, 'transition_state')
                for edge_mask, target in self.nfa.consuming[bit.bit_length() - 1]:
                    self.budget.charge('work', 1, 'transition_edge')
                    if edge_mask & mask:
                        seeds |= 1 << target
            result = self._intern(self._closure(seeds))
        capacity = self.budget.limits.cache_entries
        if capacity:
            if len(self.cache) == capacity:
                del self.cache[next(iter(self.cache))]
            else:
                self.budget.retain(64, 'transition_cache')
            self.cache[key] = result
            count_key = f'{self.nfa.scope}.peak_cache_entries'
            self.budget.counters[count_key] = max(len(self.cache), self.budget.counters.get(count_key, 0))
        return result

    def ignored(self, identity: int, directory: bool) -> bool:
        return self.outputs[identity][int(directory)]
