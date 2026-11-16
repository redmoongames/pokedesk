"""Prepare redistributable dependencies; never reads a player's installation.

The pinned core and mGBA source are published with the GitHub release. Python is
the upstream standalone distribution, verified before extracting its install
tree and every dependency notice. Only the adapter is compiled locally.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-pgo%2Blto-full.tar.zst'
PYTHON_SHA256 = '016758f4881e5f71d63eddfbcdd53f25c5a9152435a863e4dc0770758eae32c3'
CORE_SHA256 = '54ae92e80b012013f6d777fb3158b9f925be22c97896049b8549614d7514f505'
SOURCE_SHA256 = {'5cbf639e527fb586bf33e14d59037eab35f78f45154e0b79c784fff474c3bc37',
                 'a1cf3087787b251e632220175b93613270510ed5adaa6a5cb729e9e2c313a601'}
MGBA_COMMIT = '7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6'
RUNTIME = 'runtime/python/cpython-3.12.16-macos-aarch64-none'
ADAPTER_FILES = ('bridge.c', 'link.c', 'playback.m', 'build.py')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(output, core, source, python_archive):
    if digest(core) != CORE_SHA256 or digest(python_archive) != PYTHON_SHA256 or digest(source) not in SOURCE_SHA256:
        raise ValueError('Dependency hash does not match the pinned release')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output must be a new directory')
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='pokedesk-dependencies-') as temporary:
        staging = Path(temporary)
        subprocess.run(['tar', '-xf', str(Path(python_archive).resolve()), '-C', str(staging),
                        'python/install', 'python/licenses', 'python/PYTHON.json'], check=True)
        runtime = output / RUNTIME
        runtime.parent.mkdir(parents=True)
        shutil.move(staging / 'python/install', runtime)
        shutil.move(staging / 'python/licenses', output / 'licenses')
        shutil.copyfile(staging / 'python/PYTHON.json', output / 'licenses/PYTHON.json')
        # Neither package managers, dev static libraries nor stdlib tests are
        # needed by the application. All runtime extension modules are retained.
        for directory in list(runtime.rglob('__pycache__')):
            shutil.rmtree(directory)
        for name in ('lib/python3.12/site-packages', 'lib/python3.12/test',
                     'lib/python3.12/idlelib/idle_test', 'lib/python3.12/config-3.12-darwin',
                     'lib/python3.12/ensurepip', 'include'):
            if (runtime / name).exists():
                shutil.rmtree(runtime / name)
        (runtime / 'lib/python3.12/site-packages').mkdir()
        for path in (runtime / 'bin').iterdir():
            if path.name not in ('python3', 'python3.12'):
                path.unlink()
        for path in runtime.rglob('*'):
            if path.is_symlink() and not path.exists():
                path.unlink()
        native = staging / 'native'
        native.mkdir()
        for name in ADAPTER_FILES:
            shutil.copyfile(ROOT / 'native' / name, native / name)
        shutil.copyfile(core, native / 'mgba_libretro.dylib')
        (staging / 'vendor').mkdir()
        shutil.copyfile(source, staging / 'vendor/mgba-7a12d6d-source.tar.gz')
        subprocess.run([sys.executable, '-B', str(native / 'build.py'), '--adapter-only'], check=True)
        (output / 'native').mkdir()
        for name in ('libpokemon.dylib', 'mgba_libretro.dylib'):
            shutil.copyfile(native / name, output / 'native' / name)
        shutil.copyfile(ROOT / 'licenses/mgba-MPL-2.0.txt', output / 'licenses/mgba-MPL-2.0.txt')
        # mGBA includes third-party sources; preserve their notices too.
        archive = Path(source).resolve()
        subprocess.run(['tar', '-xf', str(archive), '-C', str(staging),
                        f'mgba-{MGBA_COMMIT}/LICENSE', f'mgba-{MGBA_COMMIT}/src/third-party'], check=True)
        notices = output / 'licenses/mgba-third-party'
        notices.mkdir()
        extracted = staging / f'mgba-{MGBA_COMMIT}/src/third-party'
        for path in extracted.rglob('*'):
            if path.is_file() and any(k in path.name.lower() for k in ('license', 'copying', 'copyright', 'notice')):
                destination = notices / path.relative_to(extracted)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    files = {}
    for path in sorted(output.rglob('*')):
        if path.is_dir() and not path.is_symlink():
            continue
        files[path.relative_to(output).as_posix()] = (dict(link=str(path.readlink())) if path.is_symlink()
                                                    else dict(sha256=digest(path)))
    manifest = dict(schema=1, platform='macos-arm64', python_url=PYTHON_URL,
        python_archive_sha256=PYTHON_SHA256, mgba_commit=MGBA_COMMIT,
        core_sha256=CORE_SHA256, mgba_source_sha256=digest(source),
        adapter_sources={name:digest(ROOT / 'native' / name) for name in ADAPTER_FILES}, files=files)
    (output / 'dependencies.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--core', required=True, type=Path)
    parser.add_argument('--mgba-source', required=True, type=Path)
    parser.add_argument('--python-archive', required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.output, args.core, args.mgba_source, args.python_archive))


if __name__ == '__main__':
    main()
