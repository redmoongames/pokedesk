"""Exercise a built app on disposable copies of the user's ROM/save.

Never used as a bundle input. The worker imports code and native libraries from
the generated immutable installation, using that installation's own Python.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.002)
    raise AssertionError('Timed out waiting for a release contract')


def worker(profile, version):
    sys.path.insert(0, str(version / 'src'))
    from pokemon_red.engine_runtime import EngineRuntime
    from pokemon_red.engine import Game
    from pokemon_red.paths import session_paths
    from pokemon_red.save_metadata import png
    from pokemon_red.engine import BUTTONS
    from collections import deque
    class ProbeRuntime(EngineRuntime):
        """Read-only probes/recording in the test subclass, never production RPC."""
        def _dispatch(self, controller, method, args):
            if method == 'install_probe':
                self.frames = deque(maxlen=256)
                advance = controller.game.advance
                def recorded(frames=1, keys=0):
                    if frames:
                        self.frames.append((self.applied_epoch, keys))
                    return advance(frames, keys)
                controller.game.advance = recorded
                return
            if method == 'probe':
                return dict(keys=sorted(controller.keys), frame=controller.game.frame,
                            owner=controller.game.owner_thread, frames=list(self.frames))
            return super()._dispatch(controller, method, args)
    runtime = ProbeRuntime(profile, paused=True)
    runtime.ready.result(15)
    runtime.submit('install_probe').result(5)
    scripts = profile.parent / 'probe-scripts'
    scripts.mkdir()
    observer = scripts / 'observe_long.py'
    observer.write_text('def run(bot):\n    for _ in range(1000):\n        bot.wait_frames(60)\n')
    result = dict(installation=session_paths(profile).installation.release_id, takeover_ms=[])
    try:
        wait_for(lambda: runtime.latest is not None)
        assert runtime.latest.status['owner_thread_id'] == runtime.thread.ident != threading.get_ident()
        initial_frame = runtime.latest.frame
        runtime.set_preferences(dict(autosave_enabled=True, autosave_seconds=5, sound_enabled=False))
        runtime.submit('set_speed', 16).result(5)
        runtime.submit('start_bot', observer).result(5)
        wait_for(lambda: runtime.latest.status['automation']['running'])
        before_save = (profile / 'Data/FireRed.state').stat().st_mtime_ns
        wait_for(lambda: (profile / 'Data/FireRed.state').stat().st_mtime_ns > before_save, 9)
        assert runtime.latest.status['automation']['running']
        result['autosave_during_bot'] = True
        for index in range(6):
            started = time.perf_counter()
            epoch = runtime.take_control(pause=True)
            wait_for(lambda: runtime.latest.epoch >= epoch and runtime.latest.status['paused'])
            result['takeover_ms'].append(round((time.perf_counter() - started)*1000, 3))
            assert not runtime.latest.status['automation']['running']
            # A manual command after revocation is accepted; old bot commands
            # must not regain control when simulation resumes.
            runtime.submit('set_speed', 1).result(5)
            runtime.submit('manual', 'START', True).result(5)
            def pressed_in_core():
                probe = runtime.submit('probe').result(5)
                assert probe['owner'] == runtime.thread.ident
                return 'START' in probe['keys'] and any(e >= epoch and mask & BUTTONS['START'] for e, mask in probe['frames'])
            wait_for(pressed_in_core)
            runtime.submit('manual', 'START', False).result(5)
            wait_for(lambda: 'START' not in runtime.submit('probe').result(5)['keys'])
            runtime.submit('pause', False).result(5)
            if index != 5:
                runtime.submit('set_speed', 16).result(5)
                runtime.submit('start_bot', observer).result(5)
                wait_for(lambda: runtime.latest.status['automation']['running'])
                time.sleep(.06)
        snapshot = runtime.latest
        final_frame = runtime.submit('probe').result(5)['frame']
        result.update(frames_advanced=snapshot.frame - initial_frame,
                      manual_input_after_takeover=True, owner_thread_separate=True)
        video = snapshot.video
        if video and video.startswith(b'P6\n240 160\n255\n'):
            (profile.parent / 'game-frame.png').write_bytes(png(video.split(b'\n', 3)[3]))
    finally:
        runtime.take_control(close=True)
        runtime.finished.result(15)
        runtime.thread.join(2)
        assert not runtime.thread.is_alive()
    with Game(profile) as game:
        assert game.frame == final_frame
        assert game.loaded_from == profile / 'Data/FireRed.state'
        result['cold_restore'] = True
    result['max_takeover_ms'] = max(result['takeover_ms'])
    assert result['max_takeover_ms'] < 250, result
    return result


def check(app, rom, state, save, work):
    if work.exists():
        raise ValueError('Work directory must be new; live profiles are never reused')
    work.mkdir(parents=True)
    bundle = app / 'Contents/Resources/installation'
    python = bundle / 'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'
    # Relaunch the preparation driver through the bundled runtime, not whatever
    # Python happened to start this developer command.
    driver = work / 'prepare.py'
    driver.write_text('''from pathlib import Path
import json,sys,time
bundle,profile,rom=map(Path,sys.argv[1:])
sys.path.insert(0,str(bundle/'src'))
from pokemon_red.desktop_install import prepare_desktop
start=time.monotonic()
version=prepare_desktop(bundle,profile,rom)
print(json.dumps(dict(root=str(version.root),seconds=time.monotonic()-start)))
''')
    inputs = [p for p in (rom, state, save) if p is not None]
    before = {p: sha(p) for p in inputs}
    profile = work / 'Library'
    (profile / 'Data').mkdir(parents=True)
    for original, name in ((state, 'FireRed.state'), (save, 'FireRed.sav')):
        if original is not None:
            shutil.copyfile(original, profile / 'Data' / name)
    protected = {p.name: sha(p) for p in (profile / 'Data').iterdir()}
    prepared = json.loads(subprocess.check_output([str(python), '-I', '-B', str(driver),
                          str(bundle), str(profile), str(rom)], text=True))
    for name, digest in protected.items():
        assert sha(profile / 'Data' / name) == digest, 'Setup rewrote a save'
    version = Path(prepared['root'])
    pinned_python = version / 'runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3'
    payload = subprocess.check_output([str(pinned_python), '-I', '-B', str(Path(__file__).resolve()),
                                     '--worker', str(profile), '--version-root', str(version)], text=True)
    result = json.loads(payload)
    assert all(sha(path) == digest for path, digest in before.items()), 'A source ROM/save changed'
    result.update(preparation_seconds=round(prepared['seconds'], 3), source_files_unchanged=True,
                  setup_preserved_save_bytes=True, bundled_python=True)
    (work / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--rom', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--save', type=Path)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--version-root', type=Path)
    args = parser.parse_args()
    if args.worker and args.version_root:
        result = worker(args.worker, args.version_root)
    elif args.app and args.rom and args.state and args.work:
        result = check(args.app.resolve(), args.rom.resolve(), args.state.resolve(),
                       args.save.resolve() if args.save else None, args.work.resolve())
    else:
        parser.error('--app, --rom, --state and --work are required')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
