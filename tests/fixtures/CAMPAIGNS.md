# Reproducible Git conformance campaigns

These are finite conformance campaigns, not a proof that arbitrary Git behavior
belongs to the profile. The engine's proof claim is separately scoped to
`git-root-ascii-v1`. Production modules never import the Git harness.

Run all checks from the repository root:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

Git is a mandatory test dependency. No test is silently skipped when Git is
missing, a command fails, framing is malformed, or a generated accepted policy
is rejected. The oracle creates disposable repositories and actual untracked
regular files. Equal component-depth target batches are antichains; the work
file tree is rebuilt between depths. Thus `a` and `a/b` are never accidentally
both tested as directories. The root `.gitignore` retains the supplied policy;
terminal nested `.gitignore` files are empty. `.git` components and a root
`.gitignore/` prefix are refused before any file write.

The independent harness strips every inherited `GIT_*` variable, uses an empty
repository template and index, empties `info/exclude`, isolates HOME/XDG config,
disables system/global Git config and global/system attributes/excludes, fixes
`LC_ALL=C`, and sets `core.ignoreCase=false`. NTFS/HFS protections and Unicode
precomposition are disabled for the Linux fixture filesystem. Git command
errors fail the run. The narrowly expected warning for an allowed nested
directory named `.gitignore` is recognized; unrelated warnings fail.

Each depth batch uses NUL stdin with `./` path prefixes and:

```sh
git check-ignore --no-index --stdin -z --verbose --non-matching
```

Exactly four NUL-terminated fields are required for each path; the returned path
must equal its query. The Boolean is exclusion only if the record names a
winning rule whose raw pattern does not begin with `!`. Every individual query
is also run through `git check-ignore --no-index --quiet -- ./PATH`. In particular,
a verbose exit of zero for an include rule is not classified as exclusion.

Paths in mandatory campaigns are materializable on the fixture Linux host.
If a valid abstract path exceeds filesystem capabilities, the oracle raises an
explicit `UnmaterializablePath` error and does not count it as checked. This does
not narrow the engine's abstract language. A separate oracle contract test
exercises this distinction using an oversized component.

## Archived evidence

`design_cases.json` contains raw policy hex, raw ASCII paths, expected ignored
Booleans, and explicit normative accepted/rejected classifications. All archived
query decisions are rechecked in Git, including unsupported policies. Production
parser/reference checks are separate: every accepted row must parse and match
every saved decision; every rejected row must return diagnostics and no policy.
No production parse result is used to derive the expected classification.

| Archived campaign | Policy/case rows | Accepted | Rejected | Git queries | Accepted queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Path probe | 84 | 84 | 0 | 84 | 84 |
| Main grammar | 351 | 256 | 95 | 22,569 | 14,841 |
| Supplement grammar | 25 | 15 | 10 | 4,700 | 2,820 |
| Proof fixtures | 46 | 45 | 1 | 46 | 45 |
| Total | 506 | 400 | 106 | 27,399 | 17,790 |

The recorded fixture Git version was 2.52.0. This repository ships the complete
compact corpus needed to rerun every query; no external archive is required.
Raw policy bytes, path strings, saved decisions and normative rejection reasons
are retained. Classifications were reviewed against the normative grammar
before replaying the production parser. Exploratory names such as
`accepted_edge` do not override the stricter normative class grammar.

Compact fixture SHA-256:
`e35789bfdb1e13c41b6bc2e15df14f31f697440dc9db2a22eb4f1fff19103f52`

## Exhaustive reduced universe

Component alphabet: `{a,b}`. Every word of length one or two is included:
`a`, `b`, `aa`, `ab`, `ba`, `bb`. Every one- or two-component path is included:
6 + 36 = 42 paths.

Fixed ordered-rule vocabulary (12 rules):
`a`, `!a`, `b/`, `!b/`, `*`, `!a/`, `/a`, `a/*`, `a/**`, `**/b`, `a/**/b`, `[ab]`.

Every ordered policy of length 0, 1, or 2 is included, with duplicates permitted:
1 + 12 + 144 = 157 policies. This yields exactly 6,594 actual-file query checks,
each with an independent quiet crosscheck. Exhaustiveness applies only to this
stated finite universe.

Input SHA-256:
`583f7078141d4dc6773855b80d4c59559d588cc78ef0bd9ff4b7dfa2c05d1997`

## Seeded accepted policies

