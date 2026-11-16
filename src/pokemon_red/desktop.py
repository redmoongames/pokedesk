"""Small first-run UI; preparation stays off Tk and never opens a live save."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import queue
import sys
import threading

from . import localized_tk as tk
from .localized_tk import filedialog, messagebox
from .desktop_install import (default_library, installed_version, prepare_desktop,
                              launch_command, SetupCancelled, LibraryBusyError)
from .desktop_install import InvalidRomError
from .i18n import set_locale, t, LOCALE_NAMES
from .ui import BG, TEXT, MUTED, AMBER, GREEN, Button, Segments, label, theme


def activate_startup():
    """Activate once after Tk creates TKApplication, never on focus loss.

    Creating NSApplication in the C launcher would prevent Tk from installing
    its subclass. This UI-only call is intentionally after Tk initialization.
    """
    import ctypes
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    app = send(objc.objc_getClass(b'NSApplication'), objc.sel_registerName(b'sharedApplication'))
    policy = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(('objc_msgSend', objc))
    policy(app, objc.sel_registerName(b'setActivationPolicy:'), 0)
    activate = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(('objc_msgSend', objc))
    activate(app, objc.sel_registerName(b'activateIgnoringOtherApps:'), True)


class SetupWindow:
    def __init__(self, root, bundle, library, done):
        self.root, self.bundle, self.library, self.done = root, bundle, library, done
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='desktop-setup')
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.future = None
        self.closed = False
        self.closing = False
        from .settings import Settings
        self.settings = Settings(library)
        set_locale(self.settings['language'])
        root.title('PokéDesk')
        root.configure(bg=BG)
        root.geometry('610x460')
        root.minsize(550, 430)
        theme(root)
        body = tk.Frame(root, bg=BG, padx=28, pady=24)
        body.pack(fill='both', expand=True)
        language = tk.StringVar(value=self.settings['language'])
        def change_language(code):
            self.settings.set('language', code)
            set_locale(code)
        Segments(body, list(LOCALE_NAMES.items()), language, change_language).pack(fill='x', pady=(0, 20))
        label(body, t('setup.title'), 23, bold=True)
        label(body, t('setup.intro'), 12, MUTED, wraplength=550).pack_configure(pady=(10, 14))
        label(body, t('setup.rom_format'), 12, TEXT, wraplength=550)
        self.status = label(body, '', 12, GREEN, wraplength=550)
        self.status.pack_configure(pady=(18, 8))
        self.choose = Button(body, t('setup.choose'), self.select_rom, variant='primary', height=42)
        self.choose.pack(fill='x', pady=(8, 8))
        label(body, t('setup.local'), 10, MUTED, wraplength=550)
        Button(body, t('setup.open_data'), self.open_library, variant='ghost').pack(anchor='w', pady=(10, 0))
        self.exit_button = Button(body, t('setup.exit'), self.close, variant='ghost')
        self.exit_button.pack(anchor='e', side='bottom')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.createcommand('::tk::mac::Quit', self.close)
        menu = tk.Menu(root, tearoff=False)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=t('setup.choose'), accelerator='⌘O', command=self.select_rom)
        file_menu.add_separator()
        file_menu.add_command(label=t('setup.exit'), command=self.close)
        menu.add_cascade(label=t('setup.file'), menu=file_menu)
        root.configure(menu=menu)
        root.bind('<Command-o>', lambda _: self.select_rom() if self.future is None else None)
        root.after_idle(self.choose.focus_set)
        candidate = library / 'Data/FireRed.gba'
        if candidate.is_file():
            self.begin(candidate)
        self.timer = root.after(80, self.poll)

    def open_library(self):
        import subprocess
        self.library.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(['/usr/bin/open', str(self.library)])

    def select_rom(self):
        path = filedialog.askopenfilename(parent=self.root, title=str(t('setup.choose')),
                                         filetypes=[('Game Boy Advance ROM', '*.gba')])
        if path:
            self.begin(Path(path))

    def begin(self, path):
        if self.future is not None:
            return
        self.cancelled.clear()
        self.choose.configure(state='disabled')
        self.status.configure(text=t('setup.checking'), fg=GREEN)
        self.future = self.pool.submit(prepare_desktop, self.bundle, self.library, path,
                                      progress=self.events.put, cancelled=self.cancelled)

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                stage = self.events.get_nowait()
            except queue.Empty:
                break
            self.status.configure(text=t(stage), fg=GREEN)
        if self.future is not None and self.future.done():
            future, self.future = self.future, None
            try:
                version = future.result()
            except SetupCancelled:
                self.finish_close()
                return
            except Exception as error:
                if self.closing:
                    self.finish_close()
                    return
                key = str(error)
                if isinstance(error, LibraryBusyError) or key in ('setup.rom_conflict',):
                    text = t(key)
                elif isinstance(error, InvalidRomError):
                    text = t('setup.bad_rom')
                else:
                    text = t('setup.failed', error=str(error))
                self.status.configure(text=text, fg=AMBER)
                self.choose.configure(state='normal')
            else:
                self.pool.shutdown(wait=False)
                self.root.destroy()
                if not self.closing:
                    self.done(version)
                return
        self.timer = self.root.after(80, self.poll)

    def close(self):
        if self.future is not None:
            self.closing = True
            self.cancelled.set()
            self.choose.configure(state='disabled')
            self.exit_button.configure(state='disabled')
            self.status.configure(text=t('setup.cancelling'), fg=MUTED)
        else:
            self.finish_close()

    def finish_close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main(bundle=None, library=None):
    bundle = Path(bundle or Path(__file__).resolve().parents[2])
    library = Path(library or os.environ.get('POKEDESK_LIBRARY', default_library())).expanduser().resolve()
    def launch(version):
        launcher = os.environ.get('POKEDESK_LAUNCHER')
        if launcher:
            environment = os.environ.copy()
            environment.pop('POKEDESK_REPAIR', None)
            os.execve(launcher, [launcher], environment)
            return
        command, environment = launch_command(version, library)
        os.execve(version.python, command, environment)
    # Hashing a ready installation happens before an engine/UI is created.
    version = installed_version(library, bundle)
    if version is not None:
        launch(version)
        return
    root = tk.Tk()
    SetupWindow(root, bundle, library, launch)
    activate_startup()
    root.mainloop()
