"""Isolated process entry point. User scripts implement def run(bot)."""
from pathlib import Path
import runpy
import os
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemon_red.bot import connect, ControlLost, HandedOff


def main():
    from pokemon_red.installation_versions import validate_bot
    if os.environ.get('POKEMON_RUN_MANIFEST'):
        validate_bot(Path(os.environ['POKEMON_RUN_MANIFEST']).parent)
    script = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(script.parent))
    parent = int(os.environ.get("POKEMON_BOT_PARENT_PID", "0"))
    if parent:
        def watch_parent():
            while True:
                time.sleep(.5)
                if os.getppid() != parent:
                    os._exit(1)
        threading.Thread(target=watch_parent, daemon=True).start()
    bot = None
    success = False
    failure = None
    try:
        bot = connect()
        namespace = runpy.run_path(str(script), run_name="__pokemon_bot__")
        run = namespace.get("run")
        if not callable(run):
            raise TypeError("В скрипте должна быть функция def run(bot).")
        run(bot)
        success = True
    except HandedOff:
        success=True
    except ControlLost as error:
        print(str(error), flush=True)
    except BaseException as error:
        failure=dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        if bot:
            try:
                bot.finish(success=success,error=failure)
            except (ControlLost, RuntimeError):
                pass
            bot.close()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
