from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import time

from .engine import Game, ROOT
from .telemetry import read_state
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(description="FireRed: игра и телеметрия напрямую из libmgba")
    parser.add_argument("--snapshot", action="store_true", help="Один снимок координат/денег/HP в JSON, без изменения сессии")
    parser.add_argument("--watch", action="store_true", help="Сессия без окна; печатать JSON раз в секунду")
    parser.add_argument("--seconds", type=float, default=0, help="Ограничение длительности --watch (0 — до Ctrl+C)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--paused", action="store_true", help="Открыть окно на паузе")
    args = parser.parse_args()
    from .paths import session_paths
    if not args.snapshot or session_paths(args.root).installation.release_id is not None:
        import sys
        from .installation_versions import bootstrap_process
        bootstrap_process(args.root, sys.argv[1:])
    if args.snapshot:
        with Game(args.root) as game:
            print(json.dumps(read_state(game), ensure_ascii=False, indent=2))
        return
    if args.watch:
        import fcntl
        with (args.root / "Data/.session.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error("Сессия уже открыта. Сначала закрой окно проекта.")
            with Game(args.root) as game:
                settings = Settings(args.root)
                started = time.monotonic()
                last_save = started
                def interrupted(*_):
                    raise KeyboardInterrupt
                signal.signal(signal.SIGTERM, interrupted)
                signal.signal(signal.SIGHUP, interrupted)
                try:
                    while not args.seconds or time.monotonic() - started < args.seconds:
                        tick = time.monotonic()
                        print(json.dumps(read_state(game), ensure_ascii=False), flush=True)
                        for _ in range(60):
                            game.advance()
                            time.sleep(max(0, tick + (_ + 1) / 59.7275 - time.monotonic()))
                            if settings["autosave_enabled"] and time.monotonic() - last_save >= settings["autosave_seconds"]:
                                game.save()
                                last_save = time.monotonic()
                except KeyboardInterrupt:
                    pass
                finally:
                    game.save(backup=True)
        return
    from .startup import run
    run(args.root, paused=args.paused)
