"""Allowlisted source export and independent folder/package verification.

Never imports the application, follows source symlinks, or writes playthroughs.
This is a distribution boundary, not a general-purpose secret-detection service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import zipfile
import zlib

MANIFEST = 'SOURCE_EXPORT.json'
LIMIT = 2 * 1024 * 1024
SCREENSHOTS = {'docs/screenshots/party.png', 'docs/screenshots/training.png',
               'docs/screenshots/encounters.png'}
FORBIDDEN = {'data', 'profiles', 'sessions', 'roms', 'templates', 'runtime',
             'assets', 'vendor', 'checkpoints', 'fixtures', 'pokemon.app'}
PRIVATE = re.compile(r"/(?:Users|home)/[^/\s\"']+/|/var/(?:folders)/|[A-Z]:\\Users\\[^\\\s]+\\")
SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}')


class ExportError(ValueError):
    pass


def safe_name(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise ExportError('Invalid export path: ' + name)
    if any(p.casefold() in FORBIDDEN for p in path.parts):
        raise ExportError('Private/resource directory is forbidden: ' + name)
    lower = path.name.lower()
    if (path.suffix.lower() in {'.gba', '.gb', '.gbc', '.sav', '.srm', '.state', '.db', '.sqlite', '.sqlite3', '.dylib', '.so', '.dll', '.pem', '.key'}
            or '.state.' in lower or '.sqlite' in lower or lower.startswith('.env')):
        raise ExportError('Private/binary file is forbidden: ' + name)
    return path


def check_text(name, data):
    safe_name(name)
    if len(data) > LIMIT or b'\0' in data:
        raise ExportError('Oversized or binary source file: ' + name)
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ExportError('Non-text source file: ' + name) from error
    if PRIVATE.search(text) or SECRET.search(text):
        raise ExportError('Personal path or credential detected in: ' + name)
    return data


def check_payload(name, data):
    """Only explicitly reviewed documentation images may contain binary data."""
    if name not in SCREENSHOTS:return check_text(name, data)
    safe_name(name)
    if len(data)>LIMIT or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ExportError('Invalid documentation screenshot: '+name)
    offset=8;tags=[]
    while offset<len(data):
        if offset+12>len(data):raise ExportError('Truncated PNG: '+name)
        size=struct.unpack('>I',data[offset:offset+4])[0]
        tag=data[offset+4:offset+8];end=offset+12+size
        if end>len(data) or tag not in (b'IHDR',b'PLTE',b'IDAT',b'IEND',b'sRGB',b'gAMA',b'cHRM',b'pHYs',b'iCCP',b'tRNS',b'cICP'):
            raise ExportError('Unexpected PNG chunk/metadata: '+name)
        body=data[offset+8:end-4]
        if zlib.crc32(tag+body)&0xffffffff != struct.unpack('>I',data[end-4:end])[0]:
            raise ExportError('PNG checksum mismatch: '+name)
        if not tags:
            if tag!=b'IHDR' or len(body)!=13:raise ExportError('Invalid PNG header: '+name)
            width,height=struct.unpack('>II',body[:8])
            if not 1<=width<=4096 or not 1<=height<=4096 or width*height>8_000_000:
                raise ExportError('Oversized PNG dimensions: '+name)
        if tag==b'IEND' and (body or end!=len(data)):raise ExportError('Trailing PNG data: '+name)
        tags.append(tag);offset=end
    if tags.count(b'IHDR')!=1 or not tags or tags[-1]!=b'IEND' or tags.count(b'IEND')!=1 or b'IDAT' not in tags:
        raise ExportError('Incomplete PNG: '+name)
    return data


def read_regular(root, name):
    relative = safe_name(name)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ExportError('Symlink is forbidden: ' + name)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ExportError('Expected a regular source file: ' + name)
    if path.stat().st_size > LIMIT:
        raise ExportError('Oversized source file: ' + name)
    return check_payload(name, path.read_bytes())


def selection(root):
    policy = json.loads(read_regular(root, 'tools/source_export_manifest.json'))
    if policy.get('schema') != 1:
        raise ExportError('Unsupported source policy')
    names = set(policy['files'])
    for tree in policy['trees']:
        base = str(safe_name(tree['path']))
        if tree['pattern'] not in ('*.py', 'test_*.py'):
            raise ExportError('Unsupported source glob')
        directory = root / base
        if directory.is_symlink():
            raise ExportError('Symlink is forbidden: ' + base)
        if not directory.is_dir():
            raise ExportError('Required source directory is missing: ' + base)
        names.update(str(p.relative_to(root).as_posix()) for p in directory.glob(tree['pattern']))
    result = {name: read_regular(root, name) for name in sorted(names)}
    for source, destination in policy.get('rename', {}).items():
        safe_name(destination)
        if destination in result:
            raise ExportError('Duplicate export destination: ' + destination)
        result[destination] = result[source]
    return result


def inventory(files):
    return [dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in sorted(files.items())]


def export_source(project, output):
    project = Path(project).resolve()
    output = Path(output).absolute()
    output = output.parent.resolve() / output.name
    if output == project or output.is_relative_to(project):
        raise ExportError('Export must be outside the working installation')
    if os.path.lexists(output):
        raise ExportError('Output already exists; refusing to overwrite it')
    files = selection(project)  # Validate everything before creating any output.
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.pokedesk-source-', dir=output.parent))
    try:
        for name, data in files.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (temporary / MANIFEST).write_text(json.dumps(dict(schema=1, files=inventory(files)), indent=2) + '\n', encoding='utf-8')
        verify_export(temporary)
        if os.path.lexists(output):
            raise ExportError('Output appeared during export; refusing to overwrite it')
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return dict(files=len(files), bytes=sum(map(len, files.values())))


def verify_export(folder):
    folder = Path(folder).resolve()
    manifest = json.loads(read_regular(folder, MANIFEST))
    if manifest.get('schema') != 1 or not isinstance(manifest.get('files'), list):
        raise ExportError('Unsupported export inventory')
    listed = [row['path'] for row in manifest['files']]
    if len(listed) != len(set(listed)):
        raise ExportError('Duplicate export inventory entry')
    expected = selection(folder)
    # Public README is intentionally generated from the reviewed source README.
    if set(listed) != set(expected) or inventory(expected) != manifest['files']:
        raise ExportError('Export inventory, policy or source hashes do not match')
    actual = set()
    for directory, dirs, names in os.walk(folder, followlinks=False):
        parent = Path(directory)
        for name in [*dirs, *names]:
            if (parent / name).is_symlink():
                raise ExportError('Symlink in exported tree')
        for name in names:
            relative = (parent / name).relative_to(folder).as_posix()
            if relative != MANIFEST:
                read_regular(folder, relative)
                actual.add(relative)
    if actual != set(listed):
        raise ExportError('Unexpected or missing files in exported tree')
    return dict(files=len(listed), verified=True)


def verify_artifact(archive, source):
    """Inspect without extraction; payload bytes must match a verified export."""
    source, archive = Path(source), Path(archive)
    verify_export(source)
    originals = selection(source)
    payload = {}
    byte_budget = sum(map(len, originals.values())) + 4 * LIMIT
    member_budget = len(originals) + 32
    if archive.suffix == '.whl':
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > member_budget or sum(e.file_size for e in entries) > byte_budget:
                raise ExportError('Archive exceeds source size/member budget')
            for entry in entries:
                if entry.is_dir():
                    continue
                if entry.file_size > LIMIT or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ExportError('Oversized or symlink archive member')
                if entry.filename in payload:
                    raise ExportError('Duplicate archive member')
                payload[entry.filename] = package.read(entry)
    else:
        with tarfile.open(archive) as package:
            roots = set()
            for entry in package:
                if entry.isdir():
                    continue
                if not entry.isfile() or entry.size > LIMIT:
                    raise ExportError('Non-regular or oversized archive member')
                byte_budget -= entry.size
                if byte_budget < 0 or len(payload) >= member_budget:
                    raise ExportError('Archive exceeds source size/member budget')
                safe_name(entry.name)
                root, slash, name = entry.name.partition('/')
                roots.add(root)
                if not slash or name in payload:
                    raise ExportError('Invalid or duplicate archive member')
                payload[name] = package.extractfile(entry).read()
            if len(roots) != 1:
                raise ExportError('Multiple source archive roots')
    seen = set()
    for name, data in payload.items():
        check_payload(name, data)
        mapped = 'src/' + name if name.startswith('pokemon_red/') else name
        if mapped in originals:
            if data != originals[mapped]:
                raise ExportError('Artifact payload differs from verified source: ' + name)
            seen.add(mapped)
            continue
        # Generated package metadata is text-only and has a narrow namespace.
        parts = PurePosixPath(name).parts
        metadata = {'METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt',
                    'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'not-zip-safe'}
        if len(parts) == 2 and parts[0].endswith(('.dist-info', '.egg-info')) and parts[1] in metadata:
            continue
        if len(parts) == 3 and parts[0] == 'src' and parts[1].endswith('.egg-info') and parts[2] in metadata:
            continue
        if len(parts) >= 3 and parts[0].endswith('.dist-info') and parts[1] == 'licenses':
            license_name = '/'.join(parts[2:])
            if license_name not in originals or data != originals[license_name]:
                raise ExportError('Changed artifact license')
            seen.add(license_name)
            continue
        if name in ('PKG-INFO', 'setup.cfg'):
            continue
        raise ExportError('Unexpected artifact member: ' + name)
    required = {name for name in originals if name.startswith('src/pokemon_red/')}
    required.update(name for name in originals if name in ('LICENSE','NOTICE','THIRD_PARTY_NOTICES.md') or name.startswith('licenses/'))
    if not required <= seen:
        raise ExportError('Artifact is missing application source or UI catalogs')
    return dict(files=len(payload), verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--check', type=Path)
    group.add_argument('--check-artifact', type=Path)
    args = parser.parse_args()
    try:
        if args.output:
            result = export_source(args.project, args.output)
        elif args.check:
            result = verify_export(args.check)
        else:
            result = verify_artifact(args.check_artifact, args.project)
    except (ExportError, OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, 'Source export rejected: ' + str(error) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
