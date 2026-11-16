from .i18n import t
from .entity_names import ability_name,move_name,pokemon_name
from .entity_names import display_entity_names as _entity_label
"""Compact persistent battle observer; all data is a detached UI snapshot."""
from . import localized_tk as tk
from .catalog import species,ability,move
from .telemetry import status_name
from .types_ui import Badges,types_for,defensive_profile,TYPE_INFO
from .mechanics import ranked_attacks
from .sprites import sprite
from .ui import BG,CARD,TEXT,MUTED,GREEN,BLUE,AMBER,RED,BORDER,Button,Meter,label,theme,short,cached_font
from .tooltips import Tooltip


def opponents(state,root):
    battle=state.get('battle') or {};result=[]
    for mon in battle.get('enemy_party',[]):
        if not mon.get('checksum_valid',True) or not species(mon.get('species_id',0),root) or not all(a.get('valid',True) for a in mon.get('moves',[])):continue
        live=next((m for m in battle.get('enemies',[]) if m.get('party_slot')==mon['slot'] and m.get('uid')==mon.get('uid') and m.get('identity_valid',True)),None)
        row=dict(mon,opponent=True,active=live is not None)
        if live:row.update({k:live[k] for k in ('species_id','species','hp','max_hp','stats','stages','types','ability_id','status_code','moves') if k in live})
        row['status']=status_name(row.get('status_code',0),row.get('hp',0));result.append(row)
    return result


def matchup_text(profile,key):
    values=profile[key]
    return ' · '.join(TYPE_INFO[typ][0]+(f' ×{factor:g}' if factor else '') for typ,factor in values) or 'Нет'

class TeamRow(tk.Canvas):
    def __init__(self,parent,root,command):
        super().__init__(parent,height=37,bg=BG,highlightthickness=0,takefocus=True,cursor='hand2',width=280)
        self.root_path=root;self.command=command;self.mon=None;self.selected=False;self.photo=None
        self.bind('<Configure>',lambda _:self.draw());self.bind('<Button-1>',lambda _:self.invoke());self.bind('<Return>',lambda _:self.invoke());self.bind('<space>',lambda _:self.invoke())
        self.bind('<FocusIn>',lambda _:self.draw());self.bind('<FocusOut>',lambda _:self.draw())
    def invoke(self):
        if self.mon:self.command(self.mon['uid'])
        return 'break'
    def set(self,mon,selected):self.mon=mon;self.selected=selected;self.draw()
    def draw(self):
        if not self.mon or not self.winfo_exists():return
        self.delete('all');m=self.mon;w=self.winfo_width();active=m.get('active');hp=m.get('hp',0);maximum=max(1,m.get('max_hp',1))
        self.create_rectangle(1,1,w-1,36,fill='#233747' if self.selected else CARD,outline=BLUE if self.selected or self.focus_get() is self else BORDER)
        if active:self.create_rectangle(2,2,5,35,fill=GREEN,outline='')
        self.photo=sprite(self,self.root_path,m['species_id'],scale=.5,shiny=m.get('shiny',False),gray=hp<=0)
        if self.photo:self.create_image(26,18,image=self.photo)
        font=cached_font(self,('Helvetica',10,'bold'));name=_entity_label(species(m['species_id'],self.root_path)['name'])
        self.create_text(47,11,text=short(name,w-155,font),anchor='w',font=font,fill=TEXT if hp else MUTED)
        self.create_text(w-9,11,text=('В БОЮ · ' if active else '')+f'Lv {m.get("level","?")}',anchor='e',font=('Helvetica',8,'bold'),fill=GREEN if active else MUTED)
        end=max(85,w-87);self.create_rectangle(47,24,end,28,fill=BORDER,outline='');self.create_rectangle(47,24,47+(end-47)*min(1,hp/maximum),28,fill=GREEN if hp/maximum>.3 else AMBER,outline='')
        self.create_text(w-9,26,text=f'{hp}/{maximum}',anchor='e',font=('Helvetica',9),fill=MUTED)

