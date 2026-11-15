"""Switzerland reference: data, portrait, document and footage accents at 30 fps."""
import math
from next_reference_templates import text

DOCUMENTARY_TEMPLATES = {n: n for n in (
    'stat_callout', 'data_comparison', 'document_focus', 'portrait_profile')}


def documentary_params(template, params, frames):
    if type(frames) is not int or frames < 60:
        raise ValueError(f'{template}: нужно минимум 2 секунды')
    p = dict(params)
    start = p.get('start_frame', 0)
    arrival = p.get('arrival_frames', 18)
    if type(start) is not int or type(arrival) is not int or not 0 <= start < start+arrival <= frames-10:
        raise ValueError(f'{template}: start_frame/arrival_frames внутри сцены с временем для чтения')
    p.update(start_frame=start, arrival_frames=arrival)
    if template == 'stat_callout':
        text(p.get('value'), 'stat_callout.value', 24)
        text(p.get('label'), 'stat_callout.label', 80)
        if p.get('layout', 'card') not in ('card', 'overlay'):
            raise ValueError('stat_callout: layout card/overlay')
    elif template == 'portrait_profile':
        text(p.get('name'), 'portrait_profile.name', 80)
        text(p.get('description'), 'portrait_profile.description', 200)
    elif template == 'data_comparison':
        text(p.get('title'), 'data_comparison.title', 100)
        if 'unit' in p: text(p['unit'], 'data_comparison.unit', 30)
        rows = p.get('items')
        if not isinstance(rows, list) or not 2 <= len(rows) <= 5:
            raise ValueError('data_comparison: 2–5 items с общей единицей unit')
        p['items'] = []
        previous = start
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('data_comparison: item — объект')
            text(row.get('label'), 'data_comparison.label', 60)
            text(row.get('display'), 'data_comparison.display', 32)
            value, onset = row.get('value'), row.get('start_frame')
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('data_comparison: value — конечное неотрицательное число в общей единице')
            if type(onset) is not int or not previous <= onset <= frames-arrival-10:
                raise ValueError('data_comparison: последовательные start_frame из речи с временем для чтения')
            previous = onset
            p['items'].append(dict(row))
        if not max(r['value'] for r in rows) > 0:
            raise ValueError('data_comparison: хотя бы одно значение больше нуля')
    else:
        rect = p.get('focus_rect')
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError('document_focus: focus_rect [x,y,width,height] относительно исходного изображения')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect):
            raise ValueError('document_focus: конечные координаты')
        x, y, w, h = rect
        if not (0 <= x < x+w <= 1 and 0 <= y < y+h <= 1):
            raise ValueError('document_focus: прямоугольник внутри документа 0..1')
        zoom_start, mark = p.get('zoom_start_frame', 30), p.get('highlight_start_frame', 65)
        if type(zoom_start) is not int or type(mark) is not int or not start+arrival <= zoom_start < zoom_start+arrival <= mark <= frames-arrival-10:
            raise ValueError('document_focus: сначала документ, затем приближение, затем выделение')
        if p.get('mark', 'highlight') not in ('highlight', 'circle'):
            raise ValueError('document_focus: mark highlight/circle')
        if 'caption' in p: text(p['caption'], 'document_focus.caption', 120)
        p.update(zoom_start_frame=zoom_start, highlight_start_frame=mark)
    return p


def validate_documentary_scene(scene):
    name = scene.get('template')
    if name not in DOCUMENTARY_TEMPLATES:
        return
    if scene.get('type') not in ('photo', 'video') or (name != 'stat_callout' and scene['type'] != 'photo'):
        raise ValueError(f'{name}: нужен photo; stat_callout также принимает video')
    if name == 'stat_callout' and scene.get('type') == 'video' and scene.get('params', {}).get('layout', 'card') != 'overlay':
        raise ValueError('stat_callout: для video используй layout:overlay')
    frames = round(float(scene.get('end', scene.get('duration', 5)))*30)-round(float(scene.get('start', 0))*30)
    documentary_params(name, scene.get('params', {}), frames)


def documentary_sfx(template, params, frames):
    p = documentary_params(template, params, frames)
    starts = [r['start_frame'] for r in p['items']] if template == 'data_comparison' else [p.get('highlight_start_frame', p['start_frame'])]
    return [dict(asset='sfx/marker_scribble.mp3' if template == 'document_focus' else 'sfx/text3.mp3',
                 start_frame=s, end_frame=s+p['arrival_frames'], loop=template == 'document_focus') for s in starts]
