"""Compatibility accessors: all version constants belong to GameAdapter."""
from .game_adapters import adapter

def hoenn(game):return adapter(game.root).menus=='rs'
def save_block(game,number,symbol_table=None):
    from .telemetry import symbols
    s=symbol_table if symbol_table is not None else symbols(game.root);name='gSaveBlock'+str(number)
    return game.read32(s[name+'Ptr']) if adapter(game.root).memory.save_blocks_are_pointers else s[name]
def flags_offset(game):return adapter(game.root).memory.flags
def battle_struct(game,symbol_table):
    direct=adapter(game.root).memory.battle_struct
    return direct if direct is not None else game.read32(symbol_table['gBattleStruct'])
def vars_offset(game):return adapter(game.root).memory.variables
def flag(game,number):return bool(game.read8(save_block(game,1)+flags_offset(game)+number//8)&(1<<(number%8)))
def storage(game):
    from .telemetry import symbols
    s=symbols(game.root)
    return s['gPokemonStorage'] if hoenn(game) else game.read32(s['gPokemonStoragePtr'])
def main_flags(game,symbol_table=None):
    from .telemetry import symbols
    s=symbol_table if symbol_table is not None else symbols(game.root)
    return game.read8(s['gMain']+adapter(game.root).memory.main_flags)
