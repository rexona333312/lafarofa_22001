"""Authoring record for avatar_input.json; no search, generation or model calls."""
import copy
import hashlib
import json
from pathlib import Path

from avatar_templates import AVATAR_TEMPLATES, resolve_avatar_chunks, timeline_summary, ai_prompt_manifest, probe_video
from presets import validate_scene, validate_tracks
from stock_downloader import validate_search_plan
from text_overlays import normalize_text_cues
from narrative_templates import carousel_groups
from reference_templates import comparison_groups

ROOT = Path(__file__).resolve().parent
INPUT = Path('/Users/ilia/Downloads/avatar_input.json')
PROJECT = ROOT / 'output/scene_001'
OUT = PROJECT / 'planning'

# Explicit semantic cuts: exclusive WhisperX word endpoint | layout/source | visible subject.
# A = full presenter; I = generated still; V = real video; R = real photo;
# L = presenter left with generated still; S = presenter left with real photo.
SHOTS = '''
10|A|Opening direct address about buying a new perfume
16|I|A mature woman delighted by a new perfume bottle in a contemporary perfume shop
25|V|woman choosing familiar perfume bottle bathroom vanity
36|I|A new clear perfume bottle untouched beside a familiar amber bottle on a home vanity, the woman's hand reaching for the amber bottle
50|L|A mature woman considering an unused perfume bottle beside a work handbag and a separate evening clutch
57|R|perfume bottles fragrance selection shelf
70|V|woman shopping perfume store consultation
78|I|A mature woman sitting at a dining table thoughtfully considering when she would wear a fragrance, a small perfume bottle and blank notebook in front of her
86|V|woman writing fragrance notes notebook
97|A|Explain the personal criterion, not a universal fragrance rule
110|I|Close-up of a mature woman thoughtfully examining a perfume sample strip before buying, shop counter visible
119|R|perfume sampling blotter strips bottles
132|I|Three neatly spaced blank fragrance testing cards and one perfume bottle on a warm cream desk, simple open space above
138|A|The mistakes can happen at every age
155|V|mature women perfume shopping fragrance consultation
164|R|perfume bottle tester paper strip counter
176|V|perfume sprayed blotter strip woman smelling
183|I|A perfume bottle with fresh citrus peel, a few flowers and a soft pale fabric on a tabletop, restrained subjective associations rather than a scientific formula diagram
188|A|The immediate feeling: this is the one
199|I|A mature woman enjoying a fragrance test strip, natural relaxed expression and realistic shop setting
205|A|The pleasant first impression is not yet the purchase decision
213|V|perfume testing waiting blotter strip
224|I|The same mature woman revisiting a paper fragrance strip later at a shop counter, thoughtful expression, different camera angle
234|I|Close-up of a mature woman gently lowering a fragrance strip after a second smell, a subtle uncertain expression, no disgust or physical symptoms
242|A|Validate the viewer's own perception
248|R|perfume tester paper blotter close up
260|V|woman walking perfume shop browsing shelves
269|I|A mature woman returning to the same perfume testing counter after browsing other shelves, a single strip waiting beside a clear bottle
277|R|woman considering perfume test strip closeup
291|I|A restrained still life of one perfume tester, a paper strip, fresh citrus and a small sweet ingredient kept separate, illustration of subjective impressions
304|R|fragrance evaluation notes sample paper
315|A|If you can only say it smells good, wait
327|I|A perfume bottle still on the shop counter beside a paper strip, the shopper's open hand paused before choosing
331|A|The purchase comes later
341|R|paper perfume blotter strips tester bottle
344|V|perfume paper testing strips closeup
355|I|Several separated perfume strips on a clean counter with an unperfumed bare forearm resting away from them, no spraying on the arm
362|A|Paper strips are useful for preliminary selection
374|I|Ten blank perfume sample strips arranged on a tray, three brought slightly forward as a shortlist, clearly separated and countable
386|V|perfume sprayed paper strip testing closeup
393|S|perfume wrist testing small area
406|R|perfume paper blotter and wrist comparison
415|I|A mature woman comparing a fragrance strip with her own wrist, curious expression, no irritation or medical claim
424|A|Only if you tolerate perfume on the skin
432|V|perfume application instructions bottle label
450|V|perfume testing small wrist application woman
460|I|The mature woman checking a small fragrance test on her wrist later at home, daylight and calm reflection
471|I|A perfume strip beside the woman's resting wrist, she considers whether the impressions differ, no visual diagnosis
478|A|The strip helps with sorting
487|I|Two blank perfume blotters beside a handbag and one small test bottle, personal choice still open
499|V|woman testing perfume wearing fragrance daily
509|R|perfume recommendation consultation woman store
515|I|Two mature women talking about one perfume bottle over coffee, one enthusiastic and the other listening
520|R|perfume customer reviews smartphone hands
528|V|perfume shop assistant consultation customer
538|I|A mature woman discovering an unfamiliar fragrance at a shop with a consultant, friendly conversation and several bottles behind them
546|V|perfume shop consultation trying new fragrance
555|I|Two women considering the same perfume bottle with subtly different reactions, respectful disagreement, ordinary modern setting
560|R|perfume personal preferences sample selection
567|A|What matters is what you like wearing
578|V|perfume sample testing woman store
588|I|A mature woman assessing one perfume strip herself while a friend's hand gestures in the background, attention stays on her own reaction
598|R|perfume personal fragrance selection woman
601|A|Ask the person what they like about it
612|I|Two mature friends discussing the same perfume bottle at a kitchen table, the listener interested and attentive
622|V|women discussing perfume fragrance preferences
633|I|A perfume bottle beside a small dessert plate in a conversational setting, illustration of a subjective sweet association, not a claim about ingredients
640|I|A small perfume bottle beside an open holiday suitcase on a bright hotel table
647|V|mature woman office desk working
660|A|Clearly explain what you are looking for in a consultation
670|V|perfume shop consultation customer explaining preferences
677|I|The mature woman gesturing between a familiar amber bottle and a new clear sample while consulting a shop assistant
684|I|A consultant presenting one selected test strip after listening to the customer's preferences, other bottles remain in the background
695|A|Praise is a clue; the final choice stays with you
709|R|perfume bottle blotter consultation counter
717|R|perfume bottle paper strip decision shopper
725|I|A relaxed mature shopper looking at a few perfume samples without specialist books or charts, simple personal choice
736|L|A perfume sample on a desk beside an everyday handbag, the possible wearing occasion is the visual focus
749|I|Three separate tabletop areas with two bottle sizes, labelled-by-shape sample strips and an evening clutch, no generated writing or numbers
757|R|perfume bottle sizes shop shelf price tags
764|A|Introduce a hypothetical price example
775|I|Two clear rectangular unbranded perfume bottles of the same design family, one small 50 milliliter bottle and one larger 100 milliliter bottle, standing side by side in the left half of a cream tabletop, blank labels, generous uncluttered space on the right for an editor-added hypothetical price comparison
787|R|two perfume bottles different sizes tabletop
795|A|The large bottle is cheaper per milliliter
802|I|Two different sized perfume bottles beside a wallet and a receipt-shaped blank slip, comparison without generated prices
812|R|large small perfume bottles bathroom vanity
821|A|The calculation is correct, but it answers only one question
825|R|perfume price comparison bottles
830|A|What matters is what you actually need
847|I|A large mostly full perfume bottle standing unused at the back of a bathroom shelf while a smaller familiar bottle is near the front
857|I|A shopper hesitating in front of a perfume display with sale-colored blank shelf tags, she has not selected a bottle
866|V|woman smelling perfume sample before purchase
878|I|A mature woman considering a large perfume bottle beside a smaller bottle of the same unbranded family, composed space for a question
891|V|perfume bottle different sizes packaging comparison
903|I|The mature woman selecting the small sample-size perfume bottle at a shop counter, larger bottle remains behind
912|V|woman using small perfume bottle at home
919|R|small perfume bottle packaging closeup
935|L|A small fragrance bottle beside a closed wallet on a home table, limited purchase commitment rather than financial investment imagery
951|V|perfume bottle volume packaging label closeup
961|R|perfume bottles fragrance test strips
968|I|Four distinct blank perfume test strips laid separately across a clean shop counter, four unbranded bottles behind them
981|A|You remember that one was good, but which one?
995|I|Loose unlabelled fragrance strips partially visible inside an open handbag, no readable names, the ambiguity is clear
1001|A|Accuracy matters
1014|R|perfume eau de parfum eau de toilette bottle labels
1021|V|perfume bottle label product name version closeup
1029|I|A woman's hands holding a perfume bottle while noting its identity in a notebook, visible blank space where exact labels will be added in editing
1035|V|smartphone taking photo perfume bottle label
1042|V|writing pencil perfume blotter strip
1050|I|A close-up of a pencil touching the end of a fragrance strip beside several separated blank strips, no generated lettering
1059|I|A notebook with a few simple unlettered marks beside a scent strip, clear composition for editor-added short impressions
1069|R|perfume blotter notes citrus fragrance summer
1078|A|Notes are more useful than relying on memory
1085|V|woman comparing perfume test strips
1093|R|two perfume favorites sample bottles shortlist
1103|A|If you can barely distinguish them, stop comparing
1114|I|A mature woman taking a calm break outside the perfume shop with her testing materials put away
1128|I|A rested mature woman returning to a small orderly perfume selection on another occasion, no purchase pressure or checkout interaction
1134|R|perfume everyday evening occasion bottle
1143|I|An understated perfume bottle beside an everyday tote and a light cardigan on a bright morning table
1151|I|The same unbranded perfume design beside an evening clutch on a softly lit dressing table, contemporary adult setting
1163|A|One perfume does not have to serve every situation
1174|I|A mature shopper thoughtfully choosing between two unbranded perfume samples rather than an overwhelming shelf
1181|A|You decide what everyday means for you
1188|V|mature woman arriving office work handbag
1193|I|Two women around sixty taking a relaxed walk in a contemporary German city park, natural clothing and daylight
1198|I|A mature woman enjoying a quiet Sunday morning at home by a window, a perfume bottle on a side table
1213|A|No prescribed fragrance style for an age or occasion
1227|V|perfume consultation describing fragrance notes
1236|I|A restrained perfume still life with fresh citrus, flowers, soft fabric and warm wood textures separated around one bottle, subjective associations not an ingredient chart
1248|R|perfume fragrance notes paper blotter subjective impressions
1260|I|A mature woman comparing two perfume test strips beside a short blank note card, her preferences narrow the choice
1271|V|woman trying fragrance sample perfume store
1275|A|Introduce one simple question
1284|I|A perfume bottle beside an everyday handbag and a calendar-shaped blank card on a home table, a concrete first wearing occasion
1294|A|A situation coming to mind clarifies the occasion
1303|I|The mature woman considering a perfume bottle without reaching for her wallet, no urgency
1316|V|woman returning perfume tester shelf walking away
1328|A|Transition to the question behind all the others
1345|R|familiar perfume bottle new perfume samples
1357|A|What exactly should the new perfume do differently?
1374|R|perfume sample bottles different fragrances vanity
1386|R|three perfume candidate bottles unbranded
1400|R|favorite perfume bottle woman holding
1407|I|The familiar amber perfume bottle in fresh morning window light with a citrus peel nearby, a subjective freshness association
1414|I|The familiar amber bottle beside a personal photograph turned away from camera and a soft scarf, emotional memory without invented biography
1418|A|And what is missing?
1431|I|A woman calmly considering her familiar perfume bottle beside a light seasonal scarf, personal fit rather than a universal seasonal prescription
1445|V|woman explaining fragrance preferences perfume consultation
1451|I|A mature woman curiously exploring a new unbranded fragrance shelf while keeping her current bottle in her bag
1458|R|woman exploring new perfume tester bottle
1467|I|A woman examining one unfamiliar perfume sample with open curiosity and no immediate purchase decision
1472|A|You do not have to give anything up
1482|R|favorite perfume bottle new fragrance sample vanity
1495|R|single perfume bottle fragrance samples vanity
1499|R|everyday perfume bottle evening fragrance sample
1509|I|A familiar amber bottle beside a smaller evening fragrance sample and a simple evening clutch, both can coexist
1518|V|woman browsing perfume bottles store shelf
1528|I|An attractive sculptural perfume bottle foregrounded while a shopper hesitates behind it, appearance alone is not the decision
1537|A|Summarize the path to buying
1558|I|A familiar amber perfume bottle and one new clear sample on a cream table, negative space on the right for a three-question summary panel
1569|V|perfume blotter strips shortlist two three
1575|R|perfume sample strips notebook product names versions
1583|A|Repeat the skin-tolerance condition
1593|V|reading perfume application instructions testing small area
1602|V|woman returning fragrance test strip after waiting
1608|A|Now introduce the three final checks
1617|I|The mature woman checking the same fragrance strip again after a break, calm concentrated expression, wide space for a short question
1627|I|A perfume candidate beside an everyday bag and an evening clutch, intended occasion is the question rather than a rigid dress-code rule
1638|I|A woman assessing a perfume herself while blank sale tags and other shoppers remain soft in the background, independent decision
1648|A|Three honest yes answers make the purchase comfortable
1660|S|perfume tester blotter undecided woman
1667|I|A perfume tester returned carefully to its shelf, no rejected brand or product named
1677|V|woman selecting small perfume bottle sample store
1687|A|There is no need to hurry or become an expert
1699|I|The mature woman placing a fragrance sample next to the bag she actually uses, ordinary realistic daily routine
1706|A|Invite the viewer to answer
1713|I|A familiar amber perfume bottle in a woman's hand at her home vanity, personal everyday choice, space for a question
1725|A|Ask what she likes about it and invite comments
'''

