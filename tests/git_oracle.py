"""Development-only Git oracle. No GlobDelta matching or parsing code is imported.

All targets are real regular files. Equal-depth antichains prevent a target from
also becoming another target's parent directory. An unavailable/unusable Git is
an error, never a successful or skipped conformance result.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


class GitOracleError(AssertionError):
    """The oracle did not establish a trustworthy answer."""


class UnmaterializablePath(GitOracleError):
    """A valid abstract path exceeds this host's filesystem capabilities."""


@dataclass(frozen=True)
class GitDecision:
    ignored: bool
    source: bytes
    line: int | None
    pattern: bytes
    path: bytes
    actual_type: str
    verbose_returncode: int
    quiet_returncode: int


def parse_verbose(output: bytes, paths: tuple[bytes, ...]):
    """Validate exact four-field NUL framing and queried-path correspondence."""
    fields = output.split(b'\0')
    if not output.endswith(b'\0') or len(fields) != 4 * len(paths) + 1:
        raise GitOracleError(f'Bad verbose NUL framing: {output!r}')
    records = []
    for index, path in enumerate(paths):
        source, line, pattern, echoed = fields[index * 4:index * 4 + 4]
        if echoed != b'./' + path:
            raise GitOracleError(f'Wrong echoed path: {echoed!r}, expected {path!r}')
        if source:
            if source != b'.gitignore' or not line.isdigit() or int(line) < 1 or not pattern:
                raise GitOracleError(f'Unexpected ignore source record: {source!r}, {line!r}, {pattern!r}')
        elif line or pattern:
            raise GitOracleError('Nonmatching record has a line or pattern')
        # Verbose exits successfully for negated matches as well as exclusions.
        ignored = bool(source) and not pattern.startswith(b'!')
        records.append((ignored, source, int(line) if line else None, pattern))
    return records


def _safe_path(path: bytes):
    if not isinstance(path, bytes) or not path or any(b < 32 or b > 126 for b in path):
        raise ValueError(f'Not a profile path: {path!r}')
    components = path.split(b'/')
    if any(c in (b'', b'.', b'..', b'.git') for c in components):
        raise ValueError(f'Unsafe path components: {path!r}')
    if components[0] == b'.gitignore' and len(components) > 1:
        raise ValueError('Root .gitignore must remain the policy file')


