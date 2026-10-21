"""Create resource ZIPs and versioned standalone installers from the worktree."""
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
PAYLOAD_MARKER = '# ANREROLL_POWERSHELL_PAYLOAD'


def validate_version(version: str) -> None:
    if len(version) > 64 or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Use a three-part numeric version without a v prefix, for example 1.0.0.')


def cmd_installer(script: str) -> bytes:
    # The full, readable PS1 is embedded: no second installer download, temporary
    # PS1, encoded command, admin prompt or persistent execution-policy changes.
    command = (
        "$ErrorActionPreference='Stop'; try { "
        "if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'PowerShell 5.1 or newer is required.' }; "
        "$launcher=[IO.Path]::GetFullPath($env:ANREROLL_SETUP_LAUNCHER); "
        "$content=[IO.File]::ReadAllText($launcher,[Text.Encoding]::UTF8); "
        f"$marker='{PAYLOAD_MARKER}'+[char]13+[char]10; "
        "$offset=$content.IndexOf($marker,[StringComparison]::Ordinal); "
        "if ($offset -lt 0) { throw 'Installer payload is missing.' }; "
        "Set-Location -LiteralPath ([IO.Path]::GetDirectoryName($launcher)); "
        "& ([scriptblock]::Create($content.Substring($offset+$marker.Length))) "
        "} catch { Write-Error $_; exit 1 }"
    )
    header = [
        '@echo off',
        'setlocal DisableDelayedExpansion',
        'set "ANREROLL_SETUP_LAUNCHER=%~f0"',
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "{command}"',
        'set "ANREROLL_SETUP_EXIT=%ERRORLEVEL%"',
        'if not "%ANREROLL_SETUP_EXIT%"=="0" echo Setup failed. Review the error above.',
        'if not defined ANREROLL_SETUP_NO_PAUSE pause',
        'exit /b %ANREROLL_SETUP_EXIT%',
        '',
        PAYLOAD_MARKER,
    ]
    return ('\r\n'.join(header) + '\r\n' + script.replace('\r\n', '\n').replace('\n', '\r\n')).encode('utf-8')


def build_installers(root: Path, output: Path, version: str, *, replace: bool = False) -> list[Path]:
    validate_version(version)
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root / 'assets'):
        raise ValueError('Output must not be inside assets.')
    script = checked_file(root, 'Setup.ps1').read_text(encoding='utf-8-sig')
    default = "    [string]$ResourceTag = 'latest',"
    if script.count(default) != 1:
        raise ValueError('Cannot pin the installer resource version; review Setup.ps1.')
    script = script.replace(default, f"    [string]$ResourceTag = 'v{version}',")
    script = script.replace('#Requires -Version 5.1\n', f'#Requires -Version 5.1\n# Arknights_Reroll resource release: v{version}\n', 1)
    contents = {
        output / f'Setup_{version}.ps1': script.replace('\n', '\r\n').encode('utf-8-sig'),
        output / f'Setup_{version}.cmd': cmd_installer(script),
    }
    installers = list(contents)
    for path, data in list(contents.items()):
        digest = hashlib.sha256(data).hexdigest()
        contents[path.with_suffix(path.suffix + '.sha256')] = f'{digest}  {path.name}\n'.encode('ascii')
    # Check all collisions before writing anything, and never replace old
    # versions implicitly. Re-running unchanged generation is safe/idempotent.
    for path, data in contents.items():
        if path.is_symlink():
            raise ValueError(f'Refusing installer symlink: {path}')
        if path.exists() and not replace and path.read_bytes() != data:
            raise FileExistsError(f'Preserving existing installer: {path}; use --replace-installers explicitly.')
    output.mkdir(parents=True, exist_ok=True)
    for path, data in contents.items():
        path.write_bytes(data)
    return installers


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
    validate_version(version)
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
    parser.add_argument('--version', required=True, help='Three-part numeric release version, e.g. 1.0.0 (no v prefix).')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--installer-output-dir', type=Path, default=ROOT / 'Distribution')
    parser.add_argument('--installers-only', action='store_true', help='Generate installers without rebuilding the resource ZIP.')
    parser.add_argument('--replace-installers', action='store_true', help='Explicitly replace generated installers of the same version.')
    args = parser.parse_args()
    assets = [] if args.installers_only else build(ROOT, args.output_dir, args.version)
    assets += build_installers(ROOT, args.installer_output_dir, args.version, replace=args.replace_installers)
    for path in assets:
        print(f'{path}\n  SHA256 {sha256(path)}')


if __name__ == '__main__':
    main()
