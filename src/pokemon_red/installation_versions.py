"""Content-addressed installation snapshots and per-run version contracts.

Snapshot preparation/verification is startup or background work, never frame
work. Files are independent copies (APFS clones when possible), not hardlinks.
Only installation trees enter a release; profiles, ROMs and journals never do.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import ctypes
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

TREES = ('src', 'native', 'vendor', 'assets', 'runtime', 'Bots')
MANIFEST = 'installation-version.json'
RUN_MANIFEST = 'execution.json'
SCHEMA = 1
_lock = threading.RLock()
_prepared = {}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='installation-prepare')
_capacity = threading.BoundedSemaphore(8)


def submit_preparation(function, *, notify=lambda:None):
    if not _capacity.acquire(blocking=False):raise RuntimeError('Installation preparation queue is full')
    try:future = _pool.submit(function)
    except BaseException:_capacity.release();raise
    def done(_):
        _capacity.release();notify()
    future.add_done_callback(done)
    return future


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _hash(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class InstallationVersion:
    root: Path
    id: str

    @property
    def python(self):
        path = self.root/'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'
        return path if path.exists() else Path(sys.executable)

    def worker(self, name):return self.root/'src/pokemon_red'/name

    def environment(self):
        environment=os.environ.copy();environment['POKEDESK_RELEASE_ID']=self.id
        environment.setdefault('POKEDESK_INSTALLATION_ORIGIN',str(Path(__file__).resolve().parents[2]))
        return environment


def inventory(source):
    """Follow top-level legacy aliases, preserve only safe internal links."""
    source = Path(source).resolve();records = [];sources = {}
    for name in (*TREES, 'main.py'):
        base = source/name
        if not base.exists():continue
        if base.is_dir():
            resolved = base.resolve()
            paths = sorted(p for p in base.rglob('*') if '__pycache__' not in p.parts)
        else:resolved = source;paths = [base]
        for path in paths:
            if path.is_dir() and not path.is_symlink():continue
            relative = path.relative_to(source).as_posix()
            if path.is_symlink():
                target = path.readlink()
                if target.is_absolute() or not path.resolve().is_relative_to(resolved):
                    raise ValueError('Installation link escapes its resource tree: '+relative)
                record = dict(path=relative, link=str(target))
            elif path.is_file():
                record = dict(path=relative, sha256=_hash(path), size=path.stat().st_size,
                              executable=bool(path.stat().st_mode & 0o111))
            else:raise ValueError('Unsupported installation file: '+relative)
            records.append(record);sources[relative] = path
    return records, sources


def read_version(root):
    root = Path(root).resolve();data = json.loads((root/MANIFEST).read_text())
    if data.get('schema') != SCHEMA or data.get('id') != digest(dict(schema=SCHEMA, files=data.get('files'))):
        raise ValueError('Invalid installation manifest')
    if root.name != data['id']:raise ValueError('Installation directory does not match its version')
    return InstallationVersion(root, data['id'])


@lru_cache(maxsize=1)
def loaded_version():
    root = Path(__file__).resolve().parents[2]
    if not (root/MANIFEST).is_file():return None
    return read_version(root)


def loaded_id():
    version = loaded_version()
    return version.id if version else None


def activate_loaded_installation():
    version = loaded_version()
    if version is not None:
        expected = os.environ.get('POKEDESK_RELEASE_ID')
        if expected is not None and expected != version.id:
            raise ValueError('Process installation differs from its launch version')
        from .paths import set_process_installation
        origin = Path(os.environ.get('POKEDESK_INSTALLATION_ORIGIN', str(version.root)))
        set_process_installation(version.root, version.id, origin)
    return version


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = False
    if sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        clone = libc.clonefile;clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clone.restype = ctypes.c_int
        cloned = clone(os.fsencode(source), os.fsencode(destination), 0) == 0
    if not cloned:shutil.copy2(source, destination)


def prepare_installation(source, store=None):
    """Build atomically; recheck source and the copied payload before publish."""
    from .persistence import atomic_bytes, sync_directory
    source = Path(source).resolve()
    if (source/MANIFEST).is_file():return read_version(source)
    store = Path(store or source/'Sessions/installations').resolve();store.mkdir(parents=True, exist_ok=True)
    with _lock:
        records, sources = inventory(source);identifier = digest(dict(schema=SCHEMA, files=records))
        destination = store/identifier
        if destination.exists():
            version = read_version(destination);verify_installation(version)
            return version
        staging = Path(tempfile.mkdtemp(prefix='.preparing-', dir=store))
        try:
            for record in records:
                target = staging/record['path'];target.parent.mkdir(parents=True, exist_ok=True)
                if 'link' in record:target.symlink_to(record['link'])
                else:
                    _copy(sources[record['path']], target)
                    target.chmod(0o555 if record['executable'] else 0o444)
            copied, _ = inventory(staging)
            if copied != records or inventory(source)[0] != records:
                raise ValueError('Installation changed during snapshot preparation')
            atomic_bytes(staging/MANIFEST, json.dumps(dict(schema=SCHEMA, id=identifier, files=records), sort_keys=True).encode(), durable=True)
            (staging/MANIFEST).chmod(0o444)
            for folder in sorted((p for p in staging.rglob('*') if p.is_dir() and not p.is_symlink()), key=lambda p:len(p.parts), reverse=True):
                sync_directory(folder);folder.chmod(0o555)
            sync_directory(staging);staging.chmod(0o555)
            # Another process may have prepared the identical version.
            try:staging.rename(destination)
            except OSError:
                if not destination.is_dir():raise
                verify_installation(read_version(destination))
            sync_directory(store)
            return read_version(destination)
        finally:
            if staging.exists():
                for folder in (staging, *staging.rglob('*')):
                    if folder.is_dir() and not folder.is_symlink():folder.chmod(0o755)
                shutil.rmtree(staging)


def verify_installation(version):
    record = json.loads((version.root/MANIFEST).read_text())
    if read_version(version.root).id != version.id or inventory(version.root)[0] != record['files']:
        raise ValueError('Installation payload does not match its version')
    return version


def version_for_job(root):
    version = loaded_version()
    if version is not None:return version
    # Embedding/debug callers have no process bootstrap. Freeze the actual
    # application's installation, not an arbitrary profile's src alias.
    source = Path(__file__).resolve().parents[2]
    with _lock:
        version = _prepared.get(source)
        if version is None or not version.root.exists():
            from .paths import session_paths
            store = source/'Sessions/installations' if os.access(source, os.W_OK) else session_paths(root).library/'Sessions/installations'
            version = prepare_installation(source, store);_prepared[source] = version
        return version


def pin_job(job, parent, kind):
    from .paths import bind_installation, session_paths
    from .persistence import atomic_bytes
    job = Path(job).resolve();version = version_for_job(parent)
    bind_installation(job, version.root, library=session_paths(parent).library)
    identity = dict(release_id=version.id, run_id=uuid.uuid4().hex)
    from .editions import rom_sha1
    atomic_bytes(job/RUN_MANIFEST, json.dumps(dict(schema=SCHEMA, kind=kind, execution=identity,rom_sha1=rom_sha1(parent)), sort_keys=True).encode(), durable=True)
    (job/RUN_MANIFEST).chmod(0o444);job_identity.cache_clear()
    return identity


def bound_version(job):
    """Management can launch an older job in its own isolated process.

    This does not activate that version in the caller's emulator/GUI process.
    """
    from .paths import LAYOUT_FILE
    job=Path(job).resolve();record=json.loads((job/LAYOUT_FILE).read_text())
    link=Path(record['installation'])
    if link.is_absolute():raise ValueError('Installation link must be relative')
    version=read_version(job/link)
    if job_identity(job)['release_id'] != version.id:raise ValueError('Job installation does not match its execution')
    return version


@lru_cache(maxsize=1024)
def job_identity(folder):
    folder = Path(folder).resolve()
    for current in (folder, *folder.parents):
        path = current/RUN_MANIFEST
        if path.is_file():
            record = json.loads(path.read_text())
            if record.get('schema') != SCHEMA:raise ValueError('Invalid execution manifest')
            identity = record.get('execution')
            if not isinstance(identity,dict) or set(identity) != {'release_id','run_id'}:raise ValueError('Invalid execution identity')
            return identity
    return None


def validate_worker(folder):
    expected = job_identity(Path(folder))
    if expected is not None and loaded_id() != expected['release_id']:
        raise ValueError('Worker installation differs from its job')
    return expected


def stamp_result(path, value):
    if Path(path).name not in ('result.json','progress.json','prologue-checkpoint.json'):return value
    expected = job_identity(Path(path).parent)
    if expected is None or not isinstance(value,dict):return value
    # Unbootstrapped embedding hosts can reconstruct a checked checkpoint. A
    # versioned worker always reports the version of its actual imported code.
    return dict(value, _execution=dict(expected, release_id=loaded_id() or expected['release_id']))


def require_result(expected, value):
    if expected is not None and value.get('_execution') != expected:
        from .i18n import t
        raise ValueError(t('execution.result_mismatch'))


def require_response(value):
    if value.get('_installation') != loaded_id():
        raise ValueError('Response installation differs from its caller')


def versioned_response(value):
    return dict(value,_installation=loaded_id())


def wrap_response(value):
    return dict(result=value,_installation=loaded_id()) if loaded_id() is not None else value


def unwrap_response(value):
    if loaded_id() is None:return value
    if not isinstance(value,dict):raise ValueError('Missing response installation')
    require_response(value);return value['result']


@dataclass(frozen=True)
class PreparedBot:
    job: Path
    script: Path
    version: InstallationVersion
    execution: dict


def prepare_bot(root, script):
    from .paths import session_paths
    from .persistence import atomic_bytes
    script = Path(script).resolve();job = session_paths(root).workspaces.root/'bot-runs'/uuid.uuid4().hex
    execution = pin_job(job, root, 'bot');version = version_for_job(root)
    source_root = Path(__file__).resolve().parents[2]
    if script.is_relative_to(source_root/'Bots'):
        script = version.root/script.relative_to(source_root)
    target = job/'script';target.mkdir()
    # Freeze local Python helpers as well as the selected entry point. Mutable
    # gameplay configuration stays in bot.project_dir/Data.
    files = list(script.parent.glob('*.py'))
    for package in script.parent.iterdir():
        if package.is_dir() and not package.is_symlink() and (package/'__init__.py').is_file():files.extend(package.rglob('*.py'))
    if len(files)>2000:raise ValueError('Too many local bot modules')
    if sum(source.stat().st_size for source in files)>32*1024*1024:
        raise ValueError('Local bot modules exceed the snapshot budget')
    before = {source:_hash(source) for source in files}
    hashes = {}
    for source in files:
        if source.is_symlink() or source.stat().st_size>2*1024*1024:raise ValueError('Unsupported local bot module')
        relative = source.relative_to(script.parent);payload = source.read_bytes();destination = target/relative
        atomic_bytes(destination,payload,durable=True);destination.chmod(0o444)
        hashes[str(relative)] = hashlib.sha256(payload).hexdigest()
        if hashes[str(relative)] != before[source]:raise ValueError('Bot source changed during preparation')
    if any(_hash(source) != before[source] for source in files):raise ValueError('Bot source changed during preparation')
    if script.name not in hashes:raise ValueError('Bot entry point was not captured')
    atomic_bytes(job/'script-version.json',json.dumps(hashes,sort_keys=True).encode(),durable=True)
    (job/'script-version.json').chmod(0o444)
    for directory in sorted((p for p in target.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):directory.chmod(0o555)
    target.chmod(0o555)
    return PreparedBot(job, target/script.name, version, execution)


def validate_bot(job):
    job = Path(job);validate_worker(job)
    for name, expected in json.loads((job/'script-version.json').read_text()).items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or _hash(job/'script'/path) != expected:
            raise ValueError('Bot script differs from its run manifest')


def bootstrap_process(profile, arguments):
    """Exec before UI/core creation so even lazy owner imports are pinned."""
    if loaded_version() is not None:return
    from .paths import session_paths
    paths = session_paths(profile);source = paths.installation.root
    # Legacy standalone profiles may expose only native/vendor aliases. Their
    # launcher still belongs to the actual application, not to that data folder.
    if not (source/'main.py').is_file() or not (source/'src/pokemon_red/installation_versions.py').is_file():
        source = Path(__file__).resolve().parents[2]
    version = prepare_installation(source, paths.library/'Sessions/installations')
    environment = os.environ.copy()
    environment['POKEDESK_INSTALLATION_ORIGIN'] = str(source)
    environment['POKEDESK_RELEASE_ID'] = version.id
    for key in ('PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY'):environment.pop(key,None)
    command = [str(version.python),'-I','-B',str(version.root/'main.py'),*arguments,'--root',str(Path(profile).resolve())]
    os.execve(version.python, command, environment)