CHAPTERS = [(0, 'einleitung'), (155, '7 · erster eindruck'), (331, '6 · papier und haut'),
            (499, '5 · fremde empfehlungen'), (695, 'zwischenfazit'), (749, '4 · preis und größe'),
            (951, '3 · namen und versionen'), (1128, '2 · trageanlass'),
            (1328, '1 · den eigenen wunsch klären'), (1528, 'zusammenfassung')]

STYLE = ('Photorealistic contemporary documentary editorial still photograph, horizontal 16:9, '
         'natural skin texture and realistic anatomy, understated warm cream, muted navy and charcoal palette, '
         'soft natural light, ordinary present-day German or European surroundings, no luxury-advert glamour. '
         'Where a recurring shopper appears, portray a fictional woman about 58 with a short salt-and-pepper bob, '
         'navy blouse and light beige cardigan; do not depict the masked presenter or a real celebrity. '
         'Recurring fictional bottles: familiar small amber oval bottle with dark cap; new clear rectangular bottle '
         'with silver cap, both unbranded. Keep physical proportions and packaging consistent between related images. ')

def build():
    OUT.mkdir(exist_ok=True)
    data = json.loads(INPUT.read_text())
    project = json.loads((PROJECT / 'project.json').read_text())
    local = json.loads((PROJECT / 'luna_input.json').read_text())
    words = data['word_timestamps']
    assert words == local['word_timestamps'], 'Selected project is not the supplied transcription'
    duration = data['audio_duration']
    library = project['avatar_library']
    assert duration == project['audio_duration']
    for clip in library:
        measured = probe_video(PROJECT / 'downloads' / clip['filename'])
        assert abs(measured['duration'] - clip['duration']) < .04
    by_label = {c['label']: c for c in library}
    # Genuine useful gestures; short thoughtful clip is reserved for shots which fit it.
    previous_clip, ordinal = None, 0
    chunks, first = [], 0
    sentence_ends = [i+1 for i,w in enumerate(words) if w['word'].endswith(('.', '?', '!'))]
    for row in SHOTS.strip().splitlines():
        last_s, kind, subject = row.split('|', 2)
        last = int(last_s)
        start = words[first]['start'] if first else 0
        end = words[last]['start'] if last < len(words) else duration
        assert last > first
        section = max(i for i,(a,_) in enumerate(CHAPTERS) if a <= first)
        scene_id = 1 + sum(a <= first for a in sentence_ends)
        chunk = dict(scene_id=scene_id, word_range=[first,last], start=start, end=end,
                     text=' '.join(w['word'] for w in words[first:last]),
                     type='video' if kind in ('A','V') else 'photo', query=subject,
                     visual_intent=subject, editor_note_ru='Современная иллюстрация конкретной фразы; проверить предмет и действие перед сборкой.',
                     media_origin='ai_image' if kind in ('I','L') else 'real',
                     search_mode='broll', entity='perfume', entity_type='object', match_policy='illustrative',
                     source_policy=['youtube','archive','licensed_stock'] if kind == 'V' else ['editorial','archive','licensed_stock'],
                     preset='PHOTO_STATIC' if kind in ('A','V') else 'PHOTO_SLOW_ZOOM',
                     params={'fit':'contain','zoom_start':0,'zoom_end':.035})
        chunk['chapter'] = CHAPTERS[section][1]
        if kind == 'V':
            chunk.update(search_queries=[subject], negative_keywords=['animation','cartoon','AI generated'],
                         visual_fallbacks=[dict(role='photo',type='photo',query=subject,search_mode='exact',
                                               entity='perfume',entity_type='object',
                                               source_policy=['editorial','archive','licensed_stock'])])
            chunk['editor_note_ru'] = 'Найти реальное действие из фразы. Исходный звук не использовать. При отсутствии видео — фото того же действия; проверить возраст героини и контекст.'
        elif kind in ('R','S'):
            chunk['search_queries'] = [subject]
            chunk['editor_note_ru'] = 'Реальная современная иллюстрация, не свидетельство конкретного случая. Без придуманного бренда; читаемые этикетки и фактический объём проверить на найденном материале.'
        if kind in ('I','L'):
            framing = ('The principal object and action must sit in the center-right of this photograph, '
                       'with a medium or close framing so they remain legible in a 58 percent screen-width panel. '
                       'Do not place a face, hand action or bottle against an edge. '
                       if kind == 'L' else
                       'Compose one coherent scene, with a clearly readable principal subject and modest negative space for editor-added captions. ')
            chunk['ai_prompt'] = STYLE + 'Visible scene: ' + subject + '. ' + framing + (
                'No readable text, letters, numbers, prices, brand logos, watermarks, infographic panels or collage. '
                'Exact German words and numerical values will be rendered separately in the editor. '
                'No mist clouds suggesting imaginary chemical processes, no rashes or medical before-and-after claims. '
                'This is a fictional illustration of the narration, not photographic evidence of a named event.')
            chunk['editor_note_ru'] = 'ИИ-иллюстрация бытовой ситуации. Сгенерировать по ai_prompt, затем загрузить в этот кадр. Надписи и цифры добавляет Remotion; не встраивать их в фото.'
        if kind in ('A','L','S'):
            seconds = end-start
            short_question = first in (1271,1414) and seconds <= 2.9
            candidates = ([by_label['avatar_thoughtful_tilt.mp4']] if short_question else
                          [by_label[label] for label in ('avatar_neutral.mp4','avatar_posture_shift.mp4','avatar_emphasis_nod.mp4')])
            clip = candidates[ordinal % len(candidates)]
            if clip['id'] == previous_clip and len(candidates)>1:
                clip = candidates[(ordinal+1)%len(candidates)]
            offset = min([.35,2.1,4.0,1.25][ordinal%4], max(0,clip['duration']-seconds-.1))
            if short_question:
                offset = 0
            chunk['avatar'] = {'clip_id':clip['id'],'source_start':round(offset,3)}
            chunk['template'] = 'avatar_full' if kind == 'A' else 'avatar_left'
            chunk['params'] = dict(avatar_width=.42,avatar_fit='cover',avatar_position=[.5,.45],
                                   media_fit='contain',media_position=[.5,.5],zoom_start=0,zoom_end=.035,arrival_frames=18)
            chunk['editor_note_ru'] = 'Ведущая на обращении, вопросе или выводе. Выбран конкретный клип и допустимое смещение. Исходный звук выключен; рот не синхронизировать.'
            if kind == 'A':
                chunk.update(query='ведущая',visual_intent=subject,preset='PHOTO_STATIC')
            previous_clip, ordinal = clip['id'], ordinal+1
        chunk['id'] = len(chunks)
        chunks.append(chunk)
        first = last
    assert first == len(words)

    def at(a):
        return next(c for c in chunks if c['word_range'][0] == a)
    def scene(a, name, **params):
        c = at(a); assert 'avatar' not in c
        c['template'] = name
        c['params'] = {**c['params'], 'paper':'paper/paper2.jpg', **params}
        return c
    def f(c, index):
        return round((words[index]['start']-c['start'])*30)

    # Seven actual countdown chapter headers. No historical dates or reference facts.
    for a, title in [(155,'7 · der erste eindruck'),(331,'6 · papier ist nur die vorauswahl'),
                     (499,'5 · empfehlungen und eigene vorlieben'),(749,'4 · rabatt und milliliterpreis'),
                     (951,'3 · namen und versionen auseinanderhalten'),(1128,'2 · den trageanlass klären'),
                     (1328,'1 · was gefällt dir — und was fehlt?')]:
        scene(a,'chapter_heading',text=title,arrival_frames=12,underline_start=9,underline_frames=15)

    scene(695,'bullet_panel',title='drei hinweise',style='classic',side='right',items=[
        {'text':'der erste moment','start_frame':f(at(695),701),'reveal_frames':15},
        {'text':'das papier','start_frame':f(at(695),705),'reveal_frames':15},
        {'text':'die meinung anderer','start_frame':f(at(695),707),'reveal_frames':15}])

    # Correct hypothetical arithmetic, figures appear at their spoken onsets.
    scene(764,'bullet_panel',title='beispiel: zwei angebote',style='classic',side='right',items=[
        {'text':'50 ml · 50 €','start_frame':f(at(764),767),'reveal_frames':12},
        {'text':'100 ml · 80 €','start_frame':f(at(764),773),'reveal_frames':12}])
    scene(775,'bullet_panel',title='preis pro milliliter',style='classic',side='right',items=[
        {'text':'50 ml: 1 € / ml','start_frame':f(at(775),779),'reveal_frames':12},
        {'text':'100 ml: 0,80 € / ml','start_frame':f(at(775),785),'reveal_frames':12}])
    # A list of genuine different wishes, not fabricated product recommendations.
    scene(1357,'bullet_panel',title='drei verschiedene wünsche',style='classic',side='right',items=[
        {'text':'eine neue duftrichtung ausprobieren','start_frame':f(at(1357),1360),'reveal_frames':12},
        {'text':'etwas für einen bestimmten anlass','start_frame':f(at(1357),1365),'reveal_frames':12},
        {'text':'den bisherigen duft ersetzen','start_frame':f(at(1357),1371),'reveal_frames':12}])
    # Repeated summary questions are explicitly spoken, not injected before the first reveal.
    scene(1537,'bullet_panel',title='zuerst: deinen wunsch klären',style='torn_sidebar',side='right',
          timing_mode='speech',items=[
              {'text':'was gefällt dir am bisherigen duft?','start_frame':f(at(1537),1542),'reveal_frames':18},
              {'text':'was fehlt?','start_frame':f(at(1537),1549),'reveal_frames':18},
              {'text':'wann möchtest du den neuen tragen?','start_frame':f(at(1537),1552),'reveal_frames':18}])

    cues=[]
    def cue(a, template, text=None, span=None, params=None):
        c=at(a); assert c.get('template') not in {'chapter_heading','bullet_panel','paired_evidence'}
        start=words[span[0]]['start'] if span else c['start']
        item={'id':f'T{len(cues)+1:03d}','kind':'accent','template':template,
              'chunk_index':chunks.index(c),'start':start,'end':c['end'],
              'text':text or ' '.join(w['word'] for w in words[span[0]:span[1]]),
              'params':{'font_size':62,'color':'#ffffff',**(params or {})}}
        if span: item['word_range']=span
        cues.append(item)
    cue(70,'question_panel_bottom','wann möchtest du deinen neuen duft tragen?')
    cue(199,'marker_highlight','als kaufentscheidung reicht es noch nicht.')
    cue(269,'question_panel_top','was gefällt mir jetzt noch daran?')
    cue(362,'marker_highlight','aus 10 düften werden 2 oder 3.')
    cue(415,'marker_highlight','wenn du parfum auf der haut verträgst')
    cue(560,'speech_words_overlay',span=[560,567])
    cue(795,'marker_highlight','insgesamt: 30 euro mehr')
    cue(857,'selective_marker','prüfe deshalb zuerst den duft und danach den preis.',
        params={'highlight_ranges':[[2,5],[6,9]]})
    cue(866,'question_panel_bottom','würde ich ihn auch ohne rabatt in dieser größe kaufen?')
    cue(995,'impact_typewriter',span=[999,1000])
    cue(1029,'marker_highlight','ein foto vom flakon geht auch.')
    cue(1059,'selective_marker','frisch · zu süß · erinnert mich an sommer',
        params={'highlight_ranges':[[0,1],[2,4],[5,9]]})
    cue(1085,'marker_highlight','zwei favoriten lassen sich leichter vergleichen als fünf.')
    cue(1275,'question_panel_bottom','wann würde ich diesen duft zum ersten mal tragen?')
    cue(1445,'speech_words_overlay',span=[1445,1451])
    cue(1472,'marker_highlight','dein bisheriger klassiker darf bleiben.')
    cue(1608,'question_panel_bottom','gefällt mir der duft auch beim späteren erneuten prüfen?')
    cue(1617,'question_panel_top','passt er zu dem anlass, für den ich ihn suche?')
    cue(1627,'question_panel_bottom','möchte ich ihn unabhängig von rabatt und fremdem lob wirklich tragen?')
    cue(1706,'question_panel_top','welchen duft trägst du am häufigsten?')

    transitions=[]
    chapter_starts={a for a,_ in CHAPTERS[1:]}
    for left,right in zip(chunks,chunks[1:]):
        boundary=left['end']
        paired=left.get('params',{}).get('comparison_group') == right.get('params',{}).get('comparison_group') and left.get('template')=='paired_evidence'
        if right['word_range'][0] in chapter_starts:
            transitions.append({'kind':'transition-fade','start':round(boundary-.3,6),'end':round(boundary+.3,6),
                                'params':{'variant':'editorial','dipTo':'#10131b'}})
        elif paired or 'avatar' in left or 'avatar' in right or left['type']=='video' or right['type']=='video':
            transitions.append({'kind':'cut','start':boundary,'end':boundary})
        else:
            transitions.append({'kind':'crossfade','start':round(boundary-.2,6),'end':round(boundary+.2,6),'strength':.55})
    timeline={'video_mode':'ai_avatar','main_entity':'perfume','main_entity_type':'object','scientific_name':'',
              'query_budget':6,'chunks':chunks,'transitions':transitions,'audio_tracks':[],'text_cues':cues}

    # The same validation paths used by the importer, without modifying the live project or searching.
    for i,c in enumerate(chunks):
        assert c['start'] == (chunks[i-1]['end'] if i else 0)
        assert c['end']-c['start'] >= 1/30
        validate_scene(c); validate_search_plan(c)
    validate_tracks(timeline,duration,chunks)
    comparison_groups(chunks); carousel_groups(chunks)
    normalize_text_cues(cues,duration,chunks,words)
    prepared=[]
    for i,c in enumerate(chunks):
        prepared.append({**copy.deepcopy(c),'duration':c['end']-c['start'],'_chunk_id':i,'_files':[]})
    resolve_avatar_chunks(prepared,{**project,'scene_dir':str(PROJECT)})
    assert chunks[-1]['end']==duration
    manifest=ai_prompt_manifest(chunks)
    summary=timeline_summary(chunks)
    all_backgrounds=[c for c in chunks if c.get('template')!='avatar_full']
    background_total=sum(c['end']-c['start'] for c in all_backgrounds)
    all_ai=sum(c['end']-c['start'] for c in all_backgrounds if c['media_origin']=='ai_image')
    summary.update(duration_seconds=duration,word_count=len(words),shot_count=len(chunks),
                   avatar_shot_count=sum('avatar' in c for c in chunks),
                   ai_image_count=len(manifest),text_cue_count=len(cues),
                   remotion_scene_count=sum(bool(c.get('template')) for c in chunks),
                   input_sha256=hashlib.sha256(INPUT.read_bytes()).hexdigest(),
                   project='scene_001',audio_tracks_added=0,
                   template_counts={name:sum(c.get('template')==name for c in chunks) for name in sorted({c.get('template') for c in chunks if c.get('template')})},
                   real_video_seconds=sum(c['end']-c['start'] for c in chunks if c['type']=='video' and 'avatar' not in c),
                   real_photo_seconds=sum(c['end']-c['start'] for c in chunks if c['type']=='photo' and c['media_origin']=='real'),
                   all_background_seconds=background_total,all_background_ai_seconds=all_ai,
                   all_background_ai_percent=100*all_ai/background_total,
                   all_background_real_percent=100*(background_total-all_ai)/background_total,
                   ratio_note='All-background percentages include photos beneath chapter_heading overlays; current UI summary excludes these chapter scenes.')
    for name,value in [('timeline.json',timeline),('google_flow_prompts.json',manifest),('timeline_report.json',summary)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    lines=['# Google Flow: фото для немецкого ролика о парфюме','',
           'Генерировать статичные изображения 16:9. Точные цифры и немецкие подписи добавляет Remotion. '
           'Сохраняй результат с именем asset_id; загружай в указанный кадр. Архив ZIP сейчас не распределяется автоматически.','']
    for item in manifest:
        c=chunks[item['chunk_id']]
        item['semantic_role']=('question' if '?' in c['text'] else 'spoken_list' if c.get('template')=='bullet_panel' else 'illustration')
        item['chapter']=c['chapter']
        lines += [f'## {item["asset_id"]} · кадр {item["chunk_id"]+1} · {c["start"]:.2f}–{c["end"]:.2f} с',
                  '',f'Озвучка: {c["text"]}','','```text',item['prompt'],'```','']
    (OUT/'google_flow_prompts.md').write_text('\n'.join(lines)+'\n')
    (OUT/'google_flow_prompts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    build()
