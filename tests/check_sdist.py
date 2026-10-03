"""Build an sdist and verify it preserves the shipped validation material.

Development-only helper; requires the pre-provisioned setuptools backend.
Usage: python tests/check_sdist.py OUTPUT_DIRECTORY
"""
from pathlib import Path
import sys
import tarfile


def main():
    from setuptools.build_meta import build_sdist

    root = Path(__file__).resolve().parent.parent
    expected = {'README.md', 'LICENSE', 'pyproject.toml'}
    for folder in ('src', 'docs', 'examples', 'schemas', 'tests'):
        expected.update(str(p.relative_to(root)) for p in (root / folder).rglob('*')
                        if p.is_file() and '__pycache__' not in p.parts
                        and not p.name.endswith(('.pyc', '.pyo'))
                        and not any(part.endswith('.egg-info') for part in p.parts))
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / build_sdist(str(output))
    with tarfile.open(archive, 'r:gz') as package:
        files = {member.name.partition('/')[2] for member in package.getmembers()
                 if member.isfile()}
        missing = sorted(expected - files)
        assert not missing, f'Source distribution is missing validation files: {missing}'
        assert not any('__pycache__' in p or p.endswith(('.pyc', '.pyo')) for p in files)
    print(f'Source distribution contains all {len(expected)} required files: {archive.name}')


if __name__ == '__main__':
    main()
