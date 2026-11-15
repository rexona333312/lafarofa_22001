# Пресеты V2

Доступны одиночные кадры: PHOTO_STATIC, PHOTO_SLOW_ZOOM, PHOTO_SLOW_ZOOM_OUT, PHOTO_PAN, BLUR_BG_CENTER, BLUR_BG_STATIC, ARCHIVE_PAPER.

С 2026-10-06 обычное движение фотографий снова рендерит FFmpeg: PHOTO_SLOW_ZOOM, PHOTO_SLOW_ZOOM_OUT, PHOTO_PAN, BLUR_BG_CENTER и движение ARCHIVE_PAPER/пользовательских zoom_start/zoom_end. Используется zoompan с плавной косинусной кривой, обработкой в увеличенном разрешении 4× и уменьшением через Lanczos. Имена пресетов и существующие timeline JSON сохраняются. PHOTO_STATIC/BLUR_BG_STATIC без пользовательского движения остаются неподвижными, включая автоматический размытый фон. Remotion используется для монтажных шаблонов, аватара и текстовой графики; FFmpeg собирает видео и звук.

Фото-плашки Remotion сохраняют пропорции исходного фото и небольшое закругление. Доступны прежние бумажные шаблоны и blur-in, fade-in, scale-in, spring-in.

Представление персонажа: `person_intro_left`, `person_intro_center`, `person_intro_right`. Только фотография одного человека. Фон вырезается локально U²-Net и сохраняется в кэше; прозрачный PNG используется напрямую. Человек, подпись и стрелка плавно входят снизу. Обязателен `params.person_name`; `params.person_role` — дополнительная подпись. `params.background` выбирает существующее изображение из `assets/backgrounds/` или `assets/paper/`; по умолчанию используется бумага. Отдельный text_cue для такого кадра не нужен. Установка: `pip install -r requirements-person-intro.txt` в окружении приложения.


Переходы: cut, fade, crossfade, blur-reveal, frosted-glass-wipe, transition-fade, transition-wipe, directional-wipe и библиотечные Light Leaks. По умолчанию cut; переходы выбираются по смыслу, обязательной квоты нет. Light Leaks используют screen и opacity 1.

SPLIT_SCREEN, PHOTO_COLLAGE, FILM_LOOK, ARCHIVE_FILM, CINEMATIC_GRADE, UNDERWATER_GRADE, spin, whip_pan, zoom_blur, slide и glitch-переходы отключены. Поле panels и непустое effects отклоняются при проверке. ARCHIVE_PAPER сохранён.

В режиме ИИ-аватар доступны отдельные Remotion-композиции `avatar_full`, `avatar_left`, `avatar_right`. Они используют поле `avatar` для клипа ведущей и один обычный фон кадра для бокового варианта; поле `panels` не требуется. Исходный звук обоих видео отключён, общая озвучка сохраняется. Формат и параметры: [AVATAR_MODE.md](../AVATAR_MODE.md).

Дополнительные layers и audio_tracks добавляются только по отдельной просьбе. По умолчанию сохраняется пользовательская озвучка.


Доступны 7 текстовых шаблонов Remotion: marker_highlight, question_panel_bottom, question_panel_top, impact_typewriter, speech_words_grid, speech_words_overlay, selective_marker (kind:accent). Карты: map_geographic или map_annotations с params.geo; режим карты-картинки отключён. Старые проекты при загрузке сохраняют материалы и таймкоды, удалённые эффекты пропускаются.
