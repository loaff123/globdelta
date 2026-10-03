# Correctness argument and implementation invariants

This argument applies only to [git-root-ascii-v1](profile.md). Finite tests and a
sound algorithm design do not, by themselves, prove that an implementation is
correct. The implementation needs independent review of every invariant below.
The current evidence status is in [validation.md](validation.md).

## Independent reference interpreter

The reference evaluator matches component atoms with iterative dynamic
programming, then matches whole components and globstars. It does not call the
NFA, lazy subset, or product-search code and imports no external matcher.
DP dimensions and work are checked against budgets before allocation.

For `c1/.../ck`, each proper prefix is evaluated as a directory, in order.
All applicable rules are considered, and the last matching rule wins. Positive
rules ignore; negated rules include; no matching rule includes by default.
Filter by directory/file applicability before selecting the maximum rule index.
The first ignored directory is the blocking ancestor. Otherwise the terminal
node is evaluated as a regular file.

Every directory uses the final ordered policy. Rules do not mutate an ongoing
traversal as they are read. Thus a later rule can reopen an ancestor when that
rule actually matches that ancestor, but a descendant exception cannot reopen
an ancestor which the final policy still ignores.

Explanations give prefix-end byte offsets, directory/file type, ordered matching
rule IDs, winning rule, ignored decision and first blocker. Source rules retain
physical line/byte positions. Optional terminal matches below a blocker are
ineffective; their inclusion cannot change the effective decision. Optional
traces may be omitted with `trace_complete: false`; the causal winner/blocker
remains required for a successful result.

## Tagged NFAs and stable subsets

Each accepted atom is regular over a fixed finite ASCII alphabet. Thompson-style
fragments compose these languages, the supported globstars and the implicit
basename prefix. Each rule's accepting tag carries its index, polarity and
node-type applicability. The combined epsilon-NFA has a union start state.
No suffix is appended merely to imply descendant exclusion: directory traversal
is modeled separately.

An interned subset is an immutable bitset of every NFA state reachable after
exactly the consumed prefix, including epsilon closure. Separate file and
directory winners apply type filtering before rule ordering. Subset IDs remain
stable as long as search keys refer to them. Transitions are pure functions of
subset and byte. A bounded transition cache may evict entries; it may not evict
or reuse interned subset identities. Recomputed transitions consume work again.
Consuming-edge byte masks and NFA-state subset bitsets are different objects.

## Directory latch

A policy state is an unblocked subset ID or absorbing `BLOCKED`. Before a slash,
first require the validity automaton to accept the separator. If already
blocked, stay blocked. Otherwise inspect the current subset's directory winner:
ignore enters `BLOCKED`; include advances the matcher through the slash.
Non-slash bytes advance only unblocked matchers. At a valid file EOF, blocked
means ignored; otherwise consult the subset's file winner.

Inductively, immediately after each slash, the latch says exactly whether an
already completed proper directory prefix is ignored. This proves the effective
file-output invariant. Never latch at a partial component based on its possible
file-EOF decision: ignoring `a` does not prevent later bytes from making `ab`
which a later rule includes.

## Finite valid-path machine

A finite dangerous-prefix trie tracks empty/nonempty components, first versus
later components and exact prefixes of `.`, `..`, `.git`, and root-only
`.gitignore`. Once no forbidden spelling can result without a separator, a
safe-other state is enough. It never stores the unbounded component name.

Separator/EOF checks reject empty, `.`, `..` and `.git` components. A separator
also rejects root `.gitignore`; EOF permits it. Do not kill an intermediate
`.git` state: appending `x` makes `.gitx` valid. Nested `.gitignore` directories
are permitted. A dead validity transition is discarded before matcher work and
cannot latch either policy.

## Product BFS and shortlex witnesses

The complete visited key is exactly `(before_state, after_state, validity_state)`.
No full path, ancestor name, rule history or absolute depth belongs in the key.
One predecessor ID and incoming byte per discovered state suffice for
reconstruction. Depth can be bounded integer metadata outside the key.

Starting with both epsilon closures and the validity start, visit states with a
FIFO queue and enumerate bytes in ascending order from 0x20 through 0x7e.
At every valid file EOF, test the two directional differences. The first witness
in each direction is shortest in byte length and then unsigned-byte
lexicographically first. Reconstruct and replay that witness independently under
both policies before labeling its direction found. A replay mismatch is an
internal error, never a returned witness.

Two prefixes reaching the same full product key have exactly the same possible
valid suffixes and outputs. The first BFS representative is no longer, and is
shortlex-first among equally long representatives. Discarding later paths to
that key cannot hide a better witness. This is the reason finite state merging
is valid without a path-depth cutoff.

If the two NFAs have nA and nB states, and the validity machine has k states, a
coarse product bound is `k * (2**nA + 1) * (2**nB + 1)`, including the absorbing
blocked states. Exhaustive reachability is finite; exponential growth can still
make it impractical. Exhaustion establishes absence for each direction without
a witness, over the whole abstract profile. Finite conformance campaigns alone
do not establish this theorem.

Stop successfully when both witnesses have been found (the assessment is
complete although the graph need not be exhausted), or when the graph is
exhausted (remaining directions are absent). On a budget stop, keep independently
verified witnesses and mark every unresolved direction unknown. A materialized
witness length cap must never prune the language and then certify equivalence.

## Review obligations

Review parser acceptance/raw-byte spans, component and globstar compilation,
epsilon closure, applicability-before-ordering, validity boundary transitions,
slash-time latching, full product-key identity, FIFO/byte order, independent
replay, and every allocation/stop boundary. Unexplained disagreements with the
accepted profile block a release. The theoretical argument and empirical test
coverage are deliberately reported separately.
