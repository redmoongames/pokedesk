"""Wake Tk from worker threads without invoking Tcl from those threads."""
import socket
import tkinter as tk


class EventPump:
    def __init__(self, window, callback, *, fallback_ms=2):
        self.window = window
        self.callback = callback
        self.closed = False
        self.reader, self.writer = socket.socketpair()
        self.reader.setblocking(False)
        self.writer.setblocking(False)
        self.fallback_ms=fallback_ms
        self.file_handler = False
        try:
            window.createfilehandler(self.reader, tk.READABLE, self._ready)
            self.file_handler = True
        except (AttributeError, NotImplementedError, tk.TclError):
            pass
        self.timer = window.after(50 if self.file_handler else self.fallback_ms, self._timer)

    def notify(self):
        if self.closed:
            return
        try:
            self.writer.send(b"\0")
        except (BlockingIOError, OSError):
            pass  # A full pipe already contains a wakeup.

    def _ready(self, *_):
        try:
            while self.reader.recv(4096):
                pass
        except (BlockingIOError, OSError):
            pass
        if not self.closed:
            try:self.callback()
            except Exception as error:
                self.window.report_callback_exception(type(error),error,error.__traceback__)

    def _timer(self):
        if self.closed:
            return
        try:
            self._ready()
        finally:
            if not self.closed:
                self.timer = self.window.after(50 if self.file_handler else self.fallback_ms, self._timer)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.window.after_cancel(self.timer)
        if self.file_handler:
            self.window.deletefilehandler(self.reader)
        self.reader.close()
        self.writer.close()
