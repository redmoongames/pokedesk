"""Small detached save summaries; no party decoding or live UI work."""
import json,struct,zlib,binascii

def png(rgb,width=240,height=160):
    if len(rgb)!=width*height*3:raise ValueError('Некорректный размер кадра')
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,1))+chunk(b'IEND',b'')

def capture_summary(game):
    from .editions import edition
    if edition(game.root).family=='hoenn':
        from .hoenn import capture_summary as capture_hoenn_summary
        return capture_hoenn_summary(game)
    from .telemetry import symbols,maps,decode_text
    sy=symbols(game.root);sb1=game.read32(sy['gSaveBlock1Ptr']);sb2=game.read32(sy['gSaveBlock2Ptr'])
    info=dict(ready=False,player=None,money=None,map=None,pokedex=dict(caught=0,seen=0,total=386),play_time=None)
    if not (0x02000000<=sb1<=0x02040000-0x3d68 and 0x02000000<=sb2<=0x02040000-0xf24):return info
    first=game.read_bytes(sb1,0x294);second=game.read_bytes(sb2,0x90);key=game.read32(sb2+0xf20)
    name=decode_text(second[:8]);money=int.from_bytes(first[0x290:0x294],'little')^key;group,number=first[4:6]
    if not name or money>999999:return info
    mask=(1<<386)-1
    info.update(ready=True,player=name,money=money,map=dict(group=group,number=number,name=maps(game.root).get((group,number),f'Map {group}:{number}')),
                pokedex=dict(caught=(int.from_bytes(second[0x28:0x5c],'little')&mask).bit_count(),seen=(int.from_bytes(second[0x5c:0x90],'little')&mask).bit_count(),total=386),
                play_time=dict(hours=int.from_bytes(second[0xe:0x10],'little'),minutes=second[0x10],seconds=second[0x11]))
    return info

def capture(game):
    return json.dumps(capture_summary(game),ensure_ascii=False,separators=(',',':')).encode(),png(game.rgb())
