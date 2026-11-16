"""Read-only evolution families and level-up opportunities; no game mutations."""
from collections import defaultdict,deque


class EvolutionIndex:
    def __init__(self,species):
        self.species=species;self.parents=defaultdict(list)
        for key,sp in species.items():
            for edge in sp['evolutions']:
                if str(edge['target']) in species:self.parents[edge['target']].append((int(key),edge))
    def children(self,number):
        return [e['target'] for e in self.species[str(number)]['evolutions'] if str(e['target']) in self.species]
    def descendants(self,number):
        result=set();pending=list(self.children(number))
        while pending:
            n=pending.pop()
            if n==number or n in result:continue
            result.add(n);pending.extend(self.children(n))
        return result
    def family(self,number):
        seen=set();pending=[number]
        while pending:
            n=pending.pop()
            if n in seen:continue
            seen.add(n);pending.extend(self.children(n));pending.extend(p for p,_ in self.parents[n])
        roots=[n for n in seen if not any(p in seen for p,_ in self.parents[n])];depth={n:0 for n in roots};queue=deque(roots)
        while queue:
            n=queue.popleft()
            for child in self.children(n):
                if child not in depth:depth[child]=depth[n]+1;queue.append(child)
        return sorted(seen,key=lambda n:(depth.get(n,0),self.species[str(n)]['national_id']))
    def levels(self,number):
        result={}
        for row in self.species[str(number)]['learnset']:result[row['move']]=min(result.get(row['move'],100),row['level'])
        return result
    def outlook(self,number):
        children=self.children(number);result={}
        for move,level in self.levels(number).items():
            if not children:continue
            absent=[];direct=[];later=[]
            for child in children:
                stages={child}|self.descendants(child);learners=[n for n in stages if move in self.levels(n)]
                if not learners:absent.append(child)
                elif move in self.levels(child):direct.append((child,self.levels(child)[move]))
                else:later.extend(learners)
            kind='exclusive' if len(absent)==len(children) else 'branch' if absent else 'later' if later else 'shared'
            result[move]=dict(kind=kind,missing=absent,direct=direct,later=sorted(set(later)),level=level)
        return result


def outlook_text(info,species,*,known=False):
    if not info:return ''
    names=lambda rows:', '.join(species[str(n)]['name'] for n in rows)
    kind=info['kind']
    if kind=='exclusive':
        text='После эволюции этот приём больше не изучается по уровню ни у одной следующей формы.'
    elif kind=='branch':text='Не изучается по уровню после выбора ветки: '+names(info['missing'])+'.'
    elif kind=='later':text='У следующей формы этого приёма по уровню нет; он снова доступен у '+names(info['later'])+'.'
    else:
        text='У следующих форм: '+', '.join(species[str(n)]['name']+' · Lv '+str(lv) for n,lv in info['direct'])+'.'
    if known:text+=' Этот Pokémon уже знает приём: при эволюции он сохранится.'
    if any(lv==1 for _,lv in info['direct']):text+=' Приём на Lv 1 не обязательно выучится при эволюции; может понадобиться Вспоминатель приёмов.'
    return text
