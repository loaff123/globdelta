# Development, installation and hosted CI

Python 3.11+ is required. The runtime uses only the standard library. Git is a
mandatory development oracle, not a runtime dependency. Test absence or failure
of Git is an error; do not skip those tests to obtain a green run.

## Provision the build tools once

The build backend is standard `setuptools.build_meta`, with setuptools 84.0.0+
and wheel 0.48.0+. CI pins 84.0.0 and 0.48.0 for reproducibility. Provision them beforehand from an authorized source or a local
wheelhouse. An offline wheelhouse setup can use:

```sh
python -m pip install --no-index --find-links /path/to/build-wheelhouse \
  setuptools==84.0.0 wheel==0.48.0
```

This step requires those exact distributions already in the wheelhouse. It is
separate from building the project. There is no custom wheel builder, no network
runtime and no project install hook.

## Mandatory source tests

Run from the checkout root:

```sh
git --version
PYTHONPATH=src python -m unittest discover -s tests -v
```

The mandatory command is `python -m unittest discover -s tests -v`; `PYTHONPATH`
selects the source package for a source-only run. In an installed environment,
run the same command without `PYTHONPATH`. A subprocess-backed isolated Git
oracle is allowed in tests; production must never import or call that harness.

## Source distribution completeness

With the standard backend provisioned, run:

```sh
python tests/check_sdist.py dist
```

This builds an sdist and verifies that it includes the source, independent Git
oracle, complete fixture corpus, schema, docs and examples. No external design
archive is needed to run the tests. CI requires this packaging check.

## Offline build and clean install

```sh
python -m pip wheel --no-build-isolation --no-deps --no-index . --wheel-dir dist
python -m venv /tmp/globdelta-check
/tmp/globdelta-check/bin/python -m pip install --no-index --no-deps \
  dist/globdelta-0.1.0-py3-none-any.whl
/tmp/globdelta-check/bin/globdelta --version
/tmp/globdelta-check/bin/python -m unittest discover -s tests -v
/tmp/globdelta-check/bin/python examples/run_examples.py \
  --globdelta /tmp/globdelta-check/bin/globdelta
```

Choose an unused venv path; do not use `--system-site-packages`. Do not carry
`PYTHONPATH=src` into the clean installed run. Building with `--no-build-isolation`
is intentional: the pre-provisioned backend is used, and `--no-index` prevents
an accidental package-index lookup. The clean environment installs only the
wheel with `--no-index --no-deps`.

The example runner invokes the installed command, checks exit/status/direction
semantics and explanations, and prints a concise observed summary. An expected
changed result exits 1 and is asserted by the runner rather than discarded.

## Hosted CI definition

[The GitHub Actions workflow](../.github/workflows/ci.yml) provisions its build
backend before switching package operations offline, explicitly checks Git,
runs the full mandatory suite, builds the wheel without isolation/dependencies,
installs it into a clean venv and exercises the installed CLI. Backend
provisioning and checkout are network operations of hosted CI, not part of the
offline build/install or runtime claims.

The matrix targets Ubuntu 24.04 with Python 3.11–3.14. Official checkout and
setup-python actions are pinned by commit, permissions are read-only, and
checkout credentials are not persisted. Inspect the
[run for your exact revision](https://github.com/loaff123/globdelta/actions/workflows/ci.yml);
a workflow definition alone is not evidence of a passing run. Local evidence
and platform limits are recorded in [validation.md](validation.md).

## Review checklist

- Full accepted grammar and exact rejection/source-span tests
- Independent reference, automata and real-file Git agreement
- Exhaustive declared finite universe and reported randomized seeds
- Both directional witnesses, shortlex minimality and full exhaustion
- Every resource boundary, found/unknown preservation and cache eviction
- Valid JSON, source-reference invariants and bounded fallback output
- Read-only explicit inputs, exclusive output and hostile-label escaping
- Fresh offline wheel installation and actual installed-command transcripts

Do not present a finite test campaign as a proof over all policies or Git
versions. Do not claim release completion while required evidence is pending.
