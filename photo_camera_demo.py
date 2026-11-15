"""Render real-image A/B examples through the production pipeline, retain old graph for comparison only."""
import json
import shutil
import subprocess
import wave
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import numpy as np
import ffmpeg_builder as builder
from presets import graph_for_scene
from reference_requested_templates_demo import run
from config import OUTPUT_DIR

ROOT=Path(__file__).resolve().parent
NAME='scene_photo_camera_remotion'


def legacy(source,output,duration,scene,width=1920,height=1080):
    inputs,graph,_=graph_for_scene([str(source)],scene,duration,width,height,30)
    builder._run_ffmpeg(['-y',*inputs,'-filter_complex_threads','2','-filter_complex',graph,'-map','[vout]',
       '-frames:v',str(round(duration*30)),'-r','30','-c:v','libx264','-threads','4','-preset','veryfast',
       '-crf','20','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(output)])


def measure_pan(folder):
    source=folder/'marker.png';im=Image.new('RGB',(1920,1080),'black')
    ImageDraw.Draw(im).rectangle((940,0,979,1079),fill='white');im.save(source)
    scene={'type':'photo','preset':'PHOTO_PAN','params':{'fit':'cover','direction':'right'}}
    paths=[folder/'marker_legacy.mp4',folder/'marker_remotion.mp4']
    legacy(source,paths[0],6,scene,320,180)
    builder._render_preset([str(source)],str(paths[1]),6,scene,320,180)
    rows=[]
    for video in paths:
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-f','rawvideo','-pix_fmt','gray','-'])
        frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,180,320).astype(float)
        weights=frames.sum(axis=1);pos=(weights*np.arange(320)).sum(axis=1)/weights.sum(axis=1)
        steps=np.diff(pos)[30:-30]
        # Compare against the best-fitted continuous easing, allowing constant encoding bias and crop conventions.
        ease=.5-.5*np.cos(np.pi*np.arange(len(pos))/(len(pos)-1))
        matrix=np.stack([np.ones(len(pos)),ease],axis=1)
        fitted=matrix@np.linalg.lstsq(matrix,pos,rcond=None)[0]
        row={'file':video.name,'frames':len(pos),'travel_pixels':float(pos[-1]-pos[0]),
             'largest_step_pixels':float(np.max(np.abs(steps))),
             'near_frozen_middle_steps':int(np.sum(np.abs(steps)<.01)),
             'middle_steps':len(steps),'curve_residual_rms_pixels':float(np.sqrt(np.mean((pos-fitted)**2)))}
        rows.append(row)
    (folder/'motion_measurements.json').write_text(json.dumps(rows,indent=2))
    print('MEASURED',json.dumps(rows),flush=True)


def main():
    folder=Path(OUTPUT_DIR,NAME);downloads=folder/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'assets/backgrounds/white_house.jpg',downloads/'architecture.jpg')
    shutil.copy2(ROOT/'output/scene_reference_234/downloads/witnesses.jpg',downloads/'archive.jpg')
    shutil.copy2(ROOT/'output/scene_reference_requested_five/downloads/illustration.jpg',downloads/'portrait.jpg')
    cases=[('zoom_in','PHOTO_SLOW_ZOOM',210,'architecture.jpg',{'fit':'cover'},'Приближение · 7 с'),
           ('zoom_out','PHOTO_SLOW_ZOOM_OUT',210,'architecture.jpg',{'fit':'cover'},'Отдаление · 7 с'),
           ('pan','PHOTO_PAN',210,'archive.jpg',{'fit':'cover','direction':'right'},'Панорама · 7 с'),
           ('small_photo','PHOTO_SLOW_ZOOM',90,'portrait.jpg',{},'Маленькое фото и размытый фон · 3 с')]
    chunks=[];cursor=0
    for i,(name,preset,n,picture,params,title) in enumerate(cases):
        chunks.append({'id':i,'_chunk_id':i,'scene_id':name,'type':'photo','preset':preset,'params':params,
          'query':picture,'files':[picture],'_files':[str(downloads/picture)],'text':title,
          'start':cursor/30,'end':(cursor+n)/30,'duration':n/30})
        cursor+=n
    voice=folder/'silence.wav'
    with wave.open(str(voice),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(48000);out.writeframes(b'\0'*(cursor*1600*4))
    cuts=[{'kind':'cut','start':c['start'],'end':c['start']} for c in chunks[1:]]
    output,used=builder.build_video(chunks,str(folder),NAME,audio_path=str(voice),audio_duration=cursor/30,
       transitions=cuts,progress_callback=lambda m:print(m,flush=True))
    clean=[{k:v for k,v in c.items() if not k.startswith('_')} for c in chunks]
    timeline={'chunks':clean,'transitions':cuts,'text_cues':[],'audio_tracks':[]}
    (folder/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (ROOT/'examples/timeline_photo_camera_remotion.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    header=Image.new('RGB',(1920,60),'#111');draw=ImageDraw.Draw(header);font=ImageFont.load_default(size=28)
    draw.text((30,12),'OLD FFMPEG',fill='white',font=font);draw.text((990,12),'REMOTION CAMERA',fill='white',font=font)
    header.save(folder/'header.png')
    sections=[]
    for chunk,(name,preset,n,picture,params,title) in zip(chunks,cases):
        print('COMPARE',name,flush=True)
        own=folder/f'{name}_remotion.mp4';old=folder/f'{name}_legacy.mp4'
        run('ffmpeg','-v','error','-y','-ss',str(chunk['start']),'-i',output,'-frames:v',str(n),
          '-c:v','libx264','-crf','18','-preset','fast','-an','-movflags','+faststart',str(own))
        legacy(downloads/picture,old,n/30,chunk)
        run('ffmpeg','-v','error','-y','-i',str(old),'-i',str(own),'-loop','1','-i',str(folder/'header.png'),
           '-filter_complex','[0:v]scale=960:540,setsar=1[a];[1:v]scale=960:540,setsar=1[b];[a][b]hstack=inputs=2,pad=1920:600:0:60:black[c];[c][2:v]overlay=0:0[v]',
           '-map','[v]','-frames:v',str(n),'-c:v','libx264','-crf','19','-preset','fast','-an',str(folder/f'compare_{name}.mp4'))
        sections.append(f'''<section><h2>{title}</h2><div class="pair"><figure><figcaption>Старый FFmpeg</figcaption><video preload="metadata" src="{old.name}" muted playsinline></video></figure><figure><figcaption>Новая камера Remotion</figcaption><video preload="metadata" src="{own.name}" muted playsinline></video></figure></div><div class="controls"><button class="play">▶ Вместе</button><button class="reset">Сначала</button><button class="step">+1 кадр</button><input type="range" min="0" max="{n/30}" step="0.033333" value="0"><output>0.00 с</output><select aria-label="Звук" hidden><option value="mute">Без звука</option></select></div></section>''')
    listing=folder/'concat.txt';listing.write_text(''.join(f"file '{folder/f'compare_{case[0]}.mp4'}'\n" for case in cases))
    run('ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-frames:v',str(cursor),
       '-c:v','libx264','-crf','19','-preset','fast','-an','-movflags','+faststart',str(folder/'comparison.mp4'))
    previous=(Path(OUTPUT_DIR)/'scene_reference_requested_five/index.html').read_text()
    css=previous.split('<style>',1)[1].split('</style>',1)[0]
    script=previous.split('<script>',1)[1].split('</script>',1)[0]
    (folder/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Камера фотографий · Remotion</title><style>'''+css+'''</style><main><h1>Камера фотографий · Remotion</h1><p>Слева старый рендер FFmpeg, справа новый путь Remotion на тех же исходниках и длительностях. Имена пресетов и timeline JSON сохранены. Дробные координаты, плавный разгон и торможение, рендер 2× с уменьшением.</p><p>Обычные фото без декоративных карточек и звуков. Размытый фон, подписи источников, переходы и наложения поддерживаются. Для прежних проектов новые рендеры автоматически пересобираются; старые готовые MP4 сами не меняются.</p>'''+''.join(sections)+'''</main><script>'''+script+'''</script></html>''')
    measure_pan(folder)
    print('DONE',output,flush=True)


if __name__=='__main__':main()
