"""Build offline grayscale PNG variants, preserving the source alpha channel."""
from pathlib import Path
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1]
root=tk.Tk();root.withdraw();count=0
for path in sorted((ROOT/'assets/pokemon').glob('*.png'))+sorted((ROOT/'assets/pokemon/shiny').glob('*.png')):
    destination=path.parent/'gray'/path.name
    if destination.exists():continue
    destination.parent.mkdir(exist_ok=True)
    base=tk.PhotoImage(master=root,file=str(path));image=base.copy()
    for y in range(base.height()):
        for x in range(base.width()):
            if base.transparency_get(x,y):continue
            r,g,b=base.get(x,y);value=(299*r+587*g+114*b+500)//1000
            image.put(f'#{value:02x}{value:02x}{value:02x}',(x,y))
    image.write(str(destination),format='png');count+=1
root.destroy();print('Built',count,'grayscale sprites')
