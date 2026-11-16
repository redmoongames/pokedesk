"""Direct ctypes access to mGBA. No window capture or synthetic OS input."""
from __future__ import annotations

from .paths import session_paths, resource

import ctypes
import hashlib
import zlib
import os
from pathlib import Path
import platform
import time
import threading
import uuid

from .persistence import SaveSnapshot, atomic_bytes, sync_file, sync_directory, publish_checkpoint

ROOT = Path(__file__).resolve().parents[2]
ROM_SHA1 = "dd5945db9b930750cb39d00c84da8571feebf417"
BUTTONS = {name: 1 << bit for bit, name in enumerate(
    ("A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L")
)}


class Game:
    """One independent FireRed emulator instance; only explicit save() writes Data.

    Examples:
        with Game() as game:
            print(game.read32(0x03005008))
            game.press("RIGHT", frames=20)
            game.save()
    """

    def __init__(self, root: Path = ROOT, *, resume: bool = True):
        self.paths = session_paths(Path(root).resolve())
        self.root = self.paths.profile.root
        self.data = self.paths.profile.data
        self.handle = None
        self.owner_thread = threading.get_ident()
        self.save_producer=uuid.uuid4().hex
        self.active_seconds=0.0
        self._active_at=None
        self.revision = 0
        self.state_generation = 0
        self.loaded_from: Path | None = None
        self.recovered_from: Path | None = None
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("Вложенная сборка предназначена для macOS на Apple Silicon (чип M).")
        from .editions import edition,validate_rom
        self.edition=edition(self.root);self.rom_sha1=self.edition.sha1
        rom = self.data / "FireRed.gba"
        if not rom.is_file():
            raise FileNotFoundError(f"Файл игры не найден: {rom}")
        rom_bytes=rom.read_bytes();validate_rom(rom_bytes,self.edition.id);self.rom_crc32=zlib.crc32(rom_bytes)
        self.lib = ctypes.CDLL(str(resource(self.root, "native/libpokemon.dylib")))
        pointer, uint = ctypes.c_void_p, ctypes.c_uint
        self._bind("open", [ctypes.c_char_p], pointer)
        self._bind("close", [pointer], None)
        self._bind("step", [pointer, uint, uint], None)
        for width in (8, 16, 32):
            self._bind(f"read{width}", [pointer, uint], uint)
        self._bind("read_block", [pointer, uint, pointer, uint], ctypes.c_int)
        for name in ("capture_state", "capture_save"):
            self._bind(name, [pointer, ctypes.POINTER(pointer)], ctypes.c_size_t)
        self._bind("free_buffer", [pointer], None)
        for name in ("load_state", "save_state", "load_save", "save_save"):
            self._bind(name, [pointer, ctypes.c_char_p], ctypes.c_int)
        if hasattr(self.lib, 'pokemon_restore_state'):
            self._bind('restore_state', [pointer, pointer, ctypes.c_size_t], ctypes.c_int)
        self._bind("rgb", [pointer], pointer)
        self._bind("frame", [pointer], uint)
        self._bind("audio_rate", [pointer], uint)
        self._bind("audio_read", [pointer, pointer, uint], uint)
        self._bind("audio_clear", [pointer], None)
        if hasattr(self.lib,'pokemon_current_keycode'):
            self._bind('current_keycode',[ctypes.c_int],ctypes.c_int)
        if hasattr(self.lib,'pokemon_current_scroll'):
            self._bind('current_scroll',[ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_int)],ctypes.c_int)
        self.handle = self.lib.pokemon_open(os.fsencode(rom))
        if not self.handle:
            raise RuntimeError("mGBA не смогла открыть ROM.")
        try:
            checkpoint = self.data / "FireRed.state"
            save = self.data / "FireRed.sav"
            candidates = self.recovery_checkpoints() if resume else []
            if resume and (checkpoint.is_file() or candidates):
                attempts = ([checkpoint] if checkpoint.is_file() else []) + candidates
                for candidate in attempts:
                    try:
                        self.load_state(candidate)
                        if candidate != checkpoint:
                            self.recovered_from = candidate
                        break
                    except (RuntimeError, OSError):
                        # A rejected state may have partially changed the core.
                        self.close()
                        self.handle = self.lib.pokemon_open(os.fsencode(rom))
                        if not self.handle:
                            raise RuntimeError("Не удалось перезапустить ядро при восстановлении.")
                else:
                    raise RuntimeError("Не удалось загрузить состояние и его резервные копии. Файлы сохранены без изменений.")
            elif resume and save.is_file():
                if not self.lib.pokemon_load_save(self.handle, os.fsencode(save)):
                    raise RuntimeError("Не удалось загрузить сохранение FireRed.sav.")
                self.loaded_from = save
        except BaseException:
            self.close()
            raise

    def _bind(self, name, args, result):
        function = getattr(self.lib, "pokemon_" + name)
        function.argtypes, function.restype = args, result

    def _check(self):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError("Ядро доступно только потоку владельца игровой сессии")
        if not self.handle:
            raise RuntimeError("Сессия уже закрыта.")

    def current_keycode(self,pressed=True):
        fn=getattr(self.lib,'pokemon_current_keycode',None)
        return fn(int(pressed)) if fn else -1

    def current_scroll_delta(self):
        fn=getattr(self.lib,'pokemon_current_scroll',None)
        if not fn:return None
        x,y,precise=ctypes.c_double(),ctypes.c_double(),ctypes.c_int()
        return (x.value,y.value,bool(precise.value)) if fn(ctypes.byref(x),ctypes.byref(y),ctypes.byref(precise)) else None

    def read8(self, address: int) -> int:
        self._check()
        return self.lib.pokemon_read8(self.handle, address)

    def read16(self, address: int) -> int:
        self._check()
        return self.lib.pokemon_read16(self.handle, address)

    def read32(self, address: int) -> int:
        self._check()
        return self.lib.pokemon_read32(self.handle, address)

    def read_bytes(self, address: int, count: int) -> bytes:
        self._check()
        if type(count) is not int or not 0 <= count <= 1_048_576:
            raise ValueError("Недопустимый размер чтения.")
        if type(address) is not int or not 0 <= address <= 0xFFFFFFFF or address + count > 0x1_0000_0000:
            raise ValueError("Недопустимый адрес чтения.")
        if not count:
            return b""
        buffer = (ctypes.c_ubyte * count)()
        if not self.lib.pokemon_read_block(self.handle, address, buffer, count):
            raise RuntimeError("Не удалось прочитать диапазон памяти.")
        return bytes(buffer)

    def advance(self, frames: int = 1, keys: int = 0) -> None:
        self._check()
        if not 0 <= frames <= 1_000_000:
            raise ValueError("frames должно быть от 0 до 1 000 000.")
        before=time.monotonic()
        self.lib.pokemon_step(self.handle, keys & 0x3FF, frames)
        if frames:
            after=time.monotonic()
            gap=before-self._active_at if self._active_at is not None else 0
            self.active_seconds+=max(0,gap if gap<=.25 else 0)+max(0,after-before)
            self._active_at=after
            self.revision += 1

    def press(self, button: str, frames: int = 2, *, release_frames: int = 1) -> None:
        names = button.upper().split("+")
        try:
            mask = sum(BUTTONS[name] for name in set(names))
        except KeyError as error:
            raise ValueError(f"Неизвестная кнопка: {error.args[0]}") from error
        self.advance(frames, mask)
        self.advance(release_frames, 0)

    @property
    def frame(self) -> int:
        self._check()
        return self.lib.pokemon_frame(self.handle)

    def rgb(self) -> bytes:
        self._check()
        return ctypes.string_at(self.lib.pokemon_rgb(self.handle), 240 * 160 * 3)

    @property
    def audio_rate(self) -> int:
        self._check()
        return self.lib.pokemon_audio_rate(self.handle)

    def read_audio(self, max_frames: int = 65536) -> bytes:
        """Drain interleaved signed 16-bit stereo PCM, at audio_rate Hz."""
        self._check()
        if not 1 <= max_frames <= 65536:
            raise ValueError("Invalid audio buffer size")
        if not hasattr(self,'_audio_buffer') or len(self._audio_buffer)<max_frames*2:
            self._audio_buffer=(ctypes.c_int16*(max_frames*2))()
        buffer=self._audio_buffer
        count = self.lib.pokemon_audio_read(self.handle, buffer, max_frames)
        return ctypes.string_at(buffer, count * 4)

    def clear_audio(self):
        self._check()
        self.lib.pokemon_audio_clear(self.handle)

    def validate_checkpoint(self,data):
        # Pinned mGBA serialized GBA header: CRC32 @8, game code @0x1c.
        if len(data)>=32 and int.from_bytes(data[:4],'little')&0xffffff00==0x01000000:
            if data[0x1c:0x20]!=self.edition.code or int.from_bytes(data[8:12],'little')!=self.rom_crc32:
                raise RuntimeError('Сохранение создано для другой игры или ROM; оно не загружено')

    def load_state(self, path: Path) -> None:
        self._check()
        path = Path(path).resolve()
        if path.name=='state.z':
            from .save_timeline import SaveTimeline
            self.restore_checkpoint(SaveTimeline.restore_bytes(path.parent,self.rom_sha1))
            self.loaded_from=path
            return
        self.validate_checkpoint(path.read_bytes())
        if not self.lib.pokemon_load_state(self.handle, os.fsencode(path)):
            raise RuntimeError(f"Не удалось загрузить состояние: {path.name}")
        self.loaded_from = path
        self.revision += 1
        self.state_generation += 1

    def recovery_checkpoints(self) -> list[Path]:
        candidates = list((self.data / "backups/autosaves").glob("*/FireRed.state"))
        candidates += list((self.data / 'rewind').glob('*/state.z'))
        candidates += list((self.data / "backups/sessions").glob("*.state"))
        stamped = []
        for path in candidates:
            try:
                stamped.append((path.stat().st_mtime_ns, path))
            except OSError:
                # A read-only snapshot can race the active session's rotation.
                continue
        return [path for _, path in sorted(stamped, reverse=True)]

    def restore_checkpoint(self, data: bytes) -> None:
        """Restore detached mGBA checkpoint bytes on their core's owner thread."""
        self._check()
        if not isinstance(data, bytes) or not 0 < len(data) <= 16 * 1024 * 1024:
            raise ValueError('Некорректный checkpoint')
        self.validate_checkpoint(data)
        restore = getattr(self.lib, 'pokemon_restore_state', None)
        if restore is None:
            raise RuntimeError('Для отдельной сессии требуется обновлённый native adapter')
        buffer = ctypes.create_string_buffer(data)
        if not restore(self.handle, buffer, len(data)):
            raise RuntimeError('mGBA отклонила checkpoint')
        self.loaded_from = None
        self.revision += 1
        self.state_generation += 1

    def capture_save(self, *, metadata: bool = True) -> SaveSnapshot:
        """Copy a consistent state into detached bytes; no disk I/O or fsync.

        Must run on the same owner thread as advance/read. Only the returned
        immutable snapshot may be handed to a file writer.
        """
        self._check()
        blobs = []
        for name in ("capture_state", "capture_save"):
            pointer = ctypes.c_void_p()
            try:
                size = getattr(self.lib, "pokemon_" + name)(self.handle, ctypes.byref(pointer))
                if not pointer.value or not 0 < size <= 16 * 1024 * 1024:
                    raise OSError("Не удалось захватить состояние игры в памяти")
                blobs.append(ctypes.string_at(pointer, size))
            finally:
                if pointer.value:
                    self.lib.pokemon_free_buffer(pointer)
        summary,preview=b'',b''
        if metadata:
            from .save_metadata import capture
            summary,preview=capture(self)
        return SaveSnapshot(blobs[0], blobs[1], self.frame, time.time(),summary,preview,self.save_producer,self.active_seconds)

    def save(self, *, backup: bool = False) -> Path:
        """Synchronous SDK/CLI facade. The GUI submits detached bytes to its writer."""
        return publish_checkpoint(self.capture_save(), self.data, self.rom_sha1, backup=backup)

    def save_to(self, directory: Path) -> Path:
        return self.capture_save(metadata=False).publish(directory)

    def close(self):
        if self.handle:
            self._check()
            self.lib.pokemon_close(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
