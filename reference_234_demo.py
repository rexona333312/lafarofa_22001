"""Production sidebar demo, plus independently paced 3s / 7s examples."""
import json
import shutil
import wave
from pathlib import Path
from ffmpeg_builder import build_video
from reference_templates import motion_params
from reference_requested_templates_demo import run
from config import OUTPUT_DIR

ROOT=Path(__file__).resolve().parent
NAME='scene_reference_234'


def main():
    folder=Path(OUTPUT_DIR,NAME); downloads=folder/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    source='/Users/ilia/Downloads/scenes/test-Scene-234.mp4'
    run('ffmpeg','-v','error','-y','-i',source,'-frames:v','1',str(downloads/'witnesses.jpg'))
    shutil.copy2(source,folder/'reference_234.mp4')
    words=json.loads(Path('/Users/ilia/Downloads/vidrush1.json').read_text())['word_timestamps']
    start=853.333333
    def onset(word):
        w=next(w for w in words if start<=w['start']<861.233333 and w['word'].strip('.,?!').lower()==word)
        return round((w['start']-start)*30)
    spoken={'style':'torn_sidebar','side':'right','timing_mode':'speech','title':'what witnesses reported',
        'archival':True,'panel_start':0,'arrival_frames':34,'title_start':6,'title_frames':12,
        'items':[{'text':'experienced cray fishermen','start_frame':onset('experienced'),'reveal_frames':35},
                 {'text':'a pale shape and heaving water','start_frame':onset('pale'),'reveal_frames':59},
                 {'text':'a head compared to a roof','start_frame':onset('head'),'reveal_frames':29}]}
    stretched={'style':'torn_sidebar','side':'right','timing_mode':'stretch','title':'what witnesses reported',
        'archival':True,'items':[{'text':row['text']} for row in spoken['items']]}
    short=motion_params('bullet_panel',stretched,90)
    hold={**short,'timing_mode':'speech'}
    specs=[('speech_7_9s',237,spoken),('stretch_3s',90,stretched),('stretch_7s',210,stretched),('fast_hold_7s',210,hold)]
    chunks=[];cursor=0
    for index,(label,frames,params) in enumerate(specs):
        chunks.append({'id':index,'_chunk_id':index,'scene_id':label,'type':'photo','preset':'PHOTO_STATIC',
          'template':'bullet_panel','params':params,'query':'witnesses.jpg','files':['witnesses.jpg'],
          '_files':[str(downloads/'witnesses.jpg')],'search_mode':'broll',
          'text':'a group of experienced cray fishermen, a pale shape, water that heaved, a head compared to a roof, a length they could not agree on',
          'start':cursor/30,'end':(cursor+frames)/30,'duration':frames/30})
        cursor+=frames
    voice=folder/'silence.wav'
    with wave.open(str(voice),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(48000);out.writeframes(b'\0'*(cursor*1600*4))
    transitions=[{'kind':'cut','start':c['start'],'end':c['start']} for c in chunks[1:]]
    output,used=build_video(chunks,str(folder),NAME,audio_path=str(voice),audio_duration=cursor/30,
        transitions=transitions,progress_callback=lambda msg:print(msg,flush=True))
    clean=[{k:v for k,v in c.items() if not k.startswith('_')} for c in chunks]
    timeline={'chunks':clean,'transitions':transitions,'text_cues':[],'audio_tracks':[]}
    save=lambda path,data:path.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    save(folder/'timeline.json',timeline);save(ROOT/'examples/timeline_reference_234.json',timeline)
    save(folder/'project.json',{'scene_name':NAME,'scene_dir':str(folder),'audio_path':str(voice),
        'audio_duration':cursor/30,'language':'en',**timeline,'downloads_complete':True,'processing_mode':'fast',
        'file_overrides':{str(k):v for k,v in used.items()},
        'assets':{'witnesses.jpg':{'user_supplied':True,'source':'Benchmark-only clean reference frame'}}})
    for c,(label,frames,params) in zip(chunks,specs):
        run('ffmpeg','-v','error','-y','-ss',str(c['start']),'-i',output,'-t',str(frames/30),
            '-frames:v',str(frames),'-c:v','libx264','-crf','18','-preset','fast','-c:a','aac',
            '-movflags','+faststart',str(folder/f'{label}.mp4'))
        run('ffmpeg','-v','error','-y','-ss',str((frames-2)/30),'-i',str(folder/f'{label}.mp4'),
            '-frames:v','1',str(folder/f'{label}.jpg'))
    run('ffmpeg','-v','error','-y','-i',str(folder/'reference_234.mp4'),'-i',str(folder/'speech_7_9s.mp4'),
      '-filter_complex','[0:v]scale=960:540,setsar=1[a];[1:v]scale=960:540,setsar=1[b];[a][b]hstack=inputs=2[v]',
      '-map','[v]','-map','1:a:0','-frames:v','237','-c:v','libx264','-crf','19','-preset','fast',
      '-c:a','aac','-movflags','+faststart',str(folder/'comparison.mp4'))
    save(folder/'motion_params.json',{label:motion_params('bullet_panel',p,n) for label,n,p in specs})
    # Reuse the tested synchronized-seeking controls from the prior deliverable.
    previous=(Path(OUTPUT_DIR)/'scene_reference_requested_five/index.html').read_text()
    script=previous.split('<script>',1)[1].split('</script>',1)[0]
    (folder/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><title>234 · Боковой список</title>
<style>*{box-sizing:border-box}body{margin:0;background:#111;color:#eee;font:16px system-ui;padding:28px}main{max-width:1500px;margin:auto}h1{font-size:32px}h2{font-size:23px}p{color:#aaa;line-height:1.6}section{padding:24px 0;border-top:1px solid #444}.pair,.durations{display:grid;grid-template-columns:1fr 1fr;gap:16px}.durations{grid-template-columns:repeat(3,1fr)}figure{margin:0}figcaption{margin-bottom:12px}video{width:100%;background:#000}button,select{background:#292929;border:1px solid #555;color:white;padding:10px;border-radius:5px}.controls{display:flex;gap:12px;align-items:center;margin-top:12px}input{flex:1}output{width:80px}@media(max-width:800px){.pair,.durations{grid-template-columns:1fr}.controls{flex-wrap:wrap}}</style>
<main><h1>234 · Боковой список с рваным краем</h1>
<p>Вариант существующего bullet_panel: сверху раскрывается тёмная боковая панель с красным рваным краем, затем заголовок и фактурные полосы пунктов. Белый Coolvetica. Раскрытие панели — 34 кадра (1,13 с), быстрое начало и сильное замедление.</p>
<p>В нашем примере пункты появляются по word_timestamps: «experienced» — 0,77 с, «pale» — 2,47 с, «head» — 5,00 с. Референс собирает весь список раньше речи. Фото взято только для сравнения; в рабочем видео используются материалы текущего сценария. SFX нашей библиотеки на 30%, новая озвучка не добавлялась.</p>
<section><h2>Референс и наш вариант · 7,9 секунды</h2><div class="pair"><figure><figcaption>Референс 234</figcaption><video preload="metadata" src="reference_234.mp4" playsinline></video></figure><figure><figcaption>Remotion · пункты по речи</figcaption><video preload="metadata" src="speech_7_9s.mp4" playsinline></video></figure></div>
<div class="controls"><button class="play">▶ Вместе</button><button class="reset">Сначала</button><button class="step">+1 кадр</button><input type="range" min="0" max="7.9" step="0.033333" value="0"><output>0.00 с</output><select aria-label="Звук"><option value="ours">Звук шаблона</option><option value="ref">Звук референса</option><option value="mute">Без звука</option></select></div></section>
<h2>Длительность сцены и скорость движения</h2><p>Первые два примера растягивают сборку относительно всей длительности. Третий сохраняет скорость трёхсекундного примера, но держит готовый список до конца семисекундной сцены. Это демонстрации темпа; реальную речь следует синхронизировать по её JSON.</p><button id="startDurations">▶ Запустить три примера вместе</button>
<div class="durations" style="margin-top:20px"><figure><figcaption>3 с · сборка до 2,83 с</figcaption><video controls preload="metadata" src="stretch_3s.mp4" playsinline></video></figure><figure><figcaption>7 с · сборка до 6,57 с</figcaption><video controls preload="metadata" src="stretch_7s.mp4" playsinline></video></figure><figure><figcaption>7 с · сборка за 2,83 с и удержание</figcaption><video controls preload="metadata" src="fast_hold_7s.mp4" playsinline></video></figure></div></main><script>'''+script+'''
document.getElementById('startDurations').onclick=async()=>{const vs=[...document.querySelectorAll('.durations video')];document.querySelectorAll('section video').forEach(v=>v.pause());for(const [i,v] of vs.entries()){v.currentTime=0;v.muted=i!==0}await Promise.all(vs.map(v=>v.play()))};
</script></html>''',encoding='utf-8')
    print('DONE',output,flush=True)


if __name__=='__main__':main()
