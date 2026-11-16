from pathlib import Path
from copy import deepcopy
from contextlib import ExitStack
from unittest.mock import patch
import tempfile,shutil,json,re,time,sys,traceback
import argparse
parser=argparse.ArgumentParser(description='Read-only GUI localization audit using a disposable copy of Data.')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();P=Path(__file__).resolve().parents[1];W=args.output.parent;W.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(P/'src'))
from pokemon_red import localized_tk as tk
from pokemon_red import i18n
from pokemon_red import ui,table
from pokemon_red.gui import Monitor
from pokemon_red.entity_names import entities
records={};screen='startup';language='en';errors=[];search_checks=[]
original=i18n.render

def tracked(value,**kw):
 result=original(value,**kw)
 if screen!='language-switch' and str(value).strip() and not isinstance(value,i18n.Verbatim):
  records[(language,screen,str(value),str(result))]=dict(locale=language,screen=screen,source=str(value),text=str(result),message_key=getattr(value,'key',None))
 return result

def drive(duration=.08):
 end=time.monotonic()+duration
 while time.monotonic()<end:
  root.update();time.sleep(.004)

def check(name,action):
 global screen
 screen=name
 try:action();drive()
 except Exception as e:errors.append(dict(locale=language,screen=name,error=repr(e),traceback=traceback.format_exc()))

