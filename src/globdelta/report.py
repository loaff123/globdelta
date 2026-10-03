"""Stable, bounded report encoding without whole-object materialization.

The encoder reserves every ASCII fragment before appending it. String values are
escaped one code point at a time, so even a hostile, already-owned input label
cannot cause an unbounded intermediate JSON string. Optional trace data may be
removed; a mandatory-field overflow becomes an explicitly incomplete envelope.
A fixed 8192-byte emergency allowance is outside the adjustable payload budget
so a failure to reserve encoding scratch can itself be reported safely.
"""
from dataclasses import fields, replace

from .budget import Limits
from .model import (BlockedAncestor, Diagnostic, Direction, Explanation, Input,
                    LimitStop, Report, Rule, Span, Step, Stop, Witness)


class _Full(Exception):
    def __init__(self, used: int, increment: int, maximum: int):
        self.stop = LimitStop('report_bytes', 'report', used, increment, maximum)


class _Writer:
    def __init__(self, maximum: int):
        self.maximum = maximum
        self.data = bytearray()

    def raw(self, text: str) -> None:
        # Callers supply constant syntax or short scalar encodings, never labels.
        size = len(text)
        if size > self.maximum - len(self.data):
            raise _Full(len(self.data), size, self.maximum)
        self.data.extend(text.encode('ascii'))

    def string(self, value: str | bytes) -> None:
        self.raw('"')
        for character in value:
            code = character if isinstance(character, int) else ord(character)
            if code == 34:
                self.raw('\\"')
            elif code == 92:
                self.raw('\\\\')
            elif 32 <= code <= 126:
                self.raw(chr(code))
            elif code <= 65535:
                self.raw('\\u%04x' % code)
            else:
                code -= 65536
                self.raw('\\u%04x\\u%04x' % (55296 + (code >> 10), 56320 + (code & 1023)))
        self.raw('"')

    def object(self, items) -> None:
        self.raw('{')
        first = True
        for key, value in items:
            if not first:
                self.raw(',')
            first = False
            self.string(key)
            self.raw(':')
            self.value(value)
        self.raw('}')

    def array(self, items) -> None:
        self.raw('[')
        first = True
        for item in items:
            if not first:
                self.raw(',')
            first = False
            self.value(item)
        self.raw(']')

    def value(self, value) -> None:
        if value is None:
            self.raw('null')
        elif isinstance(value, bool):
            self.raw('true' if value else 'false')
        elif isinstance(value, (str, bytes)):
            self.string(value)
        elif isinstance(value, int):
            self.raw(str(value))
        elif isinstance(value, _Object):
            self.object(value.items)
        elif isinstance(value, tuple):
            self.array(value)
        else:
            self.object(_members(value))


class _Object:
    """A lazy field sequence; no nested dictionaries or copied trace arrays."""
    __slots__ = ('items',)

    def __init__(self, items):
        self.items = items


def _members(value):
    if isinstance(value, Report):
        yield 'schema_version', 1
        yield 'tool', _Object((('name', 'GlobDelta'), ('version', '0.1.0')))
        yield 'profile', _Object((('id', 'git-root-ascii-v1'), ('semantics_revision', 1)))
        for key in ('command', 'inputs', 'result', 'assessment_complete', 'graph_exhausted'):
            yield key, getattr(value, key)
        if value.command == 'diff':
            yield 'directions', _Object((('newly_ignored', value.newly_ignored or Direction()),
                                         ('newly_included', value.newly_included or Direction())))
        else:
            query = value.query if value.query is not None else b''
            yield 'query', _Object((('path', query), ('byte_length', len(query))))
            if value.explanation is not None:
                yield 'explanation', value.explanation
        yield 'limits', value.limits
        yield 'usage', _Object(value.usage)
        yield 'stop', value.stop
        yield 'diagnostics', _Object((('items', value.diagnostics), ('truncated', value.diagnostics_truncated)))
    elif isinstance(value, Explanation):
        for key in ('ignored', 'basis', 'winning_rule_id', 'first_blocked_ancestor',
                    'rule_table', 'steps', 'trace_complete'):
            yield key, getattr(value, key)
        yield 'terminal_matches', _Object((('effective', value.terminal_effective),
                              ('matching_rule_ids', value.terminal_matching_rule_ids)))
    elif isinstance(value, Rule):
        yield 'rule_index', value.index
        for key in ('line', 'column_start', 'column_end_exclusive', 'byte_start', 'byte_end'):
            yield key, getattr(value.span, key)
        yield 'source_text', value.source
        yield 'polarity', 'include' if value.include else 'ignore'
        yield 'applicability', 'directory' if value.directory_only else 'file_and_directory'
    elif isinstance(value, Witness):
        yield 'path', value.path
        yield 'byte_length', len(value.path)
        yield 'minimality', value.minimality
        yield 'before', value.before
        yield 'after', value.after
    elif isinstance(value, Direction):
        yield 'status', value.status
        if value.witness is not None:
            yield 'witness', value.witness
    elif isinstance(value, (Limits, Input, LimitStop, Stop, Diagnostic, Span, Step, BlockedAncestor)):
        for field in fields(value):
            yield field.name, getattr(value, field.name)
    else:
        raise TypeError('unsupported report value type')


