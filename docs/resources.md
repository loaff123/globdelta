# Resources and inconclusive results

The accepted path language has no maximum component length, total length, or
depth. Resource controls limit a computation, not the language being compared.
Lazy determinization can be exponential in NFA size; two-policy product search
can multiply that growth. No practical completion or speed guarantee follows
from finite-state decidability.

## Limits

Pass a frozen `Limits(...)` instance to the library. The CLI accepts repeated
`--limit NAME=VALUE` options, for example:

```sh
globdelta diff before.gitignore after.gitignore --format json \
  --limit cache_entries=0 --limit product_states=10000
```

Names are exact, case-sensitive Python field names. Values must be integers in
`[0, 2**63 - 1]`. `report_bytes` must be at least 8192 for the failure envelope.
Zero is valid for the other fields, although zero capacity may make a request
immediately inconclusive. Invalid names or values are configuration errors,
not evidence about policy semantics.

| Name | Default | What it bounds |
| --- | ---: | --- |
| `input_bytes` | 65,536 | Input bytes per policy |
| `line_bytes` | 2,048 | Content bytes of a physical line |
| `rules` | 256 | Effective rules per policy |
| `ast_items` | 4,096 | Parsed atoms, components and class items per policy |
| `nfa_states` | 8,192 | NFA states per policy |
| `nfa_edges` | 24,576 | NFA edges per policy |
| `subsets` | 50,000 | Stable interned subsets per policy |
| `product_states` | 50,000 | Distinct visited product keys |
| `transitions` | 4,750,000 | Candidate byte transitions |
| `work` | 20,000,000 | Charged parser/NFA/closure/search work |
| `reference_work` | 20,000,000 | Independent interpreter work for explain |
| `replay_work` | 20,000,000 | Reserved independent witness verification work |
| `cache_entries` | 8,192 | Retained transition-cache entries per policy |
| `payload_bytes` | 67,108,864 | Accounted owned payload and scratch estimates |
| `replay_payload_bytes` | 8,388,608 | Separately reserved replay portion of overall payload capacity |
| `witness_bytes` | 4,096 | Materialized witness or explain-path byte length |
| `explanation_steps` | 4,096 | Optional recorded explanation steps |
| `explanation_matches` | 16,384 | Optional recorded matching-rule IDs |
| `diagnostics` | 64 | Diagnostic items |
| `report_bytes` | 1,048,576 | Encoded report bytes, with an 8192-byte minimum |

These defaults were exercised by the release fixtures in [benchmark-results.json](benchmark-results.json); they are capacity choices, not completion or speed promises.
All effective values and usage counters appear in reports. Scoped usage names
can distinguish before/after policy counters. Peak counters describe a peak
rather than a cumulative allocation count.

## Accounting assumptions

Reserve budget before allocating or expanding owned structures. Account for
input/AST retention, NFA edges/states, closure and transition scratch, interned
subset bitsets, cache entries, product predecessor records, reconstructed
witness bytes and explanation/report materialization. Check multiplied
work/dimension sizes before allocating them. Stable subset identity is not an
evictable cache: removing it would invalidate product-state keys.

Transition-cache saturation may evict an entry rather than stop; the bookkeeping
must remain bounded too. Recomputing the entry consumes work. A zero-size cache
must change only resource use, not decisions. Avoid an unbudgeted all-state,
all-byte closure table. Replay has separate work and payload capacity so normal search work
cannot erase an already discovered direction before independent verification.

Count and logical-byte estimates bound tool-owned data and work. Python object
headers, interpreter/allocator behavior, imported modules and host overhead
vary. These budgets are **not a portable hard process-RSS limit**; use an
external process/container memory limit if that operational guarantee is needed.
Three times `report_bytes` is reserved for report construction, transient encoding
copies and output, and `replay_payload_bytes` is reserved independently for
witness verification. These consume portions of overall payload capacity, so
a payload limit smaller than the required reservations can stop before search.
A separate fixed emergency envelope of at most 8192 encoded bytes exists outside
the adjustable analysis payload limit. If the normal report reserve fails, this
envelope omits unvalidated query text and labels rather than trying a full-size
encoding; it preserves the original failure and discloses the omissions. There is no v1 wall-clock deadline. Limits may be reached before a syntactically
valid input is fully parsed; that is inconclusive, not unsupported syntax.

## Stop semantics

`stop.reason` is `limit` for a resource stop. Its limit record names the counter,
phase, already used amount, requested increment and maximum. Never mark a node
fully explored after only part of its transitions ran. Never turn an unresolved
direction into absent, or return exit 0 after a limit stop.

- No verified witness and unresolved search: `result: inconclusive`
- One verified witness and one unresolved direction: `result: different`,
  `assessment_complete: false`, exit 4
- Both directions resolved: a complete comparison; absence requires exhaustion

A `witness_bytes` limit controls reconstruction/replay and output only. The BFS
cannot drop long paths and claim equivalence over the remaining short ones.
A long-path equivalence proof may need no witness materialization at all.

The raw-byte SHA-256 describes only complete input. For an input that could not
be completely read, report `complete_read: false`, `sha256: null` and only the
bytes actually read. `rule_count` is null when parsing was incomplete. Never
fabricate metadata for an unread suffix.

## Bounded reports

Reports remain complete JSON documents, including on failure. Check encoded
size before adding output fragments; do not cut a JSON string or append a
truncation marker to a partial document. Optional explanation traces may be
omitted with `trace_complete: false` while keeping the verified decision and
mandatory causal rule/blocker. Diagnostic truncation is explicit as well.

If the required report and verified witnesses cannot fit, use a reserved
minimal failure envelope. This is not a complete semantic assessment. The
output budget must not cause an incomplete report to masquerade as equivalent.
Text and JSON share the same conclusion and completeness semantics.
