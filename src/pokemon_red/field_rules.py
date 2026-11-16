"""Story badges and overworld objects belong to an engine/region adapter."""
from .game_adapters import for_id

def rules(game_id='firered'):
    rs=for_id(game_id).menus=='rs'
    return dict(cut_graphics=82 if rs else 95,cut_badge=1 if rs else 2,
        badges=dict(cut=1,surf=5,strength=4,fly=6,flash=2,rock_smash=3,dive=7,waterfall=8) if rs else dict(cut=2,surf=5,strength=4,fly=3,flash=1))

def tree(obj,grid):return obj.get('graphics_id')==grid.get('cut_graphics',95)
