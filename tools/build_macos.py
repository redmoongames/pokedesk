"""Build and audit a ROM-free, relocatable Apple Silicon .app.

Developer tool only. Players use the prebuilt DMG. Inputs are this clean source
tree plus a hash-verified dependency directory, never a playable installation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from export_source import selection

RUNTIME = 'runtime/python/cpython-3.12.16-macos-aarch64-none'
FORBIDDEN = {'.gba', '.gb', '.gbc', '.sav', '.srm', '.state', '.sqlite', '.sqlite3'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dependencies(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'dependencies.json').read_text())
    if manifest.get('schema') != 1 or manifest.get('platform') != 'macos-arm64':
        raise ValueError('Unsupported dependency manifest')
    for name, expected in manifest.get('adapter_sources', {}).items():
        if name not in ('bridge.c', 'link.c', 'playback.m', 'build.py') or sha256(ROOT / 'native' / name) != expected:
            raise ValueError('Native adapter source changed; rebuild dependencies')
    records = manifest['files']
    actual = set()
    for path in folder.rglob('*'):
        if path.is_dir() and not path.is_symlink():
            continue
        name = path.relative_to(folder).as_posix()
        if name == 'dependencies.json':
            continue
        actual.add(name)
        record = records.get(name)
        if record is None:
            raise ValueError('Unlisted dependency: ' + name)
        if path.is_symlink():
            if not path.exists() or path.readlink().is_absolute() or not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError('Dependency link escapes its directory: ' + name)
            if record != dict(link=str(path.readlink())):
                raise ValueError('Changed dependency link: ' + name)
        elif not path.is_file() or record.get('sha256') != sha256(path):
            raise ValueError('Changed dependency: ' + name)
    if actual != set(records):
        raise ValueError('Missing dependencies')
    for name in ('native/libpokemon.dylib', 'native/mgba_libretro.dylib', RUNTIME + '/bin/python3'):
        if not (folder / name).is_file():
            raise ValueError('Missing required dependency: ' + name)
    if not (folder / 'licenses').is_dir():
        raise ValueError('Dependency license texts are required')
    return manifest


def audit_bundle(app):
    app = Path(app).resolve()
    installation = app / 'Contents/Resources/installation'
    if not (installation / 'desktop_main.py').is_file():
        raise ValueError('Missing application entry point')
    files = []
    for path in app.rglob('*'):
        if path.is_symlink():
            if not path.exists() or not path.resolve().is_relative_to(app):
                raise ValueError('External bundle symlink: ' + str(path.relative_to(app)))
            continue
        if path.is_dir():
            if path.name.casefold() in ('data', 'profiles', 'sessions', 'roms', 'templates', 'checkpoints'):
                # Python's own stdlib includes packages called data; only the
                # application installation's top-level user trees are forbidden.
                if path.parent == installation:
                    raise ValueError('Private tree in bundle: ' + path.name)
            continue
        name = path.relative_to(app).as_posix()
        if path.suffix.lower() in FORBIDDEN or '.state.' in path.name.lower():
            raise ValueError('ROM/save/database in bundle: ' + name)
        if path.stat().st_size >= 1024*1024:
            with path.open('rb') as stream:
                header = stream.read(0xc0)
            if header[0xac:0xb0] in (b'BPRE', b'BPGE', b'AXVE', b'AXPE'):
                raise ValueError('Game cartridge header in bundle: ' + name)
        if path.suffix in ('.dylib', '.so') or name == 'Contents/MacOS/PokeDesk':
            linked = '\n'.join(subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True).splitlines()[1:])
            if '/Users/' in linked or '/opt/homebrew/' in linked or '/usr/local/' in linked:
                raise ValueError('Nonportable native dependency: ' + name)
        files.append(dict(path=name, sha256=sha256(path), bytes=path.stat().st_size))
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return dict(schema=1, files=files, roms=0, saves=0)


def icon_png(size):
    """Original pixel P mark, no game artwork or third-party fonts."""
    glyph = ['11110', '11011', '11011', '11110', '11000', '11000', '11000']
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            gx, gy = (x*12//size)-3, (y*12//size)-2
            ink = 0 <= gx < 5 and 0 <= gy < 7 and glyph[gy][gx] == '1'
            edge = min(x, y, size-1-x, size-1-y) < size//18
            color = (152, 214, 184, 255) if ink else (41, 62, 65, 255) if edge else (23, 29, 33, 255)
            pixels.extend(color)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(pixels), 6)) + chunk(b'IEND', b''))


def build(dependencies, output, version):
    dependencies, output = Path(dependencies).resolve(), Path(output).resolve()
    manifest = verify_dependencies(dependencies)
    if output.exists():
        raise ValueError('Output must be a new directory')
    output.mkdir(parents=True)
    app = output / 'PokeDesk.app'
    contents = app / 'Contents'
    installation = contents / 'Resources/installation'
    installation.mkdir(parents=True)
    source = selection(ROOT)
    # Only runtime code and explicit release seeds enter the game installation.
    for name, payload in source.items():
        if name.startswith(('src/', 'Bots/')) or name in ('main.py', 'desktop_main.py'):
            path = installation / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    for name in ('runtime', 'native'):
        shutil.copytree(dependencies / name, installation / name, symlinks=True)
    (installation / 'native/distribution.json').write_text(json.dumps(dict(schema=1, games=['firered'])) + '\n')
    notices = contents / 'Resources/licenses'
    shutil.copytree(dependencies / 'licenses', notices)
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT / name, notices / name)
    shutil.copytree(ROOT / 'licenses', notices / 'project-dependencies')
    # uv's local libpython install ID must never enter a public bundle.
    python_lib = installation / RUNTIME / 'lib/libpython3.12.dylib'
    subprocess.run(['install_name_tool', '-id', '@rpath/libpython3.12.dylib', str(python_lib)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(python_lib)], check=True)
    runtime_source = {name: payload for name, payload in source.items()
        if name.startswith(('src/', 'Bots/')) or name in
        ('main.py', 'desktop_main.py', 'native/app_launcher.m', 'tools/build_macos.py', 'tools/prepare_macos_dependencies.py')}
    identifier = hashlib.sha256(json.dumps(dict(version=version,
        source={n: hashlib.sha256(b).hexdigest() for n, b in runtime_source.items()},
        dependencies=manifest), sort_keys=True).encode()).hexdigest()
    (installation / 'desktop-build.json').write_text(json.dumps(dict(schema=1, version=version, build_id=identifier), indent=2) + '\n')
    info = dict(CFBundleDisplayName='PokéDesk', CFBundleName='PokéDesk',
        CFBundleExecutable='PokeDesk', CFBundleIdentifier='games.redmoon.pokedesk',
        CFBundlePackageType='APPL', CFBundleShortVersionString=version.split('-')[0],
        CFBundleVersion=version.split('-')[0], CFBundleIconFile='PokeDesk.icns',
        LSMinimumSystemVersion='13.0', NSHighResolutionCapable=True,
        LSApplicationCategoryType='public.app-category.games')
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    executable = contents / 'MacOS/PokeDesk'
    executable.parent.mkdir()
    subprocess.run(['clang', '-O2', '-fobjc-arc', '-arch', 'arm64', '-mmacosx-version-min=13.0',
                    str(ROOT / 'native/app_launcher.m'), '-framework', 'AppKit', '-o', str(executable)], check=True)
    iconset = output / 'PokeDesk.iconset'
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            (iconset / f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png').write_bytes(icon_png(size*scale))
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(contents / 'Resources/PokeDesk.icns')], check=True)
    shutil.rmtree(iconset)
    # Existing nested code keeps its signatures. Ad-hoc sign the final envelope;
    # Developer ID/notarization is a separate documented release step.
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    report = audit_bundle(app)
    (output / 'bundle-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--version', default='0.1.0-beta.1')
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    if args.audit:
        print(json.dumps(audit_bundle(args.audit), indent=2))
    elif args.dependencies and args.output:
        print(build(args.dependencies, args.output, args.version))
    else:
        parser.error('--dependencies and --output are required for a build')


if __name__ == '__main__':
    main()
