"""Small, frozen local before/after probe. Never performs stock search or cloud calls."""
import html
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reference_analysis/apple_retrieval_20261021'
SOURCE=Path('/Users/ilia/Downloads/The Real Reason Hitler Never Invaded Switzerland - Clips')


def run(*args):subprocess.run(args,check=True,capture_output=True)


def prepare():
    media=OUT/'media';media.mkdir(parents=True,exist_ok=True)
    pictures=[]
    for label,clip in [('mountain',177),('map',86),('foundry',160)]:
        picture=media/f'{label}.jpg'
        run('ffmpeg','-v','error','-y','-ss','0.4','-i',str(SOURCE/f'Clip-{clip:03}.mp4'),
            '-frames:v','1','-vf','scale=960:540',str(picture))
        pictures.append(str(picture.relative_to(OUT)))
    cases=[]
    for query,expected in [('Alpine mountain landscape',0),
            ('Men examining a large sheet of paper at a table',1),
            ('Molten metal pouring from a furnace into a container',2),
            ('A person swimming underwater',None)]:
        cases.append(dict(query=query,paths=pictures,fast=True,expected_candidate=expected))
    for label,clip,query in [('foundry',160,'Molten metal pouring from a furnace into a container'),
                            ('map',86,'Men examining a large sheet of paper at a table')]:
        parts=[]
        for i,(number,duration) in enumerate([(177,2),(clip,4),(177,9)]):
            part=media/f'{label}_part_{i}.mp4';parts.append(part)
            run('ffmpeg','-v','error','-y','-i',str(SOURCE/f'Clip-{number:03}.mp4'),'-an',
                '-vf','scale=960:540,fps=30,tpad=stop_mode=clone:stop_duration=10','-t',str(duration),
                '-c:v','libx264','-preset','fast','-crf','21',str(part))
        listing=media/f'{label}.txt';listing.write_text(''.join(f"file '{p}'\n" for p in parts))
        movie=media/f'{label}_gap.mp4'
        run('ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(movie))
        cases.append(dict(query=query,paths=[str(movie.relative_to(OUT))],fast=False,
                          expected_candidate=0,action_interval=[2,6],target_duration=2))
    catalog=json.loads((ROOT/'reference_analysis/swiss_1019_20261019/clip_catalog.json').read_text())
    (OUT/'cases.json').write_text(json.dumps(dict(
        scope='Three reference subjects, one negative query, two controlled videos with action between coarse samples. Not a measurement of whole-video matching accuracy.',
        labels='Visible content manually checked against source frames, not model-generated ground truth.',
        reference=[c for c in catalog['clips'] if c['clip'] in [86,160,177]],cases=cases),ensure_ascii=False,indent=2))
    print('Frozen six cases:',OUT/'cases.json',flush=True)


def probe(version):
    if version=='before':
        path=ROOT/'backups/before_apple_retrieval_20261021/vision_ranker.py'
        spec=importlib.util.spec_from_file_location('previous_apple_vision',path)
        model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    else:
        import vision_ranker as model
    assert model.VISION_PROVIDER=='apple','Benchmark must use Apple only'
    rows=[]
    for number,case in enumerate(json.loads((OUT/'cases.json').read_text())['cases']):
        plan=dict(query=case['query'],search_mode='broll',match_policy='illustrative',_fast_vision=case['fast'])
        started=time.monotonic()
        results=model._apple_rank(plan,[OUT/p for p in case['paths']],case.get('target_duration',2),
                                  lambda s:print(f'{version} {number+1}: {s}',flush=True))
        relevant=[r for r in results if r['relevant']]
        selected=max(relevant,key=lambda r:(r['score'],r['confidence'])) if relevant else None
        correct=(selected is None if case['expected_candidate'] is None else
                 selected is not None and selected['index']==case['expected_candidate'])
        if correct and case.get('action_interval'):
            a,b=case['action_interval']
            correct=selected['start']>=a-.05 and selected['end']<=b+.05
        rows.append(dict(case=number+1,query=case['query'],correct=bool(correct),selected=selected,
                         results=results,seconds=round(time.monotonic()-started,2)))
        (OUT/f'{version}.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    print(version,sum(r['correct'] for r in rows),'/',len(rows),flush=True)


def report():
    before=json.loads((OUT/'before.json').read_text());after=json.loads((OUT/'after.json').read_text())
    rows=[]
    for a,b in zip(before,after):
        def choice(r):
            s=r['selected']
            return 'Отклонены все' if s is None else (f"Кандидат {s['index']+1}" if r['case']<=4 else f"Кандидат {s['index']+1}, {s['start']:.2f}–{s['end']:.2f} с")
        rows.append(f'<tr><td>{a["case"]}. {html.escape(a["query"])}</td><td>{html.escape(choice(a))}<br>{"✓" if a["correct"] else "✗"}</td><td>{html.escape(choice(b))}<br>{"✓" if b["correct"] else "✗"}</td></tr>')
    table='<table><thead><tr><th>Задача</th><th>До</th><th>После</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
    extra=(f'<p><strong>Итог: {sum(r["correct"] for r in before)} из {len(before)} → {sum(r["correct"] for r in after)} из {len(after)}.</strong> '
           'В первом прогоне пример с металлом остался ошибкой Apple: модель приняла литьё за белую жидкость в миске. '
           'В рабочем поиске предусмотрена попытка другого кандидата или источника.</p>'
           '<p><a href="tests_latest.json">Последние тесты</a> · <a href="tests.json">Полный прогон</a> · '
           '<a href="protected_files.json">Защищённые файлы</a></p>'
           '<h2>Проверка основного сборщика · 4 с · 1080p/30 fps</h2>'
           '<video controls src="../../output/scene_apple_retrieval/scene_apple_retrieval.mp4"></video>')
    (OUT/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Apple: проверка подбора</title><style>body{background:#161819;color:#eee;font:16px/1.6 system-ui;max-width:1180px;margin:35px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #555;padding:14px}a{color:#e4bb74}img{width:32%}video{width:100%;max-width:900px}code{color:#e4bb74}</style><h1>Проверка Apple до и после изменения подбора</h1><p>6 небольших локальных задач: три сюжета из пользовательского референса VidRush, отрицательный запрос и два специально собранных 15-секундных исходника. В них нужное действие есть только на 2–6 секунде, между исходными редкими выборками. Это проверка конкретных сбоев; результат не показывает процент точности на 40-минутном ролике. Историческая достоверность и единство события здесь не оцениваются.</p><p>Обе версии используют тот же Apple через fm; облачных вызовов и поиска по платным источникам в проверке нет. Ожидаемые результаты зафиксированы до запуска. Предметные подписи сверены по кадрам, а не приняты из старого отчёта.</p>'''+table+extra+'''<h2>Исходные сюжеты</h2><img src="media/mountain.jpg"><img src="media/map.jpg"><img src="media/foundry.jpg"><h2>Действие между выборками</h2><video controls src="media/foundry_gap.mp4"></video><p><a href="cases.json">Условия</a> · <a href="before.json">До</a> · <a href="after.json">После</a></p></html>''',encoding='utf-8')
    print('Report:',OUT/'index.html',flush=True)


if __name__=='__main__':
    {'prepare':prepare,'before':lambda:probe('before'),'after':lambda:probe('after'),'report':report,'both':lambda:(probe('before'),probe('after'),report())}[sys.argv[1]]()
