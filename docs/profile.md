# Profile and accepted grammar

Normative semantics revision 1. This document defines the supported language,
not every pattern or filesystem behavior accepted by Git.

## Normative profile

Profile identifier: `git-root-ascii-v1`.

A policy decision concerns one hypothetical, untracked, regular file relative to a root directory. The two input files supply alternative contents of that root's `.gitignore`. No other ignore source exists. Matching is ASCII byte-oriented and case-sensitive. Every proper path prefix is a directory. There are no symlinks, submodules, tracked-file effects, nested policy files with rules, global ignores, or `info/exclude` rules.

Let `A` be the 95 bytes 0x20 through 0x7e inclusive. Let `C = A - {'/'}`. A candidate path is one or more nonempty `C` components separated by `/`, with these additional conditions:

- No component is exactly `.`, `..`, or `.git`
- The first component cannot be `.gitignore` when followed by `/`
- No leading or trailing `/`, doubled separator, control byte, DEL, or non-ASCII byte
- The terminal filename `.gitignore` is allowed, including at the root
- A nested directory named `.gitignore` is allowed; exclude only the root `.gitignore/` prefix

There is no semantic maximum component length, total length, or depth. Paths are abstract finite strings, not promises of creatability on every filesystem. A space, backslash, colon, asterisk, or closing bracket is a legal component byte. This is deliberately broader than portable filenames and narrower than all Git filenames. A resource limit never silently becomes a path-language restriction.

The terminal root `.gitignore` can be queried as the policy file itself. For testing a terminal nested `.gitignore`, create it empty so it introduces no additional rules. A `.gitignore` directory is not a nested policy file.

The tool does not answer Git status, whether Git would add a tracked file, filesystem case/normalization behavior, or equivalence of Docker, npm, CODEOWNERS, ripgrep, or another ignore dialect.

## Byte grammar and source positions

### Physical input

Read bytes, not text with universal-newline conversion. Accept printable ASCII bytes plus LF or CRLF line terminators. The last line may omit its terminator. Reject UTF-8 BOM, every non-ASCII byte, HT, NUL, DEL, bare CR, and CR at EOF without LF, even in comments. This is an acceptance boundary, not an assertion that Git rejects them.

A physical line is processed in this order:

1. Record raw byte start/end, physical line number, and original bytes; remove its LF or CRLF terminator
2. Validate the permitted bytes
3. If byte zero is `#`, record a comment and do not parse its pattern syntax
4. Remove unescaped trailing ASCII spaces, as defined below
5. If empty, record a blank line and add no rule
6. Consume at most one initial unescaped `!` as the rule's include polarity; a second `!` is an ordinary literal
7. Parse the remaining pattern and its source spans; reject a missing body

Leading spaces are significant. There are no inline comments. An initial `\#` or `\!` means a literal marker, not a comment or polarity. `!#x` is an include rule for literal `#x`. Braces, parentheses, `+`, `@`, and other non-metacharacters are literals; there is no brace expansion or extglob syntax.

Trailing-space algorithm: starting at the right edge, remove a space if the immediately preceding consecutive run of backslashes has even length. Stop at a non-space or a space with an odd preceding run. Do not erase the backslash quoting a preserved space. Equivalent left-to-right implementations must retain source spans and be independently tested. Thus `foo\<space><space>` becomes a pattern for `foo<space>`; `foo\\<space>` becomes a pattern for `foo\`; and `foo<space>\<space>` keeps two literal terminal spaces. These examples use angle-bracket labels only to make spaces visible.

All source locations use one-based physical line and one-based byte column, plus zero-based half-open byte offsets into the original input. Columns include negation, anchors, and escapes. Preserve mappings when dropping syntax markers or trimming spaces. Diagnostics point to the first offending byte; unclosed brackets point to their opening bracket; a missing final body points immediately after the last marker. Rule indices increase only for effective pattern lines; physical line numbers never change.

### Pattern structure

After negation, allow at most one initial unescaped `/` as a root marker and at most one final unescaped `/` as a directory-only marker. Strip these markers for component parsing. The remaining pattern must contain one or more nonempty components separated by unescaped `/`.

Reject escaped separators (`\/`) anywhere, repeated separators, an empty body after marker removal, or a slash within a bracket class. Check escape/separator structure before treating a final slash as a directory marker. Do not normalize `a//b` or approximate escaped slash behavior.

A component consists of literal bytes, escaped literals, `?`, `*`, bracket classes, or the special whole component `**`:

