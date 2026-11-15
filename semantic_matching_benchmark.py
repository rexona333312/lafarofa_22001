"""Frozen real corrections; local Apple only, no downloads, search or paid calls."""
import importlib.util
import html
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'reference_analysis/semantic_matching_20261021'


def probe(version):
    if version == 'before':
        spec = importlib.util.spec_from_file_location('previous_semantic_vision',
            ROOT / 'backups/before_semantic_matching_20261021/vision_ranker.py')
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
    else:
        import vision_ranker as model
    assert model.VISION_PROVIDER == 'apple'
    rows = []
    for case in json.loads((OUT / 'cases.json').read_text()):
        started = time.monotonic()
        plan = {**case['plan'], '_candidate_metadata': case['metadata'], '_fast_vision': True}
        results = model._apple_rank(plan, [OUT / p for p in case['paths']], 3,
            lambda s: print(f'{version} {case["chunk_id"]}: {s}', flush=True))
        rows.append(dict(scene=case['scene'], chunk_id=case['chunk_id'], expected=case['expected'],
            results=results, correct=[r['relevant'] == e and
                                      (bool(r.get('match_checks')) or not r.get('needs_review'))
                                      for r, e in zip(results, case['expected'])],
            seconds=round(time.monotonic() - started, 2)))
        (OUT / f'{version}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(version, sum(sum(r['correct']) for r in rows), '/', sum(len(r['correct']) for r in rows), flush=True)


def report():
    before = json.loads((OUT / 'before.json').read_text())
    after = json.loads((OUT / 'after.json').read_text())
    controls = json.loads((OUT / 'controls.json').read_text())
    rows = []
    labels = ['Другой человек с похожим именем', 'Фототехника вместо портрета', 'Открытка вместо обложки пластинки']
    for label, old, new in zip(labels, before, after):
        cells = []
        for row in (old, new):
            bad, good = row['results']
            cells.append('<td>Неподходящий: <b>' + ('принят' if bad['relevant'] else 'отклонён') +
                '</b><br>Твоя замена: <b>' + ('принята' if good['relevant'] else 'отклонена') + '</b></td>')
        rows.append('<tr><td>' + label + '</td>' + ''.join(cells) + '</tr>')
    check_rows = ''.join('<tr><td>' + html.escape(c['label']) + '</td><td>' +
        ('Пройдено' if c['correct'] else 'Ошибка') + '</td><td>' +
        html.escape(c['result']['reason']) + '</td></tr>' for c in controls)
    tests = json.loads((OUT / 'tests.json').read_text()) if (OUT / 'tests.json').exists() else {}
    focused = json.loads((OUT / 'tests_focused.json').read_text()) if (OUT / 'tests_focused.json').exists() else {}
    test_text = (f"Полный прогон: {tests.get('total', 'ожидается')} тестов. "
        'Осталась прежняя ошибка теста PhotoCamera: он требует Remotion при существующем FFmpeg backend. '
        f'Профильный прогон: {focused.get("total", "ожидается")} тестов, код завершения {focused.get("exit_code", "ожидается")}. '
        'Подробности и все ошибки — в журнале.')
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проверка соответствия материалов сценарию</title><style>
body{font:16px/1.6 system-ui;background:#17191b;color:#f1f0e9;max-width:1120px;margin:40px auto;padding:0 24px 70px}
h1{font-size:36px;line-height:1.2}h2{margin-top:44px;font-size:24px}p{max-width:900px}a{color:#e9bd79}
table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;padding:15px;border-bottom:1px solid #444}
img,video{width:100%;height:auto}b{color:#e7c58f}.note{border-left:3px solid #d6b77f;padding-left:18px}
@media(max-width:700px){body{margin:24px auto;padding:0 14px}h1{font-size:28px}td,th{padding:9px;font-size:14px}}
</style><h1>Соответствие материалов сценарию</h1><p>21 октября 2026 · текущая версия · тот же локальный Apple Vision</p>
<p>Улучшены проверка источника, имён, произведения, видимого формата и обязательного контекста. Отдельное несоответствие отклоняет материал независимо от общего балла. Полные алиасы и обязательные признаки используются в повторном поиске; бюджет поиска сохранён.</p>
<h2>Три реальные ошибки из сохранённых проектов</h2>
<p>До: 3 из 6 решений верны. После: 6 из 6. Неподходящие исходники отклонены; три выбранные тобой замены приняты. Положительные ручные примеры имеют подтверждённую редактором личность: это проверка их пригодности, а не самостоятельного распознавания лица.</p>
<table><thead><tr><th>Ошибка</th><th>До</th><th>После</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table>
<p>Слева — прежний исходник, справа — сохранённая ручная замена.</p><img src="pairs.jpg" alt="Три пары исходников до и после ручной замены">
<h2>Контроль общих правил</h2><p>4 из 4 контрольных задач. В примере с годом метаданные специально заданы как 2024 при требовании 1940: это проверка противоречия, а не утверждение о дате фотографии.</p>
<table><thead><tr><th>Условие</th><th>Результат</th><th>Объяснение Apple</th></tr></thead><tbody>''' + check_rows + '''</tbody></table>
<h2>Превью основного сборщика</h2><p>6 секунд · 1920×1080 · 30 fps · три принятых изображения · без озвучки. Полное декодирование FFmpeg прошло без ошибок.</p>
<video controls preload="metadata" poster="../../output/scene_semantic_matching/preview.jpg" src="../../output/scene_semantic_matching/scene_semantic_matching.mp4"></video>
<h2>Проверки</h2><p>''' + html.escape(test_text) + '''</p>
<p><a href="tests.json">Сводка тестов</a> · <a href="tests.log">Полный журнал</a> · <a href="tests_focused.json">Профильные тесты</a> · <a href="protected_files.json">37 защищённых файлов</a> · <a href="preview_verification.json">Проверка видео</a></p>
<p><a href="cases.json">Зафиксированные пары</a> · <a href="before.json">Apple до</a> · <a href="after.json">Apple после</a> · <a href="controls_cases.json">Условия контроля</a> · <a href="controls.json">Результаты контроля</a></p>
<p>Промежуточные неудачные варианты сохранены: <a href="after_attempt1.json">первый</a>, <a href="after_attempt2.json">второй</a>, <a href="after_attempt3.json">третий</a>. Во время проверки не выполнялись внешние поисковые запросы и вызовы платных моделей.</p>
<h2>Как запустить</h2><p>Перезапусти приложение и выполни новый поиск. В старых проектах используй повторный поиск нужного кадра; сохранённые ручные замены не перезаписывались. Новые необязательные поля плана: work_title и required_format; роль, место и период передаются через context.</p>
<p class="note">Это небольшой диагностический набор. Он не измеряет точность на новом политическом или военном ролике и не подтверждает 15 минут правок на 40 минут видео. Apple может ошибаться. Дополнительные локальные проверки увеличивают время подбора; облачная модель не добавлялась.</p></html>'''
    (OUT / 'index.html').write_text(page, encoding='utf-8')
    print(OUT / 'index.html')


if __name__ == '__main__':
    report() if sys.argv[1] == 'report' else probe(sys.argv[1])
