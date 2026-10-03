# CLI, Python API and versioned reports

This is the version 0.1.0 alpha public contract. See
[validation scope](validation.md) for observed tests and support limits.

## CLI

```text
globdelta diff BEFORE AFTER [--format text|json] [--output REPORT] [--limit NAME=VALUE ...]
globdelta explain POLICY PATH [--format text|json] [--output REPORT] [--limit NAME=VALUE ...]
globdelta --version
```

Format defaults to text; output defaults to stdout. Limit options may repeat
with different names; use the [documented fields](resources.md). The two input
files are explicit alternative root-policy contents. Their filenames do not
have to be `.gitignore`. Explain's `PATH` is hypothetical, not an input file.

Production performs no repository discovery, filesystem tree walk, inherited
Git configuration lookup, Git/subprocess execution, network access or policy
rewriting. CLI input is bounded binary reading. SHA-256 covers raw input bytes
before parsing/line-ending normalization. Input file descriptors are read-only.

An explicit report destination is created exclusively; every existing path,
including a symlink, is refused. There is no overwrite flag. This avoids a
check-then-overwrite race and prevents an output alias from overwriting input.
All user-supplied labels, patterns, paths and diagnostic text must be escaped in
terminal output, including filenames with terminal control characters.

## Pure Python interface

```python
from globdelta import Limits, compare_policies, explain_path, parse_policy

parse_result = parse_policy(b"*.log\n!keep.log\n", Limits())
comparison = compare_policies(b"cache\n", b"**/cache\n", Limits())
explanation = explain_path(b"cache/\n", b"cache", Limits())
```

Signatures:

```text
parse_policy(data: bytes, limits: Limits = Limits()) -> ParseResult
compare_policies(before_bytes: bytes, after_bytes: bytes,
                 limits: Limits = Limits()) -> Report
explain_path(policy_bytes: bytes, path_bytes: bytes,
             limits: Limits = Limits()) -> Report
```

`Limits`, results and nested semantic records are immutable typed values. The
core consumes bytes and performs no file I/O. `ParseResult` carries `policy`
(or null), a diagnostic tuple, an optional limit stop and deterministic usage.
A successful parsed `Policy` carries exact raw size, SHA-256 and a tuple of
rules. Parsing failure and resource exhaustion are explicit; neither is an
empty-policy/equivalent sentinel. Comparison and explain use `Report`; explain
includes the effective Boolean decision and causal `Explanation`.

`Report` exposes `result`, `assessment_complete`, `graph_exhausted`,
`newly_ignored`, `newly_included`, `explanation`, `inputs`, `limits`, `usage`,
`stop` and `diagnostics`. Each `Direction` has `status` and optional `witness`;
`Witness.path` is bytes in Python (an ASCII string in JSON). `Explanation`
exposes `ignored`, `basis`, `winning_rule_id` and `first_blocked_ancestor`,
as well as the optional trace and referenced rule table. `Report` and
`ParseResult` types are also top-level exports.

The serialization helpers are `globdelta.report.to_json(report) -> str`,
`to_text(report) -> str` and `exit_code(report) -> int`. Read semantic status,
not truthiness or witness emptiness. Invalid API configuration/programmer
arguments are distinct from a normal unsupported or inconclusive policy result.

## Direction and result invariants

Each diff direction is `found`, `absent` or `unknown`:

- `found`: a concrete witness passed independent interpreter replay
- `absent`: exhaustive reachable-product search established no witness
- `unknown`: unresolved; no absence or equivalence claim is allowed

`newly_ignored` means included before and ignored after. `newly_included` means
ignored before and included after. A found witness includes its ASCII path,
byte length, `minimality: shortest-shortlex`, and both explanations. Unknown
and absent directions never contain a witness. Shortlex means minimum byte
length and then unsigned-byte lexicographic order. Paths can contain spaces.

`result` is equivalent only for absent/absent, different if either direction
is found, and otherwise inconclusive for an unresolved comparison. Invalid
policy syntax or an out-of-profile query is unsupported; I/O/internal failures
are error. Successful explain is explained.

`assessment_complete` means both diff directions are resolved, or that explain
has its decision and mandatory causal explanation. `graph_exhausted` is separate:
both witnesses can be found without exhausting the graph. It is null for
explain. A found/unknown comparison is different and incomplete, exiting 4.

| Exit | Condition |
| --- | --- |
| 0 | Equivalent complete diff; or successful explain, either decision |
| 1 | Different diff with both directions resolved |
| 2 | Invalid invocation or budget configuration |
| 3 | Unsupported syntax/bytes or out-of-profile hypothetical path |
| 4 | Resource-incomplete assessment, including found/unknown |
| 5 | I/O or internal consistency failure |

## JSON schema version 1

[report.schema.json](../schemas/report.schema.json) is the original project
proposal schema, retained unchanged while the implementation is validated.
Conformance requires semantic invariants as well as structural schema checks.
The schema identifier is `urn:globdelta:report:1`; the profile is
`git-root-ascii-v1`, semantics revision 1.

Top-level serialization order is:

1. `schema_version`, `tool`, `profile`, `command`
2. `inputs`, `result`, `assessment_complete`, `graph_exhausted`
3. `directions` for diff; `query` and `explanation` for explain
4. `limits`, `usage`, `stop`, `diagnostics`

Inputs are ordered before/after or a single policy. Records hold role, escaped
or JSON-safe display label, raw bytes read, complete-read flag, exact SHA-256
(null if incomplete), and rule count (null if parsing incomplete). Explain's
query records path and byte length once, so prefix offsets have an unambiguous
base. Explanation rule IDs refer to a shared rule table for that explanation;
the before/after explanation or policy input provides the input-role context.

Rule source references use one-based physical lines and byte columns, and
zero-based half-open raw byte offsets. Explanations distinguish default
inclusion, a direct winning rule, and the first blocked ancestor. Matching rules
are ordered. Terminal matches beneath a blocking ancestor have
`terminal_matches.effective: false`; `basis: blocked_ancestor` explains why.
An optional full trace can be absent without losing the mandatory cause.

Schema validation alone cannot check that a rule reference exists, source spans
are correct, path byte lengths agree, paths satisfy the validity language or
witness decisions actually differ. Tests must check those separately. Required
cross-field invariants include equivalent iff absent/absent, different iff at
least one found, complete iff neither diff direction unknown, graph exhaustion
implies no unknown, and direction-consistent before/after decisions.

A report that cannot fit its output budget uses a bounded failure envelope and
never claims equivalence. See [resources.md](resources.md).
