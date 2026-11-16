"""Durable file publication. This module never holds or calls an emulator core."""
from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import os
from pathlib import Path
import platform
import uuid


def sync_file(file, *, durable=False):
    file.flush()
    os.fsync(file.fileno())
    if durable and platform.system() == "Darwin":
        try:
            fcntl.fcntl(file.fileno(), getattr(fcntl, "F_FULLFSYNC", 51))
        except OSError as error:
            if error.errno not in (errno.EINVAL, errno.ENOTSUP, errno.ENOTTY):
                raise


def sync_directory(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(descriptor)


def atomic_bytes(path: Path, data: bytes, *, durable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as file:
            file.write(data)
            sync_file(file, durable=durable)
        temporary.replace(path)
        if durable:
            sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SaveSnapshot:
    """Detached bytes captured at one frame by the core's owner thread.

    The state embeds SRAM. FireRed.state is the authoritative commit; startup
    never combines its state with the separate cartridge export FireRed.sav.
    """
    state: bytes
    sram: bytes
    frame: int
    captured_at: float
    summary: bytes = b''
    preview: bytes = b''
    producer: str = ''
    active_seconds: float | None = None

    def verify(self, directory: Path) -> None:
        """Confirm the exact captured pair on the writer, before acknowledging it."""
        from .save_timeline import verify_snapshot
        verify_snapshot(self,directory)

    def publish(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        staged = []
        try:
            # Stage and flush both before replacing either. Publish state last.
            for filename, data in (("FireRed.sav", self.sram), ("FireRed.state", self.state)):
                target = directory / filename
                temporary = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
                staged.append((temporary, target))
                with temporary.open("wb") as file:
                    file.write(data)
                    sync_file(file, durable=True)
            for temporary, target in staged:
                temporary.replace(target)
                sync_directory(directory)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
        return directory / "FireRed.state"


def publish_checkpoint(snapshot: SaveSnapshot, data: Path, rom_sha1: str, *, backup=False, on_warning=None):
    """Publish a complete commit and retain its compressed rollback history."""
    from .save_timeline import publish
    return publish(snapshot,data,rom_sha1,backup=backup,on_warning=on_warning)
