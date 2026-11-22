#!/usr/bin/env python3
"""Build current world records and the recent-record feed from the WCA results export.

Usage: python3 build_records.py <WCA_export_tsv.zip | folder_with_tsvs> <output_dir>
Writes <output_dir>/records.json. Uses the export's own regional record flags (WR), so
it matches the official records.
"""
import datetime, json, os, sys, tempfile, zipfile
from collections import defaultdict

src, out_dir = sys.argv[1], sys.argv[2]
os.makedirs(out_dir, exist_ok=True)
if src.endswith('.zip'):
    D = tempfile.mkdtemp()
    with zipfile.ZipFile(src) as z:
        for name in ('competitions', 'persons', 'results'):
            z.extract(f'WCA_export_{name}.tsv', D)
        if 'metadata.json' in z.namelist():
            z.extract('metadata.json', D)
else:
    D = src

EVENTS = [('333', '3x3x3'), ('222', '2x2x2'), ('444', '4x4x4'), ('555', '5x5x5'), ('666', '6x6x6'),
          ('777', '7x7x7'), ('333bf', '3x3x3 Blindfolded'), ('333fm', 'Fewest Moves'), ('333oh', '3x3x3 One-Handed'),
          ('clock', 'Clock'), ('minx', 'Megaminx'), ('pyram', 'Pyraminx'), ('skewb', 'Skewb'), ('sq1', 'Square-1'),
          ('444bf', '4x4x4 Blindfolded'), ('555bf', '5x5x5 Blindfolded'), ('333mbf', '3x3x3 Multi-Blind')]
EVSET = {e for e, _ in EVENTS}


def rows(name):
    with open(f'{D}/WCA_export_{name}.tsv', encoding='utf-8', errors='replace') as f:
        header = f.readline().rstrip('\n').split('\t')
        idx = {h: i for i, h in enumerate(header)}
        n = len(header)
        for line in f:
            p = line.rstrip('\n').split('\t')
            if len(p) == n:
                yield idx, p


try:
    stamp = json.load(open(f'{D}/metadata.json')).get('export_date', '')
except Exception:
    stamp = ''

comps = {}
for idx, p in rows('competitions'):
    y, m, d = int(p[idx['year']]), int(p[idx['month']]), int(p[idx['day']])
    try:
        ey, em, ed = int(p[idx['end_year']]), int(p[idx['end_month']]), int(p[idx['end_day']])
    except ValueError:
        ey, em, ed = y, m, d
    comps[p[idx['id']]] = (p[idx['name']], f'{ey:04d}-{em:02d}-{ed:02d}')

country = {}
for idx, p in rows('persons'):
    if p[idx['sub_id']] == '1' or p[idx['wca_id']] not in country:
        country[p[idx['wca_id']]] = p[idx['country_id']]

ROUND = {'0': 0, '1': 1, 'd': 2, '2': 3, 'e': 4, '3': 5, 'g': 6, 'f': 7, 'b': 8, 'c': 9}
recs = {'single': defaultdict(list), 'average': defaultdict(list)}
for idx, p in rows('results'):
    ev = p[idx['event_id']]
    if ev not in EVSET:
        continue
    for kind, col, flag in (('single', 'best', 'regional_single_record'), ('average', 'average', 'regional_average_record')):
        if p[idx[flag]] != 'WR':
            continue
        v = int(p[idx[col]])
        if v <= 0:
            continue
        comp = p[idx['competition_id']]
        if comp not in comps:
            continue
        recs[kind][ev].append((comps[comp][1], ROUND.get(p[idx['round_type_id']], 5), -v, v, p[idx['person_id']],
                               p[idx['person_name']], comp))


def holder(pid, name):
    return {'id': pid, 'name': name, 'country': country.get(pid, '')}


out = {'updated': stamp, 'events': {}, 'recent': []}
feed = []
for ev, label in EVENTS:
    entry = {'name': label}
    for kind in ('single', 'average'):
        lst = sorted(recs[kind].get(ev, []))
        if not lst:
            continue
        # walk the progression: a new record is any flagged result lower than the best so far
        best = None; prev = None; steps = []
        for date, rnd, _, v, pid, name, comp in lst:
            if best is None or v < best:
                prev = best; best = v
                steps.append(dict(event=ev, kind=kind, value=v, prev=prev, date=date, comp=comp,
                                  holders={pid: name}))
            elif v == best:
                steps[-1]['holders'][pid] = name          # tied the record at the same time or later
        cur = steps[-1]
        entry[kind] = dict(value=cur['value'], date=cur['date'], comp=dict(id=cur['comp'], name=comps[cur['comp']][0]),
                           holders=[holder(a, b) for a, b in cur['holders'].items()], prev=cur['prev'])
        for st in steps[-8:]:
            feed.append(dict(event=ev, kind=kind, value=st['value'], prev=st['prev'], date=st['date'],
                             comp=dict(id=st['comp'], name=comps[st['comp']][0]),
                             holders=[holder(a, b) for a, b in st['holders'].items()]))
    out['events'][ev] = entry
feed.sort(key=lambda x: (x['date'], x['event']), reverse=True)
out['recent'] = feed[:60]
with open(os.path.join(out_dir, 'records.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('done', len(out['events']), 'events; latest record date', feed[0]['date'] if feed else '-', '; export', stamp)
