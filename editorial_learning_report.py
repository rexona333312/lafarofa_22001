"""Read-only audit of saved corrections and a local reuse/Apple diagnostic."""
from concurrent.futures import ThreadPoolExecutor
import copy
import html
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps
import editorial_learning as learning
import stock_downloader as media

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'reference_analysis/editorial_learning_20261021'
SCENES = ['scene_009', 'scene_010', 'scene_012', 'scene_013']


def _load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def _samples(path):
    if not path or not path.is_file():return []
    if path.suffix.lower() in learning.IMAGE_SUFFIXES:
        with Image.open(path) as im:return [im.convert('RGB').copy()]
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
        '-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True))
    samples=[]
    for t in [0,duration/2,max(0,duration-.12)]:
        result=subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1',
            '-vf','scale=320:180:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True)
        with Image.open(io.BytesIO(result.stdout)) as im:samples.append(im.convert('RGB').copy())
    return samples


def prepare():
    OUT.mkdir(exist_ok=True,parents=True)
    old_media=_load('old_match_helpers',ROOT/'backups/before_editorial_learning_20261021/media_matching.py')
    old=_load('old_retrieval_rules',ROOT/'backups/before_editorial_learning_20261021/stock_downloader.py')
    old.requested_work=old_media.requested_work
    rows=[]
    for scene in SCENES:
        data=json.loads((ROOT/'output'/scene/'project.json').read_text())
        for chunk in data['chunks']:
            chosen=data.get('file_overrides',{}).get(str(chunk['id']),chunk.get('files',[])[:1])
            if not any(name.startswith('user_') for name in chosen):continue
            originals=[n for n in chunk.get('files',[]) if not n.startswith('user_')]
            name=originals[0] if originals else None
            asset=data.get('assets',{}).get(name,{})
            details=(asset.get('search_text',''),asset.get('page_url',''))
            rows.append(dict(scene=scene,chunk_id=chunk['id'],plan=chunk,selected=chosen,original=name,
                original_exists=bool(name and (ROOT/'output'/scene/'downloads'/name).is_file()),
                source=asset,metadata_before=old._matches_plan(chunk,*details) if name else None,
                metadata_after=media._matches_plan(chunk,*details) if name else None,
                reason_for_edit='Not recorded: upload/selection is not proof of a specific semantic failure.'))
    notes_path=OUT/'visual_notes.json'
    notes=json.loads(notes_path.read_text()) if notes_path.exists() else {}
    for row in rows:row['visual_notes']=notes.get(row['scene'],{}).get(str(row['chunk_id']),'')
    def preview(row):
        tile=Image.new('RGB',(660,360),'#202326');draw=ImageDraw.Draw(tile)
        try:font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',13)
        except OSError:font=ImageFont.load_default()
        draw.text((10,5),f'{row["scene"]} #{row["chunk_id"]} | '+row['plan']['query'][:76],font=font,fill='white')
        for position,name in enumerate([row['original'],row['selected'][0]]):
            path=ROOT/'output'/row['scene']/'downloads'/name if name else None
            try:pictures=_samples(path)
            except (OSError,ValueError,subprocess.SubprocessError):pictures=[]
            if row['plan']['type']=='video':
                y=32+position*142
                draw.text((10,y),('ORIGINAL' if position==0 else 'EDITOR CHOICE')+' | start / middle / end',font=font,fill='#dfc698')
                for i,im in enumerate(pictures):tile.paste(ImageOps.contain(im,(210,118)),(10+216*i,y+20))
            else:
                x=10+position*326
                draw.text((x,32),'ORIGINAL' if position==0 else 'EDITOR CHOICE',font=font,fill='#dfc698')
                if pictures:tile.paste(ImageOps.contain(pictures[0],(310,245)),(x,52))
            if not pictures:draw.text((10+position*326,80),'No retained media',font=font,fill='#aaa')
        draw.text((10,326),row['source'].get('search_text','No previous candidate')[:95],font=font,fill='#ddd')
        return tile
    with ThreadPoolExecutor(max_workers=3) as pool:
        tiles=list(pool.map(preview,rows))
    for start in range(0,len(rows),6):
        board=Image.new('RGB',(1320,1080),'#17191b')
        for offset,tile in enumerate(tiles[start:start+6]):board.paste(tile,((offset%2)*660,(offset//2)*360))
        name=f'pairs_{start//6+1:02}.jpg';board.save(OUT/name,quality=88)
        for row in rows[start:start+6]:row['contact_sheet']=name
    (OUT/'audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    stats=dict(manual=len(rows),photos=sum(r['plan']['type']=='photo' for r in rows),
        videos=sum(r['plan']['type']=='video' for r in rows),old_candidates=sum(r['original'] is not None for r in rows),
        old_media=sum(r['original_exists'] for r in rows),
        metadata_rejected_before=sum(r['metadata_before'] is False for r in rows),
        metadata_rejected_after=sum(r['metadata_after'] is False for r in rows),
        newly_rejected=sum(r['metadata_before'] is True and r['metadata_after'] is False for r in rows),
        approved_photos=len(learning.load_approved(ROOT/'output')))
    (OUT/'summary.json').write_text(json.dumps(stats,indent=2));print(stats,flush=True)


def preview():
    from ffmpeg_builder import build_video
    rows=json.loads((OUT/'audit.json').read_text())
    case=next(r for r in rows if r['scene']=='scene_013' and r['chunk_id']==80)
    entries=learning.load_approved(ROOT/'output');used=set();chunks=[];assets={};sources=[]
    target=ROOT/'output/scene_editorial_learning';target.mkdir(exist_ok=True)
    for i in range(4):
        plan=copy.deepcopy(case['plan']);plan.update(id=i,start=i*1.5,end=(i+1)*1.5,duration=1.5)
        result=learning.reuse_approved(plan,entries,target,i,used)
        if not result:break
        path,asset=result;sources.append(asset['approved_from'])
        assets[Path(path).name]=asset
        chunks.append(dict(type='photo',query=plan['query'],start=i*1.5,end=(i+1)*1.5,duration=1.5,
            preset='PHOTO_STATIC',params={'fit':'contain'},_files=[path]))
    assert len(chunks)==4, len(chunks)
    result,_=build_video(chunks,str(target),'scene_editorial_learning',progress_callback=lambda s:print(s,flush=True))
    subprocess.run(['ffmpeg','-v','error','-i',result,'-f','null','-'],capture_output=True,check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',result],text=True))
    (OUT/'reuse_demo.json').write_text(json.dumps(dict(chunks=chunks,assets=assets,sources=sources,
        external_requests=0,probe=probe,video=result,decode='passed'),ensure_ascii=False,indent=2))
    print(result,flush=True)


def probe():
    import vision_ranker as vision
    assert vision.VISION_PROVIDER=='apple'
    rows=json.loads((OUT/'audit.json').read_text());results=[]
    for cid in [38,139]:
        row=next(r for r in rows if r['scene']=='scene_013' and r['chunk_id']==cid)
        for name,expected in [(row['original'],False),(row['selected'][0],True)]:
            path=ROOT/'output'/row['scene']/'downloads'/name
            plan={**row['plan'],'_fast_vision':True,'_candidate_metadata':[dict(
                title=row['source'].get('search_text','') if not name.startswith('user_') else '',
                source=row['source'].get('source',''),user_supplied=name.startswith('user_'))]}
            started=time.monotonic()
            result=vision._apple_rank(plan,[path],min(2.,plan['duration']),lambda s:print(f'{cid}: {s}',flush=True))[0]
            results.append(dict(chunk_id=cid,file=name,expected=expected,result=result,
                correct=result['relevant']==expected and bool(result.get('match_checks')),
                seconds=round(time.monotonic()-started,2)))
            (OUT/'apple_video.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print('Apple video:',sum(r['correct'] for r in results),'/',len(results),flush=True)


def report():
    rows=json.loads((OUT/'audit.json').read_text());stats=json.loads((OUT/'summary.json').read_text())
    video=json.loads((OUT/'apple_video.json').read_text()) if (OUT/'apple_video.json').exists() else []
    tests=json.loads((OUT/'tests.json').read_text()) if (OUT/'tests.json').exists() else {}
    focused=json.loads((OUT/'tests_focused.json').read_text()) if (OUT/'tests_focused.json').exists() else {}
    table=[]
    for row in rows:
        status='Нет прежнего кандидата' if row['original'] is None else ('Не проходит ограничения метаданных' if row['metadata_after'] is False else 'Причину замены нужно уточнять по содержимому/моменту')
        table.append('<tr><td>'+row['scene']+' · '+str(row['chunk_id']+1)+'</td><td>'+html.escape(row['plan']['query'])+
            '</td><td>'+html.escape(row['source'].get('search_text','—'))+'</td><td>'+status+
            '<br>'+html.escape(row.get('visual_notes',''))+'</td><td><a href="'+row['contact_sheet']+'">Кадры</a></td></tr>')
    pictures=''.join('<details><summary>Контактный лист '+str(i)+'</summary><img loading="lazy" src="pairs_'+f'{i:02}'+'.jpg"></details>' for i in range(1,(len(rows)+5)//6+1))
    videorows=''.join('<li>Кадр '+str(r['chunk_id']+1)+' · '+('ручная замена' if r['expected'] else 'прежний кандидат')+': '+
        ('принят' if r['result']['relevant'] else 'отклонён')+' · '+html.escape(r['result']['reason'])+'</li>' for r in video)
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Память правок и подбор материалов</title><style>
body{background:#171a1c;color:#eee;font:16px/1.65 system-ui;max-width:1200px;margin:40px auto;padding:0 24px 60px}h1{font-size:36px;line-height:1.15}h2{margin-top:40px}a{color:#e2bd81}td,th{padding:12px;border-bottom:1px solid #444;text-align:left;vertical-align:top}table{border-collapse:collapse;font-size:14px;width:100%}video,img{max-width:100%;height:auto}details{margin:18px 0}strong{color:#e2bd81}.note{border-left:3px solid #e2bd81;padding-left:18px}</style>
<h1>Память правок и проверка готового видеоряда</h1><p>21 октября 2026 · текущая версия · Apple Vision</p>
<p>Проверены сохранённые состояния четырёх проектов: <strong>'''+str(stats['manual'])+''' ручных выборов</strong>, '''+str(stats['photos'])+''' фото и '''+str(stats['videos'])+''' видео. Для '''+str(stats['old_candidates'])+''' есть запись прежнего кандидата; сами прежние файлы доступны в '''+str(stats['old_media'])+''' случаях. Для видео извлечены начало, середина и конец. Причины кликов не записывались: правильное имя или название не объясняют, почему редактор заменил качество, момент или ракурс.</p>
<h2>Что изменилось</h2><ul><li>Выбранные редактором фото стали локальной библиотекой: '''+str(stats['approved_photos'])+''' уникальных изображений с пригодным профилем запроса. Для исторических ручных загрузок автоматически заимствуются портреты; точные произведения и документы требуют актуальной проверки. Учитываются сущность, явный контекст, дата, формат, роль и ограничения; один файл не используется несколько раз в одном поиске. Видео автоматически не переносятся между событиями.</li>
<li>Одна новая загрузка или выбор может исправить ещё до двух совместимых незаполненных/сомнительных кадров. Ручные выборы, соседний кадр и подтверждённые актуальной проверкой материалы сохраняются. Причина правки записывается как неизвестная, а не придумывается.</li>
<li>Произведение проверяется вместе с автором/исполнителем и видом: сценическая постановка не совпадает с бытовым значением слова. На сохранённых метаданных добавлены '''+str(stats['newly_rejected'])+''' отказов, которые прежние правила пропускали. Это проверка фильтра, не измерение общей точности.</li>
<li>Для интервью/исполнения/действия отдельно проверяются реальное движение, заставка и фото под музыку. В музыкальных превью сохраняется звук; тишина отклоняется, при одинаковом смысловом балле предпочтительнее окно с большей долей слышимого звука. Это не распознавание текста песни.</li>
<li>После подбора сравниваются реальные изображения: если рядом повторяется фото, выбирается другая уже подтверждённая версия из пула. Если её нет — показывается предупреждение. Три одинаковых фактических плана при запланированной смене крупности тоже отмечаются. Решение редактора не переставляется.</li></ul>
<h2>Демонстрация повторного использования</h2><p>Четыре ранее выбранных изображения из совместимых запросов. <strong>Ноль внешних поисковых запросов.</strong> 6 секунд, основной сборщик, полное декодирование без ошибок. Это демонстрация библиотеки, а не готовый документальный эпизод.</p><video controls src="../../output/scene_editorial_learning/scene_editorial_learning.mp4"></video>
<h2>Локальная проверка Apple на видео</h2><ul>'''+videorows+'''</ul><p>Условия: прежние кандидаты из двух музыкальных/интервью сцен и сохранённые ручные замены. Ручная личность подтверждена редактором; пригодность кадров проверяется моделью. Неудачные результаты остаются в журнале.</p>
<p><a href="apple_video_attempt1.json">Первый прогон</a> · <a href="apple_video_attempt2.json">Второй прогон</a> — оба содержат сохранённый отказ настоящему интервью до исправления классификации крупного плана.</p><h2>Все 57 сохранённых замен</h2><table><thead><tr><th>Проект / кадр</th><th>Запрос</th><th>Прежний источник</th><th>Проверка</th><th>Просмотр</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table>'''+pictures+'''
<h2>Проверки и данные</h2><p>Полный прогон: '''+str(tests.get('total','ожидается'))+''' тестов; журнал содержит итог и все ошибки. Профильный прогон финального кода: '''+str(focused.get('total','ожидается'))+''' тестов, код завершения '''+str(focused.get('exit_code','ожидается'))+'''. Известный прежний тест PhotoCamera требует Remotion при FFmpeg backend.</p><p><a href="audit.json">Полные записи</a> · <a href="summary.json">Сводка</a> · <a href="apple_video.json">Apple: результаты видео</a> · <a href="reuse_demo.json">Источники превью</a> · <a href="tests.log">Полный журнал</a> · <a href="tests_focused.log">Профильные тесты</a> · <a href="ui_checks.json">Проверки интерфейса</a> · <a href="protected.json">Защищённые файлы</a></p>
<p class="note">Архивные проекты анализировались без изменения. Новые действия сохраняются с предыдущим и новым выбором, запросом и прежними источниками; прошлую полную историю кликов восстановить нельзя. Новая версия не обучает веса Apple и не воспроизводит внутренний алгоритм VidRush. Результат «15 минут правок на 40 минут ролика» ещё не измерен. При несовпадении профиля выполняется обычный поиск.</p></html>'''
    (OUT/'index.html').write_text(page,encoding='utf-8');print(OUT/'index.html')


if __name__=='__main__':
    {'prepare':prepare,'preview':preview,'probe':probe,'report':report}[sys.argv[1]]()
