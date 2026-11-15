"""Distinct reference families after clip 67; all timings are local frames at 30 fps."""
import math

NEXT_TEMPLATES = {name: name for name in (
    'object_pointer', 'corner_section', 'date_interval', 'bullet_panel', 'echo_statement')}


def text(value, label, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}: нужна непустая строка до {limit} символов')
    return value


def point(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in value):
        raise ValueError(f'{label}: координаты [x,y] в видимом кадре 0..1')
    return list(value)


def next_motion_params(template, params, frames):
    if type(frames) is not int or frames < 30:
        raise ValueError(f'{template}: сцена не короче секунды')
    p = dict(params)
    nominal = {'object_pointer': 60, 'corner_section': 90, 'date_interval': 180,
               'bullet_panel': 120, 'echo_statement': 60}[template]
    scale = min(1, frames / nominal)

    def frame(key, default, duration=False):
        value = params.get(key, max(1 if duration else 0, round(default*scale)))
        if type(value) is not int or not (1 if duration else 0) <= value < frames:
            raise ValueError(f'{template}: {key} — кадр внутри сцены')
        p[key] = value
        return value

    def window(start, duration, start_default, duration_default):
        a, b = frame(start, start_default), frame(duration, duration_default, True)
        if a+b >= frames:
            raise ValueError(f'{template}: {start}/{duration} должны закончиться до конца сцены')

    if template == 'object_pointer':
        text(params.get('label'), 'object_pointer.label', 80)
        for key in ('anchor', 'label_point'):
            p[key] = point(params.get(key), f'object_pointer.{key}')
        p['control_point'] = point(params.get('control_point',
            [p['anchor'][0], p['label_point'][1]]), 'object_pointer.control_point')
        window('start_frame', 'arrival_frames', 0, 12)
        p['line_frames'] = frame('line_frames', 18, True)
        if p['start_frame']+p['line_frames'] >= frames:
            raise ValueError('object_pointer: линия должна закончиться до стыка')
        # Preserve readable tags at screen edges; render uses these same coordinates.
        p['label_point'] = [min(.84, max(.16, p['label_point'][0])), min(.94, max(.06, p['label_point'][1]))]
    elif template == 'corner_section':
        lines = params.get('lines')
        if not isinstance(lines, list) or not 1 <= len(lines) <= 3:
            raise ValueError('corner_section: 1–3 строки lines')
        p['lines'] = []
        for i, row in enumerate(lines):
            if not isinstance(row, dict):
                raise ValueError('corner_section: строка — объект')
            text(row.get('text'), 'corner_section.lines.text', 50)
            start, duration = row.get('start_frame', round((15+i*24)*scale)), row.get('reveal_frames', max(1, round(24*scale)))
            if type(start) is not int or type(duration) is not int or start < 0 or duration < 1 or start+duration >= frames:
                raise ValueError('corner_section: тайминг строки должен помещаться в сцену')
            p['lines'].append({**row, 'start_frame': start, 'reveal_frames': duration})
        if params.get('corner', 'top_left') not in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
            raise ValueError('corner_section: неизвестный угол corner')
    elif template == 'date_interval':
        for key in ('from_year', 'to_year'):
            if type(params.get(key)) is not int or not 1 <= params[key] <= 9999:
                raise ValueError(f'date_interval: подтверждённый {key} 1..9999 обязателен')
        if params['to_year'] < params['from_year']:
            raise ValueError('date_interval: to_year не меньше from_year')
        for key in ('from_label', 'to_label'):
            text(params.get(key), f'date_interval.{key}', 65)
        text(params.get('unit', 'years'), 'date_interval.unit', 20)
        p['difference'] = params['to_year']-params['from_year']
        for key, default in [('grid_start', 53), ('from_start', 58), ('difference_start', 93), ('to_start', 103)]:
            frame(key, default)
        frame('arrival_frames', 15, True)
        window('line_start', 'line_frames', 93, 45)
        if not p['grid_start'] <= p['from_start'] <= p['difference_start'] <= p['to_start']:
            raise ValueError('date_interval: порядок grid → from → difference → to')
        if max(p['grid_start'], p['to_start'])+p['arrival_frames'] >= frames:
            raise ValueError('date_interval: оставь время на появление дат')
    elif template == 'bullet_panel':
        style = params.get('style','classic')
        if style not in ('classic','report','torn_sidebar'):
            raise ValueError('bullet_panel: style classic/report/torn_sidebar')
        stretched = style == 'torn_sidebar' and params.get('timing_mode','speech') == 'stretch'
        if style == 'torn_sidebar' and params.get('timing_mode','speech') not in ('speech','stretch'):
            raise ValueError('torn_sidebar: timing_mode speech/stretch')
        text(params.get('title'), 'bullet_panel.title', 65)
        if params['title'].strip().casefold() == 'bullet point overlay':
            raise ValueError('bullet_panel: нужен смысловой заголовок, не название эффекта')
        items = params.get('items')
        if not isinstance(items, list) or not 2 <= len(items) <= 6:
            raise ValueError('bullet_panel: 2–6 пунктов items')
        if style == 'torn_sidebar':
            # Stretch is opt-in. Speech onsets and explicitly supplied windows are never retimed.
            scale = frames / 237 if stretched else min(1, frames / 237)
            window('panel_start', 'arrival_frames', 0, 33 if stretched else 34)
            window('title_start', 'title_frames', 19 if stretched else 18, 18 if stretched else 14)
        else:
            window('panel_start', 'arrival_frames', 0, 12)
        p['items'] = []
        previous = -1
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError('bullet_panel: пункт — объект')
            text(item.get('text'), 'bullet_panel.items.text', 100)
            start_default = round(frames*(.20+.64*i/(len(items)-1))) if stretched else None
            duration_default = max(1, round(frames*.10)) if stretched else max(1,round(24*scale))
            start, duration = item.get('start_frame',start_default), item.get('reveal_frames',duration_default)
            if type(start) is not int or type(duration) is not int or start < previous or start < p['panel_start'] or duration < 1 or start+duration >= frames:
                raise ValueError('bullet_panel: нужны последовательные start_frame, оставляющие время до стыка')
            p['items'].append({**item, 'start_frame': start, 'reveal_frames': duration})
            previous = start
        if style == 'torn_sidebar' and p['items'][0]['start_frame'] < p['title_start']+p['title_frames']:
            raise ValueError('torn_sidebar: заголовок должен появиться до первого пункта')
        if params.get('side', 'left') not in ('left', 'right'):
            raise ValueError('bullet_panel: side left/right')
    else:
        text(params.get('text'), 'echo_statement.text', 160)
        text(params.get('echo'), 'echo_statement.echo', 60)
        window('start_frame', 'arrival_frames', 0, 12)
        p['camera_frames'] = params.get('camera_frames', min(85, frames-p['start_frame']-1))
        if type(p['camera_frames']) is not int or p['camera_frames'] < 1 or p['start_frame']+p['camera_frames'] >= frames:
            raise ValueError('echo_statement: camera_frames должны помещаться в сцену')
        for key,default in [('camera_scale_start', .7603), ('camera_scale_end', 1)]:
            value=params.get(key,default)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .5 <= value <= 1.5:
                raise ValueError('echo_statement: camera_scale_start/end от 0.5 до 1.5')
            p[key]=value
    if type(params.get('archival', False)) is not bool:
        raise ValueError(f'{template}: archival true/false')
    return p


