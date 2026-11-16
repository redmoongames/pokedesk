"""Persistent directed paths and fresh validation of preview-to-bot handoffs."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sqlite3,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.navigation import Navigator
from pokemon_red.path_cache import PathCache
from pokemon_red.training import TrainingProblem
from pokemon_red.optimizer import make_training_plan
from pokemon_red.prepared_plan import prepare_packet,checked_plan,resolve_plan
from pokemon_red.run_context import versions
from test_grind import mon


def grid():
    return dict(name='Test',width=8,height=4,tiles=[[[0,0,3,0] for _ in range(8)] for _ in range(4)],objects=[],trainers=[],obstacles=[],script_triggers=[],warps=[])


class PathCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'vendor').symlink_to(ROOT/'vendor');self.grids={'Test':grid(),'Other':grid()};self.caches=[]
    def tearDown(self):
        for cache in self.caches:cache.close()
        self.tmp.cleanup()
    def nav(self):
        t=SimpleNamespace(root=self.root,bot=SimpleNamespace(map=lambda name:self.grids[name]),state=lambda:dict(map={'name':'Test'},position={'x':0,'y':0}))
        nav=Navigator(t);nav.shared_paths=PathCache(self.root);self.caches.append(nav.shared_paths);return nav

    def test_paths_survive_new_navigator_and_disk_connection(self):
        nav=self.nav();expected=nav.local_path('Test',(0,0),(7,0));nav.shared_paths.close()
        with patch('pokemon_red.navigation.path_to',side_effect=AssertionError('searched cached directed path')):
            restored=self.nav();self.assertEqual(restored.local_path('Test',(0,0),(7,0)),expected)
            restored.reset();self.assertEqual(restored.local_path('Test',(0,0),(7,0)),expected)

    def test_negative_path_and_ledge_direction_are_separate(self):
        g=grid();g.update(width=3,height=1,tiles=[[[0,0,3,0],[1,0x38,0,0],[0,0,3,0]]]);self.grids['Test']=g
        nav=self.nav();self.assertEqual(nav.local_path('Test',(0,0),(2,0)),[(2,0)])
        with self.assertRaises(RuntimeError):nav.local_path('Test',(2,0),(0,0))
        with patch('pokemon_red.navigation.path_to',side_effect=AssertionError('repeated cached failure')):
            restored=self.nav();self.assertEqual(restored.local_path('Test',(0,0),(2,0)),[(2,0)])
            with self.assertRaisesRegex(RuntimeError,'Blocked'):restored.local_path('Test',(2,0),(0,0))

    def test_changed_local_obstacle_or_policy_misses_but_other_map_does_not(self):
        nav=self.nav();nav.local_path('Test',(0,0),(7,0))
        self.grids['Other']['obstacles']=[[2,0]]
        with patch('pokemon_red.navigation.path_to',side_effect=AssertionError('unrelated map invalidated path')):
            self.nav().local_path('Test',(0,0),(7,0))
        self.grids['Test']['obstacles']=[[2,0]]
        from pokemon_red.navigation import path_to
        with patch('pokemon_red.navigation.path_to',wraps=path_to) as search:
            self.nav().local_path('Test',(0,0),(7,0));self.assertEqual(search.call_count,1)
            changed=self.nav();changed.shared_paths.namespace='new walking policy';changed.local_path('Test',(0,0),(7,0));self.assertEqual(search.call_count,2)

    def test_farm_entries_bounds_and_failed_search_are_cached(self):
        g=self.grids['Test']
        for x in range(1,7):g['tiles'][1][x]=[0,2,3,1]
        first=self.nav().farm_area('Test',(0,1))
        with patch('pokemon_red.navigation.safe_grass_pair',side_effect=AssertionError('repeated farm search')):
            self.assertEqual(self.nav().farm_area('Test',(0,1)),first)
        nav=self.nav()
        with self.assertRaises(TrainingProblem):nav.farm_area('Test',(0,1),[0,2,7,3])
        with patch('pokemon_red.navigation.safe_grass_pair',side_effect=AssertionError('repeated failed farm search')):
            with self.assertRaises(TrainingProblem):self.nav().farm_area('Test',(0,1),[0,2,7,3])

    def test_cut_and_story_changes_do_not_reuse_a_blocked_path(self):
        g=self.grids['Test'];g['obstacles']=[[3,y] for y in range(4)]
        with self.assertRaises(RuntimeError):self.nav().local_path('Test',(0,0),(7,0))
        g['obstacles'].remove([3,1]);g['objects']=[dict(local_id=1,x=3,y=1,graphics_id=95)]
        # The opened cell is a real Cut/action dependency in the geometry key.
        self.assertTrue(self.nav().local_path('Test',(0,0),(7,0)))
        g['script_triggers']=[[3,1]]
        with self.assertRaises(RuntimeError):self.nav().local_path('Test',(0,0),(7,0))

    def test_corrupt_cache_is_optional_and_disk_is_bounded(self):
        cache=PathCache(self.root,limit=2);self.caches.append(cache)
        for i in range(4):cache.put('path','geometry',[i],dict(ok=True,value=[]))
        self.assertEqual(cache.db.execute('SELECT count(*) FROM entries').fetchone()[0],2)
        cache.memory.clear();cache.db.execute("UPDATE entries SET body='corrupt'");cache.db.commit()
        self.assertIsNone(cache.get('path','geometry',3))
        cache.put('path','geometry',[4],dict(ok=True));cache.memory.clear()
        self.assertIsNone(cache.get('path','geometry',4))
        cache.close();(self.root/'Data/navigation-cache.sqlite3').write_bytes(b'broken database')
        nav=self.nav();self.assertTrue(nav.local_path('Test',(0,0),(7,0)))


class PreparedPlanTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(trainee='t',route='Route1',target=20)
        self.inv=dict(ready=True,party=[mon(25,12,'t',[84,98]),mon(19,10,'r',[33],ability_id=50),mon(21,16,'s',[64])],boxes=[],field_badges=[],_planning=dict(state=dict(map={'name':'Route1'},position={'x':0,'y':0}),grids={'Route1':dict(grid(),name='Route1')},speed=8,revision=0))
        self.geo=dict(farm=dict(map='Route1',hub='Viridian',entry=[0,0],pair=[[1,1],[2,1]],cost=[0,40]),travel_seconds=20.,preparation_seconds=30.,preparation_steps=80,required_tools=[])
        with patch('pokemon_red.optimizer._route_geometry',return_value=self.geo):self.plan=make_training_plan(self.inv,self.cfg,ROOT,evidence={})
        self.packet=json.loads(json.dumps(prepare_packet(self.plan,self.inv,self.cfg,ROOT)))

    def test_valid_packet_refreshes_forecast_without_route_or_team_search(self):
        inv=deepcopy(self.inv);inv['_planning'].update(speed=2.75,revision=2);inv['party'][0].update(hp=1,experience=120)
        cfg=dict(self.cfg,_prepared_plan=self.packet)
        with patch('pokemon_red.optimizer.make_training_plan',side_effect=AssertionError('full selection at start')),patch('pokemon_red.optimizer.route_geometry',side_effect=AssertionError('geometry at start')):
            plan,reused,reason=resolve_plan(inv,cfg,ROOT)
        self.assertTrue(reused);self.assertEqual(plan['team'][0]['hp'],1);self.assertEqual(plan['forecast']['speed'],2.75);self.assertEqual(plan['forecast']['start_xp'],120)

    def test_changed_selection_conditions_force_fresh_planning(self):
        for kind in ('position','trainer','stats','move','cut_party','goal','version','not_ready'):
            inv=deepcopy(self.inv);cfg=dict(self.cfg,_prepared_plan=self.packet)
            if kind=='position':inv['_planning']['state']['position']['x']=1
            elif kind=='trainer':inv['_planning']['grids']['Route1']['script_triggers']=[[4,1]]
            elif kind=='stats':inv['party'][0]['level']+=1
            elif kind=='move':inv['party'][0]['moves'][0]['id']=33
            elif kind=='cut_party':inv['boxes']=[dict(inv['party'].pop(),location='box',box=0,box_slot=0)]
            elif kind=='goal':cfg['target']+=1
            elif kind=='not_ready':inv['ready']=False
            version=deepcopy(versions(ROOT))
            if kind=='version':version['navigation']='new policy'
            with patch('pokemon_red.prepared_plan.versions',return_value=version),patch('pokemon_red.optimizer.make_training_plan',return_value={'fresh':True}) as fresh:
                plan,reused,reason=resolve_plan(inv,cfg,ROOT)
            self.assertFalse(reused,kind);fresh.assert_called_once();self.assertEqual(plan,{'fresh':True})

    def test_npc_motion_does_not_invalidate_prepared_plan(self):
        inv=deepcopy(self.inv);g=inv['_planning']['grids']['Route1']
        g['objects']=[dict(local_id=1,x=2,y=1,anchor_x=2,anchor_y=1,movement=2,range_x=1,range_y=0)];g['obstacles']=[[2,1]]
        packet=prepare_packet(self.plan,inv,self.cfg,ROOT)
        g['objects'][0]['x']=3;g['obstacles']=[[3,1]]
        self.assertIsNotNone(checked_plan(packet,inv,self.cfg,ROOT)[0])

    def test_corrupt_packet_and_legacy_config_fall_back_safely(self):
        bad=deepcopy(self.packet);bad['plan']['team_uids']=[]
        for packet in (bad,None,{'schema':999}):
            with patch('pokemon_red.optimizer.make_training_plan',return_value=self.plan) as fresh:
                _,reused,_=resolve_plan(self.inv,dict(self.cfg,_prepared_plan=packet),ROOT)
            self.assertFalse(reused);fresh.assert_called_once()


if __name__=='__main__':unittest.main()