def _encode(report: Report) -> str:
    writer = _Writer(report.limits.report_bytes)
    writer.value(report)
    writer.raw('\n')
    return writer.data.decode('ascii')


def _without_trace(explanation: Explanation | None) -> Explanation | None:
    if explanation is None:
        return None
    required = (explanation.winning_rule_id,
                explanation.first_blocked_ancestor.winning_rule_id
                if explanation.first_blocked_ancestor is not None else None)
    return replace(explanation, steps=(), terminal_matching_rule_ids=(), trace_complete=False,
                   rule_table=tuple(rule for rule in explanation.rule_table if rule.index in required))


def _without_direction_trace(direction: Direction | None) -> Direction | None:
    if direction is None or direction.witness is None:
        return direction
    witness = direction.witness
    return replace(direction, witness=replace(witness, before=_without_trace(witness.before),
                                             after=_without_trace(witness.after)))


def _envelope(report: Report, stop: LimitStop) -> Report:
    # Reserved 8192-byte minimum covers all effective limits, accurate metadata,
    # and this fixed diagnostic even when every adjustable limit is 2**63 - 1.
    omitted = 'Mandatory report fields or known findings could not be encoded; this incomplete envelope omits findings, query text, labels, traces, and detailed counters.'
    return replace(report, inputs=tuple(replace(item, label='[label omitted]') for item in report.inputs),
                   result='inconclusive', assessment_complete=False,
                   graph_exhausted=False if report.command == 'diff' else None,
                   newly_ignored=Direction() if report.command == 'diff' else None,
                   newly_included=Direction() if report.command == 'diff' else None,
                   query=b'' if report.command == 'explain' else None,
                   explanation=None, usage=(), stop=Stop('limit', stop),
                   diagnostics=(Diagnostic('report_limit', omitted),), diagnostics_truncated=True)


def finalize_report(report: Report) -> Report:
    """Fit an immutable report without losing a causal decision silently.

    Trace details and diagnostics are optional. The witness, its replayed
    decisions, their winning source rules, and first blocked ancestor are not.
    If these cannot fit, expose no complete assessment in the reserved envelope.
    """
    reserved_diagnostic = (len(report.diagnostics) == 1 and
                           ((report.stop.reason == 'limit' and report.stop.limit is not None and
                             report.diagnostics[0].code in ('report_limit', 'emergency_reserve')) or
                            (report.stop.reason == 'error' and
                             report.diagnostics[0].code in ('io_error', 'internal_error'))))
    if not reserved_diagnostic and len(report.diagnostics) > report.limits.diagnostics:
        report = replace(report, diagnostics=report.diagnostics[:report.limits.diagnostics],
                         diagnostics_truncated=True)
    try:
        _encode(report)
        _encode_text(report)
        return report
    except _Full:
        pass
    candidate = replace(report, explanation=_without_trace(report.explanation),
                        newly_ignored=_without_direction_trace(report.newly_ignored),
                        newly_included=_without_direction_trace(report.newly_included))
    try:
        _encode(candidate)
        _encode_text(candidate)
        return candidate
    except _Full:
        pass
    if candidate.diagnostics:
        candidate = replace(candidate, diagnostics=(), diagnostics_truncated=True)
    try:
        _encode(candidate)
        _encode_text(candidate)
        return candidate
    except _Full as full:
        result = _envelope(report, full.stop)
        _encode(result)  # The reserved envelope is itself checked, never sliced.
        _encode_text(result)
        return result


