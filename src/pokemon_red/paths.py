"""Portable boundaries: immutable installation, mutable profile, job workspaces.

Legacy roots need no migration. New profiles/jobs record a relative installation
link; moving the whole portable tree preserves it. Resolution never creates files.
Game.root remains the profile (or private job) root for SDK compatibility.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import json
import os

LAYOUT_FILE = '.pokedesk-paths.json'
_process_installation = None


@dataclass(frozen=True)
class InstallationPaths:
    root: Path
    release_id: str | None = None
    origin: Path | None = None

    def resource(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Installation resource must be relative')
        return self.root / relative

    @property
    def python(self):
        return self.root / 'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'


@dataclass(frozen=True)
class ProfilePaths:
    root: Path

    @property
    def data(self):return self.root / 'Data'

    @property
    def journal(self):return self.data / 'history.sqlite3'


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path


@dataclass(frozen=True)
class SessionPaths:
    installation: InstallationPaths
    profile: ProfilePaths
    workspaces: WorkspacePaths
    library: Path
    kind: str = 'profile'


@lru_cache(maxsize=512)
def _resolve(root):
    marker = root / LAYOUT_FILE
    try:
        record = json.loads(marker.read_text(encoding='utf-8'));present = True
    except FileNotFoundError:
        present = False
    if not present:
        installation = root;library = root;kind = 'legacy'
        # Compatibility uses the documented directory layout, not a source
        # symlink (which may point at unrelated development code).
        for ancestor in (root, *root.parents):
            if ancestor.name == 'Sessions' and (ancestor.parent/'Data').is_dir():
                parent = _resolve(ancestor.parent)
                installation = parent.installation.root;library = parent.library;break
            if (ancestor.parent.name == 'Profiles' and len(ancestor.name) == 32
                    and all(c in '0123456789abcdef' for c in ancestor.name)
                    and (ancestor.parent.parent/'Data').is_dir()):
                parent = _resolve(ancestor.parent.parent)
                installation = parent.installation.root;library = parent.library;break
        if (root/'installation-version.json').is_file():
            installation = root;kind = 'installation'
    else:
        if not isinstance(record, dict) or record.get('schema') != 1 or record.get('kind') not in ('profile', 'workspace'):
            raise ValueError('Invalid portable path layout')
        link = record.get('installation')
        if not isinstance(link, str) or not link or Path(link).is_absolute():
            raise ValueError('Installation link must be relative')
        installation = (root / link).resolve();kind = record['kind']
        if not installation.is_dir():raise ValueError('Portable installation is missing')
        library_link = record.get('library', '.')
        if not isinstance(library_link,str) or not library_link or Path(library_link).is_absolute():
            raise ValueError('Library link must be relative')
        library = (root / library_link).resolve()
    explicit = record.get('release_id') if present and kind == 'workspace' else None
    if kind == 'installation':
        from .installation_versions import read_version
        explicit = read_version(root).id
    selected = InstallationPaths(installation, explicit)
    if _process_installation is not None:
        if explicit is not None and explicit != _process_installation.release_id:
            raise ValueError('Workspace belongs to another installation version')
        selected = _process_installation
    return SessionPaths(selected, ProfilePaths(root), WorkspacePaths(root / 'Sessions'), library, kind)


def session_paths(root):
    if isinstance(root, SessionPaths):return root
    return _resolve(Path(root).absolute())


def installation_root(root):return session_paths(root).installation.root


def resource(root, relative):return session_paths(root).installation.resource(relative)


def set_process_installation(root, release_id, origin):
    global _process_installation
    _process_installation = InstallationPaths(Path(root).resolve(), release_id, Path(origin).resolve())
    _resolve.cache_clear()


def bind_installation(root, installation, *, kind='workspace', library=None):
    """Explicit durable setup, never called by resource readers or frame work."""
    from .persistence import atomic_bytes
    root = Path(root).resolve();source = session_paths(installation)
    selected = source.installation
    installation = (selected.origin if kind == 'profile' and selected.origin else selected.root).resolve()
    if kind not in ('profile', 'workspace'):raise ValueError('Invalid portable root kind')
    library = Path(library).resolve() if library is not None else source.library
    record = dict(schema=1, kind=kind, installation=os.path.relpath(installation, root),
                  library=os.path.relpath(library, root))
    if kind == 'workspace' and selected.release_id is not None:record['release_id'] = selected.release_id
    elif kind == 'workspace' and (installation/'installation-version.json').is_file():
        from .installation_versions import read_version
        record['release_id'] = read_version(installation).id
    root.mkdir(parents=True, exist_ok=True)
    atomic_bytes(root / LAYOUT_FILE, json.dumps(record, sort_keys=True).encode(), durable=True)
    _resolve.cache_clear()
    return session_paths(root)
