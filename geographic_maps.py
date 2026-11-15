"""Real lon/lat maps. Modern boundaries are bundled; historical shapes must be supplied."""
import json
import math
from functools import lru_cache
from pathlib import Path
from next_reference_templates import text

DATA = Path(__file__).parent / 'assets/geodata/countries.geojson'
MAP_NAMES = {'map_geographic', 'map_annotations'}


def is_geo_scene(scene):
    return scene.get('template') == 'map_geographic' or (scene.get('template') in MAP_NAMES and 'geo' in scene.get('params', {}))


def coordinate(value):
    if not isinstance(value, list) or len(value) != 2 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in value) or not (-180 <= value[0] <= 180 and -85 <= value[1] <= 85):
        raise ValueError('Карта: координаты [долгота,широта], долгота ±180, широта ±85')
    return value


@lru_cache(maxsize=1)
def countries():
    return json.loads(DATA.read_text())['features']


def geographic_params(params, frames):
    p = params.get('geo')
    if not isinstance(p, dict) or frames < 60:
        raise ValueError('map_geographic: нужен params.geo и минимум 2 секунды')
    p = dict(p)
    if p.get('mode', 'terrain') not in ('flat', 'terrain'):
        raise ValueError('Карта: mode flat/terrain')
    for key in ('title', 'date'):
        if key in p: text(p[key], f'Карта.{key}', 100)
    cameras = p.get('camera')
    if not isinstance(cameras, list) or not 2 <= len(cameras) <= 12:
        raise ValueError('Карта: camera — 2–12 ключевых кадров')
    previous = -1
    for cam in cameras:
        if not isinstance(cam, dict): raise ValueError('Карта: camera — объекты')
        coordinate(cam.get('center'))
        onset = cam.get('frame')
        if type(onset) is not int or not previous < onset < frames:
            raise ValueError('Карта: camera.frame по порядку внутри сцены')
        previous = onset
        for key, lo, hi, default in [('zoom',1,12,6),('pitch',0,65,0),('bearing',-360,360,0)]:
            value=cam.get(key,default)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'Карта: {key} от {lo} до {hi}')
    if cameras[0]['frame'] != 0: raise ValueError('Карта: первая camera.frame=0')
    features=[]
    highlights=p.get('highlights', [])
    if not isinstance(highlights,list) or len(highlights)>20: raise ValueError('Карта: до 20 highlights')
    lookup={f['properties']['code']:f for f in countries()}
    for row in highlights:
        if not isinstance(row,dict) or row.get('country') not in lookup:
            raise ValueError('Карта: highlights.country — код Natural Earth, например CHE/DEU/FRA')
        features.append(lookup[row['country']])
    if 'historical_year' in p:
        raise ValueError('Карта: исторический год не меняет современные границы; используй отдельную проверенную историческую карту, а geo.date — только подпись')
    for key, minimum in [('routes',2),('markers',1),('regions',3)]:
        rows=p.get(key,[])
        if not isinstance(rows,list) or len(rows)>20: raise ValueError(f'Карта: до 20 {key}')
        for row in rows:
            if not isinstance(row,dict): raise ValueError(f'Карта: {key} — объекты')
            pts=row.get('points') if key!='markers' else [row.get('position')]
            if not isinstance(pts,list) or not minimum<=len(pts)<=100: raise ValueError('Карта: неверное количество points')
            for xy in pts: coordinate(xy)
            text(row.get('label'), 'Карта.label', 80)
    for row in highlights+p.get('routes',[])+p.get('markers',[])+p.get('regions',[]):
        onset,draw=row.get('start_frame',0),row.get('draw_frames',24)
        if type(onset) is not int or type(draw) is not int or not 0 <= onset < onset+draw <= frames-10:
            raise ValueError('Карта: start_frame/draw_frames внутри сцены с временем для чтения')
        color=row.get('color','#e5c65f')
        if not isinstance(color,str) or len(color)!=7 or color[0]!='#' or any(c not in '0123456789abcdefABCDEF' for c in color[1:]):
            raise ValueError('Карта: color #RRGGBB')
    return {**p,'features':features,'countries':{'type':'FeatureCollection','features':countries()}}


def validate_geo_scene(scene):
    if is_geo_scene(scene):
        if scene.get('type')!='photo': raise ValueError('Географическая карта: type:photo')
        geographic_params(scene.get('params',{}),round(float(scene.get('end',scene.get('duration',5)))*30)-round(float(scene.get('start',0))*30))


def graphic_placeholder(scene, folder):
    """A picker thumbnail for a map or chart rendered from structured scene data."""
    from PIL import Image, ImageDraw
    import hashlib
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(json.dumps(scene.get('params',{}),sort_keys=True).encode()).hexdigest()[:12]
    path=folder/f'map_{key}.png'
    if not path.exists():
        image=Image.new('RGB',(1280,720),'#182324');d=ImageDraw.Draw(image)
        for x in range(0,1280,80):d.line((x,0,x,720),fill='#293938')
        for y in range(0,720,80):d.line((0,y,1280,y),fill='#293938')
        d.text((60,60),'DATA COMPARISON / REMOTION' if scene.get('template')=='data_comparison' else 'GEOGRAPHIC MAP / REMOTION',fill='#e5c65f')
        d.text((60,100),'This graphic is generated during video rendering.',fill='white')
        image.save(path)
    return str(path)
