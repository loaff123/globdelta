# Measured release fixtures

These are one-run observations on a shared Linux x86-64 cloud host, using Python
3.12.14 and the default limits on 3 October 2026. Each case ran in a fresh Python
process. Elapsed time surrounds `compare_policies`; maximum RSS is the whole
process high-water mark reported by Linux, in KiB. They are not a benchmark
competition, throughput guarantee, or a portable memory promise.

The [raw measurements](benchmark-results.json) include exact policy bytes as
hex, all effective limits, full reports, deterministic usage counters, Python
and platform versions, wall time, and RSS. A reproduction is simply to decode
each `before_hex`/`after_hex` and call `compare_policies` with default `Limits`.

| Fixture | Result | Product states | Seconds | Peak RSS KiB |
| --- | --- | ---: | ---: | ---: |
| Empty identity | equivalent | 20 | 0.003686 | 11520 |
| Ancestor regression | different, complete | 54 | 0.024294 | 11776 |
| Reordered exception | different, complete | 70 | 0.024559 | 11776 |
| `cache` versus `**/cache` | equivalent | 37 | 0.009805 | 11648 |
| `cache/` versus `cache` | different, complete | 37 | 0.010139 | 11648 |
| Empty versus `*a????????????` | different, incomplete | 12307 | 10.895387 | 18160 |
| `*a????????????` versus itself | inconclusive | 8297 | 10.457341 | 18788 |

Both pathological cases stopped at exactly 20,000,000 charged work units. The
changed case retained a replayed newly-ignored witness and left the opposite
direction unknown. The identity case made no equivalence claim. Both require
exit 4 in a CLI/CI workflow. Even identical text takes the finite-state search
route in version 1; it has no separately reviewed identity certificate shortcut.

The observations justify exercising both ordinary completion and bounded
exponential-growth failure paths. They do not establish that an arbitrary
accepted policy will complete within these limits or these times.
