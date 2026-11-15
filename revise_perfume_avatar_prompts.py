"""Revision with the user's ava1–ava4 references; preserves shot timing and video assignments."""
import copy
import json
from pathlib import Path

from avatar_templates import ai_prompt_manifest
from presets import validate_scene, validate_tracks
from stock_downloader import validate_search_plan
from text_overlays import normalize_text_cues

SOURCE = Path('/Users/ilia/Downloads/avatar_perfume_2026-10-05')
TARGET = Path('/Users/ilia/Downloads/avatar_perfume_2026-10-05_ava_refs')
ROOT = Path(__file__).resolve().parent

# Keys are the existing prompt-list positions (1-based), NOT timeline shot indexes.
# Continuity groups deliberately keep one outfit reference across related images.
REFERENCE_SCENES = {
    1: ('ava1', 'At a contemporary perfume shop counter, ava1 examines a new clear rectangular perfume bottle with a silver cap. Her attentive eyes and relaxed posture convey a pleasant first impression. Medium three-quarter shot, bottle clearly visible. She is the customer, not a shop employee.'),
    4: ('ava2', 'At a home dining table, ava2 thoughtfully considers when she would wear a new perfume. A small clear perfume bottle and an open blank notebook lie in front of her. Seated medium shot with quiet space around her; she is thinking, not speaking to camera.'),
    5: ('ava1', 'At the same modern perfume shop setting, ava1 carefully examines a white paper fragrance strip before buying. Close three-quarter view of her eyes, hand and strip; the counter and clear perfume bottle are visible. Do not remove her face covering to show a sniffing pose.'),
    8: ('ava1', 'Ava1 holds a fragrance strip at the perfume shop counter. Her relaxed eyes and gentle posture convey that the first impression appeals to her, without an exaggerated smile. Medium close-up from a different angle, the strip and clear perfume bottle visible. Keep any face covering in place.'),
    9: ('ava1', 'Later at the same perfume counter, ava1 returns to the same white fragrance strip and clear rectangular bottle for a second assessment. Her eyes look thoughtful rather than excited. Side three-quarter medium shot. The same outfit, strip and bottle as her earlier shop scenes; no split-screen or clock.'),
    10: ('ava1', 'Close-up continuation of the previous shop scene: ava1 gently lowers the same fragrance strip after assessing it again. Her eyes and hand gesture suggest mild uncertainty, not disgust or illness. Same outfit, bottle and counter; keep any face covering exactly as in the reference.'),
    11: ('ava1', 'Ava1 returns to the same perfume testing counter after browsing the shop. One white fragrance strip waits beside the clear rectangular perfume bottle. Medium-wide view as her hand reaches toward the strip; shelves behind her, the outfit unchanged.'),
    20: ('ava3', 'At a contemporary kitchen table over coffee, a fictional female friend around sixty enthusiastically recommends one perfume to ava3. Ava3 is the attentive listener. Two distinct women, exactly one ava3. One unbranded bottle between them, natural conversational gestures; do not duplicate the presenter.'),
    22: ('ava3', 'Continuation of the coffee conversation: ava3 and the same fictional friend consider one perfume bottle with subtly different reactions. The friend is enthusiastic; ava3 is calmly thoughtful. Same clothing and kitchen setting, respectful difference of taste, no argument and no duplicated faces.'),
    23: ('ava3', 'Ava3 independently assesses a white fragrance strip at the same kitchen table. Her own hand and the strip are the main focus while her friend gestures softly out of focus behind. Medium close-up of attentive eyes and the strip; no uncovered features beneath her face covering.'),
    24: ('ava3', 'Ava3 asks the same fictional friend about the perfume she recommends, seated at their kitchen table. The friend explains with a small hand gesture; ava3 listens with interest. One unbranded bottle and two coffee cups. Maintain the same clothes, setting and two separate identities.'),
    27: ('ava3', 'At a modern perfume shop consultation, ava3 explains her preference by gesturing between her familiar small amber oval perfume bottle and a new clear rectangular sample bottle. A distinct fictional shop consultant listens across the counter. Medium shot with both bottles visible, natural conversational posture.'),
    35: ('ava4', 'At a perfume display with plain red shelf tags containing no writing, ava4 hesitates before choosing a bottle. Her hand pauses near a large clear perfume bottle; no purchase has been made. Medium three-quarter shot conveying an open decision rather than excitement about a sale.'),
    36: ('ava4', 'Continuation of the shop visit: ava4 thoughtfully compares a large clear rectangular perfume bottle with a smaller bottle of the same unbranded design. Both bottles are clearly visible on the counter. Medium shot, plenty of quiet space for an editor-added question; she has not reached for her wallet.'),
    37: ('ava4', 'At the same shop counter, ava4 selects the small clear perfume bottle first while the larger bottle of the same design remains behind. The hand choosing the small bottle is clearly visible. Same outfit and setting; no receipt, checkout claim, printed volume or generated prices.'),
    59: ('ava1', 'Ava1 explores one unfamiliar perfume sample at a modern perfume shop with open curiosity and no immediate decision to buy. Her familiar amber bottle remains partly visible in her open bag. Medium shot with the sample in her hand, natural attentive eyes, same reference outfit.'),
    63: ('ava1', 'Final reassessment at the perfume counter: ava1 checks the same white fragrance strip and clear rectangular bottle after waiting. Calm concentrated eyes, the same shop outfit and materials as her earlier tests. A medium close-up with space for an editor-added question; do not remove her face covering.'),
    65: ('ava1', 'Ava1 makes her own fragrance decision at the perfume counter. She studies the sample in her hand while plain red sale tags and other shoppers remain soft in the background. Her attention stays on her own assessment, not the crowd. Same reference outfit, no purchase shown, no generated lettering.'),
    67: ('ava2', 'At her home table, ava2 places a small clear perfume sample beside the everyday handbag she actually uses. Natural ordinary routine, medium view with hand, bottle and bag clearly visible. Same home outfit as her earlier thinking scene, no posed endorsement or speech to camera.'),
}

