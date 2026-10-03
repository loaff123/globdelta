# Validation status and oracle methodology

## Local release evidence

Version 0.1.0 is an alpha source release. Local validation completed on
3 October 2026 on Linux with Python 3.12.14 and Git 2.52.0. The implementation
was checked with the following finite campaigns:

- Full source suite: 90 tests passed, no skips (59.342 seconds)
- Separate independent source run: the same 90 tests passed (60.969 seconds)
- Standard setuptools 84.0.0 / wheel 0.48.0 build with `--no-index`,
  `--no-build-isolation`, and `--no-deps`
- Fresh virtual environment, offline wheel installation, no runtime dependencies
- Full installed-wheel suite: 90 tests passed (58.239 seconds)
- Installed CLI runner: four comparisons, 23 explain decisions, exclusive-output
  creation/refusal all passed; [captured reports](executed-examples.json)
- Git archive replay: 27,399 actual-file queries across 84 path, 376 grammar and
  46 additional fixture rows; 400 strict-profile accepted rows / 17,790 queries
  agree with the interpreter, and 106 unsupported rows are explicitly rejected
- Reduced finite universe: 157 ordered policies × 42 paths = 6,594 queries
- Seeded accepted-AST/raw-grammar campaign: 80 policies × 32 paths = 2,560 queries;
  256 malformed/invalid-byte cases reject reproducibly
- Generated comparison campaign: 237 policy pairs, 246 witnesses checked under
  both policies (492 Git queries), 228 absent directions, zero unknown directions
- Independent automata probes: 3,051,888 direct-language/tag cases and 71,302
  validity checks; independent product review covered 400 policy pairs and
  750,636 interpreter evaluations
- Every adjustable budget received before/at/after or applicable zero/saturation
  checks. Limits preserve found/unknown and never fabricate absence
- Actual Draft 2020-12 schema verification (jsonschema 4.26.0, development-only)
  and 1,500 seeded schema-checker mutations. The shipped suite uses a fail-closed
  standard-library checker and needs no jsonschema package
- Independent code review found no remaining critical or important issue in
  parser/reference, automata/search, or API/report/CLI release contracts
- [Seven measured default-limit fixtures](benchmarks.md), including two explicit
  20-million-work stops, record deterministic usage and observed wall/RSS

These are finite empirical checks and implementation reviews, not universal
Git conformance. The profile and finite-state argument remain the scope of any
complete equivalence result. The hosted Ubuntu 24.04 matrix targets Python
3.11–3.14; inspect [the run for your exact commit](https://github.com/loaff123/globdelta/actions/workflows/ci.yml).
No package-registry publication is claimed.

## Independent actual-file Git oracle

Tests create disposable Linux repositories with an empty template, empty index
and empty `info/exclude`. They disable global/system configuration, use an empty
global excludes file, set `LC_ALL=C` and `core.ignoreCase=false`, and make the
fixture filesystem protection settings explicit. The oracle does not import
production parsing or matching routines.

Every candidate's parents are actual directories and every terminal target is
a regular file. Root `.gitignore` is the policy file and must not be overwritten
as fixture data. A terminal nested `.gitignore` is empty. Nested `.gitignore`
directories are permitted by the profile. Never create `.git` components or
touch repository metadata as a test target.

The verbose command is:

```text
git check-ignore --no-index --stdin -z --verbose --non-matching
```

Queries have NUL framing and a `./` prefix, protecting colon-leading names from
pathspec interpretation. Parse four NUL-terminated output fields per query:
source, line, pattern and path. A verbose successful exit alone does not mean
ignored: a winning negated pattern means included. Cross-check each result with
the independent single-path quiet form, where exit 0 means ignored and exit 1
means included. Any missing executable, failed command or bad framing fails the
mandatory conformance run rather than skipping it.

Targets of different depths can collide as file versus directory. Group paths
by depth and rebuild the fixture tree between groups; equal-depth targets form
an antichain. A theoretically valid path which the host cannot materialize is
unvalidated there, never a passing Git query. Mandatory witness campaigns use
materializable sizes; long-input tests use the independent interpreter and
explicit finite-state reasoning without shrinking the semantic domain.

## Reproducible finite campaigns

See [the campaign manifest](../tests/fixtures/CAMPAIGNS.md) for fixture
provenance, declared raw classifications and detailed generation methodology.

The reduced-alphabet campaign in `tests/git_campaigns.py` uses bytes `a` and
`b`, component lengths 1–2 and path depths 1–2: six component words and 42 paths.
Its 12-rule vocabulary is `a`, `!a`, `b/`, `!b/`, `*`, `!a/`, `/a`, `a/*`,
`a/**`, `**/b`, `a/**/b`, `[ab]`. Ordered policies of length 0–2 yield
`1 + 12 + 12**2 = 157` policies and `157 * 42 = 6594` policy/path queries.
These are exhaustive only for that explicitly finite universe.

The random-policy generator uses a test-only AST and independent raw rendering
with whitespace, quoting, bracket forms, comments and line-ending variations.
The declared seeds are `0x6C0B2026` for accepted-policy generation and
`0xBAD52026` for invalid-input fuzzing. The observed campaign has 80 generated policies, exactly 32 unique paths per
policy (2,560 queries), and 256 invalid cases. Those counts are asserted by the
checked-in campaign tests. Expected semantic decisions come from real Git, not the
production parser/NFA. Mismatches require shrinking and an explicit fix/review.

Record Git executable/version, environment overrides, seeds, full policy bytes,
query path/type, oracle result and fixture digest. Every emitted witness in
materializable generated tests must be queried under both policies with Git.
Raw-byte parser fixtures are separately important because a shared parsed AST
can hide a parser bug from both matching engines.

## Support and interpretation

Local validation covers Linux, Python 3.12.14 and Git 2.52.0. The hosted matrix
targets additional Python versions, but does not validate Windows/macOS filesystems or
arbitrary Git versions. The runtime is pure Python; abstract paths still need
not be creatable on a particular filesystem.

The repository includes the implementation, mandatory oracle corpus/generators,
three example workflows, versioned schema, resource contract and reproducible
offline build/test commands. Tests fail when Git is absent or disagrees; they
do not silently skip the independent oracle.

A green finite suite is empirical evidence. The scoped equivalence argument is
in [correctness.md](correctness.md); faithful implementation remains a separate
review obligation.