Seed: `0x6c0b2026` (1812668454). Exactly 80 policies, 32 paths each, 2,560 queries.
A test-only AST generates literal atoms, `?`, `*`, conservative bracket classes,
whole-component globstars, root markers, directory markers and include/exclude
rules. Raw rendering varies literal escaping, equivalent class notation,
trailing spaces, LF/CRLF, omitted final newline, comments and blank lines.
Constructive samples from generated patterns join random paths. Expected
Booleans come only from Git, never the test AST.

Input SHA-256:
`193d03e088fe797323c9fca7b3280b9620c78ce22af8a60851bc3839396f5847`

A mismatch triggers a greedy deletion reducer over rule lines, policy bytes,
path components and path bytes. Unsupported policy candidates are not used as
reproductions. The failure prints original and reduced raw hex, case index,
seed and actual Git version. Reduction promises a deletion-minimal helpful
reproduction, not a globally smallest counterexample.

## Seeded rejected input

Seed: `0xbad52026` (3134529574). Exactly 256 invalid cases alternate invalid
physical bytes (including in comments) with unsupported/malformed patterns.
Each is parsed twice; both immutable results must agree, contain diagnostics,
and contain neither a policy nor a resource stop.

Input SHA-256:
`62459b1f904db4de7b1c247fb4af0f06f9887bfe043aa71c7c50a5f10eb5f152`

## Digest framing and results

Campaign input hashes are over each policy followed by its ordered paths. Each
byte string has an unsigned eight-byte big-endian length prefix; each policy
record ends with eight `0xff` bytes. Invalid input uses the same format with no
paths. Tests assert these input hashes so accidental input drift is visible.

Runtime output reports actual Git executable/version, isolation configuration,
query counts, seeds, input digests and generated decision digests. Decision
hashes concatenate `(policy, path, single Boolean byte)` for every checked query,
with an unsigned eight-byte big-endian length prefix before each field.

The helper `GitOracle.verify_witness(before, after, path, direction)` checks every
materializable comparison witness under both alternative policies and fails if
its claimed direction is wrong. It never treats the engine's own explanation
as an oracle result.

To keep a complete append-only JSONL evidence ledger of raw policy/path hex,
source line/pattern, file type, Boolean decisions, both return codes and the
isolated executable/configuration, select an output location explicitly:

```sh
GLOBDELTA_ORACLE_LEDGER=/tmp/globdelta-oracle.jsonl \
  PYTHONPATH=src python -m unittest tests.test_git_conformance -v
```

On Git 2.52.0 the finite decision SHA-256 is
`2bbaeb34d3ad15417e77b99861762ae122c96e37c974c126a5fbb61d3f61addd`;
the seeded accepted-policy decision SHA-256 is
`1460f57abda4da73a08b29c55e24c964e95a44e2dbcf30316eba4d4f2eaa0363`.

## Generated comparison witnesses

The comparison campaign forms adjacent cyclic pairs separately within the 157
finite policies and 80 random policies. Every generated policy appears once as
before and once as after: exactly 237 comparisons, not every possible pair.
Every emitted witness is materialized and checked under both policies, including
witnesses retained in partial results. Search is bounded by 1,500 product states,
150,000 transitions and 500,000 work units. Unresolved directions are reported as
unknown; these bounds never become path-length/depth restrictions.

In addition, every found witness emitted by `tests/test_search.py` goes through
the same two-policy actual-file Git oracle, including the ancestor-regression,
space witness, two directions, shortlex tests and found/unknown limit test.

Recorded comparison result on Git 2.52.0: 237 comparisons, 246 found witnesses,
228 absent directions, zero unknown directions, and 492 Git queries for the
witnesses. Tests assert those results and the digests below. Limits are allowed
to change only with an explicit campaign update, never by silently skipping a
witness or reclassifying an unsupported input.

Pair input SHA-256:
`8f07a2051b9e88d1904ee83a9c5dee9721d82822d9f200bf8556f2b78e36b4fc`

Comparison outcome SHA-256:
`3cd230a4f51a55164de34e1f53016365e41a4aac5b63cb05177b1afa0b887e16`

Outcome framing hashes length-prefixed before policy, after policy, direction
name and status, then a length-prefixed path for each found direction, in the
published policy-pair order (`newly_ignored`, then `newly_included`).

The same 237 pairs also run through the public `compare_policies` API; its two
directional statuses and witness bytes must equal the direct search results.
Because both results name the identical raw policy pair and path, one Git replay
of each witness validates both claims. Separate API integration tests verify the
three documented workflows and the `cache/` versus `cache` file-type contrast,
with all found paths checked against Git.
