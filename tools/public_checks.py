"""Run explicit ROM-free contracts and independently verify a fresh source export."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
from export_source import export_source, verify_export


def main():
    print('Scope: public contracts only; native/GUI/ROM integration is not run.', flush=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests/public'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun == 0:
        return 1
    with tempfile.TemporaryDirectory(prefix='pokedesk-public-') as temporary:
        folder = Path(temporary) / 'source'
        export_source(ROOT, folder)
        print('Source export:', verify_export(folder), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
