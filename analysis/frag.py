import json,sys
runs={'25w3':'r2025_w3.json','25w5':'r2025_w5.json','25w8':'r2025_w8.json','25w12':'r2025_w12.json','25w17':'r2025_w17.json','26w10':'r2026_w10.json'}
D={k:json.load(open('analysis/'+f)) for k,f in runs.items()}
bad={}
for key in D['26w10']:
    row=[]
    for k in runs:
        vs=list(D[k][key].values()); ok=sum(1 for r in vs if r)
        big=any(r and r['n']>50 for r in vs)
        row.append(f"{ok}/{len(vs)}"+("B" if big else ""))
    if any(c.split('/')[0]!=c.split('/')[1].rstrip('B') for c in row) or any(c.endswith('B') for c in row): print(key,row)
