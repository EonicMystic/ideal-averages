#!/usr/bin/env python3
"""Build current world records and the recent-record feed from the WCA results export.

Usage: python3 build_records.py <WCA_export_tsv.zip | folder_with_tsvs> <output_dir>
Writes <output_dir>/records.json. Uses the export's own regional record flags (WR), so
it matches the official records.
"""
import datetime, json, os, shutil, sys, tempfile, zipfile
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
pname = {}
for idx, p in rows('persons'):
    if p[idx['sub_id']] == '1' or p[idx['wca_id']] not in country:
        country[p[idx['wca_id']]] = p[idx['country_id']]
        pname[p[idx['wca_id']]] = p[idx['name']]

# everyone's personal best single and average per calculator event (for the profile search)
PEVS = ['333', '222', '444', '555', '666', '777', '333oh', 'clock', 'minx', 'pyram', 'skewb', 'sq1']
PEVSET = set(PEVS)
pbest = {}          # person -> {event: [single, average]}
ROUND = {'0': 0, '1': 1, 'd': 2, '2': 3, 'e': 4, '3': 5, 'g': 6, 'f': 7, 'b': 8, 'c': 9}
recs = {'single': defaultdict(list), 'average': defaultdict(list)}
for idx, p in rows('results'):
    ev = p[idx['event_id']]
    if ev not in EVSET:
        continue
    if ev in PEVSET:
        b_, a_ = int(p[idx['best']]), int(p[idx['average']])
        if b_ > 0 or a_ > 0:
            rec_ = pbest.setdefault(p[idx['person_id']], {}).setdefault(ev, [0, 0])
            if b_ > 0 and (rec_[0] == 0 or b_ < rec_[0]): rec_[0] = b_
            if a_ > 0 and (rec_[1] == 0 or a_ < rec_[1]): rec_[1] = a_
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


# ---------- profile search + personal bests (sharded so a profile loads in a few KB) ----------
def b36(n):
    d = '0123456789abcdefghijklmnopqrstuvwxyz'
    if n == 0: return '0'
    o = ''
    while n: n, m = divmod(n, 36); o = d[m] + o
    return o
def shard_of(w):
    h = 0
    for ch in w:
        h = (h * 31 + ord(ch)) % 1000003
    return h % 256
pdir = os.path.join(out_dir, 'p')
shutil.rmtree(pdir, ignore_errors=True)
os.makedirs(pdir)
shards = {}
index = []
for pid, evs in pbest.items():
    if not any(v[1] for v in evs.values()):
        continue                                   # search lists people with at least one official average
    fields = []
    for ev in PEVS:
        v = evs.get(ev)
        fields.append('' if not v else (b36(v[0]) if v[0] else '') + '.' + (b36(v[1]) if v[1] else ''))
    while fields and fields[-1] == '':
        fields.pop()
    shards.setdefault(shard_of(pid), []).append(pid + '|' + pname.get(pid, pid).replace('|', '/').replace('\t', ' ') + '|' + ','.join(fields))
    index.append(pid + '\t' + pname.get(pid, pid).replace('\t', ' '))
for k, lines in shards.items():
    with open(os.path.join(pdir, f'{k}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
import re, unicodedata
def fold(t):
    return ''.join(c for c in unicodedata.normalize('NFD', t) if not unicodedata.combining(c)).lower()
def bucket(tok):
    k = tok[:3]
    return k if re.fullmatch(r'[a-z0-9]{2,3}', k) else '_' + str(ord(tok[0]) % 64)
buckets = {}
for line in index:
    pid, name = line.split('\t')
    seen = set()
    for tok in re.split(r'[^\w]+', fold(name)):
        if len(tok) < 2:
            continue
        k = bucket(tok)
        if k in seen:
            continue
        seen.add(k)
        buckets.setdefault(k, []).append(line)
for k, lines in buckets.items():
    lines.sort(key=lambda x: x.split('\t')[1].lower())
    with open(os.path.join(pdir, f's_{k}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
print('profiles:', len(index), 'data shards:', len(shards), 'search buckets:', len(buckets))
print('done', len(out['events']), 'events; latest record date', feed[0]['date'] if feed else '-', '; export', stamp)