- A literal consumes that exact byte
- `\x` consumes literal printable ASCII `x`, except `/`, which is unsupported
- A dangling backslash is rejected, including one exposed after trimming trailing spaces
- `?` consumes exactly one byte from `C`
- `*` consumes zero or more bytes from `C`
- Outside bracket classes, an unescaped consecutive run of two or more stars is accepted only when the entire raw component is exactly `**`
- Embedded runs such as `a**b`, a whole `***`, and longer runs are rejected, not reduced to `*`
- Escaped stars and stars inside bracket classes are literal atoms and do not join unescaped star runs; `[**]` is a valid class for literal `*`
- A standalone literal `]` outside a class is accepted; a literal `[` outside a class must be escaped

The strict star rule avoids real Git implementation edge cases: whole-component runs longer than two may behave recursively despite the manual's simplified wording. Rejection is preferable to silently choosing a different language.

### Bracket classes

A class consumes one byte from a finite set contained in `C`. The production parser uses this conservative, unambiguous grammar:

1. `[` opens the class
2. Optional first `!` or `^` complements the class relative to `C`
3. A `]` in the first atom position is a literal member and requires a later closing `]`
4. A `-` in the first atom position or immediately before the closing `]` is literal
5. Other atoms are printable bytes except unescaped `[`, `]`, `-`, `\`, or `/`; a backslash may quote any printable non-slash byte
6. Between two unescaped ASCII alphanumeric atoms, an unescaped `-` denotes an inclusive ascending ASCII-byte range
7. Parse range items left to right without atom reuse. Reject a leftover interior dash, descending range, missing endpoint, missing close, or empty member list
8. Reject every unescaped `[` inside a class, including POSIX named classes, collating symbols, and equivalence classes

Range endpoints must both be unescaped ASCII alphanumeric bytes (`0-9`, `A-Z`, or `a-z`). Leading literal `]`, leading/trailing literal `-`, and every escaped atom are singleton members only, never range endpoints. Reject any apparent range using those atoms. This is the normative v1 baseline even where Git accepts a broader range syntax.

Ranges may mix ASCII letters and digits if ascending (`[9-A]`); a range's set is its inclusive byte interval intersected with `C`. Because these range endpoints are alphanumeric, no accepted range crosses the slash byte; retain the intersection invariant regardless. No locale classes, Unicode ranges, case folding, or slash consumption exists. Use one fixed 95-position mask representation everywhere for consuming bytes: byte `b` maps to bit `b - 0x20`. Component masks always clear the slash bit. A class therefore has at most 94 members, while the same representation can encode the explicit separator edge. Do not confuse byte masks with NFA-state subset bitsets. Examples accepted: `[abc]`, `[a-zA-Z0-9]`, `[!ab]`, `[^ab]`, `[]a]`, `[-ab]`, `[ab-]`, `[\[\]]`, `[\-]`. Examples rejected: `[z-a]`, `[a-b-c]`, `[--a]`, `[a-\]]`, `[[:alpha:]]`, `[]`, `[`.

A raw malformed class is not interpreted as a literal opener. Git may accept other forms or produce no matches for them; this profile rejects them with a location instead.

## Direct rule languages

A rule first matches the complete path to the node under examination. It does not itself append a descendant suffix. Descendant exclusion is modeled separately through directory decisions.

After removing marker slashes, a rule with no slash and no root marker is a basename rule. Its full-path language is `(C+/)*` followed by its component language. A slash-containing pattern or a root-marked pattern is relative to the root, without an implicit prefix. A trailing directory marker does not itself make a basename rule root-relative: `foo/` matches directories named `foo` at any depth; `/foo/` matches only the root directory.

Compile a root-relative component sequence as follows, using concatenation. These regular expressions are mathematical notation, not Python `re`:

- Ordinary nonfinal component: `component_language` followed by `/`
- Nonfinal `**` component: `(C+/)*`
- Ordinary final component: `component_language`
- Final `**` component: `C+(/C+)*`

For a slashless, unanchored `**`, use basename wildcard `C*` with the normal implicit basename prefix. For rooted `/**`, the final-`**` translation matches every valid nonempty path. These translations need agree only after intersection with the valid-path language; empty components that a component `*` could recognize are never valid completed nodes; a prefix ending in `/` remains extendable but is not an EOF terminal.

Consequences:

- `a/**/b` matches direct nodes `a/b`, `a/x/b`, and `a/x/y/b`
- `a/**` does not directly match node `a`; it matches nodes inside `a`
- `a/**/` does not match regular file `a/b`, but can exclude directory `a/b`, thereby excluding regular file `a/b/c`
- `a/**/**/b` can match `a/b`; adjacent globstars are supported
- `a/*` directly matches `a/x`; it can also cause `a/x/y` to be ignored because `a/x` is an excluded directory

Directory-only rules have applicability `{directory}`. Other rules have `{directory, file}`. Filter matching tags for the current node type before selecting the highest rule index. The last matching applicable rule decides: a positive rule excludes, a negation includes, and no match includes by default. In particular, `*` followed by `!a/` still excludes regular file `a`.