def to_json(report: Report) -> str:
    """Return deterministic ASCII JSON whose encoded size is within its cap."""
    return _encode(finalize_report(report))


def exit_code(report: Report) -> int:
    report = finalize_report(report)
    if report.stop.reason == 'error' or report.result == 'error':
        return 5
    if report.stop.reason == 'limit' or report.result == 'inconclusive':
        return 4
    if report.result == 'unsupported':
        return 3
    if report.result == 'explained' and report.assessment_complete:
        return 0
    if report.result == 'equivalent' and report.assessment_complete:
        return 0
    if report.result == 'different':
        return 1 if report.assessment_complete else 4
    return 5


def _text_explanation(writer: _Writer, role: str, path: bytes, explanation: Explanation) -> None:
    writer.raw('  ' + role + ': ' + ('ignored' if explanation.ignored else 'included') + '; ')
    writer.string(explanation.basis)
    if explanation.winning_rule_id is not None:
        writer.raw('; winning rule ' + str(explanation.winning_rule_id))
    writer.raw('\n')
    if explanation.first_blocked_ancestor is not None:
        ancestor = explanation.first_blocked_ancestor
        writer.raw('    first blocking ancestor: byte prefix [0:' + str(ancestor.prefix_end) +
                   '] of the path above; rule ' + str(ancestor.winning_rule_id) + '\n')
    for rule in explanation.rule_table:
        writer.raw('    ' + role + ' rule ' + str(rule.index) + ', line ' + str(rule.span.line) +
                   ', columns ' + str(rule.span.column_start) + ':' + str(rule.span.column_end_exclusive) + ': ')
        writer.string(rule.source)
        writer.raw('\n')
    if not explanation.trace_complete:
        writer.raw('    trace incomplete (optional details omitted)\n')


def _encode_text(report: Report) -> str:
    writer = _Writer(report.limits.report_bytes)
    if report.result == 'equivalent':
        writer.raw('equivalent within git-root-ascii-v1\n')
    else:
        writer.raw(report.result + ' within git-root-ascii-v1\n')
    writer.raw('assessment_complete: ' + str(report.assessment_complete).lower() + '\n')
    writer.raw('graph_exhausted: ' + ('null' if report.graph_exhausted is None else str(report.graph_exhausted).lower()) + '\n')
    for item in report.inputs:
        writer.raw(item.role + ' input: ')
        writer.string(item.label)
        writer.raw('; raw_bytes_read=' + str(item.raw_bytes_read) +
                   '; complete_read=' + str(item.complete_read).lower() + '; sha256=')
        writer.raw(item.sha256 if item.sha256 is not None else 'null')
        writer.raw('; rule_count=' + ('null' if item.rule_count is None else str(item.rule_count)) + '\n')
    if report.command == 'diff':
        for name, direction in (('newly_ignored', report.newly_ignored), ('newly_included', report.newly_included)):
            direction = direction or Direction()
            writer.raw(name + ': ' + direction.status + '\n')
            if direction.witness is not None:
                witness = direction.witness
                writer.raw('  witness: ')
                writer.string(witness.path)
                writer.raw('; shortest-shortlex; byte_length=' + str(len(witness.path)) + '\n')
                _text_explanation(writer, 'before', witness.path, witness.before)
                _text_explanation(writer, 'after', witness.path, witness.after)
    else:
        query = report.query if report.query is not None else b''
        writer.raw('query: ')
        writer.string(query)
        writer.raw('\n')
        if report.explanation is not None:
            _text_explanation(writer, 'policy', query, report.explanation)
    writer.raw('limits: ')
    writer.value(report.limits)
    writer.raw('\nusage: ')
    writer.value(_Object(report.usage))
    writer.raw('\nstop: ')
    writer.value(report.stop)
    writer.raw('\n')
    for diagnostic in report.diagnostics:
        writer.raw('diagnostic ')
        writer.string(diagnostic.code)
        writer.raw(': ')
        writer.string(diagnostic.message)
        if diagnostic.location is not None:
            writer.raw('; location=')
            writer.value(diagnostic.location)
        writer.raw('\n')
    if report.diagnostics_truncated:
        writer.raw('diagnostics truncated\n')
    return writer.data.decode('ascii')


def to_text(report: Report) -> str:
    """Render escaped plain text with the same conclusion and causal sources."""
    return _encode_text(finalize_report(report))
