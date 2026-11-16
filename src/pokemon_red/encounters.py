"""Display exact possible levels, including gaps hidden by a min/max range."""
def level_label(entry):
    values=sorted(int(k) for k,v in entry.get('levels',{}).items() if v>0)
    if not values:return str(entry['min_level']) if entry['min_level']==entry['max_level'] else f"{entry['min_level']}–{entry['max_level']}"
    if len(values)==1:return str(values[0])
    if values==list(range(values[0],values[-1]+1)):return f'{values[0]}–{values[-1]}'
    return ', '.join(map(str,values))
