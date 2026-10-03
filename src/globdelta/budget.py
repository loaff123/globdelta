"""Deterministic logical limits, charged before owned allocations and work.

Payload charges deliberately overestimate owned packed data. They do not claim
that Python object overhead or host RSS is portable across interpreters.
"""
from contextlib import contextmanager
from dataclasses import dataclass, fields
from .model import LimitStop

@dataclass(frozen=True, slots=True)
class Limits:
    input_bytes: int = 65_536
    line_bytes: int = 2_048
    rules: int = 256
    ast_items: int = 4_096
    nfa_states: int = 8_192
    nfa_edges: int = 24_576
    subsets: int = 50_000
    product_states: int = 50_000
    transitions: int = 4_750_000
    work: int = 20_000_000
    reference_work: int = 20_000_000
    replay_work: int = 20_000_000
    replay_payload_bytes: int = 8_388_608
    cache_entries: int = 8_192
    payload_bytes: int = 67_108_864
    witness_bytes: int = 4_096
    explanation_steps: int = 4_096
    explanation_matches: int = 16_384
    diagnostics: int = 64
    report_bytes: int = 1_048_576

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if type(v) is not int or not 0 <= v <= 2**63 - 1:
                raise ValueError(f'{f.name} must be an integer in [0, 2^63-1]')
        if self.report_bytes < 8_192:
            raise ValueError('report_bytes must be at least 8192 for the failure envelope')

class LimitExceeded(Exception):
    def __init__(self, stop: LimitStop):
        self.stop = stop
        super().__init__(stop.name)

class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.counters: dict[str, int] = {}
        self.retained = 0
        self.peak = 0

    def charge(self, name: str, amount: int = 1, phase: str = 'analysis', scope: str = '') -> None:
        if amount < 0:
            raise ValueError('negative budget charge')
        key = f'{scope}.{name}' if scope else name
        used = self.counters.get(key, 0)
        maximum = getattr(self.limits, name)
        if amount > maximum - used:
            raise LimitExceeded(LimitStop(key, phase, used, amount, maximum))
        self.counters[key] = used + amount

    def check(self, name: str, amount: int, phase: str) -> None:
        maximum = getattr(self.limits, name)
        if amount > maximum:
            raise LimitExceeded(LimitStop(name, phase, 0, amount, maximum))
        self.counters[f'peak_{name}'] = max(amount, self.counters.get(f'peak_{name}', 0))

    def retain(self, amount: int, phase: str) -> None:
        if amount < 0:
            raise ValueError('negative payload')
        if amount > self.limits.payload_bytes - self.retained:
            raise LimitExceeded(LimitStop('payload_bytes', phase, self.retained, amount, self.limits.payload_bytes))
        self.retained += amount
        self.peak = max(self.peak, self.retained)

    def release(self, amount: int) -> None:
        self.retained -= amount
        if self.retained < 0:
            raise AssertionError('unbalanced payload accounting')

    @contextmanager
    def scratch(self, amount: int, phase: str):
        self.retain(amount, phase)
        try:
            yield
        finally:
            self.release(amount)

    def usage(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted((*self.counters.items(), ('peak_payload_bytes', self.peak))))