with tempfile.TemporaryDirectory(prefix='Pokemon localization screens ') as temp,ExitStack() as stack:
 folder=Path(temp);(folder/'Data').mkdir()
 for name in ('src','vendor','assets','native','runtime','Bots','ROMs','templates'):(folder/name).symlink_to(P/name,target_is_directory=True)
 (folder/'Data/FireRed.gba').symlink_to(P/'Data/FireRed.gba')
 for name in ('FireRed.state','FireRed.sav','game.json'):
  if (P/'Data'/name).exists():shutil.copy2(P/'Data'/name,folder/'Data'/name)
 (folder/'Data/settings.json').write_text(json.dumps(dict(language='en',panel_on_start=False,sound_enabled=False,autosave_enabled=False,scale=2)))
 for module in (tk,ui,table):stack.enter_context(patch.object(module,'render',tracked))
 root=tk.Tk();m=Monitor(root,folder,paused=True);root.report_callback_exception=lambda k,e,t:errors.append(dict(locale=language,screen=screen,error=repr(e)))
 try:
  deadline=time.monotonic()+10
  while not m.ready and time.monotonic()<deadline:drive(.03)
  assert m.ready
  m.show_panel();p=m.panel;drive(.3)
  for language in ('en','ru','en'):
   check('language-switch',lambda:m.set_language(language))
   for section in ('overview','collection','inventory','location','settings','hotkeys','slots','journal','scripts'):
    check(section,lambda section=section:p.show(section))
   hub=p.collection_view
   for section in ('party','owned','dex','acquisition'):
    check('pokemon-'+section,lambda section=section:(p.show('collection'),hub.select(section),hub.refresh(force=True)))
   def search_species():
    p.show('collection');hub.select('dex');out=[]
    for query in ('Бульбазавр','Bulbasaur'):
     hub.query.set(query);drive(.02);out.append(tuple(hub.dex.view.get_children()))
    assert out[0]==out[1] and out[0],out;search_checks.append(dict(locale=language,kind='species',matches=list(out[0])))
    hub.query.set('')
   check('search-species',search_species)
   for mode in ('bag','pc','library','delivery'):
    check('inventory-'+mode,lambda mode=mode:(p.show('inventory'),p.inventory_view.source.set(mode),p.inventory_view.select()))
   def search_items():
    view=p.inventory_view;view.source.set('library');view.select();out=[]
    for query in ('Суперзелье','Super Potion'):
     view.query.set(query);view.fill();out.append(tuple(sorted(r['id'] for r in view.mapping.values())))
    assert out[0]==out[1] and out[0],out;search_checks.append(dict(locale=language,kind='items',matches=list(out[0])))
    view.query.set('');view.selected_id=14;view.open_details()
   check('search-items-and-article',search_items)
   if p.inventory_view.detail_window:p.inventory_view.detail_window.destroy()
   check('pokemon-card',lambda:p.open_pokemon(mon=m.last_state['party'][0]))
   page=p.details.screens[-1].page
   for tab in page.pages:
    check('pokemon-card-'+tab,lambda tab=tab:page.tabs.select(page.pages[tab]))
   def search_moves():
    page.tabs.select(page.pages['moves']);out=[]
    for query in ('Толчок','Tackle'):
     page.learnset.query.set(query);page.learnset.fill();out.append(tuple(page.learnset.mapping.values()))
    assert out[0]==out[1] and out[0],out;search_checks.append(dict(locale=language,kind='moves',matches=[str(x) for x in out[0]]));page.learnset.query.set('')
   check('search-moves',search_moves)
   check('region-map',lambda:p.details.open_location_map('Route14'))
   check('status-dialog',lambda:__import__('pokemon_red.statuses',fromlist=['show_status']).show_status(p.window,dict(m.last_state['party'][0],status_code=8),folder))
   if hasattr(root,'_status_popup'):root._status_popup.withdraw()
   check('move-article',lambda:p.open_move(33));check('ability-article',lambda:__import__('pokemon_red.pokemon_ui',fromlist=['show_ability']).show_ability(p,65))
   for window in getattr(p,'detail_windows',{}).values():window.withdraw()
   p.details.clear()
   check('experience',lambda:__import__('pokemon_red.reference_ui',fromlist=['show_xp_calculator']).show_xp_calculator(p,1))
   for win in list(root.winfo_children()):
    if isinstance(win,tk.Toplevel) and win not in (p.window,getattr(m.battle_panel,'window',None)):win.withdraw()
   check('training',lambda:p.open_training())
   for tool in p.automation_windows.tools.values():tool['window'].withdraw()
   def travel():
    p.show('location');p.location_view.open_travel();v=p.location_view.travel
    deadline=time.monotonic()+45
    while v.result is None and time.monotonic()<deadline:drive(.05)
    if v.result is None:
     debug=dict(activity=v.activity.cget('text'),service_future=repr(v.service.future),process=repr(v.service.process),callbacks=[(f.done(),f.cancelled()) for f,_,_ in m.callbacks],runtime_alive=m.runtime.thread.is_alive(),closed=m.closed,status=m.status)
     (W/('travel-debug-'+language+'.json')).write_text(json.dumps(debug,default=str,ensure_ascii=False,indent=2));v.close();raise AssertionError('No travel result: '+str(debug)[:400])
    out=[]
    for query in ('Маршрут 14','Route 14'):
     v.search.set(query);v.fill();out.append(tuple(v.tree.get_children()))
    assert out[0]==out[1] and 'Route14' in out[0],out;search_checks.append(dict(locale=language,kind='locations',matches=list(out[0])));v.close()
   check('travel-and-search',travel)
   def capture():
    from pokemon_red.catch_view import open_autocatch
    v=open_autocatch(p,132,route='Route14',method='land_mons');drive(.15);v.close()
   check('capture',capture)
   check('encounters',lambda:m.show_battle_panel())
   from pokemon_red.mechanics import wild_mon
   ally=dict(m.last_state['party'][0]);enemy=dict(wild_mon(74,24,folder),uid='audit-foe',slot=1,checksum_valid=True,nickname='GEODUDE')
   battle=dict(flags=0,outcome=0,trainer_id=0,telemetry_valid=True,enemy_party=[enemy],allies=[dict(ally,party_slot=1)],enemies=[dict(enemy,party_slot=1,identity_valid=True)])
   check('battle',lambda:m.battle_panel.update(dict(m.last_state,in_battle=True,battle=battle)))
   if m.battle_panel:m.battle_panel.window.withdraw()
 finally:
  m.close();deadline=time.monotonic()+8
  while not m.closed and time.monotonic()<deadline:
   try:drive(.02)
   except tk.TclError:break

  from pokemon_red.startup import StartupHome
  from pokemon_red.game_selection import NewGameDialog
  from pokemon_red.profile_trade_ui import ProfileTradeDialog
  for language in ('en','ru'):
   root=tk.Tk();root.report_callback_exception=lambda k,e,t:errors.append(dict(locale=language,screen=screen,error=repr(e)))
   settings=__import__('pokemon_red.settings',fromlist=['Settings']).Settings(folder);settings.set('language',language)
   screen='playthroughs';home=StartupHome(root,folder,lambda *args:None)
   deadline=time.monotonic()+5
   while home.future is not None and time.monotonic()<deadline:drive(.03)
   check('application-settings',home.preferences)
   for child in root.winfo_children():
    if isinstance(child,tk.Toplevel):child.destroy()
   dialog=None
   def new_game():
    global dialog
    dialog=NewGameDialog(home)
    for game in ('firered','leafgreen','ruby','sapphire'):
     dialog.game.set(game);dialog.refresh();drive(.01)
   check('new-playthrough',new_game)
   if dialog:dialog.close()
   trade=None
   def exchange():
    global trade
    trade=ProfileTradeDialog(home)
   check('profile-exchange',exchange)
   if trade:trade.close()
   if home.rows:
    check('playthrough-history',lambda:home.open_history(home.rows[0]))
    if home.history:home.close_history()
   home.close();root.destroy()

