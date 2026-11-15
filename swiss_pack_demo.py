"""Render the new pack through the production assembly path, without external stock search."""
import copy
import html
import json
import shutil
import subprocess
import wave
from pathlib import Path
from PIL import Image,ImageDraw
from editorial_planning import CONTRACTS,graphics_summary
from ffmpeg_builder import build_video

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'output/scene_swiss_pack'


def run(*args):
    subprocess.run(args,check=True,capture_output=True)


def main():
    downloads=FOLDER/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    source=Path('/Users/ilia/Downloads/The Real Reason Hitler Never Invaded Switzerland - Clips')
    for clip,time in [(31,1.5),(102,0),(11,1),(29,1)]:
        path=downloads/f'ref_{clip}.jpg'
        if not path.exists():run('ffmpeg','-v','error','-y','-ss',str(time),'-i',str(source/f'Clip-{clip:03}.mp4'),'-frames:v','1',str(path))
    # Crops are benchmark illustrations from the user's reference, never template dependencies.
    with Image.open(downloads/'ref_31.jpg') as im:
        im.transform((650,900),Image.Transform.QUAD,(476,216,469,824,951,812,927,202),Image.Resampling.BICUBIC).save(downloads/'portrait.jpg',quality=95)
    with Image.open(downloads/'ref_102.jpg') as im:im.crop((365,145,1550,965)).save(downloads/'document.jpg',quality=95)
    chunks=[];specs=[];cursor=0
    def add(name,params,file='ref_11.jpg',duration=6):
        nonlocal cursor
        c=dict(id=len(chunks),_chunk_id=len(chunks),scene_id=len(specs),type='photo',query='Switzerland',search_mode='broll',
            start=cursor,end=cursor+duration,duration=duration,preset='PHOTO_STATIC',params=params,
            files=[file],_files=[str(downloads/file)])
        if name:c['template']=name
        chunks.append(c);cursor+=duration
    start=cursor
    for i,(file,caption) in enumerate([('ref_11.jpg','ALPINE TERRAIN'),('ref_29.jpg','MOUNTAIN TROOPS'),('portrait.jpg','EXILE')]):
        add('evidence_board',{'carousel_group':'swiss_factors','caption':caption},file,2)
    specs.append(dict(template='evidence_board',title='Накопление карточек',start=start,duration=6,reference=[3,19,136]))
    for name,file in [('stat_callout','ref_29.jpg'),('data_comparison','ref_11.jpg'),('document_focus','document.jpg'),('portrait_profile','portrait.jpg')]:
        p=copy.deepcopy(CONTRACTS[name]['params'])
        if name=='stat_callout':p.update(value='430,000',label='MEN UNDER ARMS',start_frame=30)
        if name=='document_focus':p.update(focus_rect=[.14,.30,.70,.07],caption='DETAIL OF THE DOCUMENT')
        if name=='portrait_profile':p.update(name='THOMAS MANN',description='German writer\nExile in Switzerland')
        specs.append(dict(template=name,title={'stat_callout':'Число + фотография','data_comparison':'Сравнение на общей шкале','document_focus':'Приближение к документу','portrait_profile':'Портрет с пояснением'}[name],start=cursor,duration=6,reference=CONTRACTS[name]['reference_clips']))
        add(name,p,file)
    p=copy.deepcopy(CONTRACTS['map_geographic']['params'])
    p['geo'].update(mode='flat',title='SWITZERLAND',camera=[
        dict(frame=0,center=[8.2,46.8],zoom=5.8,pitch=0,bearing=-4),
        dict(frame=179,center=[8.2,46.8],zoom=6.7,pitch=0,bearing=2)])
    specs.append(dict(template='map_annotations',title='Новая карта вместо map_annotations',start=cursor,duration=6,reference=[26,33]))
    add('map_annotations',p)
    p=copy.deepcopy(CONTRACTS['map_geographic']['params'])
    p['geo'].update(title='THE ALPS / GOTTHARD',routes=[],highlights=[],markers=[dict(position=[8.565,46.557],label='Gotthard Pass',start_frame=25)],camera=[
        dict(frame=0,center=[8.56,46.56],zoom=8.2,pitch=45,bearing=-18),
        dict(frame=179,center=[8.56,46.56],zoom=10,pitch=62,bearing=16)])
    specs.append(dict(template='map_geographic',title='3D-рельеф и движение камеры',start=cursor,duration=6,reference=[106]))
    add('map_geographic',p)
    # A real footage interval exercises partial graphic accounting and the video rendering branch.
    video=downloads/'skiers.mp4'
    if not video.exists():run('ffmpeg','-v','error','-y','-i',str(source/'Clip-029.mp4'),'-t','4','-an','-c:v','libx264','-pix_fmt','yuv420p',str(video))
    specs.append(dict(template='stat_overlay',title='Число поверх видео после обычного начала',start=cursor,duration=4,reference=[8,117]))
    add('stat_callout',dict(value='26',label='CANTONS',layout='overlay',start_frame=45),video.name,4)
    chunks[-1]['type']='video'
    transitions=[dict(kind='cut',start=c['start'],end=c['start']) for c in chunks[1:]]
    voice=FOLDER/'silence.wav'
    with wave.open(str(voice),'wb') as f:
        f.setparams((2,2,48000,0,'NONE','not compressed'));f.writeframes(bytes(round(cursor*48000)*4))
    timeline=dict(motion_graphics_target=70,chunks=[{k:v for k,v in c.items() if not k.startswith('_')} for c in chunks],transitions=transitions,text_cues=[],audio_tracks=[])
    (FOLDER/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (ROOT/'examples/timeline_swiss_pack.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    output,used=build_video(chunks,str(FOLDER),'scene_swiss_pack',audio_path=str(voice),audio_duration=cursor,
        transitions=transitions,progress_callback=lambda s:print(s,flush=True))
    rows=[];sheet=Image.new('RGB',(1280,8*400),'#111');draw=ImageDraw.Draw(sheet)
    for i,item in enumerate(specs):
        name=item['template'];clip=FOLDER/f'{name}.mp4'
        run('ffmpeg','-v','error','-y','-ss',str(item['start']),'-i',output,'-t',str(item['duration']),'-c:v','libx264','-crf','18','-preset','fast','-c:a','aac','-movflags','+faststart',str(clip))
        for j,t in enumerate([.15,item['duration']/2,item['duration']-1/30]):
            frame=FOLDER/f'{name}_{j}.jpg'
            run('ffmpeg','-v','error','-y','-ss',str(t),'-i',str(clip),'-frames:v','1','-vf','scale=640:360',str(frame))
        with Image.open(FOLDER/f'{name}_2.jpg') as im:sheet.paste(im,(640*(i%2),400*(i//2)+35))
        draw.text((640*(i%2)+10,400*(i//2)+10),name,fill='white')
        rows.append(f'<section><h2>{html.escape(item["title"])}</h2><p><code>{name}</code> · приёмы референса: {item["reference"]}</p><video controls preload="metadata" src="{name}.mp4" poster="{name}_2.jpg"></video><div class="frames">'+''.join(f'<img src="{name}_{j}.jpg" alt="{label}">' for j,label in enumerate(['Начало','Середина','Конец']))+'</div></section>')
    sheet.crop((0,0,1280,1600)).save(FOLDER/'overview.jpg',quality=93)
    summary=graphics_summary(chunks,[],70)
    (FOLDER/'verification.json').write_text(json.dumps(dict(duration=cursor,width=1920,height=1080,fps=30,summary=summary,specs=specs),ensure_ascii=False,indent=2))
    (FOLDER/'project.json').write_text(json.dumps(dict(scene_name='scene_swiss_pack',scene_dir=str(FOLDER),audio_path=str(voice),audio_duration=cursor,**timeline,
        assets={p.name:dict(source='User reference; demonstration crop only',rights_confirmed=False) for p in downloads.iterdir()},
        downloads_complete=True,file_overrides={str(k):v for k,v in used.items()},processing_mode='fast'),ensure_ascii=False,indent=2))
    (FOLDER/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Новая пачка Remotion</title><style>*{box-sizing:border-box}body{margin:0;background:#141719;color:#ece7dc;font:16px/1.6 system-ui}main{max-width:1250px;margin:auto;padding:40px 25px}h1{font-size:40px;line-height:1.15}h2{font-size:26px}p{color:#b9b5ac}section{border-top:1px solid #454747;padding:25px 0}video{width:100%;background:#080a0b}.frames{display:flex;gap:10px;margin-top:10px}.frames img{width:calc((100% - 20px)/3)}a{color:#e4be74}code{color:#e4be74}</style><main><h1>Новая пачка Remotion по разбору Швейцарии</h1><p>6 новых семейств; у карты есть вид сверху и 3D-рельеф. Все примеры собраны через основной сборщик в 1920×1080 / 30 fps, со звуками локальной библиотеки. Это демонстрация приёмов: тайминги заданы для превью, новой озвучки нет. Иллюстрации извлечены из пользовательского референса только для сравнения; рабочие шаблоны принимают материалы нового сценария.</p><p>Карта: NASA Blue Marble (500 м), Mapzen Terrain, современные границы Natural Earth. Первый рендер требует интернета; загруженные тайлы кэшируются. На крупном плане спутниковая подложка мягче, чем высокодетальные платные снимки. Исторические границы не восстановлены. Все подписи и числа примеров требуют проверки перед публикацией.</p><p><a href="scene_swiss_pack.mp4">Вся подборка</a> · <a href="timeline.json">JSON примера</a> · <a href="verification.json">Проверка сборки</a></p>'''+''.join(rows)+'</main></html>',encoding='utf-8')
    print('DONE',output,flush=True)


if __name__=='__main__':main()
