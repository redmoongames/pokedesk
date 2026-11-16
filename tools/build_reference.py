"""Build/check local reference packs explicitly, without opening a save/journal."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from pokemon_red.editions import EDITIONS
    from pokemon_red.reference_pack import build_reference
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--games', nargs='+', choices=EDITIONS, default=list(EDITIONS))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for game in args.games:
        path = build_reference(args.project, game, check=args.check)
        print(game + ': ' + ('verified' if args.check else 'built') + ' ' + path.name)


if __name__ == '__main__':main()
