# Three complete policy-review workflows

**Status:** all workflows below were executed against an offline-installed
0.1.0 wheel. The runner verified four comparisons, 23 explain decisions and
exclusive output behavior. [Captured installed reports](../docs/executed-examples.json)
include the observed commands, exit codes, witnesses and explanations. Reproduce
with `python examples/run_examples.py` and the installed `globdelta` command.
The runner uses only these explicit fixture inputs; it does not scan a project.

Run all commands below from the checkout root. Changed complete comparisons
intentionally exit 1, equivalence exits 0, and successful explain exits 0 for
either ignored or included. Save JSON with `--format json --output NEW_FILE`;
the destination must not already exist.

## 1. A blocked ancestor makes the exception ineffective

Before (`ancestor/before.gitignore`):

```gitignore
/build/*
!/build/keep.txt
```

After (`ancestor/after.gitignore`):

```gitignore
/build/
!/build/keep.txt
```

```sh
globdelta diff examples/ancestor/before.gitignore examples/ancestor/after.gitignore
globdelta explain examples/ancestor/before.gitignore build/keep.txt --format json
globdelta explain examples/ancestor/after.gitignore build/keep.txt --format json
```

Expected comparison: different and complete, newly ignored `build/keep.txt`
(14 bytes, shortest-shortlex), newly included absent, exit 1.

Before, directory `build` is included by default and file `build/keep.txt` is
included by physical line 2. After, directory `build` is excluded by line 1;
that is the first blocker, at path byte offset 5. The terminal exception cannot
reopen it. A terminal match shown beneath that blocker is ineffective.

Useful checks:

| Hypothetical regular file | Before | After |
| --- | --- | --- |
| `build/keep.txt` | Included | Ignored |
| `build/drop.txt` | Ignored | Ignored |
| `build` | Included | Included |
| `x/build/keep.txt` | Included | Included |

The root file `build` stays included because the changed after rule is
directory-only. The root markers prevent `x/build/keep.txt` from matching.

## 2. Reordering rules changes an exception

Before (`order/before.gitignore`):

```gitignore
*.log
!keep.log
```

After (`order/after.gitignore`):

```gitignore
!keep.log
*.log
```

```sh
globdelta diff examples/order/before.gitignore examples/order/after.gitignore --format json
globdelta explain examples/order/after.gitignore keep.log
```

Expected comparison: different and complete, newly ignored `keep.log`
(8 bytes, shortest-shortlex), newly included absent, exit 1.

Both rules match the root regular file. Before, the last matching line is
`!keep.log` and includes it; after, the last matching line is `*.log` and ignores
it. Negation has no special priority over later positive rules. The explanation
must identify the winner at physical line 2 in each policy, with the different
source text/polarity. `other.log` stays ignored, and `notes.txt` stays included.

Because these are basename rules, the same ordering also affects
`src/keep.log` when no ancestor is excluded.

## 3. Different spellings can be equivalent; node type still matters

Before (`cache/before.gitignore`):

```gitignore
cache
```

After (`cache/after.gitignore`):

```gitignore
**/cache
```

```sh
globdelta diff examples/cache/before.gitignore examples/cache/after.gitignore
```

Expected comparison: equivalent within git-root-ascii-v1, both directions
absent, graph exhausted, assessment complete, exit 0. Both patterns match nodes
named `cache` at any depth and have the same file/directory applicability.
Both ignore `cache`, `src/cache`, and `cache/item`, but include `cachex`.

Now compare a directory-only policy to the original:

```gitignore
cache/
```

```sh
globdelta diff examples/cache/directories-only.gitignore examples/cache/before.gitignore --format json
globdelta explain examples/cache/directories-only.gitignore cache
globdelta explain examples/cache/before.gitignore cache
```

Expected contrast: different and complete, shortest newly ignored regular file
`cache` (5 bytes), newly included absent, exit 1. `cache/` ignores directories
named cache and their descendants, but it does not ignore the regular file
`cache`; the non-directory-only rule does.

## Interpret partial results carefully

A resource limit can stop after one direction is verified. For example, a report
can have `result: different`, `assessment_complete: false`, a
`newly_ignored.status: found` with its full witness and a
`newly_included.status: unknown` with no witness.

The corresponding exit is **4**, not 1 or 0. The real report contains the full
verified witness and named limit stop. Treat exit 4 as failure in a semantic
no-change CI gate. Do not convert unknown to absent or assume an incomplete
result has found no change.
