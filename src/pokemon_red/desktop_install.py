"""Transactional setup for the ROM-free macOS application bundle.

Bundle resources are read-only. Each library owns its ROM and profiles; generated
game content is local and frozen with code/native/runtime before any bot starts.
An interrupted update leaves the previous installation and all saves intact.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid

from .editions import FIRERED, validate_rom
from .installation_versions import prepare_installation, read_version, verify_installation
from .paths import bind_installation
from .persistence import atomic_bytes

COPY_TREES = ('src', 'native', 'runtime', 'Bots')
RECEIPT = 'desktop-installation.json'


class SetupCancelled(Exception):
    pass


class LibraryBusyError(RuntimeError):
    pass


class InvalidRomError(ValueError):
    pass


def default_library():
    return Path.home() / 'Library/Application Support/PokeDesk'


def build_record(bundle):
    data = json.loads((Path(bundle) / 'desktop-build.json').read_text())
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('build_id'), str) or len(data['build_id']) != 64:
        raise ValueError('Invalid application build manifest')
    return data


def installed_version(library, bundle, *, verify=True):
    library = Path(library)
    try:
        record = json.loads((library / RECEIPT).read_text())
        if not isinstance(record, dict):
            return None
        if record.get('build_id') != build_record(bundle)['build_id'] or record.get('rom_sha1') != FIRERED.sha1:
            return None
        identifier = record['release_id']
        if not isinstance(identifier, str) or len(identifier) != 64 or any(c not in '0123456789abcdef' for c in identifier):
            return None
        slot = record.get('slot')
        if not isinstance(slot, str) or len(slot) != 32 or any(c not in '0123456789abcdef' for c in slot):
            return None
        version = read_version(library / 'Sessions/installations' / ('desktop-' + slot) / identifier)
        if verify:
            verify_installation(version)
            validate_rom((library / 'Data/FireRed.gba').read_bytes(), 'firered')
        return version
    except (OSError, ValueError, KeyError, TypeError):
        return None


@contextmanager
def setup_lock(library):
    data = Path(library) / 'Data'
    data.mkdir(parents=True, exist_ok=True)
    with (data / '.desktop-setup.lock').open('a') as lock, (data / '.application.lock').open('a') as application:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(application, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LibraryBusyError('setup.busy') from error
        yield


def prepare_desktop(bundle, library, rom, *, progress=lambda stage: None, cancelled=None):
    """No save files are copied, loaded or rewritten by setup.

    All expensive work and verification finish before publishing the relative
    installation link. The receipt is the commit marker; failed setup is retried
    explicitly on the next launch, never mistaken for a complete installation.
    """
    bundle, library, rom = Path(bundle).resolve(), Path(library).resolve(), Path(rom)
    cancelled = cancelled or threading.Event()
    def checkpoint(stage=None):
        if cancelled.is_set():
            raise SetupCancelled()
        if stage:
            progress(stage)
    if rom.stat().st_size != 16 * 1024 * 1024:
        raise InvalidRomError('setup.bad_rom')
    payload = rom.read_bytes()
    try:
        validate_rom(payload, 'firered')
    except ValueError as error:
        raise InvalidRomError('setup.bad_rom') from error
    manifest = build_record(bundle)
    with setup_lock(library):
        target_rom = library / 'Data/FireRed.gba'
        if target_rom.exists() and target_rom.read_bytes() != payload:
            raise ValueError('setup.rom_conflict')
        checkpoint('setup.runtime')
        with tempfile.TemporaryDirectory(prefix='.setup-', dir=library) as temporary:
            staging = Path(temporary)
            for name in COPY_TREES:
                checkpoint()
                shutil.copytree(bundle / name, staging / name, symlinks=True,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
            shutil.copyfile(bundle / 'main.py', staging / 'main.py')
            (staging / 'Data').mkdir()
            # The compiler's isolated core never sees an existing save. The
            # temporary cartridge is excluded from installation snapshots.
            atomic_bytes(staging / 'Data/FireRed.gba', payload, durable=True)
            from .rom_resources import prepare_resources
            summary = prepare_resources(staging, payload, checkpoint)
            checkpoint('setup.verify')
            # A fresh namespace also repairs damaged cached versions without
            # renaming/removing code still held by another resumable job.
            slot = uuid.uuid4().hex
            version = prepare_installation(staging, library / 'Sessions/installations' / ('desktop-' + slot))
            verify_installation(version)
            checkpoint()
            # Publication has no cancellable gap: a late Cancel cannot leave a
            # half-selected installation. Existing save bytes stay untouched.
            if not target_rom.exists():
                atomic_bytes(target_rom, payload, durable=True)
            receipt = dict(schema=1, build_id=manifest['build_id'], release_id=version.id,
                           slot=slot, rom_sha1=FIRERED.sha1, resources=summary)
            marker = library / '.pokedesk-paths.json'
            previous = marker.read_bytes() if marker.exists() else None
            try:
                bind_installation(library, version.root, kind='profile', library=library)
                atomic_bytes(library / RECEIPT, json.dumps(receipt, sort_keys=True).encode(), durable=True)
            except BaseException:
                if previous is not None:
                    atomic_bytes(marker, previous, durable=True)
                elif marker.exists():
                    marker.unlink()
                from .paths import _resolve
                _resolve.cache_clear()
                raise
            return version


def launch_command(version, library):
    environment = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY'):
        environment.pop(name, None)
    environment.update(POKEDESK_RELEASE_ID=version.id, POKEDESK_INSTALLATION_ORIGIN=str(version.root))
    command = [str(version.python), '-I', '-B', str(version.root / 'main.py'), '--root', str(Path(library).resolve())]
    return command, environment
