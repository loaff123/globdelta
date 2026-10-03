"""Strict printable-ASCII parser; unsupported syntax is never approximated."""
import hashlib
from .budget import Budget, LimitExceeded, Limits
from .model import Atom, Component, COMPONENT_MASK, Diagnostic, ParseResult, Policy, Rule, Span

class Unsupported(Exception):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.code)


def parse(data: bytes, role: str, budget: Budget, *, input_retained: bool = False) -> Policy:
    if not isinstance(data, bytes):
        raise TypeError('policy must be bytes')
    budget.charge('input_bytes', len(data), 'parse', role)
    if not input_retained:
        budget.retain(len(data), 'parse')
    budget.charge('work', len(data), 'parse')
    digest = hashlib.sha256(data).hexdigest()
    rules: list[Rule] = []
    start = 0
    line = 1
    while start < len(data):
        lf = data.find(b'\n', start)
        end = len(data) if lf < 0 else lf
        content_end = end - 1 if lf >= 0 and end > start and data[end - 1] == 13 else end
        budget.check('line_bytes', content_end - start, 'parse')
        def fail(code: str, message: str, offset: int) -> None:
            budget.charge('diagnostics', 1, 'parse')
            finish = offset + 1 if offset < content_end else offset
            raise Unsupported(Diagnostic(code, message, Span(role, line, offset - start + 1, finish - start + 1, offset, finish)))
        for off in range(start, content_end):
            if not 32 <= data[off] <= 126:
                fail('unsupported_byte', 'Only printable ASCII and LF/CRLF terminators are accepted', off)
        # Comments retain their physical-byte validation but need no pattern parse.
        if start < content_end and data[start] != 35:
            trimmed = content_end
            while trimmed > start and data[trimmed - 1] == 32:
                p = trimmed - 2
                while p >= start and data[p] == 92:
                    p -= 1
                if (trimmed - 2 - p) % 2:
                    break
                trimmed -= 1
            if trimmed > start:
                budget.charge('rules', 1, 'parse', role)
                include = data[start] == 33
                body = start + int(include)
                anchored = body < trimmed and data[body] == 47
                body += int(anchored)
                if body == trimmed:
                    fail('missing_body', 'A rule needs a nonempty pattern body', body)
                # Parse separators before considering a final directory marker.
                parts: list[Component] = []
                atoms: list[Atom] = []
                comp_start = body
                i = body
                directory_only = False
                def atom(mask: int, repeat: bool = False) -> None:
                    budget.charge('ast_items', 1, 'parse', role)
                    budget.retain(40, 'parse')
                    atoms.append(Atom(mask, repeat))
                def component(globstar: bool = False) -> None:
                    budget.charge('ast_items', 1, 'parse', role)
                    budget.retain(48 + 8 * len(atoms), 'parse')
                    parts.append(Component(tuple(atoms), globstar))
                    atoms.clear()
                while i < trimmed:
                    b = data[i]
                    if b == 47:
                        if i == comp_start:
                            fail('empty_component', 'Repeated separators are unsupported', i)
                        component()
                        if i == trimmed - 1:
                            directory_only = True
                        i += 1
                        comp_start = i
                    elif b == 92:
                        if i + 1 == trimmed:
                            fail('dangling_escape', 'Backslash must quote a printable non-slash byte', i)
                        if data[i + 1] == 47:
                            fail('escaped_separator', 'Escaped separators are unsupported', i)
                        atom(1 << (data[i + 1] - 32))
                        i += 2
                    elif b == 42:
                        j = i + 1
                        while j < trimmed and data[j] == 42:
                            j += 1
                        if j - i >= 2:
                            if i != comp_start or j - i != 2 or (j < trimmed and data[j] != 47):
                                fail('star_run', 'Only a whole component ** may contain consecutive stars', i)
                            component(True)
                            if j < trimmed:
                                directory_only = j == trimmed - 1
                                j += 1
                            i = j
                            comp_start = i
                        else:
                            atom(COMPONENT_MASK, True)
                            i = j
                    elif b == 63:
                        atom(COMPONENT_MASK)
                        i += 1
                    elif b == 91:
                        opening = i
                        i += 1
                        complement = i < trimmed and data[i] in (33, 94)
                        i += int(complement)
                        members: list[tuple[int, bool, int]] = []
                        # Each token is (byte, range-eligible, original offset).
                        first = True
                        while i < trimmed:
                            c = data[i]
                            if c == 93 and not first:
                                break
                            if c == 91:
                                fail('class_nested', 'Unescaped [ and locale classes are unsupported', i)
                            if c == 47:
                                fail('class_separator', 'A class cannot contain slash', i)
                            off = i
                            escaped = c == 92
                            if escaped:
                                i += 1
                                if i >= trimmed:
                                    fail('class_unclosed', 'Unclosed bracket class', opening)
                                c = data[i]
                                if c == 47:
                                    fail('escaped_separator', 'Escaped separators are unsupported', off)
                            budget.charge('ast_items', 1, 'parse', role)
                            budget.retain(32, 'parse')
                            eligible = not escaped and (48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122)
                            # Negative values distinguish escaped dashes from operators.
                            members.append((c if not escaped or c != 45 else -45, eligible, off))
                            first = False
                            i += 1
                        if i >= trimmed:
                            fail('class_unclosed', 'Unclosed bracket class', opening)
                        if not members:
                            fail('class_empty', 'A class needs at least one member', opening)
                        mask = 0
                        k = 0
                        while k < len(members):
                            c, eligible, off = members[k]
                            if c == 45 and k not in (0, len(members) - 1):
                                fail('class_dash', 'Interior dash must form an alphanumeric range', off)
                            if k + 2 < len(members) and members[k + 1][0] == 45:
                                d, eligible_end, _ = members[k + 2]
                                if not eligible or not eligible_end or d < c:
                                    fail('class_range', 'Range endpoints must be unescaped ascending ASCII alphanumerics', members[k + 1][2])
                                for x in range(c, d + 1):
                                    mask |= 1 << (x - 32)
                                k += 3
                            else:
                                mask |= 1 << (abs(c) - 32)
                                k += 1
                        budget.release(32 * len(members))
                        atom((COMPONENT_MASK ^ mask) if complement else mask & COMPONENT_MASK)
                        i += 1
                    else:
                        atom(1 << (b - 32))
                        i += 1
                if atoms:
                    component()
                if not parts:
                    fail('missing_body', 'A rule needs a nonempty pattern body', body)
                budget.retain(128 + trimmed - start + 8 * len(parts), 'parse')
                rules.append(Rule(len(rules) + 1, Span(role, line, 1, trimmed - start + 1, start, trimmed), data[start:trimmed], include, directory_only, anchored, tuple(parts)))
        start = end + 1
        line += 1
    budget.retain(64 + 8 * len(rules), 'parse')
    return Policy(len(data), digest, tuple(rules))


def parse_policy(data: bytes, limits: Limits = Limits()) -> ParseResult:
    budget = Budget(limits)
    try:
        policy = parse(data, 'policy', budget)
        return ParseResult(policy, usage=budget.usage())
    except Unsupported as exc:
        return ParseResult(None, (exc.diagnostic,), usage=budget.usage())
    except LimitExceeded as exc:
        return ParseResult(None, stop=exc.stop, usage=budget.usage())
