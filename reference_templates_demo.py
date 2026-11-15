"""Five production renders and synchronized comparisons against the supplied video."""
import html
import json
import shutil
import subprocess
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ffmpeg_builder import build_video
from config import OUTPUT_DIR

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT/'reference_analysis/vidrush1/motion_five'
NAME = 'scene_reference_five'


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:])
    return result


def main():
    folder = Path(OUTPUT_DIR, NAME); downloads = folder/'downloads'; downloads.mkdir(parents=True, exist_ok=True)
    for source, target in [(ANALYSIS/'frames_051/0000.jpg','office.jpg'),
                           (ANALYSIS/'frames_053/0000.jpg','fish.jpg'),
                           (ROOT/'output/scene_narrative_templates/downloads/schematic_map.png','map.png')]:
        shutil.copy2(source, downloads/target)
    with Image.open(ANALYSIS/'frames_066/0090.jpg') as image:
        for box, name in [((204,298,876,676),'testimony_one.jpg'), ((1044,298,1716,676),'testimony_two.jpg')]:
            if not (downloads/name).exists(): image.crop(box).save(downloads/name, quality=95)
    catalog = json.loads((ANALYSIS.parent/'clip_catalog.json').read_text())['clips']
    specs = [
        (51, 'chapter_heading', 235, 'office.jpg', {'text':'the authority behind the record'}),
        (53, 'date_countback', 210, 'fish.jpg', {'year':1918,'from_year':2026}),
        (65, 'editorial_statement', 96, 'office.jpg', {'text':'stead recorded the men'}),
        (66, 'paired_evidence', 92, 'testimony_one.jpg', {'comparison_group':'testimonies','label':'testimony one','archival':True}),
    ]
    chunks, previews, cursor = [], [], 0
    for clip, template, frames, picture, params in specs:
        start = cursor/30; duration = frames/30
        original = catalog[clip-1]
        context = original['transcript']
        if template == 'paired_evidence':
            # Detector clips overlap one transcript word; merge without repeating the seam.
            next_words = catalog[clip]['transcript'].split()
            if next_words and context.split()[-1].casefold() == next_words[0].casefold(): next_words = next_words[1:]
            context += ' '+' '.join(next_words)
        previews.append({'clip':clip, 'template':template, 'start':start, 'frames':frames,
                         'duration':duration,'transcript':context, 'params':params})
        subdivisions = [(40, picture, params), (52,'testimony_two.jpg',{**params,'label':'testimony two'})] if template=='paired_evidence' else [(frames,picture,params)]
        for length, media, settings in subdivisions:
            index = len(chunks)
            chunks.append({'id':index, '_chunk_id':index, 'scene_id':f'reference_{clip}', 'type':'photo',
                           'preset':'PHOTO_STATIC', 'template':template, 'params':settings,
                           'query':media, 'search_mode':'broll', 'text':context,
                           'start':cursor/30, 'end':(cursor+length)/30, 'duration':length/30,
                           'files':[media], '_files':[str(downloads/media)]})
            cursor += length
        shutil.copy2(ANALYSIS/f'ref_{clip:03}.mp4', folder/f'reference_{clip:03}.mp4')
    voice = folder/'silence.wav'
    with wave.open(str(voice), 'wb') as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(48000)
        out.writeframes(b'\0'*(cursor*1600*4))
    transitions = [{'kind':'cut','start':c['start'],'end':c['start']} for c in chunks[1:]]
    output, used = build_video(chunks, str(folder), NAME, audio_path=str(voice), audio_duration=cursor/30,
                              transitions=transitions, progress_callback=lambda message: print(message,flush=True))
    clean = [{k:v for k,v in c.items() if not k.startswith('_')} for c in chunks]
    timeline = {'chunks':clean,'transitions':transitions,'text_cues':[],'audio_tracks':[]}
    (folder/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (ROOT/'examples/timeline_reference_five.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (folder/'project.json').write_text(json.dumps({'scene_name':NAME,'scene_dir':str(folder),'audio_path':str(voice),
        'audio_duration':cursor/30,'language':'en',**timeline,
        'assets':{p.name:{'user_supplied':True,'source':'User-provided reference; demonstration crop'} for p in downloads.iterdir()},
        'file_overrides':{str(k):v for k,v in used.items()},'downloads_complete':True,'processing_mode':'fast'},ensure_ascii=False,indent=2))
    rows = []
    header = Image.new('RGB',(1920,60),'#0b0b0b'); draw = ImageDraw.Draw(header)
    font = ImageFont.load_default(size=28)
    draw.text((28,12),'REFERENCE',fill='white',font=font); draw.text((988,12),'REMOTION',fill='white',font=font)
    header.save(folder/'comparison_header.png')
    sheet = Image.new('RGB',(1440,5*240),'#101010')
    for index, item in enumerate(previews):
        template, clip = item['template'], item['clip']
        own = folder/f'{template}.mp4'; ref = folder/f'reference_{clip:03}.mp4'
        run('ffmpeg','-v','error','-y','-ss',str(item['start']),'-i',output,'-t',str(item['duration']),
            '-c:v','libx264','-crf','18','-preset','fast','-c:a','aac','-movflags','+faststart',str(own))
        for x, video in [(0,ref),(720,own)]:
            frame = folder/f'{index}_{x}.jpg'
            run('ffmpeg','-v','error','-y','-ss',str(min(item['duration']-.1,3)), '-i',str(video),
                '-frames:v','1','-vf','scale=720:405',str(frame))
            with Image.open(frame) as image:
                # Full frame scaled to fit each contact-sheet row, without losing composition.
                image.thumbnail((720,205)); sheet.paste(image,(x+(720-image.width)//2,index*240+35))
            draw = ImageDraw.Draw(sheet)
            draw.text((x+12,index*240+10), f"{clip} | {'REFERENCE' if x==0 else template}", fill='white')
        comparison = folder/f'compare_{clip:03}.mp4'
        run('ffmpeg','-v','error','-y','-i',str(ref),'-i',str(own),'-loop','1','-i',str(folder/'comparison_header.png'),'-filter_complex',
            '[0:v]fps=30,tpad=stop_mode=clone:stop_duration=0.1,scale=960:540,setsar=1[a];[1:v]fps=30,scale=960:540,setsar=1[b];[a][b]hstack=inputs=2,pad=1920:600:0:60:black[c];[c][2:v]overlay=0:0[v]',
            '-map','[v]','-map','1:a:0','-t',str(item['duration']),'-frames:v',str(item['frames']),'-c:v','libx264','-crf','20','-preset','fast',
            '-c:a','aac','-movflags','+faststart',str(comparison))
        item['original_sound'] = 'Mixed original narration and effects; no exact SFX identification claimed'
        item['template_sound'] = 'Local library SFX at original gain × 0.30; no generated narration'
        rows.append(f'''<section data-template="{template}"><h2>{clip}{'–67' if clip==66 else ''} · {template.replace('_',' ')}</h2>
<p>{html.escape(item['transcript'])}</p><div class="pair"><figure><figcaption>Референс</figcaption><video preload="metadata" src="{ref.name}?range=1" playsinline></video></figure>
<figure><figcaption>Наш шаблон · Coolvetica</figcaption><video preload="metadata" src="{own.name}?range=1" playsinline></video></figure></div>
<div class="controls"><button class="play">▶ Вместе</button><button class="reset">Сначала</button>
<button class="step">+1 кадр</button><input type="range" min="0" max="{item['duration']:.6f}" step="0.033333" value="0">
<output>0.00 с</output><select aria-label="Звук"><option value="ours">Звук шаблона</option><option value="ref">Звук референса</option><option value="mute">Без звука</option></select></div></section>''')
    sheet.save(folder/'comparison.jpg',quality=95)
    listing = folder/'comparison_concat.txt'; listing.write_text(''.join(f"file '{folder/f'compare_{i[0]:03}.mp4'}'\n" for i in specs))
    run('ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-r','30','-t',str(cursor/30),
        '-frames:v',str(cursor),'-c:v','libx264','-crf','20','-preset','fast','-c:a','aac','-movflags','+faststart',str(folder/'comparison.mp4'))
    (folder/'measurements.json').write_text(json.dumps(previews,ensure_ascii=False,indent=2))
    (folder/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Пять шаблонов — сравнение</title>
<style>*{box-sizing:border-box}body{margin:0;background:#111;color:#eee;font:16px system-ui;padding:28px}main{max-width:1500px;margin:auto}h1{font-size:32px}h2{font-size:23px}p{color:#aaa;line-height:1.5}section{padding:24px 0;border-top:1px solid #444}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}figure{margin:0}figcaption{margin:0 0 10px;color:#ddd}video{width:100%;background:#000}button,select{background:#292929;border:1px solid #555;color:white;padding:10px;border-radius:5px}.controls{display:flex;gap:12px;align-items:center;margin-top:12px}input{flex:1}output{width:80px}@media(max-width:800px){.pair{grid-template-columns:1fr}.controls{flex-wrap:wrap}}</style>
<main><h1>Пять приёмов, начиная с клипа 31</h1><p>Слева — исходный фрагмент, справа — работающий шаблон. Общая шкала позволяет сравнить начало, середину и завершение движения.
Звук референса содержит диктора и эффекты. В шаблонах — выбранные звуки нашей библиотеки на 30%; точное совпадение с исходными SFX не установлено. Примеры без новой озвучки.</p>
<p>Карта справа — условная схема. Текст адаптирован к белому Coolvetica строчными. Световой переход перед парой карточек в референсе — отдельный эффект, в шаблон пары не включён.</p>
''' + '\n'.join(rows) + '''</main><script>
const sections=[...document.querySelectorAll('section')];
for(const s of sections){const [a,b]=s.querySelectorAll('video'),slider=s.querySelector('input'),label=s.querySelector('output'),sound=s.querySelector('select'),play=s.querySelector('.play');
let requestedTime=0;
const mute=()=>{a.muted=sound.value!=='ref';b.muted=sound.value!=='ours'};mute();sound.onchange=mute;
const pause=()=>{a.pause();b.pause();play.textContent='▶ Вместе'};
const apply=v=>{if(v.readyState>=2)v.currentTime=Math.min(requestedTime,v.duration-.033)};
for(const v of [a,b])v.addEventListener('loadeddata',()=>apply(v),{once:true});
const seek=t=>{pause();requestedTime=Math.min(Number(slider.max)-.033,Math.max(0,t));apply(a);apply(b);slider.value=requestedTime;label.textContent=requestedTime.toFixed(2)+' с'};
play.onclick=async()=>{if(!a.paused){pause();return}for(const other of sections)if(other!==s)other.querySelectorAll('video').forEach(v=>v.pause());if(a.ended||a.currentTime>=Number(slider.max)-.04)seek(0);b.currentTime=a.currentTime;await Promise.all([a.play(),b.play()]);play.textContent='Ⅱ Пауза'};
s.querySelector('.reset').onclick=()=>seek(0);s.querySelector('.step').onclick=()=>seek(a.currentTime+1/30);slider.oninput=()=>seek(Number(slider.value));
a.ontimeupdate=()=>{slider.value=a.currentTime;label.textContent=a.currentTime.toFixed(2)+' с';if(b.readyState>=2&&Math.abs(a.currentTime-b.currentTime)>.04)b.currentTime=Math.min(a.currentTime,b.duration-.033)};
a.onended=()=>{pause();requestedTime=Math.min(a.currentTime,Number(slider.max)-.033);apply(b)};
}
</script></html>''',encoding='utf-8')
    print('DONE',output,flush=True)


if __name__ == '__main__': main()
