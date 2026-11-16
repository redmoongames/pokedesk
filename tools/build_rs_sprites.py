"""Decode native RS front sprites and palettes from the supplied cartridge."""
from pathlib import Path
import sys,struct,zlib,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from pokemon_red.telemetry import parse_symbols

def lz(data,offset):
 if data[offset]!=0x10:raise ValueError('GBA LZ77 header')
 size=int.from_bytes(data[offset+1:offset+4],'little');result=bytearray();offset+=4
 while len(result)<size:
  flags=data[offset];offset+=1
  for bit in range(7,-1,-1):
   if len(result)>=size:break
   if flags&(1<<bit):
    a,b=data[offset:offset+2];offset+=2;length=(a>>4)+3;distance=((a&15)<<8|b)+1
    for _ in range(length):result.append(result[-distance])
   else:result.append(data[offset]);offset+=1
 return bytes(result[:size])

def png(rgba):
 def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
 scan=b''.join(b'\0'+rgba[y*256:(y+1)*256] for y in range(64))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(scan,9))+chunk(b'IEND',b'')

def build():
 rom=(ROOT/'ROMs/Ruby-Rev2.gba').read_bytes();sy=parse_symbols((ROOT/'vendor/reference/pokeruby_rev1.sym').read_text());cat=json.loads((ROOT/'vendor/catalog/ruby.json').read_text());out=ROOT/'assets/pokemon-rs';manifest={}
 def pointer(table,index):return int.from_bytes(rom[sy[table]-0x08000000+index*8:sy[table]-0x08000000+index*8+4],'little')-0x08000000
 for key,mon in cat['species'].items():
  number=int(key);tiles=lz(rom,pointer('gMonFrontPicTable',number))
  for shiny,table in ((False,'gMonPaletteTable'),(True,'gMonShinyPaletteTable')):
   colors=[((v&31)*255//31,((v>>5)&31)*255//31,((v>>10)&31)*255//31) for v in struct.unpack('<16H',lz(rom,pointer(table,number))[:32])]
   for gray in (False,True):
    pixels=bytearray()
    for y in range(64):
     for x in range(64):
      packed=tiles[(y//8*8+x//8)*32+(y%8)*4+x%8//2];index=packed>>(4*(x%2))&15;r,g,b=colors[index]
      if gray:r=g=b=(299*r+587*g+114*b+500)//1000
      pixels.extend((r,g,b,255 if index else 0))
    relative=Path('shiny' if shiny else '')/('gray' if gray else '')/f"{mon['national_id']}.png";path=out/relative;path.parent.mkdir(parents=True,exist_ok=True);blob=png(bytes(pixels));path.write_bytes(blob);manifest[str(relative)]=hashlib.sha256(blob).hexdigest()
 (out/'manifest.json').write_text(json.dumps(dict(source='Supplied Ruby Rev 2 cartridge; native front picture and palette tables, first frame',rom_sha1=hashlib.sha1(rom).hexdigest(),files=manifest),indent=2));print('Native RS sprites',len(manifest))
if __name__=='__main__':build()
