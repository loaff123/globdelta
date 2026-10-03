# GlobDelta

Find a hypothetical regular-file path whose ignored status changes between two
explicit root `.gitignore` policies, or establish that they are **equivalent
within `git-root-ascii-v1`** when the finite-state search finishes.

GlobDelta is an offline command-line tool and Python library. It compares the
policies' effects over its entire declared abstract path language, including
paths that do not exist yet. It does not scan a working tree. Every reported
change witness is checked with an independent interpreter before release.

**Status:** version 0.1.0, alpha. Local validation passed 90 tests from source
and the same 90 tests against an offline-installed wheel on Linux, Python
3.12.14 / Git 2.52.0. All installed example workflows passed. See the
[CI runs](https://github.com/loaff123/globdelta/actions/workflows/ci.yml),
[captured reports](docs/executed-examples.json), and
[validation scope](docs/validation.md). No universal Git-conformance,
cross-platform filesystem-conformance, or general performance claim is made.

## A rule change that hides an exception

Before:

```gitignore
/build/*
!/build/keep.txt
```

After:

```gitignore
/build/
!/build/keep.txt
```

```sh
globdelta diff examples/ancestor/before.gitignore examples/ancestor/after.gitignore
globdelta explain examples/ancestor/after.gitignore build/keep.txt --format json
```

Expected result: the shortest newly ignored witness is `build/keep.txt`.
The changed first rule excludes directory `build`; the later exception cannot
reopen that blocked ancestor. There is no newly included path. A complete
comparison that finds a change exits 1, so this command intentionally fails a
zero-only CI gate.

See [three complete workflows](examples/README.md) for ancestor blocking,
ordered negation, and the equivalence of `cache` and `**/cache`, with a file-type
contrast. Shortest witnesses are ordered by byte length, then unsigned ASCII
lexicographic order. A one-space filename can be the correct shortest witness;
reports quote and escape paths rather than replacing them with friendlier ones.

## Install from source

Requires Python 3.11+. Linux is the validated development/oracle platform; the
pure-Python runtime has no third-party dependencies. This is a source release,
not a claim of availability on PyPI.

```sh
git clone https://github.com/loaff123/globdelta.git
cd globdelta
python -m venv .venv
. .venv/bin/activate
python -m pip install .
globdelta --version
globdelta diff examples/cache/before.gitignore examples/cache/after.gitignore
```

The ordinary install can download standard build tools from the configured
package index. Once installed, GlobDelta runs offline. For an offline build and
installation, provision the tools first and use the commands below.

## Build and install offline

Requires Python 3.11+. Runtime dependencies: none. The standard build backend
is `setuptools.build_meta`; provision setuptools 84.0.0+ and wheel 0.48.0+ in the
build environment beforehand. No custom wheel builder or installation hook is
used. With those build tools already present:

```sh
python -m pip wheel --no-build-isolation --no-deps --no-index . --wheel-dir dist
python -m venv /tmp/globdelta-clean
/tmp/globdelta-clean/bin/python -m pip install --no-index --no-deps dist/globdelta-0.1.0-py3-none-any.whl
/tmp/globdelta-clean/bin/globdelta --version
```

Use an unused virtual-environment path. The wheel build and clean installation
need no package index. See [development and CI](docs/development.md) for the
mandatory Git-based tests and installed-command checks.

## Commands

```text
globdelta diff BEFORE AFTER [--format text|json] [--output REPORT] [--limit NAME=VALUE ...]
globdelta explain POLICY PATH [--format text|json] [--output REPORT] [--limit NAME=VALUE ...]
globdelta --version
```

The default format is `text`; the default destination is standard output.
`PATH` is a hypothetical relative regular-file path, never a file to open.
Each input is explicitly named and read as bytes; its exact content is hashed
before parsing. An output file is created exclusively: every existing path,
including a symlink, is refused. There is no overwrite flag. Reports can contain
input filenames, policy rules, hashes and hypothetical paths; review them before
sharing them outside your project.

Examples of repeated limits:

```sh
globdelta diff before.gitignore after.gitignore --format json \
  --limit product_states=10000 --limit work=2000000 --output review.json
```

[All limits and defaults](docs/resources.md) are reported in JSON. A limit is
an inconclusive result, never evidence of equivalence. Exit 4 can retain a
proven change in one direction while the other direction remains unknown.

| Exit | Meaning |
| --- | --- |
| 0 | Complete equivalent diff, or completed explain (included or ignored) |
| 1 | Different; both directions resolved |
| 2 | Invalid command or limit configuration |
| 3 | Unsupported policy bytes/syntax or path outside the profile |
| 4 | Resource-incomplete assessment, possibly with a verified witness |
| 5 | I/O failure or internal consistency error |

For a no-change CI gate, accept only exit 0. The [caller CI recipe](docs/ci-recipe.md)
obtains two explicit policy files with the caller's Git, saves JSON, and fails
on every other exit code. GlobDelta itself never invokes Git.

## Python API

```python
from globdelta import Limits, compare_policies, explain_path, parse_policy

before = b"/build/*\n!/build/keep.txt\n"
after = b"/build/\n!/build/keep.txt\n"
report = compare_policies(before, after, Limits())
explanation_report = explain_path(after, b"build/keep.txt", Limits())
parsed = parse_policy(before, Limits())
```

These functions return immutable typed results, not Boolean/empty-path
sentinels. See [API and reports](docs/api.md), including the distinction between
`assessment_complete` and `graph_exhausted`, and [schema version 1](schemas/report.schema.json).

## Scope and limits

The profile is byte-oriented, printable ASCII and case-sensitive. It models
one root policy and hypothetical untracked regular files, with directory
prefixes. There are no nested policy rules, global ignores, `info/exclude`
rules, tracked-file effects, symlinks, or submodules. Some Git syntax is
intentionally rejected; the [normative profile and grammar](docs/profile.md)
define exactly what is accepted.

No component can be `.`, `..`, or `.git`. Root `.gitignore/` is excluded, but
terminal `.gitignore` files, including the root policy file, and nested
directories named `.gitignore` are allowed. There is no semantic path-length
or depth cutoff. Abstract paths need not be creatable on every filesystem.

Lazy determinization and product search can grow exponentially. Practical
resource limits make termination with an inconclusive result possible even
for accepted syntax. Logical budgets are not hard process-RSS limits. See
[the proof and invariants](docs/correctness.md) and [resource accounting](docs/resources.md).

## Related tools and credit

[Git `check-ignore`](https://git-scm.com/docs/git-check-ignore) explains supplied
paths and is the mandatory development oracle.
[PathSpec](https://github.com/cpburnz/python-pathspec) provides path matching.
[Ignore Lens](https://marketplace.visualstudio.com/items?itemName=ignore-lens.ignore-lens)
inspects workspace effects.
[glob-intersection](https://github.com/Pathgather/glob-intersection) demonstrates
established glob overlap and witness techniques. These are adjacent tools;
GlobDelta makes no novelty or speed claim over them. Its parser, independent
interpreter, and automata implementation are original project code.

Licensed under the [MIT License](LICENSE).
