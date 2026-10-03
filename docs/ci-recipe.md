# A caller-owned policy-change gate

GlobDelta never invokes Git or discovers a repository. Your CI job obtains two
explicit policy files, invokes the installed command and decides whether the
reported change is acceptable. The example below enforces strict semantic
no-change: every nonzero exit fails the job, including unsupported syntax and
an incomplete result with a verified change in one direction.

This Bash recipe expects the job to supply trusted immutable `BASE_COMMIT` and
`HEAD_COMMIT` IDs which are already present in its checkout. Fetching refs,
authentication and revision selection are caller responsibilities. An absent
`.gitignore` makes this recipe fail; decide explicitly if your workflow wants
to model absence as an empty policy instead.

```sh
#!/usr/bin/env bash
set -euo pipefail
: "${BASE_COMMIT:?supply the base commit ID}"
: "${HEAD_COMMIT:?supply the head commit ID}"
command -v git >/dev/null
command -v globdelta >/dev/null

# All Git operations below belong to this caller, outside GlobDelta.
base=$(git rev-parse --verify --end-of-options "${BASE_COMMIT}^{commit}")
head=$(git rev-parse --verify --end-of-options "${HEAD_COMMIT}^{commit}")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git show "${base}:.gitignore" > "$work/before.gitignore"
git show "${head}:.gitignore" > "$work/after.gitignore"

# A new directory gives exclusive output creation a fresh destination.
# Keep this directory as a CI artifact even when the gate fails.
artifact_dir=$(mktemp -d "${PWD}/globdelta-report.XXXXXX")
status=0
globdelta diff "$work/before.gitignore" "$work/after.gitignore" \
  --format json --output "$artifact_dir/report.json" || status=$?
printf 'GlobDelta exit: %s; report directory: %s\n' "$status" "$artifact_dir"

if [ "$status" -ne 0 ]; then
  printf '%s\n' 'Policy gate failed: changed, unsupported, incomplete, or errored.' >&2
  exit "$status"
fi
```

Configure your CI artifact-upload step to run even after a failed gate and
collect `globdelta-report.*/report.json`. A complete comparison with a change
exits 1. Exit 4 is also failure: it can mean one found direction and one unknown,
not merely that no change has been found. Exit 3 is unsupported syntax/profile,
not equivalence. Exit 2/5 indicate configuration or I/O/internal failures.

The input hashes in the report link the semantic assessment to the exact bytes
extracted by the caller. The recorded profile and limits state the scope of that
assessment. Store those alongside the resolved commit IDs in your CI metadata.
Never replace this gate with a string-diff-only check or silently retry an
incomplete comparison with a restricted path universe.