english_leaks=[v for v in records.values() if v['locale']=='en' and re.search('[А-Яа-яЁё]',v['text']) and not v['text'].removesuffix('  ⌄')=='Русский']
allowed=set('PokéDesk III English Select Python Boy Advance USA Europe Rev HP PP XP IV EV ATK DEF SP SPD SPEED NPC PC GBA ROM SDK TM HM KO OHKO Lv X Y WASD F1 F5 F8 F9 Esc Escape Space Shift Enter Tab Backspace Ctrl Alt Command Control Option Meta Super Caps Lock App Nap AI FireRed LeafGreen Ruby Sapphire Emerald Pokémon Pokemon Pokédex Pokedex Kanto Sevii BOX ALEX MIMIEN Python RNG link Ditto'.casefold().split())
ru_warnings=[]
for v in records.values():
 if v['locale']!='ru' or v.get('message_key') in ('inventory.english_name','world.trainer_label','scripts.sdk_hint') or re.fullmatch(r'[^\n]+\.py(?:  ⌄)?',v['text']):continue
 words=[w.rstrip('.') for w in re.findall(r'[A-Za-zÀ-ž][A-Za-zÀ-ž.-]*',v['text']) if len(w)>2 and w.rstrip('.-').casefold() not in allowed and not re.fullmatch(r'BOX\d+',w)]
 if words:ru_warnings.append(dict(v,words=words))
report=dict(screens=sorted(set(v['screen'] for v in records.values())),records=len(records),errors=errors,english_leaks=english_leaks,russian_english_candidates=ru_warnings,search=search_checks,missing=i18n.missing_translations())
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Screens',len(report['screens']),'records',len(records),'errors',len(errors),'English leaks',len(english_leaks),'RU candidates',len(ru_warnings),'searchchecks',len(search_checks),flush=True)
for e in errors:print('ERROR',e['screen'],e['error'],e.get('traceback','')[-600:],flush=True)
for v in english_leaks[:40]:print('EN LEAK',v['screen'],repr(v['source'])[:200],'=>',repr(v['text'])[:200],flush=True)
for v in ru_warnings[:40]:print('RU CANDIDATE',v['screen'],v['words'],repr(v['text'])[:220],flush=True)

raise SystemExit(bool(errors or english_leaks or ru_warnings or len(search_checks)!=12 or report['missing']))
