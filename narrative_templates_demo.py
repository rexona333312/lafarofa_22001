"""Render all new templates through the production pipeline, with local aligned narration."""
import json
import shutil
import subprocess
import wave
from pathlib import Path

import requests
from PIL import Image, ImageDraw
from config import OUTPUT_DIR, WHISPERX_PYTHON
from ffmpeg_builder import build_video
from text_overlays import normalize_text_cues
from whisperx_transcriber import _aligned_words

ROOT = Path(__file__).resolve().parent
NAME = 'scene_narrative_templates'
REFS = Path('/var/folders/70/j_fcxpls5j9946v3r2plqhpm0000gn/T')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def commons_photo(filename, destination):
    url = 'https://commons.wikimedia.org/w/api.php'
    response = requests.get(url, params={'action': 'query', 'format': 'json', 'titles': 'File:'+filename,
        'prop': 'imageinfo', 'iiprop': 'url|extmetadata'}, headers={'User-Agent': 'VideoAssembler/1.0 (template previews)'}, timeout=30)
    response.raise_for_status()
    info = next(iter(response.json()['query']['pages'].values()))['imageinfo'][0]
    meta = info.get('extmetadata', {})
    if not destination.exists():
        response = requests.get(info['url'], headers={'User-Agent': 'VideoAssembler/1.0'}, timeout=60)
        response.raise_for_status()
        destination.write_bytes(response.content)
        with Image.open(destination) as image:
            image.verify()
    return {'url': info['descriptionurl'], 'download_url': info['url'],
            'author': meta.get('Artist', {}).get('value', ''), 'license': meta.get('LicenseShortName', {}).get('value', ''),
            'license_url': meta.get('LicenseUrl', {}).get('value', '')}


def crop_reference(name, box, output):
    if output.exists():
        return
    with Image.open(REFS/name) as image:
        scale = image.width/2048
        image.crop(tuple(round(v*scale) for v in box)).convert('RGB').save(output, quality=95)


def schematic_map(output):
    if output.exists():
        return
    image = Image.new('RGB', (1920, 1080), '#657376')
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 0), (1160, 0), (1080, 100), (1140, 235), (960, 370), (1030, 440),
                  (930, 590), (1020, 740), (850, 820), (950, 1080), (0, 1080)], fill='#bcc5bf')
    draw.polygon([(560, 240), (730, 200), (790, 320), (730, 420), (580, 390)], fill='#687777')
    draw.polygon([(380, 520), (520, 455), (630, 610), (500, 755), (350, 650)], fill='#687777')
    for offset in range(8):
        draw.line([(100+offset*180, 0), (160+offset*160, 250), (120+offset*170, 500),
                   (220+offset*150, 800), (180+offset*140, 1080)], fill='#d7ded7', width=2)
    for y in range(140, 1080, 190):
        draw.line([(0, y), (600, y+70), (1050, y-30)], fill='#d7ded7', width=2)
    image.save(output)


