"""Immutable byte-language and reference-decision records."""
from dataclasses import dataclass

ASCII_MASK = (1 << 95) - 1
SLASH_MASK = 1 << (47 - 32)
COMPONENT_MASK = ASCII_MASK ^ SLASH_MASK

@dataclass(frozen=True, slots=True)
class Span:
    role: str
    line: int
    column_start: int
    column_end_exclusive: int
    byte_start: int
    byte_end: int

@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    location: Span | None = None

@dataclass(frozen=True, slots=True)
class LimitStop:
    name: str
    phase: str
    used: int
    requested_increment: int
    maximum: int

@dataclass(frozen=True, slots=True)
class Atom:
    mask: int
    repeat: bool = False

@dataclass(frozen=True, slots=True)
class Component:
    atoms: tuple[Atom, ...]
    globstar: bool = False

@dataclass(frozen=True, slots=True)
class Rule:
    index: int
    span: Span
    source: bytes
    include: bool
    directory_only: bool
    anchored: bool
    components: tuple[Component, ...]

    @property
    def basename(self) -> bool:
        return not self.anchored and len(self.components) == 1

@dataclass(frozen=True, slots=True)
class Policy:
    raw_size: int
    sha256: str
    rules: tuple[Rule, ...]

@dataclass(frozen=True, slots=True)
class ParseResult:
    policy: Policy | None
    diagnostics: tuple[Diagnostic, ...] = ()
    stop: LimitStop | None = None
    usage: tuple[tuple[str, int], ...] = ()

@dataclass(frozen=True, slots=True)
class Step:
    prefix_end: int
    node_type: str
    matching_rule_ids: tuple[int, ...]
    winning_rule_id: int | None
    ignored: bool

@dataclass(frozen=True, slots=True)
class BlockedAncestor:
    prefix_end: int
    winning_rule_id: int

@dataclass(frozen=True, slots=True)
class Explanation:
    ignored: bool
    basis: str
    winning_rule_id: int | None
    first_blocked_ancestor: BlockedAncestor | None
    rule_table: tuple[Rule, ...]
    steps: tuple[Step, ...]
    trace_complete: bool
    terminal_effective: bool
    terminal_matching_rule_ids: tuple[int, ...]

@dataclass(frozen=True, slots=True)
class Witness:
    path: bytes
    before: Explanation
    after: Explanation
    minimality: str = 'shortest-shortlex'

@dataclass(frozen=True, slots=True)
class Direction:
    status: str = 'unknown'
    witness: Witness | None = None

    def __post_init__(self):
        if self.status not in ('found', 'absent', 'unknown') or (self.status == 'found') != (self.witness is not None):
            raise ValueError('direction status and witness disagree')

@dataclass(frozen=True, slots=True)
class Stop:
    reason: str
    limit: LimitStop | None = None

@dataclass(frozen=True, slots=True)
class SearchResult:
    newly_ignored: Direction
    newly_included: Direction
    graph_exhausted: bool
    stop: Stop
    error: str | None = None
    replay_usage: tuple[tuple[str, int], ...] = ()

@dataclass(frozen=True, slots=True)
class Input:
    role: str
    label: str
    raw_bytes_read: int
    complete_read: bool
    sha256: str | None
    rule_count: int | None

@dataclass(frozen=True, slots=True)
class Report:
    command: str
    inputs: tuple[Input, ...]
    result: str
    assessment_complete: bool
    graph_exhausted: bool | None
    limits: 'Limits'
    usage: tuple[tuple[str, int], ...]
    stop: Stop
    diagnostics: tuple[Diagnostic, ...] = ()
    diagnostics_truncated: bool = False
    newly_ignored: Direction | None = None
    newly_included: Direction | None = None
    query: bytes | None = None
    explanation: Explanation | None = None

# Runtime imports avoid a model↔budget cycle; typing tools still see the type.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .budget import Limits
