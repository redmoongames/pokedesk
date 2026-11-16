"""Native acceptance on an explicit disposable checkpoint; never writes source saves."""
from pathlib import Path
import sys,json,time,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.engine import Game,BUTTONS
from pokemon_red.acquisition_play import Player
from pokemon_red.journey import Journey
from pokemon_red.telemetry import read_walk_state

class Worker:
    def heartbeat(self):pass
    def safe_point(self):pass
    def event(self,*a,**kw):pass
    def update(self,**kw):pass

class Probe(Journey):
    def __init__(self,g):super().__init__(g,Worker());self.counts={'run':0,'walk':0};self.max_deviation=0
    def advance(self,frames=12,mask=0):
        if mask&sum(BUTTONS[k] for k in ('UP','DOWN','LEFT','RIGHT')):
            self.counts['run' if mask&BUTTONS['B'] else 'walk']+=frames
            if mask&BUTTONS['B']:
                st=read_walk_state(self.g)
                assert st['open'] and st['can_run'] and not st['in_battle'],st
        return super().advance(frames,mask)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--state',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    cases={'straight':[(17,7),(31,7)],'zigzag':[(31,7),(28,7),(28,9),(31,9),(31,11),(28,11),(28,13),(31,13)],'precision':[(30,7),(31,7),(31,8),(30,8),(30,7),(31,7),(31,8),(30,8),(30,7)],'portal':[(17,7)]}
    rows=[]
    with Game(ROOT,resume=False) as g:
        for name,points in cases.items():
            for repeat in range(3):
                g.load_state(args.state);p=Probe(g);p.go(points[0]);p.counts={'run':0,'walk':0};start=g.frame;began=time.perf_counter();cpu=time.process_time()
                if name=='portal':
                    p.nav.travel('VermilionCity_PokemonCenter_1F',(7,4));p.nav.travel('VermilionCity',points[0])
                else:
                    for goal in points[1:]:
                        p.go(goal);s=p.state();assert (s['position']['x'],s['position']['y'])==goal
                s=p.state();assert s['map']['name']=='VermilionCity'
                rows.append(dict(case=name,repeat=repeat,frames=g.frame-start,seconds=time.perf_counter()-began,cpu=time.process_time()-cpu,buttons=p.counts,goal=[s['position']['x'],s['position']['y']]))
                print(name,repeat,rows[-1],flush=True)
    args.output.write_text(json.dumps(rows,indent=2))
if __name__=='__main__':main()
