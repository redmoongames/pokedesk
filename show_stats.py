"""Simple read-only example: inspect the saved session without advancing the game."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from pokemon_red import Game, read_state

with Game() as game:
    state = read_state(game)
    print("Игрок:", state["player"])
    print("Карта:", state["map"])
    print("Координаты:", state["position"])
    print("Деньги:", state["money"])
    for pokemon in state["party"]:
        print(f"{pokemon['nickname']} ({pokemon['species']}): HP {pokemon['hp']}/{pokemon['max_hp']}")
