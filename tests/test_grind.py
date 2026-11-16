"""Planning and measured cycles must not confuse estimates with actual gains."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.catalog import move,species,catalog
from pokemon_red.mechanics import wild_mon,estimate,ranked_attacks,escape_info
from pokemon_red.rules import stage_multiplier,effect_description
from pokemon_red.planning import make_plan,fingerprint
from pokemon_red.models import calculate_stats
from pokemon_red.history import History,FPS


def mon(number,level,uid,moves,**extra):
    result=wild_mon(number,level,ROOT);result.update(uid=uid,nickname=result['species'],experience=100,checksum_valid=True,is_egg=False,location='party',status='В норме',moves=[dict(move(n,ROOT),current_pp=move(n,ROOT)['pp']) for n in moves]);result.update(extra);return result

class GrindTests(unittest.TestCase):
    def test_harden_caps_and_percentages_are_generation_three(self):
        self.assertEqual(stage_multiplier(1),1.5);self.assertEqual(stage_multiplier(6),4);self.assertEqual(stage_multiplier(100),4);self.assertEqual(stage_multiplier(-6),.25)
        self.assertAlmostEqual(stage_multiplier(1,accuracy=True),4/3)
        effect=effect_description(move(106));self.assertIn('−6…+6',effect);self.assertIn('0.67',effect)
    def test_real_attacks_respect_immunity_accuracy_and_stage_changes(self):
        attacker=mon(25,12,'p',[84,98]);pidgey=wild_mon(16,4,ROOT);ground=wild_mon(27,4,ROOT)
        self.assertEqual(ranked_attacks(attacker,ground,ROOT)[0][1]['move_id'],98)
        self.assertEqual(estimate(attacker,pidgey,move(84),ROOT)['effectiveness'],2)
        normal=estimate(attacker,pidgey,move(98),ROOT)['mean'];pidgey['stages']={'defense':2};self.assertLess(estimate(attacker,pidgey,move(98),ROOT)['mean'],normal)
        attacker['moves'][0]['current_pp']=0;self.assertEqual(ranked_attacks(attacker,pidgey,ROOT)[0][0],1)
    def test_fixed_damage_multihit_and_unsafe_attacks(self):
        attacker=mon(21,12,'s',[31,69,120]);foe=wild_mon(19,15,ROOT)
        fixed=estimate(attacker,foe,move(69),ROOT);self.assertEqual((fixed['min'],fixed['max']),(12,12))
        multi=estimate(attacker,foe,move(31),ROOT);self.assertTrue(multi['approximate']);self.assertGreater(multi['max'],multi['min'])
        self.assertEqual(estimate(attacker,foe,move(120),ROOT)['mean'],0)
    def test_escape_is_ability_and_speed_not_species(self):
        rat=mon(19,8,'r',[33],ability_id=62);self.assertFalse(escape_info(rat)['guaranteed']);self.assertLess(escape_info(rat,100)['chance'],1)
        rat['ability_id']=50;self.assertTrue(escape_info(rat,100)['guaranteed'])
    def test_boxed_target_team_and_solo_are_distinct(self):
        target=mon(11,8,'t',[106],location='box',box=0,box_slot=2,box_name='BOX1');rat=mon(19,9,'r',[33],ability_id=50);pika=mon(25,12,'p',[84],location='box',box=1,box_slot=0,box_name='BOX2');bird=mon(21,12,'b',[64])
        inv=dict(ready=True,party=[rat,bird],boxes=[target,pika]);config=dict(trainee='t',strategy='switch',route='Route2',target=15)
        plan=make_plan(inv,config,ROOT);self.assertEqual(set(plan['fighters']),{'p','b'});self.assertEqual(plan['runner'],'r');self.assertEqual(set(plan['team_uids']),{'t','r','p','b'});self.assertTrue(plan['warnings'])
        with self.assertRaisesRegex(ValueError,'нет пригодных атак'):make_plan(inv,dict(config,strategy='solo'),ROOT)
        solo=make_plan(inv,dict(config,strategy='solo',trainee='p'),ROOT);self.assertEqual(solo['fighters'],['p']);self.assertEqual(set(solo['team_uids']),{'p','r','b'});self.assertEqual(solo['reserves'],['b'])
        pika['moves'][0]['current_pp']=0;self.assertEqual(make_plan(inv,dict(config,strategy='solo',trainee='p'),ROOT)['fighters'],['p']) # Center restores PP.
        self.assertIsNone(make_plan(dict(inv,party=[bird]),config,ROOT)['runner'])
    def test_team_comparison_changes_when_levels_or_attacks_change(self):
        a=mon(25,12,'p',[84]);first=fingerprint([a]);a['level']+=1;self.assertNotEqual(first,fingerprint([a]))
    def test_completed_cycle_excludes_preparation_and_partial_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=History(root);a=mon(25,12,'t',[84]);state=dict(ready=True,frame=100,map={'name':'ViridianCity_PokemonCenter_1F'},party=[a],battle=None)
            h.observe(state);h.training_event('training_run_start',dict(route='Route1',strategy='solo',trainee='t',target=15,team_fingerprint='preview'),state)
            state['frame']=1000;a['experience']+=20 # Preparation XP is excluded.
            h.training_event('preparation_complete',{},state);h.training_event('cycle_start',dict(number=1),state)
            state['frame']=1000+round(FPS*60);a['experience']+=100;h.observe(state);h.training_event('cycle_complete',{},state)
            h.training_event('cycle_start',dict(number=2),state);state['frame']+=100;a['experience']+=11;h.training_event('script_stopped',{},state)
            rows=h.cycles();self.assertTrue(rows[0]['status'].startswith('partial:'));self.assertEqual(rows[0]['target_xp'],11);self.assertEqual(rows[1]['target_xp'],100)
            rates=h.comparisons();self.assertEqual(len(rates),1);self.assertEqual(rates[0]['cycles'],1);self.assertAlmostEqual(rates[0]['xp_game_minute'],100,places=1);h.close()
            h=History(root);self.assertEqual(len(h.cycles()),2);h.close()
    def test_interrupted_cycle_keeps_last_synced_xp_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=History(root);a=mon(25,12,'t',[84]);state=dict(ready=True,frame=1,map={'name':'Route1'},party=[a],battle=None)
            h.observe(state);h.training_event('training_run_start',dict(route='Route1',strategy='solo',trainee='t',target=15,team_fingerprint='test'),state);h.training_event('cycle_start',dict(number=1),state)
            a['experience']+=50;state['frame']+=600;h.observe(state)
            h.db.close() # Simulate a process exit after the last periodic commit.
            restored=History(root);row=restored.cycles()[0];self.assertEqual(row['status'],'interrupted');self.assertEqual(row['target_xp'],50);self.assertEqual(restored.comparisons(),[]);restored.close()

    def test_takeover_during_transient_party_data_keeps_observed_xp(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=History(root);a=mon(25,12,'t',[84]);state=dict(ready=True,frame=1,map={'name':'Route1'},party=[a],battle=None)
            h.observe(state);h.training_event('training_run_start',dict(route='Route1',strategy='solo',trainee='t',target=15,team_fingerprint='test'),state);h.training_event('cycle_start',dict(number=1),state)
            a['experience']+=30;state['frame']+=600;h.observe(state)
            h.training_event('script_stopped',{},dict(state,telemetry_valid=False,party=[]));self.assertEqual(h.cycles()[0]['target_xp'],30);h.close()

    def test_reference_sqlite_uses_one_portable_store(self):
        from pokemon_red.database import load_reference
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'vendor').symlink_to(ROOT/'vendor');data=load_reference(root);self.assertEqual(len(data['species']),386);self.assertEqual(len(data['moves']),354);self.assertTrue({'Route1','Route2','Route3','Route22','ViridianForest','MtMoon_B2F'}<=set(data['routes']));self.assertEqual(len(data['routes']),29);self.assertFalse((root/'Data/history.sqlite3').exists())
    def test_matching_catalog_is_readable_while_journal_writer_is_active(self):
        from pokemon_red.database import load_reference,connect
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'vendor').symlink_to(ROOT/'vendor');load_reference(root);writer=connect(root)
            writer.execute("INSERT INTO owned_pokemon VALUES('test','now','party',1,'{}')")
            try:self.assertEqual(len(load_reference(root)['species']),386)
            finally:writer.rollback();writer.close()

    def test_buffered_inputs_do_not_hold_an_idle_sqlite_write_lock(self):
        from pokemon_red.database import connect
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);h=History(root);h.event('player_input','A',durable=False);other=connect(root)
            other.execute('BEGIN IMMEDIATE');other.rollback();other.close();h.last_commit=0;h.observe(dict(ready=False));self.assertEqual(len(h.events()),1);h.close()

    def test_sdk_accepts_a_full_pc_inventory_larger_than_one_megabyte(self):
        import io
        from pokemon_red.bot import Bot
        owned=[dict(uid=str(i),moves=[dict(description='x'*800) for _ in range(4)]) for i in range(420)]
        payload=json.dumps(dict(ok=True,result=dict(boxes=owned))).encode()+b'\n';self.assertGreater(len(payload),1024*1024)
        class Socket:
            def sendall(self,data):pass
        bot=Bot.__new__(Bot);bot.token='test';bot.socket=Socket();bot.reader=io.BytesIO(payload)
        self.assertEqual(len(bot.inventory()['boxes']),420)

    def test_pewter_is_a_supported_preparation_start(self):
        from pokemon_red.grind import validate_start
        for name in ('PewterCity','PewterCity_PokemonCenter_1F'):
            validate_start(dict(ready=True,in_battle=False,map={'name':name},controls=dict(callback='CB2_Overworld',field_locked=False),party=[{'hp':1}]))

    def test_unexpected_field_dialog_hands_off_without_pressing_a(self):
        from pokemon_red.grind import GrindTrainer
        from pokemon_red.bot import HandedOff
        class Bot:
            project_dir=ROOT
            def state(self):return dict(frame=1,party=[],controls=dict(callback='CB2_Overworld',field_locked=True,message_box=1),map={'name':'Route22'},position={'x':33,'y':5})
            def checkpoint(self,name):pass
            def handoff(self,code,message,**details):self.code=code;raise HandedOff()
            def press(self,*a,**kw):raise AssertionError('No button may skip unexpected dialog')
        bot=Bot();trainer=GrindTrainer(bot,dict(trainee='t',fighters=[],auto_team=True,route='Route22'))
        with self.assertRaises(HandedOff):trainer.state()
        self.assertEqual(bot.code,'unexpected_dialog')
        trainer.interaction='healing';self.assertEqual(trainer.state()['frame'],1)

    def test_shedinja_and_neutral_stat_formula(self):
        stats=calculate_stats(species(25),50,[31]*6,[0]*6,0);self.assertEqual(stats['hp'],110);self.assertEqual(calculate_stats(next(s for s in catalog()['species'].values() if s['national_id']==292),50)['hp'],1)

if __name__=='__main__':unittest.main()
