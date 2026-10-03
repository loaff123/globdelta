"""Pure immutable-result library API. File I/O belongs exclusively to cli.py."""
import hashlib
from dataclasses import replace
from .budget import Budget, LimitExceeded, Limits
from .model import Diagnostic, Direction, Input, Report, Span, Stop
from .parse import Unsupported, parse, parse_policy
from .reference import evaluate, invalid_path_offset
from .search import search


def _analyze(command: str, raw: tuple[bytes, ...], limits: Limits, path: bytes | None = None) -> Report:
    if any(not isinstance(data, bytes) for data in raw) or (path is not None and not isinstance(path, bytes)):
        raise TypeError('policy contents and hypothetical paths must be bytes')
    roles = ('before', 'after') if command == 'diff' else ('policy',)
    inputs = [Input(role, f'<{role}>', 0, False, None, None) for role in roles]
    budget = Budget(limits)
    left = right = Direction()
    result = 'inconclusive'
    complete = False
    exhausted = False if command == 'diff' else None
    diagnostics: tuple[Diagnostic, ...] = ()
    stop = Stop('error')
    explanation = None
    replay_usage = ()
    report_reserved = False
    try:
        # Bounded report construction has its own protected output allowance.
        budget.retain(3 * limits.report_bytes, 'report_reserve')
        report_reserved = True
        budget.retain(sum(map(len, raw)) + (len(path) if path is not None else 0), 'input_buffers')
        policies = []
        for i, data in enumerate(raw):
            # Metadata scanning is charged separately from parser scanning.
            # Oversize inputs are not hashed or presented as completely read.
            budget.check('input_bytes', len(data), 'input')
            budget.charge('work', len(data), 'input_hash')
            inputs[i] = replace(inputs[i], raw_bytes_read=len(data), complete_read=True, sha256=hashlib.sha256(data).hexdigest())
            policy = parse(data, roles[i], budget, input_retained=True)
            inputs[i] = replace(inputs[i], rule_count=len(policy.rules))
            policies.append(policy)
        if command == 'diff':
            outcome = search(policies[0], policies[1], budget)
            left, right = outcome.newly_ignored, outcome.newly_included
            exhausted, stop, replay_usage = outcome.graph_exhausted, outcome.stop, outcome.replay_usage
            if outcome.error:
                # A consistency failure invalidates this assessment; do not
                # publish any witness from a suspect engine execution.
                result = 'error'
                left = right = Direction()
                diagnostics = (Diagnostic('internal_consistency', outcome.error),)
            else:
                complete = left.status != 'unknown' and right.status != 'unknown'
                result = 'different' if 'found' in (left.status, right.status) else 'equivalent' if complete else 'inconclusive'
        else:
            assert path is not None
            budget.check('witness_bytes', len(path), 'query')
            budget.charge('reference_work', len(path), 'query_validation')
            bad = invalid_path_offset(path)
            if bad is not None:
                # A profile-invalid query is data, never a filename to open.
                end = min(bad + 1, len(path))
                budget.charge('diagnostics', 1, 'query')
                raise Unsupported(Diagnostic('unsupported_path', 'Path is outside git-root-ascii-v1', Span('path', 1, bad + 1, end + 1, bad, end)))
            explanation = evaluate(policies[0], path, budget)
            complete = True
            result, stop = 'explained', Stop('explained')
    except Unsupported as exc:
        result, stop, diagnostics = 'unsupported', Stop('unsupported'), (exc.diagnostic,)
    except LimitExceeded as exc:
        result, stop = 'inconclusive', Stop('limit', exc.stop)
    except Exception as exc:
        result, stop = 'error', Stop('error')
        complete, exhausted = False, False if command == 'diff' else None
        left = right = Direction()
        explanation = None
        diagnostics = (Diagnostic('internal_consistency', f'Internal consistency failure: {type(exc).__name__}'),)
    if not report_reserved:
        # A fixed emergency allowance exists outside the adjustable analysis
        # payload. Never try full-cap encoding after its reserve has failed.
        path = b'' if command == 'explain' else None
        diagnostics = (Diagnostic('emergency_reserve', 'Analysis did not start; query text omitted because the report reserve was unavailable.'),)
    usage = budget.usage() + tuple((f'replay.{key}', value) for key, value in replay_usage)
    report = Report(command, tuple(inputs), result, complete, exhausted, limits, usage, stop, diagnostics, False, left if command == 'diff' else None, right if command == 'diff' else None, path if command == 'explain' else None, explanation)
    from .report import finalize_report
    return finalize_report(report)


def compare_policies(before_bytes: bytes, after_bytes: bytes, limits: Limits = Limits()) -> Report:
    """Compare all abstract valid paths; incomplete work never proves absence."""
    return _analyze('diff', (before_bytes, after_bytes), limits)


def explain_path(policy_bytes: bytes, path_bytes: bytes, limits: Limits = Limits()) -> Report:
    """Explain a hypothetical relative regular-file path without opening it."""
    return _analyze('explain', (policy_bytes,), limits, path_bytes)