class GitOracle:
    def __init__(self, executable: str | None = None, ledger: Path | None = None):
        self.ledger = ledger or (Path(os.environ['GLOBDELTA_ORACLE_LEDGER']) if os.environ.get('GLOBDELTA_ORACLE_LEDGER') else None)
        self.executable = shutil.which(executable or 'git')
        if not self.executable:
            raise GitOracleError('Mandatory Git executable is unavailable')
        self._temporary = tempfile.TemporaryDirectory(prefix='globdelta-oracle-')
        self.root = Path(self._temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        (self.root / 'home').mkdir()
        (self.root / 'template').mkdir()
        (self.root / 'empty').write_bytes(b'')
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.environment.update({
            'HOME': str(self.root / 'home'), 'XDG_CONFIG_HOME': str(self.root / 'home'),
            'LC_ALL': 'C', 'LANG': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_SYSTEM': str(self.root / 'empty'),
            'GIT_CONFIG_GLOBAL': str(self.root / 'empty'), 'GIT_ATTR_NOSYSTEM': '1',
        })
        self.config = (
            '-c', 'core.ignoreCase=false', '-c', 'core.precomposeUnicode=false',
            '-c', 'core.protectNTFS=false', '-c', 'core.protectHFS=false',
            '-c', f'core.excludesFile={self.root / "empty"}',
            '-c', f'core.attributesFile={self.root / "empty"}',
            '-c', 'core.fsmonitor=false',
        )
        try:
            self.version = self.command('--version').stdout.decode('ascii').strip()
            self.command('init', '--quiet', f'--template={self.root / "template"}')
            (self.repo / '.git' / 'info').mkdir(exist_ok=True)
            (self.repo / '.git' / 'info' / 'exclude').write_bytes(b'')
            self.command('read-tree', '--empty')
            if self.command('ls-files', '-z').stdout:
                raise GitOracleError('Oracle repository index is not empty')
        except BaseException:
            self.close()
            raise
        self.queries = 0
        self.batches = 0
        self.record({'kind': 'environment', **self.metadata()})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._temporary.cleanup()

    def command(self, *args: str | bytes, stdin: bytes | None = None, allowed=(0,)):
        try:
            result = subprocess.run(
                [self.executable, *self.config, '-C', str(self.repo), *args],
                input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.environment, check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitOracleError(f'Git command failed: {args!r}: {error}') from error
        if result.returncode not in allowed:
            raise GitOracleError(f'Git command {args!r}: exit {result.returncode}, stderr={result.stderr!r}')
        # Git warns about a directory named .gitignore in the allowed profile.
        # Only that warning is expected; unknown stderr is an oracle failure.
        unexpected = [line for line in result.stderr.splitlines()
                      if not (line.startswith(b"warning: unable to access '")
                              and line.endswith(b"/.gitignore': Is a directory"))]
        if unexpected:
            raise GitOracleError(f'Unexpected Git stderr: {result.stderr!r}')
        return result

    def _rebuild(self, policy: bytes, paths: tuple[bytes, ...]):
        for item in self.repo.iterdir():
            if item.name == '.git':
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        (self.repo / '.gitignore').write_bytes(policy)
        for path in paths:
            target = self.repo / path.decode('ascii')
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if path != b'.gitignore':
                    target.write_bytes(b'')
                if not stat.S_ISREG(target.lstat().st_mode):
                    raise GitOracleError(f'Target is not a regular file: {path!r}')
            except OSError as error:
                if error.errno in (errno.ENAMETOOLONG, errno.EINVAL):
                    raise UnmaterializablePath(f'Unvalidated on this filesystem: {path!r}: {error}') from error
                raise
        if (self.repo / '.gitignore').read_bytes() != policy:
            raise GitOracleError('The policy file was overwritten while materializing paths')

    def check(self, policy: bytes, paths) -> dict[bytes, GitDecision]:
        groups = defaultdict(list)
        for path in dict.fromkeys(paths):
            _safe_path(path)
            groups[path.count(b'/')].append(path)
        decisions = {}
        for depth in sorted(groups):
            batch = tuple(groups[depth])
            self._rebuild(policy, batch)
            verbose = self.command('check-ignore', '--no-index', '--stdin', '-z',
                                   '--verbose', '--non-matching',
                                   stdin=b''.join(b'./' + p + b'\0' for p in batch),
                                   allowed=(0, 1))
            for path, record in zip(batch, parse_verbose(verbose.stdout, batch)):
                quiet = self.command('check-ignore', '--no-index', '--quiet', '--',
                                     b'./' + path, allowed=(0, 1))
                ignored, source, line, pattern = record
                if ignored != (quiet.returncode == 0):
                    raise GitOracleError(f'Quiet/verbose mismatch: policy={policy!r}, path={path!r}')
                decisions[path] = GitDecision(ignored, source, line, pattern, path,
                                             'regular-file', verbose.returncode,
                                             quiet.returncode)
                self.record({'kind': 'query', 'policy_hex': policy.hex(),
                             'policy_sha256': hashlib.sha256(policy).hexdigest(),
                             'path_hex': path.hex(), 'actual_type': 'regular-file',
                             'ignored': ignored, 'source_hex': source.hex(),
                             'line': line, 'pattern_hex': pattern.hex(),
                             'verbose_returncode': verbose.returncode,
                             'quiet_returncode': quiet.returncode})
            self.queries += len(batch)
            self.batches += 1
        return decisions

    def verify_witness(self, before: bytes, after: bytes, path: bytes, direction: str):
        """Require actual-file Git verification under both policy alternatives."""
        if direction not in ('newly_ignored', 'newly_included'):
            raise ValueError('Unknown witness direction')
        expected = (False, True) if direction == 'newly_ignored' else (True, False)
        observed = (self.check(before, [path])[path].ignored,
                    self.check(after, [path])[path].ignored)
        if observed != expected:
            raise GitOracleError(f'Wrong {direction} witness {path!r}: '
                                 f'before={before!r}; after={after!r}; Git={observed!r}')
        return observed

    def metadata(self):
        """Stable audit information, with disposable locations made explicit."""
        selected = ('HOME', 'XDG_CONFIG_HOME', 'LC_ALL', 'LANG', 'GIT_CONFIG_NOSYSTEM',
                    'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_ATTR_NOSYSTEM')
        replace_root = lambda value: value.replace(str(self.root), '$TMP')
        return {
            'executable': self.executable, 'version': self.version,
            'environment': {k: replace_root(self.environment[k]) for k in selected},
            'inherited_git_variables': 'all removed before explicit isolation overrides',
            'config': [replace_root(c) for c in self.config],
            'template': 'empty', 'index': 'empty', 'info_exclude': 'empty',
            'actual_target_type': 'regular-file', 'batching': 'equal-component-depth antichains',
            'verbose': ['check-ignore', '--no-index', '--stdin', '-z', '--verbose', '--non-matching'],
            'crosscheck': 'one quiet check per queried path',
        }

    def record(self, value):
        """Append full evidence only when the caller explicitly selects a ledger."""
        if self.ledger is not None:
            with self.ledger.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
