"""Ordinary footage: scene sequences, shot intent and advisory rhythm checks."""
from collections import Counter
import json

ROLES = ('establishing','action','detail','reaction','consequence','contrast','bridge','breathing')
SCALES = ('wide','medium','close','detail','unknown')
PACES = ('calm','normal','urgent')
RELATIONS = ('new_scene','continue','cause_effect','contrast','association')
EDITING_RULES = (
    'Монтаж обычного видеоряда: сначала спланируй цель смысловой сцены, затем связанные кадры. '
    'Для обычных photo/video chunks без template задай scene_id и shot_plan из shot_editing_contract. '
    'Общий план устанавливает место; действие показывает глагол; деталь раскрывает механизм; '
    'последствие связывает процесс с результатом; breathing даёт спокойный понятный план после плотного объяснения. '
    'Не обязательно использовать каждую роль. Разные сцены могут иметь разное число кадров. '
    'Меняй крупность при появлении новой информации, а не ради механического чередования. '
    'Один scene_id объединяет одну цель; 2–4 связанных ракурса часто лучше нескольких случайных исходников. '
    'Для каждого кадра shot_plan.goal описывает его задачу, shot_plan.action — конкретно видимое действие. '
    'У shot_plan.relation:contrast/cause_effect/association обязательно link — что связывает его с предыдущим кадром. '
    'Сопоставление должно следовать смыслу речи: работающая инфраструктура → возможное разрушение, '
    'материал → обработка → деталь → применение. Не выдавай иллюстрацию или монтажную связь за доказанный факт. '
    'Плотность монтажа зависит от темпа мысли: urgent — короткая цепочка действий, normal — объяснение, '
    'calm — рассмотрение, вывод или передышка. Не режь через равные интервалы и не меняй word_timestamps ради темпа. '
    'Мотив вроде границы, инструмента или поезда можно возвращать при смысловом возврате; не повторяй случайный файл. '
    'Выбирай момент внутри видео, где действие видно. Контактный лист не доказывает точный match-on-action. '
    'У обычной сцены внутренние стыки по умолчанию cut. transitions:[] тоже означает cut. '
    'Crossfade выбирай явно для уместной смены времени/состояния; эффектный переход — для границы разделов. '
    'Квоты скачанных переходов нет. Достаточно обычных склеек, если они поддерживают рассказ. '
    'Для спокойного фото и читаемой детали допустим PHOTO_STATIC; PHOTO_SLOW_ZOOM_OUT раскрывает окружение, '
    'PHOTO_PAN ведёт вдоль протяжённого объекта. Не назначай приближение всем фотографиям. '
    'Провайдер Vision, озвучка и контракты motion templates сохраняются. '
)


def editing_payload():
    return {'shot_editing_contract':{'applies_to':'ordinary photo/video chunks without template',
        'shot_plan':{'role':list(ROLES),'scale':list(SCALES),'pace':list(PACES),
            'goal':'зачем нужен этот кадр','action':'что конкретно видно в действии',
            'relation':list(RELATIONS),'link':'смысл связи с предыдущим кадром (для contrast/cause_effect/association)',
            'motif':'необязательный опорный образ'},
        'example':{'scene_id':'production','shot_plan':{'role':'detail','scale':'detail','pace':'normal',
            'goal':'Показать, какой узел обеспечивает точность','action':'Руки устанавливают небольшую деталь в механизм',
            'relation':'continue','motif':'precision'}},
        'timing':'word_range / original word_timestamps; no automatic retiming',
        'transitions_default':'cut','transition_quota':None}}


def validate_shot_plan(scene):
    p=scene.get('shot_plan')
    if p is None:return
    if not isinstance(p,dict):raise ValueError('shot_plan: нужен объект')
    if scene.get('type') not in ('photo','video') or scene.get('template') or scene.get('music_insert'):
        raise ValueError('shot_plan относится только к обычному видеоряду без template/music_insert')
    scene_id=scene.get('scene_id')
    if type(scene_id) not in (str,int) or (isinstance(scene_id,str) and (not scene_id.strip() or len(scene_id)>80)):
        raise ValueError('shot_plan: нужен scene_id — строка до 80 символов или целое число')
    if set(p)-{'role','scale','pace','goal','action','relation','link','motif'}:
        raise ValueError('shot_plan: неизвестное поле')
    for key,allowed in [('role',ROLES),('scale',SCALES),('pace',PACES),('relation',RELATIONS)]:
        if p.get(key) not in allowed:raise ValueError(f'shot_plan.{key}: выбери {"/".join(allowed)}')
    for key in ('goal','action'):
        if not isinstance(p.get(key),str) or not p[key].strip() or len(p[key])>240:
            raise ValueError(f'shot_plan.{key}: непустая строка до 240 символов')
    for key in ('link','motif'):
        if key in p and (not isinstance(p[key],str) or not p[key].strip() or len(p[key])>240):
            raise ValueError(f'shot_plan.{key}: непустая строка до 240 символов')
    if p['relation'] in ('contrast','cause_effect','association') and not p.get('link'):
        raise ValueError('shot_plan.link: объясни связь с предыдущим кадром')


