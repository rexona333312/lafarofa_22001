"""Timing-aware automatic effects; manual tracks and narration are left untouched."""
import array
import hashlib
import math
import random
import subprocess
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).parent / 'assets'
POOLS = {'text': ('sfx/text1.wav', 'sfx/text2.wav', 'sfx/text3.mp3'),
         'whoosh': ('sfx/whoosh.mp3', 'sfx/woosh1.wav', 'sfx/woosh2.wav')}
FAMILIES = {Path(asset).name: family for family, assets in POOLS.items() for asset in assets}


@lru_cache(maxsize=32)
def _profile(path, size, modified):
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', '16000',
                             '-f', 'f32le', 'pipe:1'], capture_output=True, check=True)
    values = array.array('f'); values.frombytes(result.stdout)
    if not values:
        raise ValueError(f'Пустой звуковой эффект: {path}')
    energy = [sum(v*v for v in values[i:i+160])/len(values[i:i+160]) for i in range(0,len(values),160)]
    peak = max(energy)
    if peak <= 1e-12:
        raise ValueError(f'Звуковой эффект без слышимого сигнала: {path}')
    active = [i for i,v in enumerate(energy) if v >= peak*.001]
    start, end = max(0,active[0]*.01-.02), min(len(values)/16000,(active[-1]+1)*.01+.04)
    # Compare a 120-ms transient, not an average diluted by several seconds of silence.
    level = max(sum(energy[i:i+12])/len(energy[i:i+12]) for i in range(max(1,len(energy)-11)))**.5
    return {'source_start':start,'span':end-start,'level':level}


def sound_profile(asset):
    path = ASSETS/asset
    info = path.stat()
    return _profile(str(path), info.st_size, info.st_mtime_ns)


def extra_scene_sfx(template, params, frames):
    """Only visible entrances/draws; no sound on continuous camera motion or plain cuts."""
    cues=[]
    def add(asset,start,length,loop=False):
        stop=min(frames,start+length)
        if 0<=start<stop:
            cues.append(dict(asset=asset,start_frame=start,end_frame=stop,loop=loop))
    if template.startswith('photo_carousel_'):
        add('sfx/whoosh.mp3',0,21)
    elif template=='evidence_board':
        add('sfx/text3.mp3',0,18)
    elif template in ('map_geographic','map_annotations') and isinstance(params.get('geo'),dict):
        geo=params['geo']
        for kind in ('highlights','markers','routes','regions'):
            for row in geo.get(kind,[]):
                draw=kind in ('routes','regions')
                add('sfx/marker_scribble.mp3' if draw else 'sfx/text3.mp3',
                    row.get('start_frame',0),row.get('draw_frames',24),draw)
    elif template=='document_focus':
        add('sfx/text3.mp3',params.get('start_frame',0),params.get('arrival_frames',18))
        add('sfx/whoosh.mp3',params.get('zoom_start_frame',30),params.get('arrival_frames',18))
    elif template=='stat_callout' and params.get('layout','card')=='card' and params.get('start_frame',0)>=params.get('arrival_frames',18):
        add('sfx/whoosh.mp3',0,params.get('arrival_frames',18))
    elif template=='text_highlight_split':
        add('sfx/text3.mp3',params['text_start'],params['arrival_frames'])
    elif template=='lower_third_contrast':
        add('sfx/text3.mp3',params['heading_start'],params['arrival_frames'])
    return cues


def transition_sfx(transitions):
    return [dict(asset='sfx/whoosh.mp3',start=t['start']+1/30,end=t['end'],loop=False,
                 preserve_gain=True,gain_db=20*math.log10(.3),fade=0)
            for t in transitions if t.get('kind') in ('blur-reveal','frosted-glass-wipe','transition-wipe','directional-wipe')]


def distribute_sfx(tracks, duration, seed='', manual_tracks=()):
    """A deterministic shuffled bag uses all three sounds before repeating a member."""
    rng=random.Random(hashlib.sha256(str(seed).encode()).digest())
    bags={};last={};last_onset={};out=[]
    manual=[float(t.get('start',0)) for t in manual_tracks if str(t.get('asset','')).startswith('sfx/')]
    def family(track):
        return FAMILIES.get(Path(track.get('asset') or track.get('_path','')).name)
    # One moving object needs one transient, even if its text appears on the same frame.
    ordered=sorted(enumerate(tracks),key=lambda pair:(float(pair[1].get('start',0)),0 if family(pair[1])=='whoosh' else 1,pair[0]))
    targets={}
    for _,original in ordered:
        track=dict(original);start=max(0,float(track.get('start',0)));end=min(duration,float(track.get('end',duration)))
        if end<=start or any(abs(start-t)<.12 for t in manual):
            continue
        group=family(track)
        if group:
            if any(abs(start-t['start'])<.12 and family(t) in POOLS for t in out[-8:]):
                continue
            if start-last_onset.get(group,-100)<.18:
                continue
            if not bags.get(group):
                bag=list(POOLS[group]);rng.shuffle(bag)
                if bag[0]==last.get(group):bag[0],bag[1]=bag[1],bag[0]
                bags[group]=bag
            asset=bags[group].pop(0);last[group]=asset;last_onset[group]=start
            profile=sound_profile(asset)
            if group not in targets:targets[group]=min(sound_profile(a)['level'] for a in POOLS[group])
            gain=.3*min(1,targets[group]/profile['level'])
            track.pop('_path',None)
            track.update(asset=asset,_source_start=profile['source_start'],gain_db=20*math.log10(gain),
                         preserve_gain=True,loop=False,fade=min(.01,(end-start)/4))
            end=min(end,start+profile['span'])
        else:
            # Simultaneous brush strokes share one sound instead of doubling its level.
            name=Path(track.get('asset') or track.get('_path','')).name
            previous=next((t for t in reversed(out) if Path(t.get('asset') or t.get('_path','')).name==name and t.get('loop') and track.get('loop') and t['end']>=start),None)
            if previous:
                previous['end']=max(previous['end'],end)
                continue
        track.update(start=start,end=end)
        out.append(track)
    return out
