"""Portable FireRed session and live memory reader."""

from .installation_versions import activate_loaded_installation
activate_loaded_installation()

from .engine import Game
from .telemetry import read_state

__all__ = ["Game", "read_state"]
