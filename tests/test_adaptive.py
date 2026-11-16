"""Battle decisions use available PP; rates are ratios over complete round trips."""
from pathlib import Path
import sys,tempfile,unittest,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from test_grind import mon
from pokemon_red.grind import GrindTrainer
from pokemon_red.mechanics import wild_mon
from pokemon_red.planning import make_plan
from pokemon_red.history import History,FPS

class Client:
    project_dir=ROOT
    def __init__(self):self.events=[]
    def event(self,*a,**kw):self.events.append((a,kw))

class AdaptiveTests(unittest.TestCase):
    def test_real_minutes_keep_elapsed_time_and_exclude_pause(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d,patch('pokemon_red.history.time.monotonic',return_value=100) as clock:
            h=History(Path(d));s=dict(ready=False)
            clock.return_value=160;h.observe(s,paused=False);self.assertEqual(h.active_seconds,60)
            clock.return_value=220;h.observe(s,paused=True);self.assertEqual(h.active_seconds,60)
            clock.return_value=250;h.observe(s,paused=False);self.assertEqual(h.active_seconds,90);h.close()
    def trainer(self,target,helpers,route='Route2'):
        rat=mon(19,15,'rat',[98],ability_id=50);party=[target,rat,*helpers]
        bot=Client();t=GrindTrainer(bot,dict(auto_team=True,strategy='adaptive',trainee=target['uid'],fighters=[m['uid'] for m in [target,*helpers]],route=route));t.preparing=False;t.runner='rat';t.want_heal=False
        s=dict(party=party,in_battle=True,battle=dict(enemies=[wild_mon(16,4,ROOT)]));return t,s,bot
    def test_target_one_hit_stays_in_for_full_xp(self):
        target=mon(25,16,'t',[84]);helper=mon(21,20,'h',[64]);t,s,b=self.trainer(target,[helper]);self.assertEqual(t.battle_fighter(s,target)['uid'],'t');self.assertEqual(b.events[-1][1]['reason'],'coverage_policy')
    def test_weak_target_uses_counter_then_exhausted_pp_uses_other_reserve(self):
        target=mon(11,8,'t',[106]);pika=mon(25,16,'p',[84]);bird=mon(21,20,'s',[64]);t,s,b=self.trainer(target,[pika,bird]);s['battle']['enemies']=[wild_mon(21,8,ROOT)];self.assertEqual(t.battle_fighter(s,target)['uid'],'p');pika['moves'][0]['current_pp']=0;self.assertEqual(t.battle_fighter(s,pika)['uid'],'s');self.assertFalse(t.need_heal(s));bird['moves'][0]['current_pp']=0;self.assertTrue(t.need_heal(s))
    def test_elemental_immunity_switches_and_effective_move_remains_when_one_runs_out(self):
        target=mon(25,12,'t',[84,98]);water=mon(7,18,'w',[55]);t,s,b=self.trainer(target,[water]);s['battle']['enemies']=[wild_mon(74,12,ROOT)];self.assertEqual(t.battle_fighter(s,target)['uid'],'w')
        s['battle']['enemies']=[wild_mon(16,3,ROOT)];target['moves'][0]['current_pp']=0;self.assertEqual(t.attack_choice(target,s['battle']['enemies'][0]),1)
    def test_default_plan_is_one_adaptive_team_with_four_reserves(self):
        team=[mon(11,8,'t',[106]),mon(19,10,'r',[98],ability_id=50),mon(25,14,'p',[84]),mon(21,16,'s',[64]),mon(12,14,'b',[93]),mon(56,14,'m',[2])]
        plan=make_plan(dict(ready=True,party=team,boxes=[]),dict(route='Route3',trainee='t',target=15),ROOT);self.assertEqual(plan['strategy'],'adaptive');self.assertEqual(len(plan['team']),6);self.assertEqual(len(plan['reserves']),4);self.assertIn('t',plan['fighters']);self.assertNotIn('r',plan['fighters'])
    def test_cycle_rate_weights_time_and_includes_transit_and_healing(self):
        with tempfile.TemporaryDirectory() as d:
            h=History(Path(d));target=mon(25,12,'t',[84]);s=dict(ready=True,frame=100,party=[target],map={'name':'ViridianCity_PokemonCenter_1F'},battle=None)
            h.observe(s);h.training_event('training_run_start',dict(route='Route1',strategy='adaptive',trainee='t',target=15),s)
            # Preparation has XP and time but belongs to no measured cycle.
            s['frame']+=round(FPS*300);target['experience']+=500
            for number,seconds in [(1,60),(2,180)]:
                h.training_event('cycle_start',dict(number=number,clinic='Viridian',area=[[12,6],[13,6]]),s)
                s['frame']+=round(FPS*seconds/2);target['experience']+=60;s['map']['name']='Route1';h.observe(s)
                # Walking home and healing add time but no XP.
                s['frame']+=round(FPS*seconds/2);s['map']['name']='ViridianCity_PokemonCenter_1F';h.observe(s);h.training_event('cycle_complete',{},s)
            rows=h.comparisons();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['cycles'],2);self.assertEqual(rows[0]['target_xp'],120);self.assertAlmostEqual(rows[0]['xp_game_minute'],30,places=1)
            # A different clinic/area is a different comparison cohort.
            h.training_event('cycle_start',dict(number=3,clinic='Pewter',area=[[1,2],[2,2]]),s);s['frame']+=round(FPS*60);target['experience']+=20;h.training_event('cycle_complete',{},s);self.assertEqual(len(h.comparisons()),2);h.close()

if __name__=='__main__':unittest.main()