def retrieval_groups(chunks):
    """Only explicitly planned adjacent ordinary shots need sequential selection."""
    groups=[]
    for index,c in enumerate(chunks):
        p=c.get('shot_plan')
        if (groups and p and chunks[groups[-1][-1]].get('shot_plan')
                and c.get('scene_id')==chunks[groups[-1][-1]].get('scene_id')):
            groups[-1].append(index)
        else:groups.append([index])
    return groups


def shot_context(chunks,index):
    c=chunks[index]
    return {'current':c.get('shot_plan',{}),'scene_id':c.get('scene_id'),
        'previous':{k:chunks[index-1].get(k) for k in ('text','query','scene_id','shot_plan')} if index else None,
        'next':{k:chunks[index+1].get(k) for k in ('text','query','scene_id','shot_plan')} if index+1<len(chunks) else None}


def visual_context(plan):
    p=plan.get('shot_plan')
    if not p:return ''
    context={'shot_plan':p,'sequence':plan.get('_shot_context',{})}
    if plan.get('_previous_visual'):
        context['previous_selected_visual']=plan['_previous_visual'].get('description','')
    return ('\nEDITORIAL SHOT REQUIREMENTS: '+json.dumps(context,ensure_ascii=False)+
        '\nJudge the visible action and requested scale; topic similarity alone is insufficient. '
        'For continue prefer a compatible setting/action/view. For contrast or association judge the stated link, '
        'not whether the images show the same subject. Never infer an identity or historical cause from the edit.')


def apply_photo_intent(chunk):
    if chunk.get('shot_plan') and chunk.get('type')=='photo' and not chunk.get('template') and not chunk.get('preset'):
        p=chunk['shot_plan']
        preset='PHOTO_STATIC' if p['role'] in ('breathing','detail') else 'PHOTO_SLOW_ZOOM_OUT' if p['role']=='establishing' else 'PHOTO_SLOW_ZOOM'
        return {**chunk,'preset':preset}
    return chunk


def editing_summary(chunks,transitions=()):
    ordinary=[c for c in chunks if not c.get('template') and not c.get('music_insert')]
    planned=[c for c in ordinary if c.get('shot_plan')]
    warnings=[];last_scale=None;run=0
    for i,c in enumerate(chunks):
        p=c.get('shot_plan')
        if not p:last_scale=None;run=0;continue
        duration=float(c.get('end',0))-float(c.get('start',0))
        if (p['pace']=='urgent' and duration>8) or (p['pace']=='calm' and duration<2):
            warnings.append(f'Кадр {i+1}: проверь длительность {duration:.2f} с для темпа {p["pace"]}; речь не сдвигалась')
        if i and c.get('scene_id')!=chunks[i-1].get('scene_id'):last_scale=None;run=0
        scale=p['scale'];run=run+1 if scale==last_scale and scale!='unknown' else 1
        if run==3:warnings.append(f'Кадр {i+1}: три обычных плана крупности {scale}; проверь необходимость повтора')
        last_scale=scale
        if p['relation']=='continue' and (not i or c.get('scene_id')!=chunks[i-1].get('scene_id')):
            warnings.append(f'Кадр {i+1}: continue не продолжает предыдущий scene_id')
    return {'ordinary_shots':len(ordinary),'planned_shots':len(planned),
        'roles':dict(Counter(c['shot_plan']['role'] for c in planned)),
        'paces':dict(Counter(c['shot_plan']['pace'] for c in planned)),
        'sequences':[[i+1 for i in g] for g in retrieval_groups(chunks) if len(g)>1],
        'explicit_transitions':dict(Counter(t.get('kind','overlay') for t in transitions or [])),
        'default_transition':'cut','warnings':warnings,
        'scope':'Planning and selection checks; factual continuity still needs source verification.'}