def main():
    folder = Path(OUTPUT_DIR, NAME)
    downloads = folder/'downloads'; downloads.mkdir(parents=True, exist_ok=True)
    sources = {}
    for filename, local in [('Silicon wafer.jpg', 'wafer.jpg'), ('Silicon wafers.jpg', 'products.jpg'),
                            ('Circuit board Closeup (24884297257).jpg', 'circuit.jpg'),
                            ('Exterior of the United States Capitol - 1.JPG', 'capitol.jpg')]:
        sources[local] = commons_photo(filename, downloads/local)
        print('Media ready:', local, flush=True)
    shutil.copyfile(ROOT/'output/scene_person_intro_trump/downloads/trump.png', downloads/'trump.png')
    shutil.copyfile(ROOT/'assets/backgrounds/white_house.jpg', downloads/'white_house.jpg')
    sources['trump.png'] = {'url': 'https://commons.wikimedia.org/wiki/File:President-Donald-Trump-Official-Presidential-Portrait.png',
                            'author': 'Daniel Torok / White House', 'license': 'Public domain'}
    sources['white_house.jpg'] = {'url': 'https://commons.wikimedia.org/wiki/File:The_White_House_South_Portico.jpg',
        'author': 'Trendscope / Simon Gagner', 'license': 'CC BY 4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/'}
    for name, box, local in [
        ('codex-clipboard-ab1c8ed5-7e2a-4c08-9da5-9f3b2b1143e5.png', (390, 448, 1650, 900), 'history1.jpg'),
        ('codex-clipboard-1695fed4-42ef-4ebd-b25c-f31b3ea42c63.png', (850, 180, 2000, 995), 'history2.jpg'),
        ('codex-clipboard-9a794680-3cf8-47a2-ae52-000e046c28d6.png', (185, 155, 1880, 1025), 'history3.jpg')]:
        crop_reference(name, box, downloads/local)
        sources[local] = {'source': 'User-provided reference photograph; cropped for preview'}
    schematic_map(downloads/'schematic_map.png')
    sources['schematic_map.png'] = {'source': 'Original illustrative diagram; not an actual geographical boundary'}
    chunks, raw_cues, segments, previews = [], [], [], []
    cursor = 0

    def add(picture, duration, narration, template=None, params=None, cue_template=None, cue_params=None):
        nonlocal cursor
        index = len(chunks)
        chunk = {'id': index, '_chunk_id': index, 'type': 'photo', 'query': picture.replace('_', ' '),
                 'search_mode': 'broll', 'source_policy': ['archive', 'editorial'], 'preset': 'PHOTO_STATIC',
                 'start': cursor, 'end': cursor+duration, 'duration': duration, 'files': [picture],
                 '_files': [str(downloads/picture)]}
        if template:
            chunk.update(template=template, params=params or {})
        credit = {'circuit.jpg': 'Photo: Jonathan Cutrer · CC BY 2.0',
                  'white_house.jpg': 'Photo: Trendscope / Simon Gagner · CC BY 4.0'}.get(picture)
        if credit:
            chunk['credits'] = {picture: credit}
        chunks.append(chunk)
        if cue_template:
            raw_cues.append({'id': f'T{len(raw_cues)+1:03d}', 'kind': 'accent', 'template': cue_template,
                             'text': narration, 'chunk_index': index, 'params': cue_params or {}})
        aiff, wav = folder/f'voice{index}.aiff', folder/f'voice{index}.wav'
        if not wav.exists():
            run('say', '-v', 'Samantha', '-r', '175', '-o', str(aiff), narration)
            run('ffmpeg', '-v', 'error', '-y', '-i', str(aiff), '-af', 'adelay=400|400,apad',
                '-t', str(duration), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(wav))
        segments.append({'start': cursor+.35, 'end': cursor+duration, 'text': narration})
        cursor += duration

    add('wafer.jpg', 5, 'new technology', cue_template='impact_typewriter')
    previews.append(('impact', 0, cursor))
    start = cursor
    add('history3.jpg', 5, 'as if something beneath it was displacing it', cue_template='speech_words_grid')
    previews.append(('words_grid', start, cursor-start))
    start = cursor
    add('capitol.jpg', 5, 'the decision changes what happens next', cue_template='speech_words_overlay')
    previews.append(('words_overlay', start, cursor-start))
    start = cursor
    add('circuit.jpg', 6, 'more power, smaller chips, and faster connections', cue_template='selective_marker',
        cue_params={'highlight_ranges': [[0, 2], [2, 4], [5, 7]]})
    previews.append(('selective_marker', start, cursor-start))
    for style, pictures, texts, archival in [
        ('paper', ['history1.jpg', 'history2.jpg', 'history3.jpg'], ['prepare the traps', 'handle the lines', 'lower the traps'], True),
        ('editorial', ['capitol.jpg', 'trump.png', 'white_house.jpg'], ['the legislature', 'the president', 'the administration'], False),
        ('dark', ['wafer.jpg', 'circuit.jpg', 'products.jpg'], ['the silicon wafer', 'the circuit board', 'the electronic components'], False),
        ('film', ['history1.jpg', 'history2.jpg', 'history3.jpg'], ['prepare the traps', 'handle the lines', 'lower the traps'], True)]:
        start = cursor
        for picture, text in zip(pictures, texts):
            add(picture, 2.5, text, template=f'photo_carousel_{style}', params={'carousel_group': style,
                'archival': archival, 'caption': text, 'paper': 'paper/paper1.jpg'})
        previews.append((f'carousel_{style}', start, cursor-start))
    voice = folder/'voice.wav'
    with wave.open(str(voice), 'wb') as output:
        output.setnchannels(2); output.setsampwidth(2); output.setframerate(48000)
        for index in range(len(chunks)):
            with wave.open(str(folder/f'voice{index}.wav'), 'rb') as audio:
                output.writeframes(audio.readframes(audio.getnframes()))
    (folder/'alignment_segments.json').write_text(json.dumps(segments), encoding='utf-8')
    aligned = folder/'aligned_words.json'
    if not aligned.exists():
        print('Aligning local demo narration with WhisperX…', flush=True)
        raw_alignment = folder/'whisperx_alignment.json'
        subprocess.run([WHISPERX_PYTHON, '-u', str(ROOT/'narrative_demo_align.py'), str(voice),
                        str(folder/'alignment_segments.json'), str(raw_alignment)], check=True)
        aligned.write_text(json.dumps(_aligned_words(json.loads(raw_alignment.read_text())), ensure_ascii=False, indent=2), encoding='utf-8')
    words = json.loads(aligned.read_text())
    cues = normalize_text_cues(raw_cues, cursor, chunks, words)
    transitions = [{'kind': 'cut', 'start': c['start'], 'end': c['start']} for c in chunks[1:]]
    output, used = build_video(chunks, str(folder), NAME, audio_path=str(voice), audio_duration=cursor,
        text_cues=cues, transitions=transitions, progress_callback=lambda msg: print(msg, flush=True))
    clean = [{k: v for k, v in c.items() if not k.startswith('_')} for c in chunks]
    timeline = {'chunks': clean, 'text_cues': cues, 'transitions': transitions, 'audio_tracks': []}
    (folder/'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT/'examples/timeline_narrative_templates.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder/'luna_input.json').write_text(json.dumps({'audio_duration': cursor, 'word_timestamps': words,
        'full_text': ' '.join(s['text'] for s in segments)}, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder/'sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder/'project.json').write_text(json.dumps({'scene_name': NAME, 'scene_dir': str(folder), 'audio_path': str(voice),
        'audio_duration': cursor, 'language': 'en', **timeline, 'assets': {name: {**meta, 'user_supplied': True} for name, meta in sources.items()},
        'file_overrides': {str(k): v for k, v in used.items()}, 'downloads_complete': True, 'processing_mode': 'fast'}, ensure_ascii=False, indent=2), encoding='utf-8')
    video = next(s for s in json.loads(run('ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_type,width,height,avg_frame_rate,nb_frames', '-of', 'json', output).stdout)['streams'] if s['codec_type']=='video')
    assert (video['width'], video['height'], video['avg_frame_rate'], int(video['nb_frames'])) == (1920, 1080, '30/1', round(cursor*30))
    sheet = Image.new('RGB', (1920, 1080))
    for i, (name, begin, duration) in enumerate(previews):
        run('ffmpeg', '-v', 'error', '-y', '-ss', str(begin), '-i', output, '-t', str(duration),
            '-c:v', 'libx264', '-crf', '18', '-preset', 'veryfast', '-c:a', 'aac', '-movflags', '+faststart', str(folder/f'{name}.mp4'))
        jpg = folder/f'{name}.jpg'
        still = begin + (duration-1 if name in ('impact', 'map') else duration*.55)
        run('ffmpeg', '-v', 'error', '-y', '-ss', str(still), '-i', output, '-frames:v', '1', str(jpg))
        with Image.open(jpg) as image:
            sheet.paste(image.resize((640, 360)), ((i%3)*640, (i//3)*360))
    sheet.save(folder/'nine_examples.jpg', quality=95)
    (folder/'preview_manifest.json').write_text(json.dumps(previews, indent=2), encoding='utf-8')
    print('READY:', output, flush=True)


if __name__ == '__main__':
    main()
