"""Create release assets from the worktree, respecting Git ignore rules."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ('assets/user/', 'assets/saved/', 'assets/failed/',
           'assets/resources/config/', 'assets/resources/debug/', 'assets/resources/model/')
SUPPORT = ('deployment/runtime.json', 'deployment/agent-requirements.txt',
           'tools/verify_install.py', 'LICENSE.MaaReroll', 'README.md', 'DEPLOYMENT.md')
MODELS = tuple('assets/resources/model/ocr/ko/' + name for name in ('det.onnx', 'rec.onnx', 'keys.txt'))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], input=data,
                            capture_output=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    return result.stdout


def checked_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Missing/outside release file: {relative}')
    for component in (path, *path.parents):
        if component == root.parent:
            break
        info = component.lstat()
        if component.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError(f'Reparse points cannot be packaged: {relative}')
    return path


def release_files(root: Path) -> list[str]:
    tracked = git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z',
                  '--', 'assets/resources', 'assets/agent')
    candidates = sorted(set(filter(None, tracked.decode('utf-8').split('\0'))) | set(SUPPORT) | set(MODELS))
    ignored = set(filter(None, git(root, 'check-ignore', '--no-index', '-z', '--stdin',
                                  data=('\0'.join(candidates) + '\0').encode()).decode('utf-8').split('\0')))
    result = []
    for relative in candidates:
        # --no-index also excludes files that were tracked before being ignored.
        # The user explicitly permits these three existing OCR files in releases.
        # They remain ignored by Git; no other ignored model/cache is included.
        if relative not in MODELS and (relative in ignored or relative.startswith(PRIVATE)):
            continue
        if not (root / relative).is_file():
            continue
        checked_file(root, relative)
        result.append(relative)
    required = {*SUPPORT, *MODELS, 'assets/resources/interface.json', 'assets/agent/main.py',
                'assets/agent/actions.py', 'assets/agent/requirements.txt'}
    if not required.issubset(result):
        raise ValueError(f'Required files are missing/ignored: {sorted(required - set(result))}')
    return result


def checksum(archive: Path) -> Path:
    destination = archive.with_suffix(archive.suffix + '.sha256')
    destination.write_text(f'{sha256(archive)}  {archive.name}\n', encoding='ascii')
    return destination


def build(root: Path, output: Path, version: str) -> list[Path]:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version):
        raise ValueError('Use a simple release version, for example v0.1.0.')
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root / 'assets'):
        raise ValueError('Output must not be inside assets.')
    files = release_files(root)
    runtime = json.loads((root / 'deployment/runtime.json').read_text(encoding='utf-8-sig'))
    required = (root / 'assets/agent/requirements.txt').read_text(encoding='utf-8-sig')
    if f'MaaFw=={runtime["maafw_version"]}' not in required.splitlines():
        raise ValueError('Agent requirements and deployment SDK versions differ.')
    manifest = {'schema_version': 1, 'version': version,
                'source_commit': git(root, 'rev-parse', 'HEAD').decode().strip(),
                'runtime': runtime, 'files': {name: sha256(root / name) for name in files}}
    destinations = [output / f'ANReroll-resources-{version}.zip']
    for name, expected in runtime['ocr']['files'].items():
        path = checked_file(root, 'assets/resources/model/ocr/ko/' + name)
        if sha256(path) != expected:
            raise ValueError(f'OCR model differs from deployment/runtime.json: {name}')
    for path in destinations:
        if path.exists() or path.with_suffix('.zip.sha256').exists():
            raise FileExistsError(f'Preserving existing release asset: {path}')
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destinations[0], 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in files:
            archive.write(root / name, name)
        archive.writestr('ANREROLL-RESOURCE.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    for path in destinations:
        checksum(path)
    return destinations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    for path in build(ROOT, args.output_dir, args.version):
        print(f'{path}\n  SHA256 {sha256(path)}')


if __name__ == '__main__':
    main()
