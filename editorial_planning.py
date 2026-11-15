"""Reference-backed planning policy and time-based, overlap-free graphics accounting."""
import math

PLANNER_RULES = (
    'Новый разбор swiss_1019: графика занимает примерно 69.9% времени этого референса, включая фото-карточки и подписи. '
    'Это ориентир, не требование для каждого текста; целевую долю смотри в editorial_policy.motion_graphics_target. '
    'Доля фото/видео и доля графики — разные метрики. Обычный pan/zoom, виньетка и переходы не входят в графику. '
    'Смысл → видимый материал → приём → события по речи. Перечисление независимых объектов: evidence_board, '
    'последовательная смена одного объекта: photo_carousel; не смешивай эти задачи. '
    'Сравнимые числовые величины в одной единице: data_comparison; один факт: stat_callout; '
    'человек с пояснением без вырезания фона: portrait_profile; читаемая деталь найденного документа: document_focus. '
    'Пространство, окружение, сеть или маршрут: map_geographic. map_annotations с params.geo '
    'тоже использует новый географический рендер. Старые карты-картинки отключены. '
    'У map_geographic type:photo, query:название территории, params.geo; фотографию карты искать не нужно. '
    'data_comparison тоже строится из данных items, без поиска фоновой фотографии. '
    'Не выдавай современные контуры за исторические. Не показывай даты/значения раньше соответствующих слов. '
    'Все *_frame — ЛОКАЛЬНЫЕ кадры при 30 fps, вычисленные по word_timestamps относительно начала chunk. '
    'У evidence_board params.caption до 60 символов; появление следующей карточки совпадает с началом следующего chunk; '
    'предыдущие карточки остаются видимыми. Сохраняй одну группу на всё перечисление. '
    'Схожий текстовый акцент поверх соседних кадров продолжай одним text_cue через стык. '
    'Чередуй объясняющую графику с обычным действием/архивом; не назначай одинаковый шаблон трём сценам подряд. '
    'Никаких случайных декоративных графиков: подписи, числа, единицы и цитаты только из сценария; '
    'focus_rect отмечает действительно видимый фрагмент документа, а не придуманную цитату. '
    'Параметры новых шаблонов и примеры смотри в documentary_template_contracts. '
)

CONTRACTS = {
    'evidence_board': {'role':'перечисление, накопление аргументов; 2–5 соседних photo chunks',
        'params':{'carousel_group':'unique-list','caption':'подпись именно этой фотографии','archival':False},
        'reference_clips':[3,19,136,180,266]},
    'stat_callout': {'role':'один числовой факт; photo card или video/photo overlay',
        'params':{'value':'430,000','label':'MEN UNDER ARMS','layout':'card','start_frame':30,'arrival_frames':18},
        'reference_clips':[8,37,100,117]},
    'data_comparison': {'role':'2–5 сравнимых величин; photo chunk, единая числовая шкала',
        'params':{'title':'MEN UNDER ARMS VS. POPULATION','unit':'people','items':[
            {'label':'MEN UNDER ARMS','value':430000,'display':'430,000','start_frame':20},
            {'label':'POPULATION','value':4000000,'display':'4 million','start_frame':70}]},
        'reference_clips':[46,76,83,121,131,153,161]},
    'document_focus': {'role':'общий вид документа → приближение → выделение; photo',
        'params':{'focus_rect':[.15,.35,.7,.1],'zoom_start_frame':30,'highlight_start_frame':65,
                  'mark':'highlight','caption':'точная короткая подпись'},'reference_clips':[102,216,240]},
    'portrait_profile': {'role':'портрет в рамке + имя + пояснение; photo без вырезания фона',
        'params':{'name':'Thomas Mann','description':'пояснение из сценария','start_frame':0},'reference_clips':[31,52,75,114]},
    'map_geographic': {'role':'реальные территории, точки и маршруты; type:photo, без стокового поиска',
        'params':{'geo':{'mode':'terrain','title':'Switzerland','camera':[
            {'frame':0,'center':[8.2,46.8],'zoom':6,'pitch':35,'bearing':-8},
            {'frame':179,'center':[8.2,46.8],'zoom':7,'pitch':55,'bearing':5}],
            'highlights':[{'country':'CHE','start_frame':20,'color':'#e5c65f'}],
            'markers':[{'position':[7.4474,46.948],'label':'Bern','start_frame':55}],
            'routes':[{'points':[[7.4474,46.948],[8.5417,47.3769]],'label':'Zurich','start_frame':85}],
            'regions':[]}},
        'reference_clips':[7,26,33,61,106,126,157,211,284]},
}


def graphics_target(value=70):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:
        raise ValueError('motion_graphics_target: число 0–100')
    return float(value)


def planning_payload(session):
    return {'editorial_policy':{'motion_graphics_target':graphics_target(session.get('motion_graphics_target',70)),
            'reference_motion_percent':69.9,'measurement':'duration_union_including_cards_and_overlays',
            'target_is_guidance':True,'reference':'reference_analysis/swiss_1019_20261019/index.html'},
            'documentary_template_contracts':CONTRACTS}


def _union(windows):
    result=[]
    for start,end in sorted(windows):
        if end<=start:continue
        if result and start<=result[-1][1]:result[-1][1]=max(end,result[-1][1])
        else:result.append([start,end])
    return result


def graphics_summary(chunks,text_cues=(),target=70):
    total=max((c['end'] for c in chunks),default=0)
    windows=[];families={};warnings=[];last=None;last_scene=None;run=0
    for index,c in enumerate(chunks):
        name=c.get('template');start,end=c['start'],c['end'];p=c.get('params',{})
        if name and not name.startswith('avatar_'):
            if name=='stat_callout' and p.get('layout')=='overlay':start+=p.get('start_frame',0)/30
            elif name=='corner_section':start+=min((r.get('start_frame',0) for r in p.get('lines',[])),default=0)/30
            windows.append([start,end]);families.setdefault(name,[]).append([start,end])
        scene=c.get('scene_id',index)
        changed=scene!=last_scene
        if changed:run=run+1 if name and name==last else 1
        if changed and run==3 and name not in ('evidence_board',) and not name.startswith('photo_carousel_'):
            warnings.append(f'Три кадра подряд с {name}: проверь повтор и смысловую непрерывность')
        last=name;last_scene=scene
    for cue in text_cues or []:
        if 'start' in cue and 'end' in cue:
            windows.append([max(0,cue['start']),min(total,cue['end'])])
    merged=_union(windows);seconds=sum(b-a for a,b in merged)
    return {'total_seconds':total,'graphics_seconds':seconds,'graphics_percent':round(seconds/total*100,2) if total else 0,
            'target_percent':graphics_target(target),'families_seconds':{k:round(sum(b-a for a,b in _union(v)),3) for k,v in families.items()},
            'warnings':warnings,'includes':'карточки, карты, диаграммы, текстовые наложения; без двойного счёта',
            'excludes':'обычный pan/zoom, аватары, виньетка, переходы'}