BASE = ('Photorealistic contemporary documentary still, horizontal 16:9. Soft natural light, realistic materials '
        'and anatomy, understated warm neutral surroundings, no luxury-advert glamour. ')
PRODUCTS = ('Only show the objects and counts requested in this scene. If a familiar bottle is requested, use a '
            'small amber oval bottle with dark cap; if a new clear bottle is requested, use a rectangular bottle '
            'with silver cap. Keep them unbranded and consistent; do not add extra bottles. ')
VIEWER = ('If a shopper appears, she is a fictional woman around 58 with a short salt-and-pepper bob, navy blouse '
          'and light beige cardigan, distinct from the presenter. ')
NEGATIVE = ('No readable text, lettering, prices, logos, watermark, collage or infographic. Exact German words '
            'and numbers are added separately by Remotion. No medical symptoms or exaggerated chemical effects.')

def stamp(seconds):
    millis = round(seconds * 1000)
    return f'{millis//60000:02d}:{(millis//1000)%60:02d}.{millis%1000:03d}'

def main():
    TARGET.mkdir(exist_ok=True)
    timeline = json.loads((SOURCE/'timeline.json').read_text())
    original = copy.deepcopy(timeline)
    old = json.loads((SOURCE/'google_flow_prompts.json').read_text())
    revisions = []
    for number, item in enumerate(old, 1):
        chunk = timeline['chunks'][item['chunk_id']]
        if number in REFERENCE_SCENES:
            reference, subject = REFERENCE_SCENES[number]
            identity = (f'Use the supplied image reference named {reference} as the presenter. Preserve her identity, '
                        'hairstyle, exact outfit, accessories and any face covering from that reference. Do not reveal '
                        'features hidden by the covering. Keep the referenced woman in the scene, not as an inset portrait. ')
            prompt = BASE + identity + subject + ' ' + PRODUCTS + NEGATIVE
            chunk['editor_note_ru'] = (f'ИИ-фото с ведущей по референсу {reference}. При генерации использовать именно '
                                      'этот референс; сохранить одежду и внешность. Статичное изображение, без lip-sync.')
            role = 'presenter_participates'
        else:
            reference = None
            subject = item['prompt'].split('Visible scene: ', 1)[1].split('. Compose one coherent scene', 1)[0].split('. The principal object', 1)[0]
            # Never clone the presenter into the background next to her live video panel.
            if number == 3:
                subject = ('A still life of an unused clear perfume bottle beside an everyday work handbag and a separate '
                           'evening clutch. The bottle and both bags are clearly readable in the center-right. No people.')
            if number == 18:
                subject = ('Close-up tabletop view of a white perfume strip beside a fictional shopper\'s relaxed wrist. '
                           'No face is shown. The two testing contexts remain visibly separate; no irritation or diagnosis.')
            # Preserve continuity of the ordinary shopper independently from presenter groups.
            if number == 21:
                subject = ('A fictional woman around 58 discovering an unfamiliar fragrance at a modern perfume shop '
                           'with a distinct consultant. Several bottles behind them; the customer remains the main subject.')
            framing = ('Keep the main object center-right and large enough to remain legible in the right 58-percent-width '
                       'panel; the presenter video will be placed on the left. Do not generate any presenter. '
                       if chunk.get('template') == 'avatar_left' else
                       'One coherent scene, clear principal subject and modest space for editor-added captions. ')
            # Generic portrait instructions are relevant only when someone is actually in the scene.
            human = any(token in subject.lower() for token in ('woman', 'women', 'shopper', 'friend', 'consultant'))
            prompt = BASE + subject.rstrip('.') + '. ' + (VIEWER if human else '') + PRODUCTS + framing + NEGATIVE
            role = 'illustration'
        chunk['ai_prompt'] = prompt
        revisions.append({'prompt_number':number, 'asset_id':item['asset_id'], 'chunk_id':item['chunk_id'],
                          'reference':reference, 'role':role})

    # Only prompt/editorial metadata changed. Voiceover, cuts, source type, effects and clips are unchanged.
    for before, after in zip(original['chunks'],timeline['chunks']):
        for key in set(before)|set(after):
            if key not in {'ai_prompt','editor_note_ru'}:
                assert before.get(key)==after.get(key),(before['id'],key)
    for key in original:
        if key!='chunks': assert original[key]==timeline[key]
    words=json.loads(Path('/Users/ilia/Downloads/avatar_input.json').read_text())['word_timestamps']
    duration=timeline['chunks'][-1]['end']
    for chunk in timeline['chunks']:
        validate_scene(chunk);validate_search_plan(chunk)
    validate_tracks(timeline,duration,timeline['chunks'])
    normalize_text_cues(timeline['text_cues'],duration,timeline['chunks'],words)

    manifest=ai_prompt_manifest(timeline['chunks'])
    lookup={r['chunk_id']:r for r in revisions}
    entries=[]
    for item in manifest:
        c=timeline['chunks'][item['chunk_id']]
        info=lookup[item['chunk_id']]
        item.update(prompt_number=info['prompt_number'],reference=info['reference'],semantic_role=info['role'],
                    chapter=c['chapter'],shot_number=c['id']+1,start=c['start'],end=c['end'])
        ref=info['reference'] or 'без референса аватара'
        # Plain numbered list requested by the user: metadata then the complete standalone prompt.
        entries.append(f'{info["prompt_number"]}. Кадр {c["id"]+1} | {stamp(c["start"])}–{stamp(c["end"])} | {item["asset_id"]} | {ref}\n'
                       f'Озвучка: {c["text"]}\nПромпт: {item["prompt"]}')
    plain='\n\n'.join(entries)+'\n'
    (TARGET/'prompts.txt').write_text(plain)
    (TARGET/'prompts.md').write_text(plain)
    (TARGET/'google_flow_prompts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (TARGET/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2)+'\n')
    report={'prompt_count':len(manifest),'presenter_in_ai_images':len(REFERENCE_SCENES),
            'without_presenter_reference':len(manifest)-len(REFERENCE_SCENES),
            'references':{name:[x['prompt_number'] for x in manifest if x['reference']==name] for name in ('ava1','ava2','ava3','ava4')},
            'live_avatar_video_timing_unchanged':True,'duration_seconds':duration,
            'presenter_still_seconds':sum(timeline['chunks'][x['chunk_id']]['end']-timeline['chunks'][x['chunk_id']]['start'] for x in manifest if x['reference']),
            'reference_images_received':False,
            'reference_rule':'ava1–ava4 are user-provided image reference names, not guarantees from text alone; use the matching image for generation. No clothing details are invented.',
            'side_panels_have_no_duplicate_presenter':all(x['reference'] is None for x in manifest if x['avatar_placement']),
            'validation':'scene/search/track/text validators passed; non-prompt timeline fields unchanged'}
    (TARGET/'prompt_revision_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    # Keep the current authoring artifacts synchronized; retain the previous delivery folder intact.
    working=ROOT/'output/scene_001/planning'
    for name in ('timeline.json','google_flow_prompts.json'):
        (working/name).write_bytes((TARGET/name).read_bytes())
    (working/'google_flow_prompts.md').write_text(plain)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('DELIVERY',TARGET)

if __name__=='__main__':
    main()
