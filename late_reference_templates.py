"""Reusable motions from 164, 171, 185 and 190; media always comes from the scene."""
from next_reference_templates import text, point

LATE_TEMPLATES = {name: name for name in (
    'detail_callouts', 'text_highlight_split', 'split_verdict', 'lower_third_contrast')}


def late_motion_params(template, params, frames):
    if type(frames) is not int or frames < 30:
        raise ValueError(f'{template}: сцена не короче секунды')
    p = dict(params)
    scale = min(1, frames / {'detail_callouts':109, 'text_highlight_split':142,
                            'split_verdict':215, 'lower_third_contrast':150}[template])

    def window(start, duration, a, b):
        x, y = params.get(start, round(a*scale)), params.get(duration, max(1,round(b*scale)))
        if type(x) is not int or type(y) is not int or x < 0 or y < 1 or x+y >= frames:
            raise ValueError(f'{template}: {start}/{duration} должны помещаться до стыка')
        p[start], p[duration] = x, y

    if type(params.get('archival',False)) is not bool:
        raise ValueError(f'{template}: archival true/false')
    if template == 'text_highlight_split':
        text(params.get('text'), 'text_highlight_split.text', 100)
        if 'caption' in params: text(params['caption'], 'text_highlight_split.caption', 65)
        window('text_start','arrival_frames',0,12)
        window('highlight_start','highlight_frames',36,20)
        window('split_start','split_frames',58,60)
        window('caption_start','caption_frames',116,12)
        if p['highlight_start'] < p['text_start']+p['arrival_frames'] or p['split_start'] < p['highlight_start']+p['highlight_frames']:
            raise ValueError('text_highlight_split: фраза → маркер → разделение кадра')
    elif template == 'split_verdict':
        window('left_start','left_frames',0,34)
        window('split_start','split_frames',0,34)
        window('right_start','right_frames',87,30)
        window('left_label_start','label_frames',24,12)
        window('right_label_start','right_label_frames',102,12)
        if p['left_start'] > p['split_start'] or p['right_start'] < p['split_start']+p['split_frames']:
            raise ValueError('split_verdict: первая версия → разделение → вторая версия')
    elif template == 'detail_callouts':
        window('media_start','arrival_frames',0,18)
        rows = params.get('annotations')
        if not isinstance(rows,list) or not 2 <= len(rows) <= 5:
            raise ValueError('detail_callouts: 2–5 annotations')
        p['annotations'] = []
        for row in rows:
            if not isinstance(row,dict): raise ValueError('detail_callouts: аннотация — объект')
            text(row.get('label'),'detail_callouts.label',65)
            start, draw = row.get('start_frame'), row.get('draw_frames',12)
            if type(start) is not int or type(draw) is not int or start < p['media_start'] or draw < 1 or start+draw >= frames:
                raise ValueError('detail_callouts: нужны реальные start_frame и draw_frames до стыка')
            anchor=point(row.get('anchor'),'detail_callouts.anchor')
            tag=point(row.get('label_point'),'detail_callouts.label_point')
            p['annotations'].append({**row,'anchor':anchor,'label_point':[min(.84,max(.16,tag[0])),min(.9,max(.1,tag[1]))],
                                     'start_frame':start,'draw_frames':draw})
    else:
        text(params.get('heading'),'lower_third_contrast.heading',80)
        window('heading_start','arrival_frames',12,18)
        rows=params.get('segments')
        if not isinstance(rows,list) or not 2 <= len(rows) <= 5:
            raise ValueError('lower_third_contrast: 2–5 segments')
        p['segments']=[]
        previous=p['heading_start']
        for row in rows:
            if not isinstance(row,dict): raise ValueError('lower_third_contrast: сегмент — объект')
            text(row.get('text'),'lower_third_contrast.text',70)
            start,duration=row.get('start_frame'),row.get('reveal_frames',18)
            if type(start) is not int or type(duration) is not int or start < previous or duration < 1 or start+duration >= frames:
                raise ValueError('lower_third_contrast: последовательные тайминги segments до стыка')
            if type(row.get('highlight',False)) is not bool: raise ValueError('lower_third_contrast: highlight true/false')
            p['segments'].append({**row,'start_frame':start,'reveal_frames':duration})
            previous=start
        if sum(len(row['text']) for row in rows) > 140:
            raise ValueError('lower_third_contrast: нижняя строка до 140 символов')
        if params.get('side','left') not in ('left','right'): raise ValueError('lower_third_contrast: side left/right')
    return p


def validate_late_scene(scene):
    if scene.get('type') not in ('photo','video'):
        raise ValueError(f"{scene['template']}: нужна фотография или видео")
    if scene['template']=='split_verdict':
        if scene['type']!='photo': raise ValueError('split_verdict: два photo chunks')
        text(scene.get('params',{}).get('label'),'split_verdict.label',65)
        text(scene.get('params',{}).get('comparison_group'),'split_verdict.comparison_group',50)
        return  # Whole-group timings are validated by comparison_groups.
    frames=round(float(scene.get('end',scene.get('duration',5)))*30)-round(float(scene.get('start',0))*30)
    late_motion_params(scene['template'],scene.get('params',{}),frames)


def late_sfx(template,params,frames):
    p=late_motion_params(template,params,frames)
    if template=='text_highlight_split':
        cues=[('sfx/marker_scribble.mp3',p['highlight_start'],p['highlight_start']+p['highlight_frames'],True),
              ('sfx/whoosh.mp3',p['split_start'],p['split_start']+p['split_frames'],False)]
    elif template=='split_verdict':
        cues=[('sfx/whoosh.mp3',p['left_start'],p['left_start']+p['left_frames'],False),
              ('sfx/whoosh.mp3',p['right_start'],p['right_start']+p['right_frames'],False)]
    elif template=='detail_callouts':
        cues=[('sfx/text3.mp3',a['start_frame'],a['start_frame']+a['draw_frames'],False) for a in p['annotations']]
    else:
        cues=[('sfx/marker_scribble.mp3',a['start_frame'],a['start_frame']+a['reveal_frames'],True) for a in p['segments'] if a.get('highlight')]
    return [{'asset':asset,'start_frame':start,'end_frame':end,'loop':loop} for asset,start,end,loop in cues]