def validate_next_scene(scene):
    if scene.get('type') not in ('photo', 'video'):
        raise ValueError(f"{scene['template']}: нужен photo/video")
    frames = round(float(scene.get('end', scene.get('duration', 5)))*30)-round(float(scene.get('start', 0))*30)
    next_motion_params(scene['template'], scene.get('params', {}), frames)


def next_sfx(template, params, frames):
    p = next_motion_params(template, params, frames)
    if template == 'object_pointer':
        cues = [('sfx/text3.mp3', p['start_frame'], p['start_frame']+p['line_frames'], False)]
    elif template == 'corner_section':
        cues = [('sfx/marker_scribble.mp3', row['start_frame'], row['start_frame']+row['reveal_frames'], True) for row in p['lines']]
    elif template == 'date_interval':
        cues = [('sfx/scrolling.mp3', p['from_start'], p['to_start']+p['arrival_frames'], True)]
    elif template == 'bullet_panel':
        cues = [('sfx/whoosh.mp3', p['panel_start'], p['panel_start']+p['arrival_frames'], False)]
        cues += [('sfx/text3.mp3', row['start_frame'], row['start_frame']+min(10, row['reveal_frames']), False) for row in p['items']]
    else:
        cues = [('sfx/whoosh.mp3', p['start_frame'], p['start_frame']+p['arrival_frames'], False)]
    return [{'asset': asset, 'start_frame': start, 'end_frame': end, 'loop': loop} for asset, start, end, loop in cues]
