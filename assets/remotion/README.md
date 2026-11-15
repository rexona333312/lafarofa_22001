# Remotion-карточки в timeline.json

## V2 — Motion, текст и переходы

Все компоненты установлены локально в `paper_card/src/remotion/`. При сборке AI не вызывается.
Исключение — новые шаблоны представления персонажа: перед Remotion локальная U²-Net отделяет человека от фона. Платный API не используется.
Пример импорта: `../../examples/timeline_remotion_v2.json` (озвучка для этого примера — 12 секунд).

Фото/видео: `chunk.template` принимает `blur-in`, `fade-in`, `scale-in`, `spring-in`.
Размер плашки рассчитывается по исходным пропорциям материала, без кадрирования в фиксированную рамку.
Сохранены поля 14 px, радиус внешних углов 28 px и внутренних 15 px, как у PaperCard.
`chunk.params.arrival_frames` — длительность появления (1–120 кадров, по умолчанию 27);
`corner_radius` — внешний радиус (0–60 px); `paper` — существующий фон из `assets/paper/`.
При импорте фон выбирается и сохраняется автоматически. SFX — случайный whoosh.mp3, woosh1.wav или woosh2.wav, громкость 30% от исходной.

### Представление персонажа

`person_intro_left`, `person_intro_center`, `person_intro_right` размещают вырезанного человека слева, по центру или справа. Все варианты плавно появляются из-за нижнего края кадра. Имя и подпись входят следом, изогнутая стрелка прорисовывается. Фон затемняется, становится чёрно-белым и размытым. Центральный вариант сохраняет подпись справа от человека.

```json
{
  "type": "photo",
  "query": "Donald Trump portrait",
  "start": 0,
  "end": 5,
  "template": "person_intro_left",
  "params": {
    "person_name": "Donald Trump",
    "person_role": "President of the United States",
    "background": "backgrounds/white_house.jpg",
    "arrival_frames": 36,
    "background_blur": 8
  }
}
```

Имя обязательно (до 100 символов), подпись необязательна (до 160). Только фото; видео не поддерживается. `background` — существующий файл из `backgrounds/` или `paper/`; без него применяется бумажный фон. Вырезка сохраняется в `.render_cache/person_cutout_*.png` отдельно от видеорендера и переиспользуется между вариантами. Прозрачный PNG можно загрузить вручную, тогда модель не нужна. Исходное фото не меняется. Установка локального обработчика: `pip install -r requirements-person-intro.txt`; первая обработка скачивает модель, следующие используют её с диска.

Пример с тремя вариантами: `examples/timeline_person_intro.json`. Проверка: `.venv/bin/python -m unittest test_person_intro -q`. Демонстрация с фотографией Трампа: `.venv/bin/python person_intro_demo.py`.

Текст задаётся в `text_cues` с `kind:accent`, `text` и именем из этого списка:

| Шаблон | Назначение |
|---|---|
| `marker_highlight` | Фраза с жёлтым маркером |
| `question_panel_bottom` | Красная панель входит снизу к центру |
| `question_panel_top` | Красная панель входит сверху к центру |
| `impact_typewriter` | Короткий ударный текст по таймкодам слов |
| `speech_words_grid` | Слова по речи на графической сетке |
| `speech_words_overlay` | Слова по речи поверх видеоряда |
| `selective_marker` | Выделение выбранных диапазонов слов |

Remotion рисует их автоматически; ручные экспорты CapCut этим шаблонам не нужны.
`chunk_index` задаёт полную длительность кадра; `start`/`end` — абсолютное время.
Одна вставка на кадр. Для слов по речи нужны таймкоды WhisperX.
Шрифт `coolvetica` загружается локально; текст строчный, кроме КАПСА `impact_typewriter`.
Изменение текста, таймингов или исходников обновляет соответствующий кэш.

Переходы: `transitions[].kind` принимает `blur-reveal`, `frosted-glass-wipe`, `transition-fade`,
`transition-wipe`, `directional-wipe`. Окно `start`/`end` симметрично окружает один стык,
длительность 0.2–2 секунды, окна не пересекаются. Общее время фильма и озвучки сохраняется.
`params.variant`: `editorial` (по умолчанию), `linear` или `spring`;
`params.direction` для шторок: `from-left`, `from-right`, `from-top`, `from-bottom`.
Дополнительно: blur-reveal — `maxBlur`, `scaleBy`; frosted-glass-wipe — `blur`, `panelWidth`, `frostColor`;
transition-fade — `dipTo`; directional-wipe — `edgeSoftness`, `depth`. Цвета — #RRGGBB.

Карточки, переходы и текст используют существующий `.render_cache`.
Изменение текста, таймингов, настроек или исходников компонента обновляет нужный рендер.
Проверка из `video_assembler`: `.venv/bin/python test_remotion_v2.py`.
Проверка с сохранением демонстрации: `.venv/bin/python test_remotion_v2.py --preview output/remotion_v2_demo`.

В `chunk` добавь `template`: `paper_card_top_right`, `paper_card_bottom_left` или `paper_card_bottom`. После выбора материала сборщик подставит первое выбранное фото или видео в карточку; звук исходного видео отключён. При импорте шаблонного кадра софт выбирает случайный фон из `assets/paper/` и записывает его в `params.paper`, чтобы повторный рендер сохранил тот же фон. Можно указать фон вручную (например, `paper/paper2.jpg`). Длительность берётся из `start`/`end` кадра. SFX из `REMOTION_SOUNDS` в `presets/__init__.py` включается в кадре появления карточки и смешивается с озвучкой. Для всех плашек whoosh выбирается случайно из whoosh/woosh1/woosh2 и звучит на первом кадре с громкостью 30%.

```json
{
  "type": "photo",
  "query": "historical photograph",
  "start": 0,
  "end": 5,
  "template": "paper_card_bottom_left"
}
```

Для рендера нужны Node.js, FFmpeg и зависимости Remotion: однократно выполни `cd assets/remotion/paper_card && npm ci`. Код композиции лежит в `paper_card/src/index.jsx`. Для нового варианта зарегистрируй его в `REMOTION_TEMPLATES` и свой файл/кадр начала SFX в `REMOTION_SOUNDS`; сам звук положи в `assets/sfx/`. Дополнительные бумажные фоны клади в `assets/paper/`.




Доступны 7 текстовых шаблонов Remotion: marker_highlight, question_panel_bottom, question_panel_top, impact_typewriter, speech_words_grid, speech_words_overlay, selective_marker (kind:accent). Карты: map_geographic или map_annotations с params.geo; режим карты-картинки отключён. Старые проекты при загрузке сохраняют материалы и таймкоды, удалённые эффекты пропускаются.
