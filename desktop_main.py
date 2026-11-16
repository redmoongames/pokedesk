"""Finder application entry point. All dependencies live beside this file."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
PINNED = os.environ.get('POKEDESK_PINNED_ROOT')
sys.path.insert(0, str((Path(PINNED) if PINNED else ROOT) / 'src'))

if __name__ == '__main__':
    if PINNED:
        from pokemon_red.installation_versions import read_version, verify_installation
        try:
            verify_installation(read_version(Path(PINNED)))
            from pokemon_red.editions import validate_rom
            validate_rom((Path(os.environ['POKEDESK_LIBRARY']) / 'Data/FireRed.gba').read_bytes(), 'firered')
        except (OSError, ValueError):
            os.environ['POKEDESK_REPAIR'] = '1'
            launcher = os.environ['POKEDESK_LAUNCHER']
            os.execve(launcher, [launcher], os.environ.copy())
        from pokemon_red.cli import main
        entry = str(Path(PINNED) / 'main.py')
        # multiprocessing.spawn must re-import the frozen entry point rather
        # than a .app bootstrap that could be replaced by a later update.
        sys.modules['__main__'].__file__ = entry
        sys.argv = [entry, '--root', os.environ['POKEDESK_LIBRARY']]
        main()
    else:
        from pokemon_red.desktop import main
        main(ROOT)
