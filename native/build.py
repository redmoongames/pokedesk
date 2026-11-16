"""Optional adapter/app rebuild, offline. Requires Apple's command line tools.

The complete corresponding mGBA source archive is in vendor/.
The library is pinned to the original official arm64 core binary so the imported
0.11 save state stays compatible. This adapter calls mCore directly, not retro_*.
"""
from pathlib import Path
import subprocess
import tarfile
import tempfile
import argparse

parser=argparse.ArgumentParser();parser.add_argument('--adapter-only',action='store_true');args=parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="pokemon-build-") as temporary:
    directory = Path(temporary)
    with tarfile.open(ROOT / "vendor/mgba-7a12d6d-source.tar.gz") as archive:
        archive.extractall(directory, filter="data")
    source = next(directory.iterdir())
    # Cooperative callers yield between ARM loops rather than core threads.
    # Disconnect may leave an already-due resync event; queue it next cycle.
    lockstep = source / 'src/gba/sio/lockstep.c'
    serial_source = lockstep.read_text()
    assert serial_source.count('mASSERT_DEBUG(nextEvent > 0);') == 1
    lockstep.write_text(serial_source.replace('mASSERT_DEBUG(nextEvent > 0);', 'if (nextEvent <= 0) nextEvent = 1;'))
    # The SIO coordinator uses wrapping signed 32-bit cycle differences.
    # Compare event times by their modular distance at the 2^31 boundary.
    serial_source=lockstep.read_text()
    comparison='if (event->timestamp > GBASIOLockstepTime(player))'
    assert serial_source.count(comparison)==1
    lockstep.write_text(serial_source.replace(comparison,'if ((int32_t)((uint32_t)event->timestamp - (uint32_t)GBASIOLockstepTime(player)) > 0)'))
    definitions = ("COLOR_16_BIT", "COLOR_5_6_5", "ENABLE_VFS", "ENABLE_DIRECTORIES", "MINIMAL_CORE=2", "M_CORE_GBA", "M_CORE_GB",
                   "DISABLE_THREADING", "MGBA_STANDALONE", "_DARWIN_C_SOURCE", "TARGET_POSIX_IO")
    subprocess.run(["clang", "-dynamiclib", "-O2", "-fwrapv", "-arch", "arm64", "-mmacosx-version-min=11.0",
                    *["-D" + definition for definition in definitions],
                    "-I" + str(source / "include"), str(ROOT / "native/bridge.c"), str(source / "src/gba/sio/lockstep.c"),
                    "-fobjc-arc", str(ROOT / "native/playback.m"),
                    "-framework", "AudioToolbox", "-framework", "Foundation", "-framework", "AppKit",
                    str(ROOT / "native/mgba_libretro.dylib"), "-Wl,-rpath,@loader_path",
                    "-Wl,-install_name,@rpath/libpokemon.dylib",
                    "-o", str(directory / "libpokemon.dylib")], check=True)
    subprocess.run(['codesign','--force','--sign','-',str(directory/'libpokemon.dylib')],check=True)
    target=ROOT/'native/libpokemon.dylib'
    import shutil
    staging=target.with_suffix('.new.dylib');shutil.copy2(directory/'libpokemon.dylib',staging);staging.replace(target)

if args.adapter_only:
    print('Built native/libpokemon.dylib atomically');raise SystemExit(0)

runtime = ROOT / "runtime/python/cpython-3.12.16-macos-aarch64-none"
python_lib = runtime / "lib/libpython3.12.dylib"
# uv rewrites the library's install ID to an absolute installation path.
# Restore a relative ID before linking the portable app entry point.
subprocess.run(["install_name_tool", "-id", "@rpath/libpython3.12.dylib", str(python_lib)], check=True)
subprocess.run(["codesign", "--force", "--sign", "-", str(python_lib)], check=True)
executable = ROOT / "Pokemon.app/Contents/MacOS/Pokemon"
executable.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["clang", "-O2", "-arch", "arm64", "-mmacosx-version-min=11.0",
                "-I" + str(runtime / "include/python3.12"), str(ROOT / "native/launcher.c"),
                "-L" + str(runtime / "lib"), "-lpython3.12",
                "-Wl,-rpath,@executable_path/../../../runtime/python/cpython-3.12.16-macos-aarch64-none/lib",
                "-o", str(executable)], check=True)
subprocess.run(["codesign", "--force", "--sign", "-", str(ROOT / "Pokemon.app")], check=True)
print("Built native/libpokemon.dylib and Pokemon.app")
