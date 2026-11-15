"""Small local demonstration through the same preparation/render path as the UI.

The reference presenter is test footage only, never a default application avatar.
"""
import json
import shutil
import subprocess
import threading
import wave
from pathlib import Path

from app import _prepare_build_chunks, _save_project
from avatar_templates import probe_video
from config import OUTPUT_DIR
from ffmpeg_builder import build_video

ROOT = Path(__file__).resolve().parent
NAME = 'scene_avatar_demo'


def main():
    folder = Path(OUTPUT_DIR, NAME)
    downloads = folder / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    source = Path('/Users/ilia/Downloads/scenes/test3-Scene-001.mp4')
    if not source.is_file():
        raise SystemExit('For this optional reference demo provide test3-Scene-001.mp4; production has no reference dependency.')
    avatar = downloads / 'avatar_demo.mp4'
    shutil.copy2(source, avatar)
    info = probe_video(avatar)
    picture = downloads / 'example.jpg'
    subprocess.run(['ffmpeg','-v','error','-y','-ss','1','-i',
                    '/Users/ilia/Downloads/scenes/test3-Scene-054.mp4','-frames:v','1',str(picture)],check=True)
    background_video = downloads / 'example_video.mp4'
    shutil.copy2('/Users/ilia/Downloads/scenes/test3-Scene-002.mp4', background_video)
    chunks = []
    cursor = 0
    for i,(template,duration) in enumerate([('avatar_full',3),('avatar_left',3.5),('avatar_right',4),('avatar_left',3)]):
        chunks.append({'id':i,'scene_id':i+1,'type':'video' if i in (0,3) else 'photo',
                       'query':'reference demonstration','search_mode':'broll','text':'Демонстрация композиции',
                       'editor_note_ru':'Тестовый ведущий из референса. Собственная ведущая загрузится позже.',
                       'template':template,'avatar':{'clip_id':'avatar_demo','source_start':0},
                       'params':{'avatar_width':.42,'media_fit':'contain','zoom_start':0,'zoom_end':.03},
                       'start':cursor,'end':cursor+duration,'duration':duration,
                       'files':[] if i==0 else [background_video.name if i==3 else picture.name]})
        cursor += duration
    voice = folder / 'silence.wav'
    with wave.open(str(voice),'wb') as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(48000)
        out.writeframes(b'\0' * round(cursor*48000)*4)
    session = {'scene_name':NAME,'scene_dir':str(folder),'video_mode':'ai_avatar',
               'avatar_library':[{'id':'avatar_demo','filename':avatar.name,'label':'Тестовый клип из референса',**info}],
               'audio_path':str(voice),'audio_duration':cursor,'language':'en','chunks':chunks,
               'assets':{name:{'source':'Локальный файл','rights_confirmed':False} for name in (picture.name,background_video.name)},
               'busy':False,'cancel':threading.Event(),'downloads_complete':True}
    cuts = [{'kind':'cut','start':c['start'],'end':c['start']} for c in chunks[1:]]
    session.update(transitions=cuts,audio_tracks=[],text_cues=[])
    _save_project(session)
    timeline = {key:session[key] for key in ('video_mode','chunks','transitions','audio_tracks','text_cues')}
    (folder/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (ROOT/'examples/timeline_avatar.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    output,_ = build_video(_prepare_build_chunks(session),str(folder),NAME,audio_path=str(voice),
                           audio_duration=cursor,transitions=cuts,progress_callback=lambda message:print(message,flush=True))
    sections=[]
    labels=['Полный экран · 3 с','Ведущая слева · 3,5 с','Ведущая справа · 4 с','Ведущая слева + видео · 3 с']
    for c,label in zip(chunks,labels):
        video=folder/(('avatar_video_background' if c['id']==3 else c['template'])+'.mp4')
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(c['start']),'-i',output,'-t',str(c['duration']),
                        '-c:v','libx264','-crf','19','-preset','fast','-an','-movflags','+faststart',str(video)],check=True)
        sections.append(f'<section><h2>{label}</h2><video controls muted playsinline preload="metadata" src="{video.name}"></video></section>')
    (folder/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><title>ИИ-аватар · примеры</title>
      <style>body{margin:0;background:#11151b;color:#eee;font:16px system-ui}main{max-width:1100px;margin:40px auto;padding:0 24px}p{color:#abb7c6;line-height:1.6}section{margin:40px 0}h2{font-size:20px}video{width:100%;border-radius:12px;background:#000}a{color:#afc7ff}</style>
      <main><h1>ИИ-аватар: три композиции</h1><p>Технический пример на ведущем из разобранного референса. Он не встроен в шаблоны: твои видео женщины в никабе заменят его после загрузки библиотеки. Фото рядом также подбирается заново по сценарию.</p>
      <p>У тестового клипа есть исходный звук; здесь он отключён. Мастер-дорожка теста — тишина. В рабочем проекте вместо неё звучит твоя озвучка. Lip-sync не требуется.</p>'''+''.join(sections)+
      '<p><a href="scene_avatar_demo.mp4">Общий пример · 13,5 с · 1080p</a></p></main></html>')
    print('DONE',output,flush=True)


if __name__ == '__main__':
    main()
