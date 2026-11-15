"""Measured reference motions, shared by validation, renderer and SFX placement."""
import math
from next_reference_templates import NEXT_TEMPLATES, next_motion_params, validate_next_scene, next_sfx
from late_reference_templates import LATE_TEMPLATES, late_motion_params, validate_late_scene, late_sfx

REFERENCE_TEMPLATES = {name: name for name in (
    'chapter_heading', 'date_countback',
    'editorial_statement', 'paired_evidence')}
REFERENCE_TEMPLATES.update(NEXT_TEMPLATES)
REFERENCE_TEMPLATES.update(LATE_TEMPLATES)


def motion_params(template, params, frames):
    """Normalize finite frame windows once; short scenes compress defaults proportionally."""
    if template in NEXT_TEMPLATES:
        return next_motion_params(template, params, frames)
    if template in LATE_TEMPLATES:
        return late_motion_params(template, params, frames)
    nominal = {'chapter_heading': 90, 'date_countback': 105,
               'editorial_statement': 96, 'paired_evidence': 92}[template]
    defaults = {
        'chapter_heading': {'arrival_frames': 12, 'underline_start': 9, 'underline_frames': 15},
        'date_countback': {'arrival_frames': 30, 'line_frames': 12, 'count_start': 33, 'count_frames': 54},
        'editorial_statement': {'arrival_frames': 18, 'reveal_start': 8, 'reveal_frames': 24,
                                'highlight_start': 12, 'highlight_frames': 45},
        'paired_evidence': {'arrival_start': 25, 'arrival_frames': 59, 'label_start': 23},
    }[template]
    scale = min(1, frames / nominal)
    result = dict(params)
    for key, value in defaults.items():
        value = params.get(key, max(1, round(value * scale)))
        if type(value) is not int or not 0 <= value < frames or (key.endswith('_frames') and value < 1):
            raise ValueError(f'{template}: {key} — целое число кадров внутри сцены')
        result[key] = value
    windows = {'chapter_heading': [('underline_start', 'underline_frames')],
               'date_countback': [('count_start', 'count_frames')],
               'editorial_statement': [('reveal_start', 'reveal_frames'), ('highlight_start', 'highlight_frames')],
               'paired_evidence': [('arrival_start', 'arrival_frames')]}.get(template, [])
    for start, duration in windows:
        if result[start] + result[duration] >= frames:
            raise ValueError(f'{template}: {start}/{duration} должны закончиться до конца сцены')
    return result


def comparison_groups(chunks):
    groups = {}
    for index, chunk in enumerate(chunks):
        if chunk.get('template') not in ('paired_evidence','split_verdict'):
            continue
        key = chunk.get('params', {}).get('comparison_group')
        if not isinstance(key, str) or not key.strip() or len(key) > 50:
            raise ValueError('paired_evidence: нужен comparison_group до 50 символов')
        groups.setdefault(key, []).append(index)
    for indices in groups.values():
        if len(indices) != 2 or indices[1] != indices[0]+1:
            raise ValueError('paired_evidence: ровно два последовательных кадра одной группы')
        first, second = (chunks[i] for i in indices)
        if first['template'] != second['template']:
            raise ValueError('Сравнение: обе карточки используют один шаблон')
        if first.get('params', {}).get('archival', False) != second.get('params', {}).get('archival', False):
            raise ValueError('paired_evidence: archival одинаковый в обеих карточках')
        frames = round(float(second['end'])*30)-round(float(first['start'])*30)
        if frames < 30:
            raise ValueError('paired_evidence: общая сцена не короче секунды')
        anchor_params = first.get('params', {})
        timing_keys = (('arrival_start', 'arrival_frames', 'label_start') if first['template']=='paired_evidence'
                       else ('left_start','left_frames','split_start','split_frames','right_start','right_frames',
                             'left_label_start','label_frames','right_label_start','right_label_frames'))
        for key in timing_keys:
            if key in second.get('params', {}) and second['params'][key] != anchor_params.get(key):
                raise ValueError('paired_evidence: тайминг задаётся в первом кадре группы')
        motion_params(first['template'], anchor_params, frames)
    return list(groups.values())


def validate_reference_scene(scene):
    template, params = scene.get('template'), scene.get('params', {})
    if template not in REFERENCE_TEMPLATES:
        return
    if template in NEXT_TEMPLATES:
        return validate_next_scene(scene)
    if template in LATE_TEMPLATES:
        return validate_late_scene(scene)
    if template == 'paired_evidence' and scene.get('type') != 'photo':
        raise ValueError(f'{template}: нужна фотография')
    frames = round((float(scene.get('end', scene.get('duration', 5)))-float(scene.get('start', 0)))*30)
    if frames < (1 if template == 'paired_evidence' else 30):
        raise ValueError(f'{template}: слишком короткий кадр')
    for key in ('text', 'label', 'title'):
        if key in params and (not isinstance(params[key], str) or len(params[key]) > 160):
            raise ValueError(f'{template}: {key} — строка до 160 символов')
    if template in {'chapter_heading', 'editorial_statement'} and not params.get('text', '').strip():
        raise ValueError(f'{template}: нужен params.text')
    if template == 'date_countback':
        if type(params.get('year')) is not int or not 1 <= params['year'] <= 9999:
            raise ValueError('date_countback: нужен подтверждённый year 1..9999')
        if type(params.get('from_year', params['year'])) is not int or not 1 <= params.get('from_year', params['year']) <= 9999:
            raise ValueError('date_countback: from_year 1..9999')
        if params.get('from_year', params['year']) < params['year']:
            raise ValueError('date_countback: from_year не меньше year')
    if template == 'paired_evidence':
        if not params.get('label', '').strip():
            raise ValueError('paired_evidence: нужна подпись каждой карточки')
        if type(params.get('archival', False)) is not bool:
            raise ValueError('paired_evidence: archival true/false')
        key = params.get('comparison_group')
        if not isinstance(key, str) or not key.strip() or len(key) > 50:
            raise ValueError('paired_evidence: нужен comparison_group')
        return  # Timing belongs to the whole pair; checked by comparison_groups.
    motion_params(template, params, frames)


def reference_sfx(template, params, frames):
    """Chosen local sounds, not claimed to be isolated from reference narration."""
    if template in NEXT_TEMPLATES:
        return next_sfx(template, params, frames)
    if template in LATE_TEMPLATES:
        return late_sfx(template, params, frames)
    p = motion_params(template, params, frames)
    if template == 'chapter_heading':
        phases = [('sfx/text3.mp3', p['underline_start'], p['underline_start']+p['underline_frames'], False)]
    elif template == 'date_countback':
        phases = ([('sfx/scrolling.mp3', p['count_start'], p['count_start']+p['count_frames'], True)]
                  if p.get('from_year', p['year']) != p['year'] else
                  [('sfx/text3.mp3', 0, p['arrival_frames'], False)])
    elif template == 'editorial_statement':
        phases = [('sfx/whoosh.mp3', 0, p['arrival_frames'], False),
                  ('sfx/marker_scribble.mp3', p['highlight_start'], p['highlight_start']+p['highlight_frames'], True)]
    else:
        phases = [('sfx/whoosh.mp3', p['arrival_start'], p['arrival_start']+p['arrival_frames'], False)]
    return [{'asset': asset, 'start_frame': start, 'end_frame': end, 'loop': loop}
            for asset, start, end, loop in phases]
