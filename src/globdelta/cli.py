"""Explicit, read-only policy inputs and exclusive report output."""
import argparse
from dataclasses import fields, replace
import hashlib
import os
import sys

from .budget import Limits
from .model import Diagnostic, Direction, Input, LimitStop, Report, Stop
from .report import exit_code, finalize_report, to_json, to_text

_READ_CHUNK = 8192


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse incorporates arbitrary option/argument strings into errors.
        super().error(ascii(message)[1:-1])


def _close_failed_stream(stream):
    try:
        stream.close()
    except (OSError, ValueError):
        pass


class _ReadFailure(Exception):
    def __init__(self, metadata: Input, stop: LimitStop | None, diagnostic: Diagnostic):
        self.metadata, self.stop, self.diagnostic = metadata, stop, diagnostic


def _read_input(label: str, role: str, limits: Limits, payload_available: int):
    """Read small chunks, using only one extra byte to distinguish exact EOF.

    Account for bytearray growth, the read chunk, and the immutable copy before reading.
    Never retain the oversize sentinel or publish a partial-file digest.
    """
    data = bytearray()
    count = 0
    digest = hashlib.sha256()
    try:
        with open(label, 'rb', buffering=0) as stream:
            while True:
                remaining = limits.input_bytes - len(data)
                size = min(_READ_CHUNK, remaining) if remaining else 1
                if remaining and 3 * (len(data) + size) > payload_available:
                    size = min(size, max(0, payload_available // 3 - len(data)))
                    if not size:
                        stop = LimitStop('payload_bytes', 'input_read',
                                         limits.payload_bytes - payload_available + 3 * len(data),
                                         3, limits.payload_bytes)
                        raise _ReadFailure(Input(role,label,count,False,None,None), stop,
                                           Diagnostic('resource_limit','Input buffering reached the payload limit.'))
                chunk = stream.read(size)
                count += len(chunk)
                if not chunk:
                    return bytes(data), Input(role,label,count,True,digest.hexdigest(),None)
                if not remaining:
                    stop = LimitStop(role + '.input_bytes','input_read',len(data),1,limits.input_bytes)
                    raise _ReadFailure(Input(role,label,count,False,None,None),stop,
                                       Diagnostic('resource_limit','Input exceeds the configured byte limit.'))
                data.extend(chunk)
                digest.update(chunk)
    except OSError as error:
        # Input labels are already preserved in metadata, and escaped by output.
        message = 'Could not read the explicitly named input (errno ' + str(error.errno) + ').'
        raise _ReadFailure(Input(role,label,count,False,None,None),None,Diagnostic('io_error',message)) from error


def _failure_report(command, inputs, limits, diagnostic, stop=None, query=None):
    resource = stop is not None
    report = Report(command,tuple(inputs),'inconclusive' if resource else 'error',
                       False,False if command == 'diff' else None,limits,(),
                       Stop('limit',stop) if resource else Stop('error'),(diagnostic,),
                       newly_ignored=Direction() if command == 'diff' else None,
                       newly_included=Direction() if command == 'diff' else None,
                       query=query)
    fitted = finalize_report(report)
    if not resource and fitted.result != 'error':
        # Output/report-size trouble must not erase the original I/O or internal
        # failure and produce an exit-5 report labelled merely inconclusive.
        diagnostic = replace(diagnostic,message=diagnostic.message +
                             ' Display labels and query text were omitted to fit the error envelope.')
        fitted = finalize_report(replace(report,
                     inputs=tuple(replace(item,label='[label omitted]') for item in inputs),
                     query=b'' if command == 'explain' else None,diagnostics=(diagnostic,)))
    return fitted


def _parser():
    parser = _SafeArgumentParser(prog='globdelta',description='Compare explicit root ignore policies offline.')
    parser.add_argument('--version',action='version',version='globdelta 0.1.0')
    subparsers = parser.add_subparsers(dest='command',required=True)
    for name in ('diff','explain'):
        command = subparsers.add_parser(name)
        if name == 'diff':
            command.add_argument('before')
            command.add_argument('after')
        else:
            command.add_argument('policy')
            command.add_argument('path',help='Hypothetical relative regular-file path; never read from disk')
        command.add_argument('--format',choices=('text','json'),default='text')
        command.add_argument('--output',metavar='REPORT',help='Exclusively create a new report file')
        command.add_argument('--limit',action='append',default=[],metavar='NAME=VALUE')
    return parser


def _limits(parser, assignments):
    accepted = {field.name for field in fields(Limits)}
    values = {}
    for assignment in assignments:
        name, separator, value = assignment.partition('=')
        if not separator or name not in accepted:
            parser.error('invalid limit assignment: ' + ascii(assignment))
        try:
            values[name] = int(value,10)
        except ValueError:
            parser.error('limit value must be an integer: ' + ascii(assignment))
    try:
        return Limits(**values)
    except ValueError as error:
        parser.error(str(error))


def main(argv=None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    limits = _limits(parser,arguments.limit)
    roles = ('before','after') if arguments.command == 'diff' else ('policy',)
    inputs = [Input(role,getattr(arguments,role),0,False,None,None) for role in roles]
    query = None
    buffers = []
    report = None
    required_report_payload = 3 * limits.report_bytes
    if limits.payload_bytes < required_report_payload:
        # Do not materialize or encode unbounded query/label values after the
        # adjustable payload budget has already failed. A fixed emergency
        # allowance (8192 bytes) is reserved independently of that budget.
        inputs = [replace(item,label='[label omitted]') for item in inputs]
        query = b'' if arguments.command == 'explain' else None
        report = _failure_report(arguments.command,inputs,limits,
                    Diagnostic('emergency_reserve','Report scratch reserve could not be allocated; display labels and query text were omitted.'),
                    LimitStop('payload_bytes','report_reserve',0,required_report_payload,limits.payload_bytes),query)
    payload_available = max(0,limits.payload_bytes - required_report_payload)
    if report is None and arguments.command == 'explain':
        # Count exact filesystem-encoded bytes using bounded single-character
        # fragments before allocating the complete byte string. The character
        # count is an immediate lower bound for a too-large query.
        query_size = len(arguments.path)
        if query_size <= payload_available:
            query_size = 0
            for character in arguments.path:
                query_size += len(os.fsencode(character))
                if query_size > payload_available:
                    break
        if query_size > payload_available:
            query = b''
            report = _failure_report(arguments.command,inputs,limits,
                     Diagnostic('emergency_reserve','Query encoding would exceed the payload limit; query text was omitted.'),
                     LimitStop('payload_bytes','query_encoding',required_report_payload,query_size,limits.payload_bytes),query)
        else:
            query = os.fsencode(arguments.path)
            payload_available -= len(query)
    try:
        for index,item in enumerate(inputs if report is None else ()):

            try:
                raw, inputs[index] = _read_input(item.label,item.role,limits,payload_available)
            except _ReadFailure as failure:
                inputs[index] = failure.metadata
                report = _failure_report(arguments.command,inputs,limits,failure.diagnostic,failure.stop,query)
                break
            buffers.append(raw)
            payload_available -= len(raw)
        if report is None:
            from .api import compare_policies, explain_path
            report = (compare_policies(buffers[0],buffers[1],limits) if arguments.command == 'diff'
                      else explain_path(buffers[0],query,limits))
            report = finalize_report(replace(report,inputs=tuple(replace(inputs[i],rule_count=item.rule_count)
                                                         for i,item in enumerate(report.inputs))))
    except Exception as error:
        report = _failure_report(arguments.command,inputs,limits,
                   Diagnostic('internal_error','Internal consistency failure (' + type(error).__name__ + ').'),query=query)
    render = to_json if arguments.format == 'json' else to_text
    code = exit_code(report)
    try:
        encoded = render(report)
        if arguments.output is None:
            sys.stdout.write(encoded)
            sys.stdout.flush()
        else:
            # 'x' maps to atomic O_EXCL creation and rejects existing symlinks,
            # hardlinks and input aliases, without a check-then-overwrite race.
            with open(arguments.output,'x',encoding='ascii',newline='') as output:
                output.write(encoded)
    except (OSError, ValueError) as error:
        # Release the successful encoding before constructing an I/O envelope.
        encoded = None
        if arguments.output is None:
            _close_failed_stream(sys.stdout)
        failure = _failure_report(arguments.command,report.inputs,limits,
                  Diagnostic('io_error','Could not write the report using exclusive creation or stdout (errno ' +
                             str(getattr(error,'errno',None)) + ').'),query=query)
        try:
            sys.stderr.write(render(failure))
            sys.stderr.flush()
        except (OSError, ValueError):
            _close_failed_stream(sys.stderr)
        return 5
    return code
