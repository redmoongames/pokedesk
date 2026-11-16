#!/usr/bin/env python3
"""Build the offline regional grid from the pinned FireRed Town Map layouts."""
from pathlib import Path
import argparse,hashlib,json,re,urllib.request
PIN='ce6406d8c2eaf46d543c8a2606de0c3cb1951982'
BASE=f'https://raw.githubusercontent.com/pret/pokefirered/{PIN}/src/data/region_map/'

def build(read):
    sources={}
    def source(name):
        raw=read(name);sources[name]=hashlib.sha256(raw).hexdigest();return raw.decode()
    sections=json.loads(source('region_map_sections.json'))['map_sections']
    names={r['id']:r.get('name',r['id'].removeprefix('MAPSEC_').replace('_',' ').title()) for r in sections}
    pages={}
    for key in ('kanto','sevii_123','sevii_45','sevii_67'):
        layers={}
        for layer,body in re.findall(r'\[(LAYER_\w+)\]\s*=\s*\{(.*?)\n    \}',source(f'region_map_layout_{key}.h'),re.S):
            rows=[re.findall(r'MAPSEC_\w+',line) for line in body.splitlines() if '{MAPSEC_' in line]
            if len(rows)!=15 or any(len(row)!=22 for row in rows):raise ValueError('Unexpected Town Map dimensions: '+key)
            layers[layer.removeprefix('LAYER_').lower()]=rows
        if set(layers)!={'map','dungeon'}:raise ValueError('Missing Town Map layer: '+key)
        pages[key]=layers
    return dict(version=1,source_commit=PIN,source=f'https://github.com/pret/pokefirered/tree/{PIN}/src/data/region_map',
                source_sha256=sources,width=22,height=15,names=names,pages=pages)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,help='Folder with downloaded source files (otherwise download pinned files)');parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'vendor/reference/region_map.json');args=parser.parse_args()
    def read(name):
        if args.source:return (args.source/name).read_bytes()
        with urllib.request.urlopen(BASE+name,timeout=30) as response:return response.read()
    args.output.write_text(json.dumps(build(read),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
