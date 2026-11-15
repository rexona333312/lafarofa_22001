"""Ordinary footage demo through the production builder; no search or paid APIs."""
import html
import json
import subprocess
import wave
from pathlib import Path
from PIL import Image, ImageDraw
from ffmpeg_builder import build_video
from shot_planning import editing_summary
from clip_ranker import _trim_to_moment

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/scene_shot_editing'
SOURCE=Path('/Users/ilia/Downloads/The Real Reason Hitler Never Invaded Switzerland - Clips')


def run(*args):subprocess.run(args,check=True,capture_output=True)


def main():
    downloads=OUT/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    chunks=[];chapters=[];cursor=0

    def add(clip,duration,scene,role,scale,pace,action,relation='continue',link=None):
        nonlocal cursor
        number=len(chunks);path=downloads/f'shot_{number:02d}.mp4'
        run('ffmpeg','-v','error','-y','-i',str(SOURCE/f'Clip-{clip:03}.mp4'),'-an','-t',str(duration),
            '-vf','fps=30','-c:v','libx264','-preset','fast','-crf','18',str(path))
        # Timings are demonstration beats, not a replacement narration alignment.
        plan=dict(role=role,scale=scale,pace=pace,goal=scene,action=action,relation=relation)
        if link:plan['link']=link
        chunks.append(dict(id=number,_chunk_id=number,type='video',query=action,search_mode='broll',
            scene_id=scene,shot_plan=plan,start=cursor,end=cursor+duration,duration=duration,
            files=[path.name],_files=[str(path)],reference_clip=clip))
        cursor+=duration

    start=cursor
    add(62,3,'discussion','action','close','normal','Офицеры склоняются над столом',relation='new_scene')
    add(63,2,'discussion','action','medium','normal','Другой ракурс людей над картой')
    add(64,1.5,'discussion','establishing','wide','normal','Общий вид группы у стола')
    chapters.append(('Связанные планы одной сцены',start,cursor,
        'Три ракурса обсуждения: от человека к группе и обстановке. Связь кадров не подтверждает дату или непрерывность события.'))
    start=cursor
    add(277,1.6,'city','establishing','wide','normal','Площадь, башни и памятник',relation='new_scene')
    add(278,2.4,'city','detail','close','normal','Памятник занимает большую часть кадра')
    chapters.append(('Смена крупности',start,cursor,'Место → конкретный объект в том же окружении.'))
    start=cursor
    add(160,2.5,'precision','action','medium','normal','Литьё раскалённого металла',relation='new_scene')
    add(162,2,'precision','detail','detail','normal','Руки и точная металлическая деталь',relation='association',link='Материал → точная обработка; разные процессы служат иллюстрацией темы')
    add(166,2.5,'precision','action','detail','normal','Работа с часовым механизмом',relation='association',link='Повторяется мотив точной ручной работы')
    chapters.append(('Процесс и предметная деталь',start,cursor,
        'Материал → деталь → применение. Это ассоциативные иллюстрации точности, не доказательство единой производственной цепочки.'))
    start=cursor
    for n,d,role,scale,action in [(56,1.4,'establishing','wide','Корабли в море'),
            (57,1,'action','medium','Люди на палубе'),(58,1.8,'action','wide','Парашютисты покидают самолёты'),
            (59,.8,'action','medium','Другой ракурс десантирования')]:
        add(n,d,'mobilization',role,scale,'urgent',action,relation='new_scene' if n==56 else 'continue')
    chapters.append(('Ускорение темпа',start,cursor,'Цепочка 1,4 / 1 / 1,8 / 0,8 с. Без ускорения исходника и речи.'))
    start=cursor
    add(178,3.5,'contrast','establishing','wide','normal','Поезд на горной железной дороге',relation='new_scene')
    add(179,2.5,'contrast','contrast','wide','normal','Разрушенная городская улица',relation='contrast',
        link='Работающая инфраструктура и образ разрушения. Не утверждается разрушение показанной железной дороги')
    chapters.append(('Контрастная связка',start,cursor,
        'Действующая инфраструктура → руины. В рабочем ролике такой контраст требует соответствующей фразы озвучки.'))
    start=cursor
    add(177,3,'breathing','breathing','wide','calm','Горная панорама',relation='new_scene')
    chapters.append(('Визуальная передышка',start,cursor,'После плотной цепочки — один спокойный широкий план без дополнительного зума.'))

    probe=OUT/'verification/apple_live.json'
    if probe.exists():
        live=json.loads(probe.read_text())
        if live.get('passed'):
            result=live['results'][0];path=downloads/'selected_action.mp4'
            import shutil
            shutil.copy2(OUT/'verification/action_candidate.mp4',path)
            if not _trim_to_moment(str(path),result['start'],result['end']):raise RuntimeError('Action trim failed')
            start=cursor;duration=result['end']-result['start'];number=len(chunks)
            chunks.append(dict(id=number,_chunk_id=number,type='video',query=live['plan']['query'],scene_id='selected_action',
                shot_plan=live['plan']['shot_plan'],start=cursor,end=cursor+duration,duration=duration,
                files=[path.name],_files=[str(path)]));cursor+=duration
            chapters.append(('Момент, выбранный Apple',start,cursor,
                f'Из проверочного исходника выбран интервал {result["start"]:.2f}–{result["end"]:.2f} с. Исходник специально составлен из трёх разных сюжетов.'))
    voice=OUT/'silence.wav'
    with wave.open(str(voice),'wb') as f:
        f.setparams((2,2,48000,0,'NONE','not compressed'));f.writeframes(bytes(round(cursor*48000)*4))
    timeline=dict(chunks=[{k:v for k,v in c.items() if not k.startswith('_')} for c in chunks],transitions=[],audio_tracks=[],text_cues=[])
    (OUT/'timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    output,used=build_video(chunks,str(OUT),'scene_shot_editing',audio_path=str(voice),audio_duration=cursor,
        transitions=[],progress_callback=lambda text:print(text,flush=True))
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',output]))
    stream=next(s for s in info['streams'] if s['codec_type']=='video')
    assert (stream['width'],stream['height'],stream['r_frame_rate'])==(1920,1080,'30/1')
    assert abs(float(info['format']['duration'])-cursor)<.08
    assert int(stream['nb_frames'])==round(cursor*30)
    report=json.loads((OUT/'render_report.json').read_text());assert report['builtin_transitions']==[]
    run('ffmpeg','-v','error','-i',output,'-f','null','-')
    rows=[];overview=Image.new('RGB',(1280,400*((len(chapters)+1)//2)),'#111');draw=ImageDraw.Draw(overview)
    for i,(title,a,b,description) in enumerate(chapters):
        file=f'chapter_{i+1}.mp4';frame=f'chapter_{i+1}.jpg'
        run('ffmpeg','-v','error','-y','-ss',str(a),'-i',output,'-t',str(b-a),'-c:v','libx264',
            '-preset','fast','-crf','20','-c:a','aac','-movflags','+faststart',str(OUT/file))
        run('ffmpeg','-v','error','-y','-ss',str((a+b)/2),'-i',output,'-frames:v','1','-vf','scale=640:360',str(OUT/frame))
        with Image.open(OUT/frame) as im:overview.paste(im,(640*(i%2),400*(i//2)+40))
        draw.text((640*(i%2)+10,400*(i//2)+10),f'{i+1}: {a:.1f}-{b:.1f}s',fill='white')
        rows.append(f'<section><h2>{i+1}. {html.escape(title)}</h2><p>{html.escape(description)}</p><video controls preload="metadata" poster="{frame}" src="{file}"></video></section>')
    overview.save(OUT/'overview.jpg',quality=92)
    (OUT/'verification/build.json').write_text(json.dumps(dict(duration=cursor,width=1920,height=1080,fps=30,
        frames=int(stream['nb_frames']),decode='passed',transitions=report['builtin_transitions'],
        editing=editing_summary(chunks,[])),ensure_ascii=False,indent=2))
    (OUT/'project.json').write_text(json.dumps(dict(scene_name='scene_shot_editing',scene_dir=str(OUT),
        audio_path=str(voice),audio_duration=cursor,**timeline,downloads_complete=True,assets={
            p.name:{'source':'User reference; demo excerpt','rights_confirmed':False} for p in downloads.iterdir()},
        file_overrides={str(k):v for k,v in used.items()},processing_mode='fast'),ensure_ascii=False,indent=2))
    (OUT/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Обычный видеоряд — новая логика монтажа</title><style>*{box-sizing:border-box}body{background:#151719;color:#e8e5de;font:17px/1.6 system-ui;margin:0}main{max-width:1160px;margin:auto;padding:40px 24px}h1{font-size:38px;line-height:1.15}h2{font-size:26px}p{color:#bdbcb6}a{color:#ecc582}video{width:100%;aspect-ratio:16/9;object-fit:contain;background:black}section{padding:26px 0;border-top:1px solid #414346}code{color:#ecc582}</style><main><h1>Обычный видеоряд: сцены, крупность и ритм</h1><p>Проверка через основной FFmpeg-сборщик: 1920×1080, 30 fps. Монтажные этюды из пользовательского референса, без озвучки и новых моушн-шаблонов. Это демонстрация приёмов; тайминги примера не являются монтажом нового сценария.</p><p>Связанные кадры получают scene_id и shot_plan; внутри сцены подбор последовательный, с учётом предыдущего выбранного материала. Конкретное действие и нужная крупность входят в запрос визуальной проверки. Темп и передышки планируются по смыслу речи; исходные word_timestamps не меняются. Старый JSON без shot_plan сохраняет совместимость, но новые связи нужно перепланировать.</p><p>Все стыки этой подборки — cut при transitions:[]. Квота эффектных переходов удалена; явно заданные переходы по-прежнему работают.</p><p><a href="scene_shot_editing.mp4">Весь ролик</a> · <a href="timeline.json">Таймлайн</a> · <a href="verification/build.json">Проверка сборки</a> · <a href="verification/apple_live.json">Живая проверка Apple</a> · <a href="verification/tests.json">Полный набор тестов</a> · <a href="verification/latest_tests.json">Последние проверки</a> · <a href="verification/apple_continuity_live.json">Проверка связи кадров</a></p><video controls preload="metadata" src="scene_shot_editing.mp4" poster="chapter_1.jpg"></video><p>Проверки: в полном наборе 169 из 170 прошли; один прежний тест ожидает Remotion PhotoCamera при существующей камере FFmpeg. На финальном коде прошли 73 профильные проверки, включая 7 тестов новой логики. Apple оценивает до трёх непрерывных окон каждого кандидата, по три кадра в окне. Это выборочная проверка, она может пропустить короткое действие или внутреннюю склейку. Выбор окна не подтверждает историческую достоверность. Независимая оценка окон убирает ошибку номера строки общего контактного листа. Пригодность самого кадра проверяется без предыдущего изображения; связь с ним оценивается отдельно. В живой проверке нужный момент выбран и два посторонних окна отклонены, но продолжение предыдущего кадра Apple не подтвердила: связь помечена для проверки. Точность модели остаётся ограниченной.</p>'''+''.join(rows)+'</main></html>',encoding='utf-8')
    print('DONE',output,flush=True)


if __name__=='__main__':main()
