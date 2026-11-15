"""Reproducible 1080p examples using the user's reference stills and unmodified SFX."""
import json
import subprocess
from pathlib import Path
from PIL import Image
from config import OUTPUT_DIR
from ffmpeg_builder import build_video
from text_overlays import normalize_text_cues

ROOT = Path(__file__).resolve().parent
NAME = 'scene_editorial_templates'
REFS = Path('/var/folders/70/j_fcxpls5j9946v3r2plqhpm0000gn/T')


def crop_reference(name, box, destination, resize=None):
    if destination.exists():
        return
    with Image.open(REFS / name) as image:
        scale = image.width / 2048
        cropped = image.crop(tuple(round(v * scale) for v in box)).convert('RGB')
        if resize:
            cropped = cropped.resize(resize, Image.Resampling.LANCZOS)
        cropped.save(destination, quality=96)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    folder = Path(OUTPUT_DIR, NAME)
    downloads = folder / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    historical = downloads / 'historical_clean.jpg'
    coast = downloads / 'coast_clean.jpg'
    trap = downloads / 'fishing_trap.jpg'
    crop_reference('codex-clipboard-ca2890f8-e562-4ad2-a896-9a464ba7e158.png',
                   (174, 35, 890, 438), historical, (1920, 1080))
    crop_reference('codex-clipboard-8c552b8d-f3e5-41fe-bf5a-f340f6708d84.png',
                   (350, 89, 1125, 525), coast, (1920, 1080))
    crop_reference('codex-clipboard-4c0237b5-b365-4350-b0a2-d730f40e3b3d.png',
                   (675, 215, 1300, 557), trap)
    # Demo dates reproduce the user's layout reference; this does not claim a date of invention.
    chunks = []
    cursor = 0
    for i, (duration, picture) in enumerate(((5, historical), (4, coast), (4, coast), (7, trap))):
        chunk = {'id': i, '_chunk_id': i, 'type': 'photo', 'duration': duration, 'start': cursor,
                 'end': cursor + duration, 'query': ('historical man writing at desk' if i == 0 else 'coastal cliffs sea'),
                 'search_mode': 'broll', 'source_policy': ['archive', 'editorial'], 'preset': 'PHOTO_STATIC',
                 '_files': [str(picture)], 'files': [picture.name]}
        if i == 3:
            chunk.update(template='history_timeline', params={'year': 1918, 'from_year': 1913,
                         'label': 'fishing trap', 'paper': 'paper/paper1.jpg', 'scroll_frames': 72})
            chunk.update(query='traditional wicker fishing trap', entity='wicker fishing trap',
                         entity_type='object', search_mode='exact',
                         editor_note_ru='Демонстрация шкалы 1913 → 1918 по референсу; это не дата изобретения')
        chunks.append(chunk)
        cursor += duration
    raw = [
        {'id': 'T001', 'kind': 'accent', 'template': 'marker_highlight',
         'text': 'they wrote every detail down', 'start': .4, 'end': 4.6},
        {'id': 'T002', 'kind': 'accent', 'template': 'question_panel_bottom',
         'text': 'was the size really the point?', 'start': 5.3, 'end': 8.7},
        {'id': 'T003', 'kind': 'accent', 'template': 'question_panel_top',
         'text': 'the evidence changed everything', 'start': 9.3, 'end': 12.7},
    ]
    cues = normalize_text_cues(raw, cursor, chunks)
    transitions = [{'kind': 'cut', 'start': c['start'], 'end': c['start']} for c in chunks[1:]]
    voice = folder / 'voice.wav'
    if not voice.exists():
        run('ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
            '-t', str(cursor), str(voice))
    output, used = build_video(chunks, str(folder), NAME, audio_path=str(voice), audio_duration=cursor,
                              text_cues=cues, transitions=transitions, progress_callback=lambda msg: print(msg, flush=True))
    clean = [{k: v for k, v in c.items() if not k.startswith('_')} for c in chunks]
    timeline = {'chunks': clean, 'text_cues': cues, 'transitions': transitions, 'audio_tracks': []}
    (folder / 'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'examples/timeline_editorial_templates.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'sources.json').write_text(json.dumps({'visuals': 'User-uploaded reference stills; cropped for template previews only',
        'dates': '1913 → 1918: demonstration dates from reference; no invention claim',
        'marker_sfx': 'User-uploaded parched_drawing_schwiss_paper_blackboard_marker_stroke_scribble_long_irregular.mp3',
        'timeline_sfx': 'User-uploaded scrolling.MP3; originals copied unchanged, mixed at 30%'}, indent=2), encoding='utf-8')
    (folder / 'project.json').write_text(json.dumps({'scene_name': NAME, 'scene_dir': str(folder),
        'audio_path': str(voice), 'audio_duration': cursor, 'language': 'en', **timeline,
        'assets': {p.name: {'source': 'User reference', 'user_supplied': True} for p in (historical, coast, trap)},
        'file_overrides': {str(k): v for k, v in used.items()}, 'downloads_complete': True,
        'processing_mode': 'fast'}, ensure_ascii=False, indent=2), encoding='utf-8')
    streams = json.loads(run('ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_type,width,height,avg_frame_rate,nb_frames,duration', '-of', 'json', output).stdout)['streams']
    video = next(s for s in streams if s['codec_type'] == 'video')
    assert (video['width'], video['height'], video['avg_frame_rate'], int(video['nb_frames'])) == (1920, 1080, '30/1', 600)
    assert any(s['codec_type'] == 'audio' for s in streams)
    sheet = Image.new('RGB', (1920, 1080))
    for i, (name, start, duration, still) in enumerate((('marker', 0, 5, 2), ('panel_bottom', 5, 4, 7),
                                                     ('panel_top', 9, 4, 11), ('timeline', 13, 7, 17))):
        run('ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-i', output, '-t', str(duration),
            '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-c:a', 'aac', '-movflags', '+faststart', str(folder / f'{name}.mp4'))
        jpg = folder / f'{name}.jpg'
        run('ffmpeg', '-v', 'error', '-y', '-ss', str(still), '-i', output, '-frames:v', '1', str(jpg))
        with Image.open(jpg) as image:
            sheet.paste(image.resize((960, 540)), ((i % 2) * 960, (i // 2) * 540))
    sheet.save(folder / 'four_templates.jpg', quality=95)
    print(f'READY: {output}', flush=True)


if __name__ == '__main__':
    main()
