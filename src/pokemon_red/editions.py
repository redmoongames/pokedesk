"""Immutable per-playthrough edition and verified, locally supplied ROM assets."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib,json
from .persistence import atomic_bytes
from .paths import installation_root, resource

@dataclass(frozen=True)
class Edition:
    id:str
    name:str
    sha1:str
    code:bytes
    symbols:str
    revision:int=1
    family:str='kanto'

    @property
    def automation(self):
        from .game_adapters import for_id
        return for_id(self.id).supports('training')
    @property
    def label(self):return f'{self.name} USA/Europe Rev {self.revision}'

FIRERED=Edition('firered','FireRed','dd5945db9b930750cb39d00c84da8571feebf417',b'BPRE','pokefirered_rev1.sym')
LEAFGREEN=Edition('leafgreen','LeafGreen','7862c67bdecbe21d1d69ce082ce34327e1c6ed5e',b'BPGE','pokeleafgreen_rev1.sym')
RUBY=Edition('ruby','Ruby','5b64eacf892920518db4ec664e62a086dd5f5bc8',b'AXVE','pokeruby_rev1.sym',2,'hoenn')
SAPPHIRE=Edition('sapphire','Sapphire','89b45fb172e6b55d51fc0e61989775187f6fe63c',b'AXPE','pokesapphire_rev1.sym',2,'hoenn')
EDITIONS={e.id:e for e in (FIRERED,LEAFGREEN,RUBY,SAPPHIRE)}
HOENN_NOTICE='Доступность автоматизации определяется адаптером игры и прогрессом прохождения.'

def edition_id(value):
    if value not in EDITIONS:raise ValueError('Выберите FireRed, LeafGreen, Ruby или Sapphire')
    return value

@lru_cache(maxsize=128)
def edition(root):
    path=Path(root)/'Data/game.json'
    if not path.exists():return FIRERED
    try:data=json.loads(path.read_text());return EDITIONS[edition_id(data['game'])]
    except (ValueError,KeyError,TypeError) as error:raise ValueError('Повреждена настройка игры прохождения') from error

def rom_sha1(root):return edition(root).sha1

def reference_path(root,name):
    return reference_for(installation_root(root),edition(root),name)

def reference_for(root,game,name):
    root=installation_root(root)
    if game.family=='hoenn':return root/'vendor/reference/editions'/('hoenn' if name=='map_groups.json' else game.id)/name
    return root/'vendor/reference/editions'/game.id/name if game is LEAFGREEN and name in ('grind_routes.json','location_reference.json','hunt_atlas.json','dex_availability.json') else root/'vendor/reference'/name

def catalog_path(root):
    root=Path(root)
    return resource(root,'vendor/catalog')/(edition(root).id+'.json')

def rom_path(library,game):
    game=EDITIONS[edition_id(game)];library=Path(library)
    return library/'Data/FireRed.gba' if game is FIRERED else library/'ROMs'/f'{game.name}-Rev{game.revision}.gba'

def validate_rom(raw,game):
    game=EDITIONS[edition_id(game)]
    if len(raw)!=16*1024*1024 or raw[0xac:0xb0]!=game.code or raw[0xbc]!=game.revision or hashlib.sha1(raw).hexdigest()!=game.sha1:
        raise ValueError(f'Нужен {game.label} (GBA, английская версия 1.{game.revision}); файл не подходит')
    return game

def available(library,game):
    path=rom_path(library,game)
    if not path.is_file():return False
    # Imported ROMs are hash-checked when installed and again at engine startup.
    return not EDITIONS[game].automation or game=='firered' or resource(library,f'vendor/catalog/{game}.json').is_file()

def install_rom(library,path,game):
    """Only a local file; never changes ROM/save files of existing profiles."""
    library=Path(library);raw=Path(path).read_bytes();spec=validate_rom(raw,game)
    target=rom_path(library,game)
    if game=='firered':
        if not target.exists():raise ValueError('Базовый ROM FireRed отсутствует')
        if target.read_bytes()!=raw:raise ValueError('Замена ROM основной игры не поддерживается')
        return target
    # Ordinary ROM import changes user data only. Reference preparation belongs
    # to the explicit maintenance/build command, including on read-only apps.
    from .reference_pack import load_reference
    load_reference(library,game=game)
    atomic_bytes(target,raw,durable=True)
    return target