class BattlePanel:
    def __init__(self,monitor):
        self.monitor=monitor;self.root_path=monitor.folder;self.selected_uid=None;self.active_uid=None;self.token=None;self.opponents=[];self.state={};self.signature=None;self.visible=False;self.auto_future=None;self.capture_future=None;self.catch_setup=None;self.catch_host=None;self.task_battle=False
        self.window=tk.Toplevel(monitor.window);self.window.title(__import__('pokemon_red.editions',fromlist=['edition']).edition(monitor.folder).name+' · Бой');self.window.configure(bg=BG);self.window.geometry('350x800');self.window.minsize(300,600);theme(self.window)
        self.window.protocol('WM_DELETE_WINDOW',self.window.withdraw);self.window.bind('<Escape>',monitor.emergency_stop);self.window.bind('<FocusOut>',monitor.focus_out)
        self.workspace_head=tk.Frame(self.window,bg=BG,padx=12,pady=8);self.workspace_head.pack(fill='x')
        self.coordinates=label(self.workspace_head,'',10,BLUE,wraplength=300)
        self.task_controls=tk.Frame(self.workspace_head,bg=BG)
        self.task_title=label(self.task_controls,'',12,bold=True)
        self.task_stop=Button(self.task_controls,t('workspace.stop'),lambda:monitor.take_control(focus=False),height=32)
        self.task_stop.pack(fill='x',pady=(6,0))
        self.task_battle_button=Button(self.task_controls,t('workspace.stage_battle'),self.toggle_task_battle,variant='ghost',height=30)
        self.body=tk.Frame(self.window,bg=BG,padx=12,pady=10)
        self.heading=label(self.body,'',11,MUTED,bold=True)
        hero=tk.Frame(self.body,bg=BG);hero.pack(fill='x',pady=(5,0));self.portrait=tk.Label(hero,bg=BG);self.portrait.pack(side='left');info=tk.Frame(hero,bg=BG);info.pack(side='left',fill='both',expand=True,padx=(5,0))
        self.name=label(info,'',17,bold=True);self.detail=label(info,'',10,MUTED);self.types=Badges(info);self.types.pack(fill='x')
        self.hp=Meter(self.body,height=5);self.hp.pack(fill='x',pady=(1,3));self.ability=label(self.body,'',10,MUTED,wraplength=320);self.ability_hint=Tooltip(self.ability)
        self.groups={}
        box=tk.Frame(self.body,bg=CARD,padx=8,pady=5);box.pack(fill='x',pady=(7,4))
        for key,title,color in [('weak','Слабости',GREEN),('resist','Сопротивления',MUTED),('immune','Иммунитет',AMBER)]:
            self.groups[key]=label(box,'',10,color,wraplength=300);self.groups[key].pack_configure(pady=2)
        self.advice=label(self.body,'',10,BLUE,wraplength=320);self.advice.pack_configure(pady=(3,5));Tooltip(self.advice,'Оценка обычного урона без критического удара. Погода, предметы и особые эффекты могут изменить результат.')
        self.move_title=label(self.body,'',10,MUTED);self.moves=[]
        for i in range(4):
            button=Button(self.body,'',lambda i=i:self.open_move(i),height=25,anchor='w',font=('Helvetica',10),variant='ghost');button.pack(fill='x');self.moves.append(button)
        label(self.body,'Команда · нажми для просмотра',10,MUTED).pack_configure(pady=(8,4))
        self.team_frame=tk.Frame(self.body,bg=BG);self.team_frame.pack(fill='x');self.cards=[TeamRow(self.team_frame,self.root_path,self.select) for _ in range(6)]
        self.footer=tk.Frame(self.window,bg=BG,padx=12,pady=9)
        buttons=tk.Frame(self.footer,bg=BG);buttons.pack(fill='x');buttons.columnconfigure((0,1),weight=1)
        self.auto=Button(buttons,t('battle.auto'),self.toggle_auto,variant='primary',height=34,width=120);self.auto.grid(row=0,column=0,sticky='ew',padx=(0,3))
        self.capture=Button(buttons,t('capture.short'),self.toggle_capture,height=34,width=120);self.capture.grid(row=0,column=1,sticky='ew',padx=(3,0))
        self.auto_reason=label(self.footer,'',9,MUTED,wraplength=320);self.auto_reason.pack_configure(pady=(4,0))
        from .field_encounters_ui import FieldEncountersView
        self.field=FieldEncountersView(monitor,self.window)
        from .automation_context import AutomationContext
        self.context=AutomationContext(self)
        self.window.bind('<Configure>',self.resized,add='+')
    def open_catch(self,trainer,number,*,route=None,method=None,preset=None):
        key=(number,route,method)
        if self.catch_setup is not None and not self.catch_setup.closed and self.catch_key==key:
            self.window.deiconify();self.window.lift();return self.catch_setup
        self.close_catch()
        self.catch_key=key;self.catch_host=tk.Frame(self.window,bg=BG)
        Button(self.catch_host,t('capture.back'),self.close_catch,variant='ghost',height=30,anchor='w').pack(fill='x',padx=8,pady=(6,0))
        body=tk.Frame(self.catch_host,bg=BG);body.pack(fill='both',expand=True)
        from .catch_view import CatchSetup
        self.catch_setup=CatchSetup(trainer,number,route=route,method=method,preset=preset,parent=body)
        self.update(self.state);self.window.deiconify();self.window.lift()
        return self.catch_setup
    def close_catch(self):
        if self.catch_setup is not None:self.catch_setup.close();self.catch_setup=None
        if self.catch_host is not None:self.catch_host.destroy();self.catch_host=None
        self.update(self.state)
    def open_saved_encounters(self,trainer,operation_id=None,sha=None):
        self.close_catch();self.catch_key=('saved',None,None);self.catch_host=tk.Frame(self.window,bg=BG)
        Button(self.catch_host,t('capture.back'),self.close_catch,variant='ghost',height=30,anchor='w').pack(fill='x',padx=8,pady=(6,0))
        body=tk.Frame(self.catch_host,bg=BG);body.pack(fill='both',expand=True)
        from .wild_history_ui import SavedEncountersView
        self.catch_setup=SavedEncountersView(trainer,body,operation_id=operation_id,sha=sha)
        self.update(self.state);self.window.deiconify();self.window.lift();return self.catch_setup
    def resized(self,event):
        if event.widget is not self.window:return
        width=max(240,event.width-26)
        for item in [self.ability,self.advice,self.auto_reason,*self.groups.values()]:item.configure(wraplength=width-(16 if item in self.groups.values() else 0))
    def select(self,uid):
        self.selected_uid=uid;self.signature=None;self.update(self.state)
    def toggle_task_battle(self):
        self.task_battle=not self.task_battle;self.update(self.state)
    def update(self,state):
        from .workspace import task_summary
        from .locations import location_name
        summary=task_summary(self.monitor);p=state.get('position') or {};name=(state.get('map') or {}).get('name')
        self.coordinates.configure(text=t('workspace.coordinates',location=location_name(name) if name else '—',x=p.get('x','—'),y=p.get('y','—')),wraplength=max(240,self.window.winfo_width()-26))
        if summary.active or summary.attention:
            self.task_controls.pack(fill='x',pady=(7,0));self.task_title.configure(text=summary.title)
            self.task_stop.configure(state='normal' if summary.active else 'disabled')
            if summary.active and state.get('in_battle') and summary.kind not in ('battle_auto','battle_capture'):
                self.task_battle_button.pack(fill='x',pady=(4,0));self.task_battle_button.configure(text=t('workspace.back_tasks') if self.task_battle else t('workspace.stage_battle'))
            else:self.task_battle_button.pack_forget();self.task_battle=False
        else:self.task_controls.pack_forget();self.task_battle=False
        self.state=state;self.field.state=state;b=state.get('battle') or {}
        if self.catch_host is not None:self.catch_host.pack_forget()
        if self.catch_setup is not None and not self.catch_setup.closed and not summary.attention:
            self.body.pack_forget();self.footer.pack_forget();self.field.frame.pack_forget();self.context.frame.pack_forget();self.visible=False
            self.window.title(getattr(self.catch_setup,'title_text',t('capture.title')));self.catch_host.pack(fill='both',expand=True);return
        if self.context.wants() and (summary.attention or summary.kind not in ('battle_auto','battle_capture')) and not (self.task_battle and state.get('in_battle')):
            self.body.pack_forget();self.footer.pack_forget();self.field.frame.pack_forget();self.visible=False
            self.window.title(t('search.context_title'));self.context.frame.pack(fill='both',expand=True);self.context.update(state);return
        self.context.frame.pack_forget()
        if not state.get('in_battle') or not b:
            self.body.pack_forget();self.footer.pack_forget();self.opponents=[];self.selected_uid=None;self.active_uid=None;self.token=None;self.signature=None;self.visible=False
            for card in self.cards:card.mon=None;card.photo=None;card.delete('all');card.pack_forget()
            self.image=None;self.portrait.configure(image='')
            if not self.field.frame.winfo_manager():self.window.title(__import__('pokemon_red.editions',fromlist=['edition']).edition(self.root_path).name+' · Встречи')
            self.field.frame.pack(fill='both',expand=True);self.field.update(state);return
        if self.field.frame.winfo_manager():self.window.title(__import__('pokemon_red.editions',fromlist=['edition']).edition(self.root_path).name+' · Бой');self.field.picker.dismiss()
        self.field.frame.pack_forget()
        if not self.visible:self.footer.pack(side='bottom',fill='x');self.body.pack(fill='both',expand=True);self.visible=True
        info=self.monitor.status.get('battle_auto',dict(active=False,pending=False,available=False,reason='Дожидаемся данных боя'))
        on=info['active'] or info['pending'];self.auto.configure(text=t('battle.auto'),variant='selected' if on else 'primary',state='normal' if (on or info['available']) and (self.auto_future is None or self.auto_future.done()) else 'disabled');self.auto_reason.configure(text=info['reason'],fg=MUTED)
        capture=self.monitor.status.get('battle_capture',dict(active=False,available=False,reason=''))
        pending=self.capture_future is not None and not self.capture_future.done()
        self.capture.configure(variant='selected' if capture['active'] else 'secondary',state='normal' if (capture['active'] or capture['available']) and not pending else 'disabled')
        if b.get('flags',0)&8:self.capture.grid_remove();self.auto.grid_configure(columnspan=2)
        else:self.capture.grid();self.auto.grid_configure(columnspan=1)
        if capture['active']:self.auto_reason.configure(text=capture['reason'])
        from .manual_battle import battle_key
        token=(getattr(self.monitor,'generation',0),battle_key(state));rows=opponents(state,self.root_path)
        active=next((m['uid'] for m in rows if m.get('active') and m.get('hp',0)>0),None)
        if token!=self.token or active!=self.active_uid:self.selected_uid=active or (rows[0]['uid'] if rows else None)
        self.token=token;self.active_uid=active;self.opponents=rows
        selected=next((m for m in rows if m['uid']==self.selected_uid),None)
        if selected is None and rows:selected=rows[0];self.selected_uid=selected['uid']
        for i,card in enumerate(self.cards):
            if i<len(rows):card.pack(fill='x',pady=(0,3));card.set(rows[i],rows[i]['uid']==self.selected_uid)
            else:card.pack_forget();card.mon=None;card.photo=None
        if not selected:
            self.heading.configure(text='Получаем данные противника…');return
        signature=(repr(selected),repr(state.get('party')),repr(b.get('allies')))
        if signature==self.signature:return
        self.signature=signature;mon=selected;sp=species(mon['species_id'],self.root_path)
        self.heading.configure(text=('Бой с тренером' if b.get('flags',0)&8 else 'Дикий Pokémon')+' · '+('сейчас в бою' if mon.get('active') else f'просмотр слота {mon["slot"]}'),fg=GREEN if mon.get('active') else MUTED)
        self.image=sprite(self.window,self.root_path,mon['species_id'],shiny=mon.get('shiny',False),gray=mon.get('hp',0)<=0);self.portrait.configure(image=self.image or '')
        self.name.configure(text=_entity_label(sp['name']));self.detail.configure(text=f'Lv {mon.get("level","?")} · HP {mon.get("hp",0)}/{mon.get("max_hp",0)} · {mon["status"]}');self.types.set(types_for(mon,self.root_path));self.hp.set(mon.get('hp',0)/max(1,mon.get('max_hp',1)))
        a=ability(mon.get('ability_id',0),self.root_path);self.ability.configure(text=t('battle.ability',name=ability_name(mon.get('ability_id',0))));self.ability_hint.text=t('entity.abilities.'+str(mon.get('ability_id',0))+'.description')
        profile=defensive_profile(mon,self.root_path)
        for key,title in [('weak','Слабости'),('resist','Сопротивления'),('immune','Иммунитет')]:self.groups[key].configure(text=title+': '+matchup_text(profile,key))
        live=(b.get('allies') or [None])[0];own=next((m for m in state.get('party',[]) if live and m['slot']==live['party_slot']),None)
        if own and own.get('hp',0)>0 and mon.get('hp',0)>0:
            ranked=ranked_attacks(own,mon,self.root_path);best=ranked[0][1] if ranked else None
            self.advice.configure(text=t('battle.damage_advice',pokemon=pokemon_name(own),move=move_name(best['move_id'],best['move']),low=best['min'],high=best['max']) if best else 'У активного Pokémon нет подходящей атаки')
        else:self.advice.configure(text='')
        self.move_title.configure(text=t('battle.moves_against',pokemon=pokemon_name(own)) if own else 'Приёмы противника')
        factors={typ:factor for key in ('weak','resist','immune') for typ,factor in defensive_profile(own,self.root_path)[key]} if own else {}
        for i,button in enumerate(self.moves):
            if i<len(mon.get('moves',[])):
                attack=mon['moves'][i];factor=factors.get(attack.get('type_id'),1);power=attack.get('power',0)
                pp=attack.get('current_pp',attack.get('pp',0));typ=TYPE_INFO.get(attack.get('type_id'),TYPE_INFO[9])[1]
                button.configure(text=_entity_label(attack['name'])+f' · {typ} · {pp} PP'+(f' · ×{factor:g}' if own and power else ''),fg=RED if own and power and factor>1 else TEXT,state='normal')
            else:button.configure(text='—',fg=MUTED,state='disabled')
    def toggle_auto(self):
        info=self.monitor.status.get('battle_auto',{})
        if self.auto_future is not None and not self.auto_future.done():return
        self.auto.configure(state='disabled')
        self.auto_future=self.monitor.runtime.submit('battle_auto',not (info.get('active') or info.get('pending')))
        self.monitor.watch(self.auto_future,lambda _:self.update(self.state),lambda error:self.auto_denied(error))
    def toggle_capture(self):
        import time
        if not self.state.get('in_battle') or (self.state.get('battle') or {}).get('flags',0)&8:return
        if self.capture_future is not None and not self.capture_future.done():return
        info=self.monitor.status.get('battle_capture',{});self.capture.configure(state='disabled')
        self.capture_future=self.monitor.runtime.submit('battle_capture',not info.get('active',False),time.time())
        self.monitor.watch(self.capture_future,lambda _:self.update(self.state),lambda error:self.auto_denied(error))
    def auto_denied(self,error):
        # A stale UI click must never revoke another automation's ownership.
        self.update(self.state);self.auto_reason.configure(text=str(error),fg=AMBER)
    def open_move(self,index):
        mon=next((m for m in self.opponents if m['uid']==self.selected_uid),None)
        if mon and index<len(mon.get('moves',[])):
            from .pokemon_ui import show_move
            if self.monitor.panel is None:self.monitor.show_panel()
            show_move(self.monitor.panel,mon['moves'][index]['id'])
    def inspect(self,index):
        if index<len(self.opponents):self.select(self.opponents[index]['uid'])
