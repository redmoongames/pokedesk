from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.speeds import SPEED_KEYS,normalize_speed,parse_speed
from pokemon_red.settings import Settings
from pokemon_red.history import History
from pokemon_red.audio import Playback

class CustomSpeedTests(unittest.TestCase):
    def test_physical_map_and_arbitrary_positive_rates(self):
        self.assertEqual(list(SPEED_KEYS.values()),[0,1,2,3,4,6,8,12,16,20])
        for s in (0,.5,1.5,2.75,5,17,32,100):self.assertEqual(normalize_speed(s),s)
        self.assertEqual(parse_speed('2,75'),2.75);self.assertEqual(parse_speed(' 0.5× '),.5)
        for v in (-1,True,None,'2',float('nan'),float('inf')):
            with self.assertRaises(ValueError):normalize_speed(v)
    def test_custom_preference_and_fractional_statistics_survive(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=Settings(p);s.set('speed',2.75);self.assertEqual(Settings(p)['speed'],2.75)
            s.set('speed',.5);self.assertEqual(Settings(p)['speed'],.5)
            h=History(p);h.observe(dict(ready=True,frame=1,party=[],map={}),speed=.5);self.assertEqual(h.speed,.5);h.close()
    def test_audio_receives_integer_sample_rate_at_fractional_speed(self):
        lib=Mock();p=Playback(lib)
        for speed,rate in ((.5,16384),(1.5,49152),(2.75,90112)):
            p.configure(active=True,rate=32768,speed=speed,enabled=True,volume=50)
            lib.pokemon_output_open.assert_called_once_with(48000);self.assertEqual(p.input_rate,rate);self.assertIsInstance(p.input_rate,int)
        p.close()
if __name__=='__main__':unittest.main()
