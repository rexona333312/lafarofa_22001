from music_inserts import bind_music_words, inserted_duration, shifted_words
import os
import re
import math
import shutil
import json
import queue
import threading
import importlib
import subprocess
import io
import uuid
import copy
import random
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, Response, stream_with_context, send_file, jsonify

from config import OUTPUT_DIR
from whisperx_transcriber import transcribe_audio, LANGUAGES, DEFAULT_LANGUAGE
from stock_downloader import (youtube_clip_request, download_youtube_clip, download_for_chunk, is_rejected_stock_preview, _has_minimum_image_resolution,
                              validate_search_plan, SEARCH_FIELDS, inherit_main_entity, retrieval_context,
                              canonical_media_url, image_perceptual_hash, DEFAULT_QUERY_BUDGET, ENTITY_TYPES)
from clip_ranker import rank_files, selection_review
from editorial_learning import load_approved, reuse_approved, record_choice, propagate_choice
from footage_sequence import balance_sequence
from ffmpeg_builder import build_video, check_ffmpeg, _probe_duration
from text_overlays import normalize_text_cues, task_status, require_text_exports, write_task_list, export_folder, TEXT_COMPONENTS
from retired_templates import without_retired_templates
from presets import PRESETS, library_catalog, validate_scene, validate_tracks, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from presets import dimensions, BUILTIN_TRANSITIONS, REMOTION_TEMPLATES, TRANSITION_INSTRUCTIONS
from narrative_templates import SPEECH_TEXT, carousel_groups
from reference_templates import comparison_groups
from editorial_planning import graphics_target, graphics_summary, PLANNER_RULES
from shot_planning import (EDITING_RULES, apply_photo_intent, retrieval_groups, shot_context, editing_summary)
from geographic_maps import is_geo_scene, graphic_placeholder
from varagent_import import inspect_project, import_media, planning_input, codex_plan, apply_motion_plan, PLAN_SCHEMA
from avatar_templates import (AVATAR_TEMPLATES, validate_video_mode, planner_payload,
                              resolve_avatar_chunks, probe_video, ai_prompt_manifest, timeline_summary,
                              validate_avatar_workflow, validate_dreamina_chunks, avatar_tasks, avatar_span, avatar_interval,
                              zoom_avatar_video)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

_SAFE_NAME = re.compile(r'^[a-zA-Z0-9_\-]+$')
_SAFE_FILE = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".wma"}
_PROCESSING_MODES = {"fast", "quality"}
SOURCE_LABELS = {"cs": "Zdroj", "de": "Quelle", "en": "Source", "es": "Fuente", "pl": "Źródło"}
LUNA_INSTRUCTIONS = (
    "Музыкальная пауза: отдельный chunk type:video, music_insert:true, duration:1–5 секунд, word_range:[i,i], text:пустая строка; остальные диапазоны покрывают исходные слова. Паузу ставь только по просьбе пользователя. Софт сдвигает озвучку и сохраняет звук выбранного клипа. Все start/end и text_cues/transitions после пауз указывай уже со сдвигом. "
    "Ты документальный монтажёр. Верни только timeline JSON с chunks, transitions, audio_tracks и text_cues. "
    "Работаем исключительно с реальными найденными материалами, без AI-генерации, аватаров и новой озвучки. "
    "Цель видеоряда: примерно 70% фото и 30% видео ПО ДЛИТЕЛЬНОСТИ. Видео выбирай для значимого движения/действия, "
    "фото для портретов, мест, объектов и документов. Бесплатные стоки — последняя ступень. "
    "Сначала выдели смысловые сцены, затем отдельные кадры внутри каждой: один chunk = один кадр. "
    "Несколько кадров одной сцены имеют одинаковый scene_id. Не объединяй разные объекты в один поисковый запрос. "
    "Правила монтажа из разбора референса vidrush1: сначала определи роль фразы — место, герой, действие, предмет, "
    "дата, причинная связь, сопоставление, оговорка, вопрос или вывод; затем выбери видимый материал и подходящий приём. "
    "Эти роли универсальны для истории, политики, науки и технологий; тема ролика сама по себе не назначает шаблон. "
    "Граница клипа детектора не равна границе смысловой сцены: продолжение одной анимации/мысли оставляй в одной сцене; "
    "новую сцену начинай при смене задачи рассказа, а отдельный кадр — при смене видимого объекта или действия. "
    "Пространственные отношения объясняй map_geographic (реальная география), последовательные этапы или предметы — photo_carousel, "
    "год с упомянутым предметом — history_timeline, первого значимого героя — person_intro либо portrait_profile для цельного портрета в рамке. "
    "Одновременное сопоставление двух версий/свидетельств показывай paired_evidence, дату без предмета — date_countback, "
    "начало новой смысловой главы — chapter_heading, короткое утверждение с атрибуцией источнику — editorial_statement. "
    "Не подменяй сравнение двух версий перелистыванием. Интервал подтверждённых дат показывай date_interval; не подменяй интервал обратным отсчётом. "
    "Не выводи служебное имя шаблона на экран. "
    "У текстовых акцентов есть иерархия: impact_typewriter — главный короткий смысловой поворот, speech_words — "
    "пояснение средней силы, marker — ключевые данные или действия, question_panel — вопрос/противопоставление/вывод. "
    "Сначала выбери один главный акцент смысловой сцены, затем только необходимые пояснения; между акцентами оставляй "
    "обычные фото/видео. Наличие вопросительного предложения не требует плашки для каждого вопроса. "
    "На начале новой смысловой части допустим более заметный переход из существующей библиотеки; "
    "внутри продолжающегося действия переход не должен отвлекать от связи кадров. Не назначай засветки/глитчи каждому стыку. "
    "Сохраняй отрицания, условия и степень уверенности: «не утверждаю X», «возможно X», «по словам свидетеля X» "
    "не превращай подписью или видеорядом в «X доказано». Не иллюстрируй отрицание буквальным кадром утверждаемого события. "
    "Проверяй материал по всей фразе: кто, что делает, с каким предметом, где и в каком времени. "
    "Совпадения по одному слову недостаточно; случайный интерьер или предмет не заменяет нужное действие. "
    "Архивный документ, реконструкция и современная иллюстрация не становятся первоисточником только из-за оформления. "
    "При отсутствии точного материала используй явно иллюстративный fallback той же сущности/действия, "
    "поясни ограничение в editor_note_ru; не выдавай фото ловушки за найденные остатки конкретного события. "
    "Названия, цифры, признаки и даты на графике бери из сценария; не добавляй увиденные в чужом референсе факты. "
    "Если в word_timestamps есть пробел, сохраняй интервал и не сочиняй пропущенные слова или синхронизацию; "
    "точную печать/появление по словам назначай только там, где есть реальные таймкоды выбранных слов. "
    "Финал может вернуться к ранее показанному месту/предмету, если сценарий делает смысловой возврат; "
    "повтор материала должен поддерживать этот возврат, а не заполнять пустоту случайным кадром. "
    "В V2 каждый chunk получает один выбранный материал; карты с geo и data_comparison вместо поиска строят изображение из своих данных. panels и обработки effects не используй. "
    "Исключение по композиции — paired_evidence: два соседних chunks с отдельными поисками образуют одну непрерывную сцену с двумя фото. "
    "Ритм определяется смыслом, обычно кадр 3–8 секунд; не режь механически через равные интервалы. "
    "При смене объекта или действия меняй кадр, даже внутри длинного предложения. Не используй panels вместо последовательности кадров. "
    "Сохрани весь текст и порядок озвучки, не добавляй фактов. Таймкоды только из word_timestamps; первый start=0, последний end=audio_duration; если есть music_insert — end=audio_duration плюс сумма музыкальных пауз. "
    "Предпочтительно для каждого chunk задай word_range:[first,last_exclusive] — индексы слов с нуля; диапазоны непрерывны и покрывают ВСЕ слова. "
    "Программа привяжет границы к началу первого слова следующего кадра, паузы останутся в предыдущем. "
    "Формат chunk: {scene_id:1,type:photo|video,word_range:[0,12],start:0,end:5,text:точный фрагмент, "
    "visual_intent:конкретно что ДОЛЖНО быть видно,editor_note_ru:краткая инструкция монтажёру, "
    "query:короткий запрос,search_queries:[1–2 запроса],search_mode:exact|broll,entity:точная сущность, "
    "entity_type:person|place|organization|object|event|species|culture|generic,entity_aliases:[], "
    "required_terms:[],negative_keywords:[],match_policy:illustrative|strict,source_policy:[],visual_fallbacks:[]}. "
    "Для конкретной песни, книги, фильма или иного произведения добавь work_title:точное название; "
    "совпадения автора/исполнителя недостаточно. Уточни в context роль человека/организации, нужное место и период "
    "по сценарию: это помогает отличать однофамильцев и разные события, не выдумывай биографию. "
    "Если важен формат материала, задай required_format:person_portrait|interview|performance|record_cover|document|map|general. "
    "Для произведений уточни work_creator:исполнитель/автор и work_kind:song|album|film|book|musical|theatre|document|other. "
    "Название вместе с автором/исполнителем и видом произведения отличает одноимённые работы и бытовое значение слова. "
    "Открытка не заменяет обложку пластинки, упоминание политика не заменяет его выступление. "
    "visual_intent описывает видимые предметы/людей/действие, не абстрактный смысл. Учитывай предыдущую и следующую фразу, "
    "но не иллюстрируй ещё не произнесённую мысль. Для темы наркотиков/здоровья предпочитай реальные документальные кадры и реальные лаборатории. "
    "Для конкретного человека, места, вида, организации: exact и собственная entity. main_entity — только дефолт, а не тема каждого кадра. "
    "scientific_name допустим только для species. Алиасы могут включать распространённое написание имени на языке источников, "
    "но не другие сущности. Запросы короткие, конкретные, на английском или языке события/источника. "
    "Например: Friedrich Merz Bundestag Rede, а не political instability leadership pressure. "
    "Для человека допускается другое реальное выступление того же человека: match_policy=illustrative. "
    "Точное событие/год требуй только при необходимости, тогда strict и required_terms. "
    "required_terms — только НЕОБХОДИМЫЕ видимые признаки; | внутри строки задаёт синонимы, между строками AND. "
    "Не требуй, чтобы метаданные повторяли всю озвучку. Не подменяй человека, вид животного, город или документ похожим. "
    "source_policy — непустой упорядоченный список: editorial (фото из веб-поиска/новостей), archive (Wikimedia-фото или Internet Archive-видео), "
    "youtube (любые публичные видео), licensed_stock (Pexels/Pixabay/Unsplash, последними). "
    "Для любой темы сначала Google Images: фото [editorial,archive]; видео сначала YouTube: [youtube,archive]. "
    "Стоки добавляй последними только для уместного общего кадра. official — только при известных настроенных каналах; обычно не нужен. "
    "На кадр до 3 кандидатов. query_budget:6 — потолок внешнего поиска, а не цель расхода. "
    "Если видео не найдётся, добавь явный visual_fallbacks: [{role:photo,type:photo,query:запрос той же сущности, "
    "search_mode:exact,entity:та же сущность,entity_type:тот же тип,source_policy:[editorial,archive]}]. "
    "После точного поиска допустимо фото той же сущности, затем близкая реальная иллюстрация по смыслу; не выдумывай события. "
    "Каждый fallback — самостоятельный план, максимум 3, с собственной source_policy. ai_fallback запрещён. "
    "Права проверит пользователь вручную, не ограничивай поиск CC и не объявляй материалы свободными. "
    "У обычных фото выбирай камеру по shot_plan: устанавливающий план — отдаление, деталь/передышка — статика; явный preset приоритетен. Низкое разрешение получает размытый фон автоматически. "
    "Базовая камера фотографий рендерится FFmpeg, имена пресетов сохранены: PHOTO_SLOW_ZOOM — приближение, PHOTO_SLOW_ZOOM_OUT — отдаление, PHOTO_PAN — перемещение. "
    "Выбирай по смыслу: приближение акцентирует уже видимый объект/деталь, отдаление раскрывает окружение и масштаб, pan ведёт по широкому изображению, PHOTO_STATIC даёт паузу для чтения. "
    "Не чередуй направления механически; params.zoom_start/zoom_end — добавка к масштабу от 0 до .2, direction:left|right|up|down у PHOTO_PAN. "
    "Движение плавно распределяется по длительности chunk; это обычный кадр, не декоративная карточка, не добавляет SFX и не учитывается в доле графических шаблонов. "
    "Для Remotion-карточек используй поле chunk.template и только имена из remotion_templates; "
    "ориентир доли графики — editorial_policy.motion_graphics_target по общей ДЛИТЕЛЬНОСТИ, распределённый по смыслу. "
    "Motion-шаблоны blur-in, fade-in, scale-in, spring-in анимируют карточку "
    "по пропорциям выбранного фото/видео без обрезки; params.arrival_frames 1..120, corner_radius 0..60. "
    "Шаблон использует выбранное фото/видео, случайно выбранный при импорте фон из assets/paper и свой SFX "
    "в момент появления карточки; не дублируй SFX в audio_tracks. "
    "Представление персонажа: person_intro_left|person_intro_center|person_intro_right — человек слева, по центру или справа. "
    "Только type:photo, выбирай чёткий одиночный портрет с головой и плечами/торсом; софт локально вырезает фон, без платного API. "
    "params.person_name — обязательное имя, params.person_role — короткая подпись без новых фактов. "
    "params.background — уместная фотография из library категории backgrounds или бумага; если не задано, используется бумажный фон. "
    "Человек, имя и стрелка плавно появляются снизу, фон чёрно-белый, затемнённый и размытый; arrival_frames по умолчанию 36. "
    "Используй представление при первом значимом появлении героя, меняй варианты по композиции; не назначай дополнительный text_cue на этот кадр. "
    "Исторический таймлайн history_timeline: только type:photo, chunk длительностью от 3 секунд. "
    "Назначай по смыслу, когда озвучка связывает конкретный год с предметом или приспособлением. "
    "params.year — точный целый год из озвучки, params.from_year — предыдущий названный год для прокрутки (по умолчанию year-3), "
    "params.label — краткое название именно упомянутого предмета; необязательно params.scroll_frames 21..180 (по умолчанию 72). "
    "Для этого chunk задай entity — точное название предмета, entity_type:object, search_mode:exact, "
    "поисковый query, search_queries и source_policy [editorial,archive] для его фотографии. "
    "Фотография остаётся целиком в рамке, фон не вырезается. Не подменяй упомянутый предмет похожим. "
    "Соседние деления считаются автоматически; это шкала, не дополнительные исторические события. Не придумывай дату изобретения. "
    "После прокрутки над шкалой появляются фото и название; дополнительный text_cue не нужен. "
    "Обязательный sfx/scrolling.mp3 играет только во время прокрутки на 30% исходной громкости, не дублируй его в audio_tracks. "
    "text_cues — отдельный массив редких текстовых вставок, максимум одна на chunk. "
    "Для accent: {id:T001,kind:accent,template:marker_highlight|question_panel_bottom|question_panel_top|impact_typewriter|speech_words_grid|speech_words_overlay|selective_marker,text:точные слова,chunk_index:0}. "
    "Не дублируй каждую фразу озвучки. chunk_index — индекс кадра с нуля и означает полную длительность кадра. "
    "Если текст нужен на части кадра, вместо chunk_index укажи абсолютные start/end внутри одного кадра; "
    "можно начать за секунду до произнесения ключевого слова, если это помогает монтажу. "
    "Текст может дословно повторять озвучку или кратко её пояснять без новых фактов. "
    "ID идут T001,T002...; текст автоматически рисуется Remotion, ручные экспорты не нужны. "
    "Текстовые шаблоны используют coolvetica и строчные буквы, кроме impact_typewriter: он всегда КАПСОМ. Используй только имена из text_templates, kind:accent. "
    "marker_highlight выбирай для ключевых слов и фактов: сначала появляется вся белая фраза, затем за ней слева направо рисуется жёлтый маркер с ручной фактурой. "
    "question_panel_bottom и question_panel_top выбирай для вопросов, противопоставлений и важных выводов: белый текст на красной плашке приходит снизу/сверху к центру за 0,7 секунды. "
    "Одновременно плавно темнеют края, центр светлее; виньетка уходит вместе с плашкой. Эти новые шаблоны не размывают фон. "
    "Для всех трёх новых текстовых шаблонов нужна вставка от 1,4 секунды, цвет всегда белый, шрифт coolvetica, позиция центр. "
    "У marker_highlight SFX sfx/marker_scribble.mp3 на 30% исходной громкости начинается с закрашиванием и обрезается по его длительности; не дублируй его в audio_tracks. "
    "Дополнительные accent-шаблоны: impact_typewriter, speech_words_grid, speech_words_overlay, selective_marker. "
    "impact_typewriter — самый сильный короткий акцент: одно слово или 2–4 слова ДОСЛОВНО из озвучки, крупный белый КАПС, "
    "буквы печатаются в интервалах произнесения выбранных слов, красное окрашивание фона нарастает с печатью. "
    "Фраза и красный фон остаются до конца chunk. SFX typewrite.WAV на 30% только во время печати, без щелчков в паузах. "
    "speech_words_grid и speech_words_overlay — менее сильное пояснение, описание происходящего или тревожная мысль, дословно из озвучки. "
    "Каждое слово мягко появляется при его произнесении с лёгким свечением; предыдущие слова остаются, собирая фразу. "
    "grid заменяет фон чёрной изогнутой сеткой, overlay оставляет выбранное фото/видео. Эти шаблоны не размывают фон. "
    "Для трёх шаблонов по речи укажи text_cue.word_range:[first,last_exclusive] — точный диапазон глобальных word_timestamps. "
    "Софт рассчитывает speech_words автоматически из WhisperX; НЕ сочиняй таймкоды и не передавай speech_words самостоятельно. "
    "Если word_range пропущен, софт ищет единственное дословное совпадение внутри вставки. Текст по речи должен оставаться внутри одного chunk. "
    "selective_marker — сначала вся белая фраза, затем одновременно жёлтые ручные мазки за несколькими ключевыми частями. "
    "params.highlight_ranges:[[first,last_exclusive],...] — от 1 до 10 непересекающихся диапазонов СЛОВ внутри text, индексы с нуля; "
    "выделенные части курсивом Coolvetica, остальные обычные; текст всегда белый. Один marker_scribble.mp3 на 30% на всё одновременное закрашивание. "
    "Серии фотографий универсальны для любой темы: этапы действий/событий или перечисление предметов. "
    "Сделай 2–5 последовательных photo chunks, каждому отдельные query/entity/search_queries/source_policy по его смыслу. "
    "Всем задай один params.carousel_group (уникальное имя серии), один и тот же template и archival. "
    "Варианты: photo_carousel_paper (бумага в клетку), photo_carousel_editorial (светлый журнальный), "
    "photo_carousel_dark (тёмный), photo_carousel_film (оформление фотоплёнки). params.archival:true только для архивной чёрно-белой серии; современные фото сохраняют цвет. "
    "Длительность каждого chunk от секунды; смены привязаны к его реальным словам. Первый кадр приходит снизу за 0,7 с; следующие плавно приезжают справа, сдвигая предыдущие влево. "
    "На внутренних стыках серии ставь cut (или не задавай переход): перелистывание встроено, crossfade поверх него запрещён. "
    "params.caption — необязательная короткая подпись из озвучки для журнального варианта. Дополнительные SFX серии не назначай без просьбы. "
    "map_annotations требует params.geo с реальными координатами; старые карты-картинки отключены. "
    "Приёмы, измеренные по клипам 51,53,65,66–67, доступны как chunk.template и работают в любой нише. "
    "chapter_heading — короткий заголовок новой главы из сценария, белый Coolvetica строчными поверх фото/видео, "
    "мягкое появление 0.4с, затем жёлтая линия слева направо 0.5с, плавное увеличение заголовка и удержание до стыка. "
    "params.text обязателен; arrival_frames:12, underline_start:9, underline_frames:15 — необязательные тайминги в кадрах. "
    "Не используй заголовок главы для каждого предложения или как обещание факта, которого нет в сценарии. "
    "date_countback — акцент на одном явно названном годе поверх фото/видео: точка, тонкая линия, виньетка, "
    "число мягко появляется и прокручивается назад до params.year (обязательный подтверждённый год). "
    "params.from_year — необязательное начало счётчика, не меньше year; если его нет, показывается только year без выдуманного числа. "
    "arrival_frames:30, line_frames:12, count_start:33, count_frames:54; год удерживается до стыка. "
    "history_timeline оставь для года вместе с предметом и шкалой, date_countback — для даты самой по себе. "
    "editorial_statement — короткая запись/утверждение/оговорка источника, params.text из сценария; бумага приходит снизу, "
    "фраза раскрывается слева направо, красная ручная полоса проходит за ней, тонкие линии завершают композицию. "
    "Белый Coolvetica строчными на тёмной подложке сохраняет читаемость. params.arrival_frames:18, reveal_start:8, "
    "reveal_frames:24, highlight_start:12, highlight_frames:45. Сохраняй в тексте авторство, отрицания и степень уверенности. "
    "paired_evidence — ровно два соседних photo chunks, один scene_id и params.comparison_group (уникальная строка до 50 символов), "
    "у каждого отдельный query/entity и params.label из сценария. Две фотографии одновременно вырастают на изогнутой тёмной сетке; "
    "красные подписи, белые рамки, archival:true только для архива, современные снимки цветные. На внутреннем стыке cut. "
    "Оба фото видны весь общий интервал группы: второй chunk продолжает анимацию первого. Не создавай две карточки из одного поиска. "
    "Тайминг пары задаётся в первом chunk: arrival_start:25, arrival_frames:59, label_start:23; общая длительность от 1с. "
    "У новых шаблонов интервалы по умолчанию сжимаются для коротких сцен; явные тайминги должны помещаться в общую сцену. "
    "Звук добавляет софт автоматически, до 30%: карта — маркер во время линий, заголовок — текстовый акцент на линии, "
    "дата — scrolling во время счётчика (или текстовый акцент при показе только года без прокрутки), утверждение — whoosh на входе и маркер на выделении, пара — whoosh на появлении. "
    "Не дублируй эти SFX в audio_tracks и текст этих пяти композиций в text_cues. "
    "Следующая пятёрка после клипа 67 — object_pointer, corner_section, date_interval, bullet_panel, echo_statement. "
    "Повторные карусели, пары, маркеры, обычные текстовые подписи не считай новыми приёмами; выбирай существующие шаблоны. "
    "object_pointer — назвать конкретный видимый объект, человека или деталь фото/видео как ориентир рассказа. "
    "params.label (до 80 символов), anchor:[x,y] на нужной детали и label_point:[x,y] для чёрной плашки с белым Coolvetica. "
    "Координаты 0..1 в видимом кадре: проверь скачанное медиа, нельзя угадывать местоположение объекта по query. "
    "control_point необязателен; плавная белая кривая рисуется к объекту за line_frames:18, плашка появляется за arrival_frames:12, start_frame:0. "
    "Не вырезай предмет; вся фотография остаётся. Это подпись объекта, а map_annotations — географическая схема. "
    "corner_section — компактный навигационный заголовок при переходе к новому пункту/аспекту: фото остаётся главным. "
    "params.lines:[{text:номер или аспект,start_frame:15,reveal_frames:24},{text:короткое название,start_frame:39,reveal_frames:24}], от 1 до 3 строк до 50 символов. "
    "Строки раскрываются по очереди на красной ручной полосе; белый Coolvetica строчными. corner:top_left|top_right|bottom_left|bottom_right. "
    "Не нумеруй пункты, если сценарий их не нумерует. Ставь начало на реальную смену раздела, не копируй опережающий тайминг референса. "
    "date_interval — сопоставление двух явно известных годов и расстояния между событиями, а не один год или историческая шкала. "
    "params.from_year/to_year обязательны 1..9999, to_year>=from_year; from_label/to_label — названия событий, unit:years или лет. "
    "Разницу лет вычисляет софт; difference не задавай вручную. Не превращай отсутствие документов в доказательство причины. "
    "Сначала медиа, затем изогнутая сетка и левая дата, далее разница и правая дата, соединение линией и медленный поворот камеры. "
    "grid_start:53, from_start:58, difference_start:93, to_start:103, arrival_frames:15, line_start:93, line_frames:45. "
    "Порядок grid→from→difference→to обязателен, явные интервалы должны помещаться до стыка; перенастрой по словам и доступному времени. "
    "bullet_panel — 2–6 перечисленных условий, неизвестных, признаков или вопросов из речи. Список на тёмном клетчатом листе поверх фото/видео. "
    "params.title — смысловой заголовок до 65 символов (служебный Bullet Point Overlay запрещён); side:left|right, panel_start:0, arrival_frames:12. "
    "params.items:[{text:короткий пункт до 100 символов,start_frame:кадр его реального упоминания,reveal_frames:24},...]. "
    "Пункты приходят последовательно по изогнутому следу букв; предыдущие остаются. start_frame обязателен для каждого пункта, вычисли по word_timestamps. "
    "Отрицание 'нельзя спросить' не превращай в неподтверждённое 'никогда не записали'; сохраняй вопросы и неопределённость. "
    "echo_statement — редкий сильный вывод/парадокс или смысловой поворот: крупная фраза и повтор ключевого понятия фоном. "
    "params.text до 160 символов, params.echo до 60 из той же мысли; белый Coolvetica строчными, красный декоративный повтор, фактура, blur→резкость 12 кадров и плавный zoom. "
    "start_frame:0, arrival_frames:12, camera_frames:85, camera_scale_start:.7603, camera_scale_end:1 (outCubic); параметры камеры необязательны. Сохраняй авторство и уверенность; не усиливай 'неизвестно' до 'доказательства опровергнуты'. "
    "Это цельная фраза с повтором фоном; impact_typewriter остаётся для печати капсом, speech_words — для показа каждого произнесённого слова. "
    "У object_pointer/corner_section/bullet_panel archival:true только для архивных фото; современные материалы цветные. "
    "Пять новых шаблонов дают SFX автоматически до 30%: указатель текстовый акцент на линии, угловые строки маркер на каждой полосе, "
    "интервал scrolling при сборке дат, список whoosh на входе и текстовый акцент на каждом пункте, echo whoosh во время появления. "
    "Не дублируй их в audio_tracks/text_cues. Используй подтверждённые тайминги речи, не переносишь даты, имена и факты из учебного ролика в другой сценарий. "
    "Приёмы 164/171/185/188/190 универсальны для документальных, политических и технологических сюжетов; медиа всегда из текущего сценария. "
    "text_highlight_split — тезис/ограничение, которое затем иллюстрируется: сначала белая фраза на тёмном фоне, "
    "затем жёлтый ручной маркер позади текста, после него текст сжимается в левую половину, справа плавно входит выбранное фото/видео. "
    "params.text до 100 символов, caption до 65 необязателен; никакой встроенной карты Австралии. "
    "text_start:0/arrival_frames:12, highlight_start:36/highlight_frames:20, split_start:58/split_frames:60 (outCubic), caption_start:116/caption_frames:12. "
    "Порядок фраза→маркер→разделение обязателен; настрой начала по word_timestamps и длительности сцены. "
    "split_verdict — две версии с поворотом 'ожидали одно — описали другое', не произвольная пара фото. "
    "Ровно два соседних photo chunks с одинаковым template, scene_id, comparison_group, отдельными query/entity и params.label до 65 символов. "
    "Первая карточка появляется по центру и перемещается влево при раскрытии правого красного поля; вторая приходит позднее, подписи печатаются. "
    "На внутреннем стыке cut; вся анимация и SFX рассчитываются на общую группу, тайминг только в первом chunk. "
    "left_start:0/left_frames:34 (inOutCubic, scale .225→1), split_start:0/split_frames:34 (та же кривая), right_start:87/right_frames:30, left_label_start:24/label_frames:12, right_label_start:102/right_label_frames:12. "
    "Вторую карточку привяжи к реальному началу противопоставления, её подпись — к названию второй версии. Красный фон — акцент, не доказательство ложности версии. "
    "detail_callouts — объяснение 2–5 видимых деталей объекта/прибора/изображения: свечение точек, угловые линии и белые подписи на чёрных плашках. "
    "Фото не вырезается: params.annotations:[{label:до 65 символов,anchor:[x,y],label_point:[x,y],start_frame:кадр произнесения,draw_frames:12},...], media_start:0/arrival_frames:18. "
    "Координаты 0..1 на видимом полном фото; проверь скачанное медиа и выбери настоящие детали. Не повторяй один указатель как пять новых шаблонов, для одного используй object_pointer. "
    "bullet_panel style:report — вариант существующего списка из клипа 188: синяя клетчатая фактурная бумага, золотистые светящиеся ромбы, "
    "белый Coolvetica, буквы приходят по дуге. style:classic сохраняет прежний вариант 149. "
    "Тот же контракт title/items/start_frame: реальные аргументы, симптомы, требования или неизвестные, 2–6 пунктов; не копируй служебный Bullet Point Overlay. "
    "bullet_panel style:torn_sidebar — вариант 234: основное фото/видео остаётся видимым, справа (side:right по умолчанию) сверху раскрывается тёмная боковая панель с рваным красным краем. "
    "Заголовок и 2–6 пунктов белым Coolvetica строчными, каждый пункт на фактурной тёмной полосе, предыдущие остаются до стыка. "
    "Выбирай для сводки наблюдений/аргументов/признаков, когда одновременно важно видеть главный объект; не превращай сомнительное свидетельство в установленный факт. "
    "timing_mode:speech по умолчанию: panel_start:0/arrival_frames:34, title_start:18/title_frames:14; items.start_frame вычисли по текущим word_timestamps, reveal_frames настрой по речи. "
    "timing_mode:stretch только для ненарративной демонстрации или явно разрешённого свободного темпа: без start_frame/reveal_frames равномерно растягивает всю сборку под длительность chunk; явные тайминги сохраняет. "
    "Длительность chunk и длительность движения независимы: 3/7 секунд допустимы, можно быстро раскрыть и удерживать либо растянуть анимацию; все интервалы должны закончиться до стыка. "
    "Для речи не растягивай start_frame механически: заново вычисли по новой озвучке. Медиа и формулировки из текущего сценария, никаких встроенных рыбаков или морских историй. "
    "lower_third_contrast — компактный вывод поверх главного фото/видео внизу: общий заголовок, затем две выделенные части и связка. "
    "params.heading до 80 символов, heading_start:12/arrival_frames:18; segments:[{text:до 70 символов,start_frame:реальный кадр,reveal_frames:18,highlight:true|false},...], 2–5 сегментов суммарно до 140 символов, side:left|right. "
    "Белый Coolvetica, выделения курсивом на фактурной красной полосе; связку 'и/но' оставь без маркера. Сохраняй отрицания и вероятность. "
    "Удерживай текст до смены кадра; если дальше другая мысль, создай следующий chunk, не оставляй старый вывод над другой темой. "
    "У всех этих приёмов SFX автоматически до 30%: split-текст маркер и whoosh на разделении, split-пара whoosh на двух входах, "
    "детали text3 на линиях, нижний вывод маркер на выделениях, report — звуки существующего bullet_panel. Не дублируй audio_tracks/text_cues. "
    "text_cues.params: font_size 16..160, color #RRGGBB, position top|center|bottom, reveal_frames 1..120. "
    "transitions:[] означает обычные склейки cut. Для скачанных переходов укажи только существующий library.id. "
    + TRANSITION_INSTRUCTIONS +
    "audio_tracks:[] — нет дополнительных ручных дорожек; автоматические SFX шаблонов остаются. effects запрещены в V2; layers не добавляй без отдельной просьбы."
)

LUNA_INSTRUCTIONS += PLANNER_RULES + EDITING_RULES + (
    "SFX добавляет сборщик по событиям анимации: текстовые акценты и whoosh чередуются между тремя вариантами каждой группы. "
    "Вход панелей, смена карточек, пункты списков, точки/маршруты карты и приближение документа уже озвучиваются автоматически. "
    "Не дублируй эти эффекты в audio_tracks; cut, crossfade, обычная камера и растворения остаются без автоматического SFX. "
)


def _bind_shots_to_words(chunks, session):
    """Bind Codex's semantic shots to real words, never estimated speech speed."""
    if not any("word_range" in chunk for chunk in chunks if isinstance(chunk, dict)):
        return chunks
    with open(os.path.join(session["scene_dir"], "luna_input.json"), encoding="utf-8") as file:
        words = json.load(file)["word_timestamps"]
    if any(isinstance(c,dict) and c.get('music_insert') for c in chunks):
        return bind_music_words(chunks, words, session['audio_duration'])
    cursor, result = 0, []
    for chunk in chunks:
        span = chunk.get("word_range") if isinstance(chunk, dict) else None
        if (not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span)
                or span[0] != cursor or not cursor < span[1] <= len(words)):
            raise ValueError("word_range: непрерывные диапазоны [first,last_exclusive], покрывающие все слова")
        end = span[1]
        result.append({**chunk, "start": 0 if cursor == 0 else words[cursor]["start"],
                       "end": words[end]["start"] if end < len(words) else session["audio_duration"],
                       "text": " ".join(word["word"] for word in words[cursor:end])})
        cursor = end
    if cursor != len(words):
        raise ValueError("word_range не покрывает конец озвучки")
    return result


_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _get_session(scene_name: str) -> dict | None:
    if not isinstance(scene_name, str) or not _SAFE_NAME.match(scene_name):
        return None
    with _sessions_lock:
        session = _sessions.get(scene_name)
        if session:
            return session
        path = os.path.join(OUTPUT_DIR, scene_name, "project.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as file:
                saved = json.load(file)
            if not isinstance(saved, dict) or not isinstance(saved.get("chunks"), list) or not isinstance(saved.get("assets"), dict):
                return None
            saved = without_retired_templates(saved)
            scene_dir = os.path.realpath(os.path.join(OUTPUT_DIR, scene_name))
            base = os.path.realpath(OUTPUT_DIR)
            if os.path.commonpath([scene_dir, base]) != base:
                return None
            saved["scene_dir"], saved["scene_name"] = scene_dir, scene_name
            voice = os.path.realpath(saved.get("audio_path") or os.path.join(scene_dir, saved.get("voice_file", "")))
            if os.path.commonpath([voice, scene_dir]) != scene_dir:
                return None
            saved["audio_path"] = voice
            saved.update({"busy": False, "cancel": threading.Event()})
            _discard_rejected_candidates(saved)
            _sessions[scene_name] = saved
            return saved
        except (OSError, ValueError, TypeError):
            return None


def _discard_rejected_candidates(session: dict):
    blocked = set()
    for name, asset in session.get("assets", {}).items():
        source = asset.get("source") or ""
        url = asset.get("original_url") or asset.get("image_url") or ""
        path = _safe_media_path(session["scene_name"], name)
        if is_rejected_stock_preview(url, source) or (
            source != "Локальный файл" and os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS
            and path and os.path.isfile(path) and not _has_minimum_image_resolution(path)
        ):
            blocked.add(name)
    if not blocked:
        return
    for chunk in session.get("chunks", []):
        chunk["files"] = [name for name in chunk.get("files", []) if name not in blocked]
        for panel in chunk.get("panels", []):
            panel["files"] = [name for name in panel.get("files", []) if name not in blocked]
    session["assets"] = {name: asset for name, asset in session["assets"].items() if name not in blocked}
    session["file_overrides"] = {
        key: [name for name in names if name not in blocked]
        for key, names in session.get("file_overrides", {}).items()
    }
    _save_assets(session)


def _claim_session(session: dict) -> bool:
    with _sessions_lock:
        if session["busy"]:
            return False
        session["busy"] = True
        session["cancel"].clear()
        return True


def _release_session(session: dict):
    with _sessions_lock:
        session["busy"] = False


def _check_cancelled(session: dict):
    if session["cancel"].is_set():
        raise RuntimeError("Сессия отменена")


def _save_assets(session: dict):
    with open(os.path.join(session["scene_dir"], "assets.json"), "w", encoding="utf-8") as f:
        json.dump(session["assets"], f, ensure_ascii=False, indent=2)
    _save_project(session)


def _save_project(session):
    saved = {key: value for key, value in session.items()
             if key not in {"busy", "cancel", "failed_media", "youtube_health"}}
    path = os.path.join(session["scene_dir"], "project.json")
    with open(path + ".tmp", "w", encoding="utf-8") as file:
        json.dump(saved, file, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


def _asset_identity(asset: dict | None) -> str:
    if not isinstance(asset, dict):
        return ""
    return canonical_media_url(asset.get("original_url") or asset.get("image_url") or "")


def _keep_new_media(files: list[str], assets: dict, seen: set[str], progress_callback=None) -> list[str]:
    unique = []
    for path in files:
        identity = _asset_identity(assets.get(os.path.basename(path)))
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        unique.append(path)
    skipped = len(files) - len(unique)
    if skipped and progress_callback:
        progress_callback(f"Убрано повторов из предыдущих сцен: {skipped}")
    return unique


def _generate_markers(chunks: list[dict], scene_dir: str, scene_name: str, progress_callback=None):
    lines = []
    for chunk in chunks:
        highlights = chunk.get("highlights") or []
        start = float(chunk.get("start", 0.0))
        for h in highlights:
            mins = int(start) // 60
            secs = int(start) % 60
            lines.append(f'{mins:02d}:{secs:02d} — "{h}" → добавь плашку')
    if not lines:
        return
    markers_path = os.path.join(scene_dir, f"{scene_name}_markers.txt")
    with open(markers_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if progress_callback:
        progress_callback(f"Маркеры подсказок ({len(lines)} шт.) → {os.path.basename(markers_path)}")


def _create_scene() -> tuple[str, str]:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    existing = [
        d for d in os.listdir(OUTPUT_DIR)
        if os.path.isdir(os.path.join(OUTPUT_DIR, d)) and d.startswith("scene_")
    ]
    numbers = []
    for name in existing:
        try:
            numbers.append(int(name.split("_")[1]))
        except (IndexError, ValueError):
            pass
    next_num = max(numbers, default=0) + 1
    while True:
        scene_name = f"scene_{next_num:03d}"
        scene_dir = os.path.join(OUTPUT_DIR, scene_name)
        try:
            os.makedirs(scene_dir)
            return scene_name, scene_dir
        except FileExistsError:
            next_num += 1


def _safe_media_path(scene_name: str, filename: str) -> str | None:
    if not _SAFE_NAME.match(scene_name) or not _SAFE_FILE.match(filename):
        return None
    candidate = os.path.realpath(os.path.join(OUTPUT_DIR, scene_name, "downloads", filename))
    base = os.path.realpath(os.path.join(OUTPUT_DIR, scene_name, "downloads"))
    if os.path.commonpath([candidate, base]) != base:
        return None
    return candidate


def _sse_response(session, messages):
    def generate():
        while (message := messages.get()) is not None:
            yield f"data: {message}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers={
        "X-Scene-Name": session["scene_name"], "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify({"error": "Файл слишком большой: максимум 512 МБ"}), 413


@app.route("/prepare", methods=["POST"])
def prepare():
    text = request.form.get("text", "").strip()
    language = request.form.get("language", DEFAULT_LANGUAGE)
    if language not in LANGUAGES:
        return jsonify({"error": "Выбери язык озвучки: cs, de, en, es или pl"}), 400
    processing_mode = request.form.get("processing_mode", "fast")
    if processing_mode not in _PROCESSING_MODES:
        return jsonify({"error": "Режим обработки: fast или quality"}), 400
    try:
        motion_target=graphics_target(float(request.form.get('motion_graphics_target',70)))
    except (ValueError,TypeError) as exc:
        return jsonify({'error':str(exc)}),400
    try:
        video_mode = validate_video_mode(request.form.get("video_mode", "faceless"))
        avatar_workflow = validate_avatar_workflow(request.form.get("avatar_workflow", "dreamina"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    uploaded = request.files.get("audio")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Загрузи готовую озвучку"}), 400
    ext = os.path.splitext(uploaded.filename)[1].lower()
    if ext not in _AUDIO_EXTENSIONS:
        return jsonify({"error": "Нужен аудиофайл: WAV, MP3, M4A, AAC, FLAC, OGG, OPUS, AIFF или WMA"}), 400
    if not check_ffmpeg() or not shutil.which("ffprobe"):
        return jsonify({"error": "Для работы нужны ffmpeg и ffprobe в PATH"}), 500
    scene_name, scene_dir = _create_scene()
    audio_path = os.path.join(scene_dir, "voiceover" + ext)
    uploaded.save(audio_path)
    audio_duration = _probe_duration(audio_path)
    if audio_duration is None or not math.isfinite(audio_duration) or audio_duration <= 0:
        os.remove(audio_path)
        os.rmdir(scene_dir)
        return jsonify({"error": "Не удалось прочитать аудио. Проверь файл озвучки"}), 400
    session = {"scene_name": scene_name, "scene_dir": scene_dir, "chunks": [], "assets": {}, "busy": True, "cancel": threading.Event(), "audio_path": audio_path, "audio_duration": audio_duration,
               "original_text": text, "language": language,
               "processing_mode": processing_mode, "motion_graphics_target": motion_target,
               "video_mode": video_mode, "avatar_library": [], "avatar_workflow": avatar_workflow, "avatar_assignments": {},
               "elderly_mode": request.form.get("elderly_mode") == "1", "reserp_mode": request.form.get("reserp_mode") == "1", "youtube_mode": request.form.get("youtube_mode") == "1",
               "brightdata_mode": request.form.get("brightdata_mode") == "1"}
    with _sessions_lock: _sessions[scene_name] = session
    _save_project(session)
    return _prepare_audio(session)


def _prepare_audio(session):
    scene_dir, scene_name = session["scene_dir"], session["scene_name"]
    text = session.get("original_text", "")
    messages = queue.Queue()
    def worker():
        try:
            def progress(message):
                session["progress"] = message
                messages.put(json.dumps({"progress": message}))
            _check_cancelled(session)
            language = session.get("language", DEFAULT_LANGUAGE)
            input_path = os.path.join(scene_dir, "luna_input.json")
            if os.path.isfile(input_path):
                with open(input_path, encoding="utf-8") as file:
                    cached = json.load(file)
                if cached.get("language") == language and cached.get("transcriber") == "whisperx-large-v2":
                    messages.put(json.dumps({"awaiting_timeline": True, "scene_name": scene_name}))
                    return
            progress(f"Озвучка загружена: {session['audio_duration']:.1f} секунд")
            words = transcribe_audio(session["audio_path"], language=language, progress_callback=progress,
                                     cancel_event=session["cancel"])
            _check_cancelled(session)
            if not words:
                raise ValueError("В озвучке не распознана речь. Проверь аудио и попробуй снова")
            transcript = text or " ".join(word["word"] for word in words)
            session["original_text"] = transcript
            with open(input_path + ".tmp", "w", encoding="utf-8") as file:
                json.dump({"text": transcript, "language": language, "transcriber": "whisperx-large-v2",
                           "audio_duration": session["audio_duration"], "word_timestamps": words,
                           "presets": list(PRESETS.values()), "remotion_templates": list(REMOTION_TEMPLATES),
                           "text_templates": TEXT_COMPONENTS, "library": library_catalog(),
                           "builtin_transitions": BUILTIN_TRANSITIONS,
                           **planner_payload(session, LUNA_INSTRUCTIONS, REMOTION_TEMPLATES)}, file, ensure_ascii=False, indent=2)
            os.replace(input_path + ".tmp", input_path)
            progress("JSON с текстом и таймкодами готов")
            _save_project(session)
            messages.put(json.dumps({"awaiting_timeline": True, "scene_name": scene_name}))
        except Exception as exc: messages.put(json.dumps({"error": str(exc)}))
        finally: _release_session(session); messages.put(None)
    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(session, messages)


def _varagent_catalog(session):
    return {"text_templates": TEXT_COMPONENTS, "builtin_transitions": BUILTIN_TRANSITIONS,
            **planner_payload(session, LUNA_INSTRUCTIONS, REMOTION_TEMPLATES)}


def _save_varagent_plan(session, plan):
    apply_motion_plan(session, plan, session["cancel"])
    for name, payload in (("varagent_motion_plan.json", plan),
                          ("timeline.json", {key: session[key] for key in ("chunks", "transitions", "audio_tracks", "text_cues")})):
        path = Path(session["scene_dir"]) / name
        path.with_suffix(path.suffix + ".tmp").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(path.with_suffix(path.suffix + ".tmp"), path)
    write_task_list(session["scene_dir"], session["text_cues"])
    _save_assets(session)


def _plan_varagent_motion(session, progress):
    payload = planning_input(session, _varagent_catalog(session))
    for attempt in range(3):
        plan = codex_plan(payload, session["scene_dir"], session["cancel"], progress)
        Path(session["scene_dir"], "varagent_motion_candidate.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            apply_motion_plan(session, plan, dry_run=True)
        except (ValueError, KeyError, TypeError) as exc:
            if attempt == 2:
                raise ValueError(f"План моушна не прошёл проверку: {exc}") from exc
            progress(f"Уточняю параметры плана: {exc}")
            payload.update(validation_feedback=str(exc), previous_plan=plan)
            continue
        _save_varagent_plan(session, plan)
        progress(f"Моушн подобран: {len(plan['scene_updates'])} сцен, {len(plan['text_cues'])} текстовых вставок, {len(plan['transitions'])} переходов")
        return


@app.route("/import_varagent", methods=["POST"])
def import_varagent():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("folder"), str):
        return jsonify(error="Укажи путь к папке VarAgent"), 400
    try:
        info = inspect_project(body["folder"], body.get("minutes", 1))
        target = graphics_target(body.get("motion_graphics_target", 70))
        if info["language"] not in LANGUAGES:
            raise ValueError("Язык проекта не поддержан: " + info["language"])
        for key in ("audio",):
            duration = _probe_duration(info[key])
            if duration is None or duration < info["duration"]-.05:
                raise ValueError("Исходная озвучка короче монтажного плана")
    except (OSError, ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    scene_name, scene_dir = _create_scene()
    session = {"scene_name": scene_name, "scene_dir": scene_dir, "chunks": [], "assets": {},
               "busy": True, "cancel": threading.Event(), "video_mode": "faceless", "avatar_workflow": "library",
               "avatar_library": [], "avatar_assignments": {}, "motion_graphics_target": target,
               "processing_mode": "fast", "transitions": [], "text_cues": [], "audio_tracks": []}
    with _sessions_lock:
        _sessions[scene_name] = session
    messages = queue.Queue()
    def worker():
        def progress(message):
            session["progress"] = message
            messages.put(json.dumps({"progress": message}))
        try:
            session.update(import_media(info, scene_dir, progress, session["cancel"]))
            session["downloads_complete"] = True
            payload = planning_input(session, _varagent_catalog(session))
            payload["output_schema"] = PLAN_SCHEMA
            Path(scene_dir, "luna_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            _save_assets(session)
            progress("Готовые сцены и таймкоды импортированы. Автоматический подбор отключён")
            messages.put(json.dumps({"varagent_ready": True, "scene_name": scene_name}))
        except Exception as exc:
            messages.put(json.dumps({"error": str(exc), "varagent_available": bool(session.get("varagent")), "scene_name": scene_name}))
        finally:
            _release_session(session)
            messages.put(None)
    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(session, messages)


@app.route("/plan_varagent", methods=["POST"])
def plan_varagent():
    body = request.get_json(silent=True) or {}
    session = _get_session(body.get("scene_name", "")) if isinstance(body, dict) else None
    if not session or not session.get("varagent"):
        return jsonify(error="Сначала импортируй папку VarAgent"), 400
    if not _claim_session(session):
        return jsonify(error="Проект уже обрабатывается"), 409
    messages = queue.Queue()
    def worker():
        try:
            def progress(message):
                session["progress"] = message
                messages.put(json.dumps({"progress": message}))
            _plan_varagent_motion(session, progress)
            messages.put(json.dumps({"varagent_ready": True, "scene_name": session["scene_name"]}))
        except Exception as exc:
            messages.put(json.dumps({"error": str(exc)}))
        finally:
            _release_session(session)
            messages.put(None)
    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(session, messages)


def _import_varagent_motion(session, uploaded):
    if not uploaded or not _claim_session(session):
        return jsonify(error="Нужен JSON плана моушна и свободный проект"), 400
    try:
        _save_varagent_plan(session, json.load(uploaded))
        return jsonify(varagent_ready=True, scene_name=session["scene_name"])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return jsonify(error=str(exc)), 400
    finally:
        _release_session(session)


@app.route("/timeline_input/<scene_name>")
def timeline_input(scene_name):
    session = _get_session(scene_name)
    path = os.path.join(session["scene_dir"], "luna_input.json") if session else ""
    if not path or not os.path.isfile(path):
        return "Not found", 404
    with open(path, encoding="utf-8") as file:
        payload = json.load(file)
    payload.update({"presets": list(PRESETS.values()), "remotion_templates": list(REMOTION_TEMPLATES),
                    "text_templates": TEXT_COMPONENTS, "library": library_catalog(),
                    "main_entity": session.get("main_entity", ""), "scientific_name": session.get("scientific_name", ""),
                    "main_entity_type": session.get("main_entity_type", "species" if session.get("scientific_name") else "generic"),
                    "query_budget": session.get("query_budget", DEFAULT_QUERY_BUDGET),
                    "builtin_transitions": BUILTIN_TRANSITIONS,
                    **planner_payload(session, LUNA_INSTRUCTIONS, REMOTION_TEMPLATES)})
    if session.get("varagent"):
        payload = {**planning_input(session, _varagent_catalog(session)), "output_schema": PLAN_SCHEMA}
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": 'attachment; filename="luna_input.json"'})


@app.route("/projects")
def projects():
    result = []
    if os.path.isdir(OUTPUT_DIR):
        for name in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            if _SAFE_NAME.fullmatch(name) and os.path.isfile(os.path.join(OUTPUT_DIR, name, "project.json")):
                result.append(name)
    return jsonify(result)


@app.route("/resume_prepare", methods=["POST"])
def resume_prepare():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", ""))
    if not session or not os.path.isfile(session.get("audio_path", "")):
        return jsonify({"error": "Озвучка проекта не найдена"}), 404
    language = data.get("language", session.get("language", DEFAULT_LANGUAGE))
    if language not in LANGUAGES:
        return jsonify({"error": "Выбери язык озвучки: cs, de, en, es или pl"}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    session["language"] = language
    _save_project(session)
    return _prepare_audio(session)


@app.route("/resume_search", methods=["POST"])
def resume_search():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", ""))
    if not session or not session.get("chunks"):
        return jsonify({"error": "Таймлайн проекта не найден"}), 404
    if session["busy"]:
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    chunk_id = data.get("chunk_id")
    if chunk_id is not None and (type(chunk_id) is not int or not any(c["id"] == chunk_id for c in session["chunks"])):
        return jsonify({"error": "Сцена не найдена"}), 400
    changed = False
    processing_mode = data.get("processing_mode", session.get("processing_mode", "quality"))
    if processing_mode not in _PROCESSING_MODES:
        return jsonify({"error": "Режим обработки: fast или quality"}), 400
    changed |= processing_mode != session.get("processing_mode", "quality")
    session["processing_mode"] = processing_mode
    for field in ("reserp_mode", "brightdata_mode", "youtube_mode"):
        value = data.get(field, session.get(field, False)) is True
        changed |= value != session.get(field, False)
        session[field] = value
    _save_project(session)
    missing_only = chunk_id is None and data.get("missing_only", True) is True
    payload = copy.deepcopy({key: session.get(key, []) for key in ("chunks", "transitions", "audio_tracks", "text_cues")})
    missing_ids = set()
    if missing_only:
        for chunk in payload["chunks"]:
            if chunk.get("files") and all(_safe_media_path(session["scene_name"], name) and
                                         os.path.isfile(_safe_media_path(session["scene_name"], name)) for name in chunk["files"]):
                continue
            missing_ids.add(chunk["id"])
            for plan in [chunk] + chunk.get("visual_fallbacks", []):
                policy = plan.get("source_policy", [])
                preferred = "youtube" if plan.get("type", "photo") == "video" else "editorial"
                if preferred in policy:
                    plan["source_policy"] = [preferred] + [source for source in policy if source != preferred]
    payload.update({key: session[key] for key in ("main_entity", "main_entity_type", "scientific_name", "query_budget") if key in session})
    return import_timeline(session, io.StringIO(json.dumps(payload)),
                           force_search=missing_ids if missing_only else {chunk_id} if chunk_id is not None else changed,
                           missing_only=missing_only)


@app.route("/project/<scene_name>")
def project(scene_name):
    session = _get_session(scene_name)
    if not session:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"scene_name": scene_name, "chunks": session["chunks"], "assets": session["assets"],
                    "varagent": ({key: session["varagent"][key] for key in ("source_dir", "full_duration", "motion_planned")}
                                 if session.get("varagent") else None),
                    "video_mode": session.get("video_mode", "faceless"),
                    "avatar_library": session.get("avatar_library", []),
                    "avatar_workflow": session.get("avatar_workflow", "library"),
                    "avatar_tasks": avatar_tasks(session) if session.get("avatar_workflow") == "dreamina" else [],
                    "avatar_summary": timeline_summary(session["chunks"]),
                    "graphics_summary": graphics_summary(session['chunks'],session.get('text_cues',[]),session.get('motion_graphics_target',70)),
                    "shot_editing": editing_summary(session["chunks"], session.get("transitions", [])),
                    "selection_review": selection_review(session["chunks"],session["assets"],session.get("file_overrides",{})),
                    "motion_graphics_target": session.get('motion_graphics_target',70),
                    "text_cues": session.get("text_cues", []),
                    "main_entity": session.get("main_entity", ""), "scientific_name": session.get("scientific_name", ""),
                    "main_entity_type": session.get("main_entity_type", "species" if session.get("scientific_name") else "generic"),
                    "query_budget": session.get("query_budget", DEFAULT_QUERY_BUDGET),
                    "language": session.get("language", DEFAULT_LANGUAGE),
                    "processing_mode": session.get("processing_mode", "quality"),
                    "reserp_mode": session.get("reserp_mode", False),
                    "brightdata_mode": session.get("brightdata_mode", False),
                    "youtube_mode": session.get("youtube_mode", False),
                    "elderly_mode": session.get("elderly_mode", False),
                    "file_overrides": session.get("file_overrides", {}),
                    "has_input": os.path.isfile(os.path.join(session["scene_dir"],"luna_input.json")),
                    "downloads_complete": session.get("downloads_complete", False),
                    "busy": session["busy"], "progress": session.get("progress", ""), "has_preview": os.path.isfile(os.path.join(session["scene_dir"],"preview.mp4")),
                    "has_final": os.path.isfile(os.path.join(session["scene_dir"], f"{scene_name}.mp4"))})


@app.route('/motion_graphics', methods=['POST'])
def set_motion_graphics():
    data=request.get_json(silent=True) or {}
    session=_get_session(data.get('scene_name',''))
    if not session: return jsonify({'error':'Нет проекта'}),400
    if not _claim_session(session): return jsonify({'error':'Проект занят'}),409
    try:
        value=graphics_target(data.get('motion_graphics_target'))
        session['motion_graphics_target']=value
        _save_project(session)
        return jsonify({'ok':True,'motion_graphics_target':value,
            'graphics_summary':graphics_summary(session['chunks'],session.get('text_cues',[]),value)})
    except (ValueError,TypeError) as exc:
        return jsonify({'error':str(exc)}),400
    finally:
        _release_session(session)


@app.route("/video_mode", methods=["POST"])
def set_video_mode():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", "")) if isinstance(data, dict) else None
    if not session:
        return jsonify({"error": "Сначала подготовь озвучку или открой проект"}), 404
    try:
        mode = validate_video_mode(data.get("video_mode"))
        workflow = validate_avatar_workflow(data.get("avatar_workflow", session.get("avatar_workflow", "library")))
        if workflow == "dreamina":
            validate_dreamina_chunks(session["chunks"], session["audio_duration"])
        if mode == "faceless" and any(c.get("template") in AVATAR_TEMPLATES or c.get("media_origin") == "ai_image" for c in session["chunks"]):
            raise ValueError("В таймлайне есть ведущая/ИИ-фото. Сначала замени эти сцены для режима Faceless")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    try:
        session["video_mode"] = mode
        session["avatar_workflow"] = workflow
        _save_project(session)
        timeline = os.path.join(session["scene_dir"], "timeline.json")
        if os.path.isfile(timeline):
            with open(timeline, encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                payload["video_mode"] = mode
                payload["avatar_workflow"] = workflow
                with open(timeline, "w", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "video_mode": mode, "avatar_workflow": workflow})
    finally:
        _release_session(session)


@app.route("/upload_avatar", methods=["POST"])
def upload_avatar():
    session = _get_session(request.form.get("scene_name", ""))
    if not session or session.get("video_mode", "faceless") != "ai_avatar":
        return jsonify({"error": "Открой проект в режиме ИИ-аватар"}), 400
    if session.get("avatar_workflow") == "dreamina":
        return jsonify({"error": "Загружай видео Dreamina в конкретную вставку аватара"}), 400
    uploads = request.files.getlist("avatars")
    if not uploads or any(not f.filename for f in uploads):
        return jsonify({"error": "Выбери видео ведущей"}), 400
    if len(session.get("avatar_library", [])) + len(uploads) > 5:
        return jsonify({"error": "В библиотеке максимум 5 клипов. Убери ненужный клип перед заменой"}), 400
    if any(os.path.splitext(f.filename)[1].lower() not in VIDEO_EXTENSIONS for f in uploads):
        return jsonify({"error": "Нужны MP4/MOV/WebM/MKV ведущей"}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    saved, entries = [], []
    try:
        folder = os.path.join(session["scene_dir"], "downloads")
        os.makedirs(folder, exist_ok=True)
        for uploaded in uploads:
            identifier = "avatar_" + uuid.uuid4().hex
            name = identifier + os.path.splitext(uploaded.filename)[1].lower()
            path = os.path.join(folder, name)
            saved.append(path)
            uploaded.save(path)
            info = probe_video(path)
            entries.append({"id": identifier, "filename": name, "label": os.path.basename(uploaded.filename), **info})
        session.setdefault("avatar_library", []).extend(entries)
        _save_project(session)
        return jsonify({"ok": True, "avatar_library": session["avatar_library"]})
    except (OSError, ValueError, subprocess.SubprocessError):
        session["avatar_library"] = [c for c in session.get("avatar_library", []) if c["id"] not in {e["id"] for e in entries}]
        for path in saved:
            if os.path.isfile(path):
                os.remove(path)
        return jsonify({"error": "Не удалось прочитать видео ведущей; библиотека не изменена"}), 400
    finally:
        _release_session(session)


@app.route("/remove_avatar", methods=["POST"])
def remove_avatar():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", "")) if isinstance(data, dict) else None
    if not session:
        return jsonify({"error": "Проект не найден"}), 404
    clip = data.get("clip_id")
    if any(c.get("avatar", {}).get("clip_id") == clip for c in session["chunks"]):
        return jsonify({"error": "Этот клип назначен сцене. Сначала поставь clip_id:auto или другой ID в timeline.json"}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    try:
        session["avatar_library"] = [c for c in session.get("avatar_library", []) if c["id"] != clip]
        _save_project(session)  # Keep the file for existing renders; only remove its library entry.
        return jsonify({"ok": True, "avatar_library": session["avatar_library"]})
    finally:
        _release_session(session)


def _dreamina_chunk(session, chunk_id):
    if not session or session.get("video_mode") != "ai_avatar" or session.get("avatar_workflow") != "dreamina":
        raise ValueError("Открой проект в режиме аватара Dreamina")
    chunk = next((c for c in session["chunks"] if c["id"] == chunk_id and c.get("template") in AVATAR_TEMPLATES), None)
    if chunk is None:
        raise ValueError("Вставка аватара не найдена")
    validate_dreamina_chunks([chunk], session["audio_duration"])
    return chunk


@app.route("/avatar_audio/<scene_name>/<int:chunk_id>")
def avatar_audio(scene_name, chunk_id):
    session = _get_session(scene_name)
    try:
        chunk = _dreamina_chunk(session, chunk_id)
        start, duration = avatar_interval(chunk, session["audio_duration"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    try:
        source = session["audio_path"]
        stat = os.stat(source)
        key = hashlib.sha256(json.dumps([source, stat.st_size, stat.st_mtime_ns, start, duration]).encode()).hexdigest()[:16]
        folder = os.path.join(session["scene_dir"], "avatar_audio")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"avatar_{chunk_id+1:03d}_{key}.wav")
        if not os.path.isfile(path):
            staging = path + ".tmp.wav"
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", source,
                                "-map", "0:a:0", "-vn", "-af", "apad", "-t", str(duration),
                                "-ar", "48000", "-c:a", "pcm_s16le", staging],
                               check=True, capture_output=True, timeout=60)
                os.replace(staging, path)
            finally:
                if os.path.isfile(staging):
                    os.remove(staging)
        return send_file(path, mimetype="audio/wav", as_attachment=True, download_name=f"avatar_{chunk_id+1:03d}.wav")
    except (OSError, subprocess.SubprocessError):
        return jsonify({"error": "Не удалось вырезать WAV из исходной озвучки"}), 400
    finally:
        _release_session(session)


@app.route("/avatar_clip", methods=["POST", "DELETE"])
def avatar_clip():
    data = (request.get_json(silent=True) or {}) if request.method == "DELETE" else request.form
    if request.method == "DELETE" and not isinstance(data, dict):
        return jsonify({"error": "Нужны scene_name и chunk_id"}), 400
    session = _get_session(data.get("scene_name", ""))
    try:
        chunk_id = int(data.get("chunk_id", -1))
        chunk = _dreamina_chunk(session, chunk_id)
        offset = float(data.get("source_start", 0))
        if not math.isfinite(offset) or not 0 <= offset <= 86400:
            raise ValueError("Начало речи в видео: число секунд от 0")
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    path = None
    old = dict(session.get("avatar_assignments", {}))
    try:
        assignments = session.setdefault("avatar_assignments", {})
        if request.method == "DELETE":
            assignments.pop(str(chunk_id), None)
        else:
            uploaded = request.files.get("video")
            if uploaded:
                if not uploaded.filename or os.path.splitext(uploaded.filename)[1].lower() not in VIDEO_EXTENSIONS:
                    raise ValueError("Загрузи MP4/MOV/WebM/MKV из Dreamina")
                name = "dreamina_" + uuid.uuid4().hex + os.path.splitext(uploaded.filename)[1].lower()
                folder = os.path.join(session["scene_dir"], "downloads")
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, name)
                uploaded.save(path)
                info = probe_video(path)
                label = os.path.basename(uploaded.filename)
                zoom_percent = 110
                tail_padding_seconds = 0
            else:
                entry = assignments.get(str(chunk_id), {})
                name = entry.get("filename", "")
                existing = _safe_media_path(session["scene_name"], name)
                if entry.get("span") != avatar_span(chunk) or not existing or not os.path.isfile(existing):
                    raise ValueError("Сначала загрузи видео Dreamina для этой реплики")
                info = probe_video(existing)
                label = entry["label"]
                zoom_percent = entry.get("zoom_percent", 100)
                tail_padding_seconds = entry.get("tail_padding_seconds", 0)
            _, duration = avatar_interval(chunk, session["audio_duration"])
            shortfall = offset + duration - info["duration"]
            if shortfall > .001 and (not uploaded or shortfall > .1 + .000001):
                raise ValueError(f"После выбранного начала в видео нужно {duration:.3f} с; файл длится {info['duration']:.3f} с. Таймлайн не изменён.")
            if uploaded:
                original_duration = info["duration"]
                if shortfall > .001:
                    zoomed_path, info = zoom_avatar_video(path, info, minimum_duration=offset + duration)
                    tail_padding_seconds = max(0, info["duration"] - original_duration)
                else:
                    zoomed_path, info = zoom_avatar_video(path, info)
                path = str(zoomed_path)
                name = zoomed_path.name
            assignments[str(chunk_id)] = {"filename": name, "label": label,
                                         "source_start": offset, "span": avatar_span(chunk),
                                         "zoom_percent": zoom_percent, "tail_padding_seconds": tail_padding_seconds, **info}
        _save_project(session)
        return jsonify({"ok": True, "avatar_tasks": avatar_tasks(session)})
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        session["avatar_assignments"] = old
        if path and os.path.isfile(path):
            os.remove(path)
        return jsonify({"error": str(exc) if isinstance(exc, ValueError) else "Не удалось обработать видео аватара; предыдущее назначение сохранено"}), 400
    finally:
        _release_session(session)


@app.route("/ai_prompts/<scene_name>")
def ai_prompts(scene_name):
    session = _get_session(scene_name)
    if not session:
        return jsonify({"error": "Проект не найден"}), 404
    return Response(json.dumps({"images": ai_prompt_manifest(session["chunks"])}, ensure_ascii=False, indent=2),
                    mimetype="application/json", headers={"Content-Disposition": 'attachment; filename="ai_prompts.json"'})


@app.route("/retrieval_debug/<scene_name>")
def retrieval_debug(scene_name):
    session = _get_session(scene_name)
    if not session: return jsonify({"error": "Проект не найден"}), 404
    rows = session.get("retrieval_debug", {})
    usage = {key: {"requests_used": entries[-1].get("requests_used", entries[-1].get("queries_used", 0)),
                   "max_requests": entries[-1].get("max_requests", entries[-1].get("query_budget"))}
             for key, entries in rows.items() if entries}
    usage.update(session.get("retrieval_usage", {}))
    return jsonify({"main_entity": session.get("main_entity", ""), "scientific_name": session.get("scientific_name", ""),
                    "main_entity_type": session.get("main_entity_type", "species" if session.get("scientific_name") else "generic"),
                    "query_budget": session.get("query_budget", DEFAULT_QUERY_BUDGET),
                    "request_usage": usage, "scenes": rows})


@app.route("/text_tasks/<scene_name>")
def text_tasks(scene_name):
    session = _get_session(scene_name)
    if not session:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify({"folder": str(export_folder(session["scene_dir"])),
                    "tasks": task_status(session["scene_dir"], session.get("text_cues", []))})


@app.route("/upload_media", methods=["POST"])
def upload_media():
    session = _get_session(request.form.get("scene_name", ""))
    uploaded = request.files.get("media")
    try:
        chunk_id = int(request.form.get("chunk_id", ""))
        panel_index = int(request.form.get("panel_index", "0"))
    except ValueError:
        return jsonify({"error": "Неверная сцена/панель"}), 400
    chunk = next((c for c in session["chunks"] if c["id"] == chunk_id), None) if session else None
    if not chunk or not uploaded or not uploaded.filename:
        return jsonify({"error": "Нужны проект, сцена и файл"}), 400
    extension = os.path.splitext(uploaded.filename)[1].lower()
    if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        return jsonify({"error": "Нужен JPG/PNG/WebP или MP4/MOV/WebM/MKV"}), 400
    if chunk.get("template") == "avatar_full":
        return jsonify({"error": "Добавь этот клип через библиотеку ведущей"}), 400
    if chunk.get("media_origin") == "ai_image" and extension not in IMAGE_EXTENSIONS:
        return jsonify({"error": "Для этого кадра нужно ИИ-фото JPG/PNG/WebP"}), 400
    if chunk.get("panels") and not 0 <= panel_index < len(chunk["panels"]):
        return jsonify({"error": "Панель не найдена"}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    filename = f"user_{uuid.uuid4().hex}{extension}"
    folder = os.path.join(session["scene_dir"], "downloads")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    previous = copy.deepcopy({key: session.get(key, [] if key=='editorial_corrections' else {}) for key in ('chunks', 'assets', 'file_overrides', 'editorial_corrections')})
    try:
        uploaded.save(path)
        dimensions(path)
        if chunk.get("template") in AVATAR_TEMPLATES:
            chunk["type"] = "video" if extension in VIDEO_EXTENSIONS else "photo"
        session['assets'][filename] = {'source': 'Локальный файл', 'rights_confirmed': False,
                                      'media_origin': chunk.get('media_origin', 'real')}
        record_choice(session, chunk, [filename])
        chunk["files"].insert(0, filename)
        session.setdefault("file_overrides", {})[str(chunk_id)] = [filename]
        if chunk.get("panels"):
            chunk["panels"][panel_index]["files"].insert(0, filename)
        related = propagate_choice(session, chunk, [filename])
        _save_assets(session)
        return jsonify({"ok": True, "filename": filename, "chunk": chunk, "asset": session["assets"][filename], 'reused_chunks':related})
    except (ValueError, KeyError, OSError, IndexError, subprocess.SubprocessError):
        session.update(previous)
        if os.path.isfile(path):
            os.remove(path)
        return jsonify({"error": "Не удалось прочитать медиафайл"}), 400
    finally:
        _release_session(session)


@app.route("/youtube_clip", methods=["POST"])
def youtube_clip():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Нужны ссылка и начало отрезка"}), 400
    session = _get_session(str(body.get("scene_name", "")))
    try:
        cid, panel = int(body.get("chunk_id", "")), int(body.get("panel_index", 0))
        chunk = next((c for c in session["chunks"] if c["id"] == cid), None) if session else None
        if not chunk: raise ValueError("Клип не найден")
        if chunk.get("panels") and not 0 <= panel < len(chunk["panels"]):
            raise ValueError("Панель не найдена")
        if chunk.get("template") == "avatar_full":
            raise ValueError("Добавь этот клип через библиотеку ведущей")
        if chunk.get("media_origin") == "ai_image":
            raise ValueError("Для этого кадра нужно ИИ-фото JPG/PNG/WebP")
        url, start, length = youtube_clip_request(body.get("url", ""), body.get("start", ""), chunk["duration"])
    except (ValueError, TypeError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    filename = f"user_{uuid.uuid4().hex}.mp4"
    folder = os.path.join(session["scene_dir"], "downloads")
    path = os.path.join(folder, filename)
    previous = copy.deepcopy({key: session.get(key, [] if key=='editorial_corrections' else {}) for key in ("chunks", "assets", "file_overrides", "editorial_corrections")})
    try:
        os.makedirs(folder, exist_ok=True)
        asset = download_youtube_clip(url, start, length, path)
        dimensions(path)
        _check_cancelled(session)
        if chunk.get("template") in AVATAR_TEMPLATES:
            chunk["type"] = "video"
        record_choice(session, chunk, [filename])
        chunk["files"].insert(0, filename)
        if chunk.get("panels"):
            chunk["panels"][panel]["files"].insert(0, filename)
        session.setdefault("file_overrides", {})[str(cid)] = [filename]
        asset.update(media_origin='real', editor_confirmed=True)
        session["assets"][filename] = asset
        _save_assets(session)
        return jsonify({"ok": True, "filename": filename, "chunk": chunk, "asset": asset})
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        session.update(previous)
        if os.path.isfile(path): os.remove(path)
        return jsonify({"error": str(exc) or "Не удалось скачать отрезок"}), 400
    finally:
        _release_session(session)

@app.route("/import_timeline", methods=["POST"])
def import_timeline(existing_session=None, existing_timeline=None, force_search=False, missing_only=False):
    session = existing_session or _get_session(request.form.get("scene_name", ""))
    uploaded = existing_timeline or request.files.get("timeline")
    if session and session.get("varagent"):
        return _import_varagent_motion(session, uploaded)
    if not session or not uploaded or not _claim_session(session):
        return jsonify({"error": "Не удалось открыть timeline.json"}), 400
    if existing_session is None:
        force_search = False  # Preserve unchanged shots and the user's choices when editing a timeline.
        for field in ("elderly_mode", "reserp_mode", "brightdata_mode", "youtube_mode"):
            if field in request.form:
                session[field] = request.form[field] == "1"
        processing_mode = request.form.get("processing_mode", session.get("processing_mode", "quality"))
        if processing_mode not in _PROCESSING_MODES:
            _release_session(session)
            return jsonify({"error": "Режим обработки: fast или quality"}), 400
        session["processing_mode"] = processing_mode
    try:
        data = json.load(uploaded)
        if isinstance(data, dict):
            data = without_retired_templates(data)
        elif isinstance(data, list):
            data = without_retired_templates({'chunks': data})['chunks']
        motion_target = graphics_target(data.get('motion_graphics_target',session.get('motion_graphics_target',70)) if isinstance(data,dict) else session.get('motion_graphics_target',70))
        video_mode = validate_video_mode(data.get("video_mode", session.get("video_mode", "faceless")) if isinstance(data, dict) else session.get("video_mode", "faceless"))
        avatar_workflow = validate_avatar_workflow(data.get("avatar_workflow", session.get("avatar_workflow", "library")) if isinstance(data, dict) else session.get("avatar_workflow", "library"))
        chunks = data.get("chunks") if isinstance(data, dict) else data
        if isinstance(data, dict) and "chunks" not in data and "word_timestamps" in data:
            raise ValueError("Загружен luna_input.json. Передай его Codex и загрузи полученный timeline.json с chunks.")
        if not isinstance(chunks, list) or not chunks or len(chunks) > 2000:
            raise ValueError("Нужен массив chunks, максимум 2000 сцен")
        if not missing_only:
            chunks = _bind_shots_to_words(chunks, session)
        project_search = {key: (data.get(key, session.get(key, "")) if isinstance(data, dict) else session.get(key, ""))
                          for key in ("main_entity", "scientific_name")}
        for key, value in project_search.items():
            if not isinstance(value, str) or len(value) > 200: raise ValueError(f"{key}: строка до 200 символов")
            project_search[key] = value.strip()
        same_main = project_search["main_entity"] == session.get("main_entity", "")
        if not same_main and isinstance(data, dict) and "scientific_name" not in data:
            project_search["scientific_name"] = ""
        default_type = session.get("main_entity_type") if same_main else None
        project_search["main_entity_type"] = data.get("main_entity_type", default_type) if isinstance(data, dict) else default_type
        if project_search["main_entity_type"] is None:
            project_search["main_entity_type"] = "species" if project_search["scientific_name"] else "generic"
        if not isinstance(project_search["main_entity_type"], str) or project_search["main_entity_type"] not in ENTITY_TYPES:
            raise ValueError("main_entity_type: species/person/place/organization/object/event/culture/generic")
        if project_search["main_entity_type"] != "species":
            project_search["scientific_name"] = ""
        project_search["query_budget"] = data.get("query_budget", session.get("query_budget", DEFAULT_QUERY_BUDGET)) if isinstance(data, dict) else session.get("query_budget", DEFAULT_QUERY_BUDGET)
        if type(project_search["query_budget"]) is not int or not 1 <= project_search["query_budget"] <= 6:
            raise ValueError("query_budget: целое число 1–6")
        papers = ([entry["id"] for entry in library_catalog() if entry["category"] == "paper"]
                  if any(isinstance(chunk, dict) and chunk.get("template") for chunk in chunks) else [])
        normalized = []
        preserved_ids = set()
        selection_ids = set()
        for index, item in enumerate(chunks):
            if not isinstance(item, dict):
                raise ValueError(f"Ошибка в чанке {index + 1}")
            if video_mode == "faceless" and (item.get("template") in AVATAR_TEMPLATES or item.get("media_origin") == "ai_image"):
                raise ValueError("Ведущая и ИИ-фото доступны в режиме video_mode:ai_avatar")
            item = inherit_main_entity(item, project_search["main_entity"], project_search["scientific_name"], project_search["main_entity_type"])
            if item.get("template") and item["template"] not in AVATAR_TEMPLATES and isinstance(item.get("params", {}), dict) and not item.get("params", {}).get("paper"):
                if not papers:
                    raise ValueError("Для Remotion нужен хотя бы один фон в assets/paper")
                item = {**item, "params": {**item.get("params", {}), "paper": random.choice(papers)}}
            if item.get("panels"):
                item["panels"] = [inherit_main_entity(p, project_search["main_entity"], project_search["scientific_name"], project_search["main_entity_type"]) if isinstance(p, dict) else p for p in item["panels"]]
            start, end = float(item["start"]), float(item["end"])
            if (item.get("type") not in ("photo", "video")
                    or not isinstance(item.get("query"), str) or not item["query"].strip()
                    or isinstance(item["start"], bool) or isinstance(item["end"], bool)
                    or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
                raise ValueError(f"Ошибка в чанке {index + 1}")
            for field in ("fallback_queries", "highlights"):
                values = item.get(field) or []
                if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                    raise ValueError(f"Неверный формат {field} в чанке {index + 1}")
            if item.get("editor_note_ru") is not None and (not isinstance(item["editor_note_ru"], str) or not item["editor_note_ru"].strip()):
                raise ValueError(f"editor_note_ru должен быть непустой строкой в чанке {index + 1}")
            if abs(start - (normalized[-1]["end"] if normalized else 0)) > .001 or end-start < 1/30:
                raise ValueError(f"Чанк {index+1}: пропуск/пересечение таймкодов или длительность меньше кадра")
            start = normalized[-1]["end"] if normalized else 0
            validate_scene(item)
            item = apply_photo_intent(item)
            validate_search_plan(item)
            for panel in item.get("panels", []):
                validate_search_plan(panel)
            previous = next((c for c in session["chunks"] if c["id"] == index), {})
            if previous:
                validate_search_plan(previous)
            if missing_only and previous.get("files") and all(
                    _safe_media_path(session["scene_name"], name) and os.path.isfile(_safe_media_path(session["scene_name"], name))
                    for name in previous["files"]):
                normalized.append(copy.deepcopy(previous))
                preserved_ids.add(index)
                selection_ids.add(index)
                continue
            if previous:
                validate_search_plan(previous)
                for panel in previous.get("panels", []):
                    validate_search_plan(panel)
            refresh = force_search is True or isinstance(force_search, set) and index in force_search
            same_query = (previous.get("query") == item["query"] and previous.get("type") == item["type"]
                          and previous.get("music_insert") == item.get("music_insert")
                          and previous.get("media_origin", "real") == item.get("media_origin", "real")
                          and previous.get("ai_prompt") == item.get("ai_prompt")
                          and previous.get("text") == item.get("text")
                          and previous.get("shot_plan") == item.get("shot_plan")
                          and previous.get("scene_id") == item.get("scene_id")
                          and previous.get("start") == start and previous.get("end") == end
                          and all(previous.get(key) == item.get(key) for key in SEARCH_FIELDS)
                          and [(p["query"], p.get("type","photo")) for p in previous.get("panels", [])] ==
                              [(p["query"], p.get("type","photo")) for p in item.get("panels", [])])
            same_query = same_query and [tuple(p.get(key) for key in SEARCH_FIELDS) for p in previous.get("panels", [])] == [tuple(p.get(key) for key in SEARCH_FIELDS) for p in item.get("panels", [])]
            if item.get("shot_plan") and index and normalized[-1].get("scene_id") == item.get("scene_id") and index-1 not in preserved_ids:
                same_query = False
            if same_query:
                selection_ids.add(index)
                if not refresh:
                    preserved_ids.add(index)
            panels = [{**p, "files": previous.get("panels", [])[n].get("files", []) if same_query else []}
                      for n, p in enumerate(item.get("panels", []))]
            normalized.append({**item, "start": start, "end": end, "id": index, "duration": end-start,
                               "files": previous.get("files", []) if same_query else [], **({"panels": panels} if panels else {})})
        duration = session.get("audio_duration", normalized[-1]["end"]) + inserted_duration(normalized)
        if abs(normalized[-1]["end"]-duration) > .05:
            raise ValueError("Последний чанк должен заканчиваться на audio_duration")
        normalized[-1]["end"] = duration
        normalized[-1]["duration"] = duration-normalized[-1]["start"]
        if avatar_workflow == "dreamina":
            validate_dreamina_chunks(normalized, duration)
        tracks = data if isinstance(data, dict) else {}
        for transition in tracks.get("transitions", []):
            if (isinstance(transition, dict) and transition.get("kind") == "overlay"
                    and os.path.basename(str(transition.get("asset", ""))).lower().startswith("light leaks")):
                transition["opacity"] = 1
        validate_tracks(tracks, duration, normalized)
        carousel_groups(normalized)
        comparison_groups(normalized)
        word_timestamps = None
        if any(isinstance(c, dict) and c.get("template") in SPEECH_TEXT for c in tracks.get("text_cues", []) or []):
            word_file = os.path.join(session["scene_dir"], "luna_input.json")
            if not os.path.isfile(word_file):
                raise ValueError("Для текста по речи сначала подготовь озвучку: нужны таймкоды WhisperX")
            with open(word_file, encoding="utf-8") as file:
                word_timestamps = json.load(file)["word_timestamps"]
            if inserted_duration(normalized):
                word_timestamps = shifted_words(word_timestamps, normalized)
        text_cues = normalize_text_cues(tracks.get("text_cues"), duration, normalized, word_timestamps)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        _release_session(session)
        return jsonify({"error": str(exc)}), 400
    messages = queue.Queue()
    previous_candidates = {_asset_identity(session["assets"].get(name))
                           for chunk in session["chunks"]
                           if isinstance(force_search, set) and chunk["id"] in force_search
                           for name in chunk.get("files", [])}
    def worker():
        try:
            def progress(message): messages.put(json.dumps({"progress": message}))
            _check_cancelled(session)
            session.update({**project_search, "motion_graphics_target":motion_target, "video_mode": video_mode, "avatar_workflow": avatar_workflow, "chunks": normalized, "transitions": tracks.get("transitions", []),
                            "audio_tracks": tracks.get("audio_tracks", []), "text_cues": text_cues,
                            "downloads_complete": False})
            if force_search and not missing_only:
                session["retrieval_debug"], session["retrieval_usage"] = {}, {}
            elif missing_only:
                for cid in force_search:
                    session.setdefault("retrieval_debug", {}).pop(str(cid), None)
                    session.setdefault("retrieval_usage", {}).pop(str(cid), None)
            session["failed_media"] = set()
            session["youtube_health"] = {"failures": 0}
            session["file_overrides"] = {k:v for k,v in session.get("file_overrides", {}).items() if int(k) in selection_ids}
            with open(os.path.join(session["scene_dir"], "timeline.json"), "w", encoding="utf-8") as file:
                json.dump({key: session[key] for key in ("motion_graphics_target", "video_mode", "avatar_workflow", "main_entity", "main_entity_type", "scientific_name", "query_budget", "chunks", "transitions", "audio_tracks", "text_cues")}, file, ensure_ascii=False, indent=2)
            write_task_list(session["scene_dir"], text_cues)
            _save_project(session)
            messages.put(json.dumps({"text_tasks": True, "scene_name": session["scene_name"]}))
            seen_media = {_asset_identity(session["assets"].get(name)) for c in normalized for name in c.get("files", [])}
            seen_media.update(previous_candidates)
            seen_media.discard("")
            image_hashes = set()
            for c in normalized:
                for name in c.get("files", []):
                    asset = session["assets"].get(name, {})
                    fingerprint = asset.get("perceptual_hash")
                    if not fingerprint:
                        path = _safe_media_path(session["scene_name"], name)
                        fingerprint = image_perceptual_hash(path) if path else None
                        if fingerprint: asset["perceptual_hash"] = fingerprint
                    if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{16}", fingerprint): image_hashes.add(fingerprint)
            existing_assets = dict(session["assets"])
            approved_library = load_approved(OUTPUT_DIR)
            used_approved = set()
            media_lock = threading.Lock()
            provider_failures = {}
            for chunk in normalized:
                messages.put(json.dumps({"chunk_found": {key: chunk.get(key) for key in ("id", "type", "query", "text", "editor_note_ru", "start", "end", "duration", "preset", "template", "params", "panels", "avatar", "media_origin", "ai_prompt")}}))
            def retrieve_chunk(original, previous_visual=None):
                chunk = copy.deepcopy(original)
                local_assets, debug = dict(existing_assets), []
                _check_cancelled(session)
                if is_geo_scene(chunk) or chunk.get('template')=='data_comparison':
                    path=graphic_placeholder(chunk,Path(session['scene_dir'])/'downloads')
                    name=os.path.basename(path)
                    chunk['files']=[name]
                    local_assets[name]={'source':'Графика Remotion из данных сцены','rights_confirmed':False,'generated_graphic':True}
                    messages.put(json.dumps({'file_downloaded':{'chunk_id':chunk['id'],'filename':name,'type':'photo','asset':local_assets[name]}}))
                    return chunk,local_assets,debug,{'requests_used':0,'max_requests':0}
                if chunk.get("template") == "avatar_full" or chunk.get("media_origin") == "ai_image":
                    # Library footage and manually generated images never spend search requests.
                    progress(f"Сцена {chunk['id']+1}: " + (("ожидает своё видео Dreamina" if avatar_workflow == "dreamina" else "клип из библиотеки ведущей") if chunk.get("template") == "avatar_full" else "ожидает ИИ-фото из Google Flow"))
                    for name in chunk.get("files", []):
                        messages.put(json.dumps({"file_downloaded": {"chunk_id": chunk["id"], "filename": name,
                                                                   "type": chunk["type"], "asset": local_assets.get(name)}}))
                    return chunk, local_assets, debug, {"requests_used": 0, "max_requests": 0}
                context = retrieval_context(chunk.get("query_budget", session["query_budget"]), (), image_hashes,
                                            debug.append, session["failed_media"])
                context["seen"], context["lock"] = seen_media, media_lock
                context["provider_failures"] = provider_failures
                options = {"progress_callback": progress, "elderly_mode": session.get("elderly_mode", False),
                           "reserp_mode": session.get("reserp_mode", False), "youtube_mode": session.get("youtube_mode", False),
                           "brightdata_mode": session.get("brightdata_mode", False),
                           "youtube_health": session["youtube_health"],
                           "excluded_urls": set(),
                           "retrieval": context,
                           "pool_sources": session.get("processing_mode", "quality") == "quality",
                           "asset_callback": lambda name, asset: local_assets.update({name: asset}),
                           "candidate_ranker": lambda plan, files, assets: rank_files(
                               plan["query"], files, assets, progress,
                               plan={**plan, "duration": chunk["duration"],
                                     "_processing_mode": session.get("processing_mode", "quality")},
                               reject_below_threshold=True)}
                for panel_index, panel in enumerate(chunk.get("panels") or [chunk]):
                    search = {**{key: value for key, value in chunk.items() if key not in SEARCH_FIELDS + ("fallback_queries",)},
                              **panel, "type": panel.get("type", "photo")}
                    # Runtime context is rebuilt here, never trusted from imported JSON.
                    search["_shot_context"] = shot_context(normalized, chunk["id"])
                    search["_previous_visual"] = previous_visual
                    search["_processing_mode"] = session.get("processing_mode", "quality")
                    search.setdefault("context", " ".join(c.get("text", "") for c in normalized[max(0, chunk["id"]-1):chunk["id"]+2]))
                    cached = [name for name in panel.get("files", []) if _safe_media_path(session["scene_name"], name) and os.path.isfile(_safe_media_path(session["scene_name"], name))]
                    if cached and chunk["id"] in preserved_ids:
                        progress(f"Сцена {chunk['id']+1}: использую уже скачанные материалы")
                        files = [os.path.join(session["scene_dir"], "downloads", name) for name in cached]
                    else:
                        # Fresh names preserve candidates referenced by an older render or an open picker.
                        offset = panel_index * 10000 + 100 * (1 + len(existing_assets))
                        with media_lock:
                            reused = reuse_approved(panel, approved_library, session['scene_dir'], chunk['id'], used_approved)
                        if reused:
                            path, asset = reused
                            files = [path]
                            local_assets[os.path.basename(path)] = asset
                            if asset.get('perceptual_hash'):
                                with media_lock: image_hashes.add(asset['perceptual_hash'])
                            progress(f'Сцена {chunk["id"]+1}: использую подтверждённый материал с теми же требованиями')
                            debug.append(dict(source='editor_approved', requests_used=0,
                                              approved_from=asset['approved_from']))
                        else:
                            files = download_for_chunk(search, chunk["id"], session["scene_dir"],
                                                       per_source=2 if session.get("processing_mode") == "fast" else 3,
                                                       file_offset=offset, **options)
                    if (files and search["type"] != panel.get("type", "photo")
                            and not (cached and chunk["id"] in selection_ids)):
                        panel["type"] = search["type"]
                        if not chunk.get("panels"):
                            chunk["type"] = search["type"]
                            if "preset" not in chunk or chunk["preset"] == "PHOTO_STATIC":
                                chunk["preset"] = "BLUR_BG_CENTER" if search["type"] == "photo" else "PHOTO_STATIC"
                        messages.put(json.dumps({"chunk_updated": {"id": chunk["id"], "type": chunk["type"], "preset": chunk.get("preset"), "panels": chunk.get("panels")}}))
                    if search.get("visual_role"):
                        panel["visual_role"] = search["visual_role"]
                    panel["files"] = list(cached) if chunk["id"] in selection_ids else []
                    if not chunk.get("panels"):
                        chunk["files"] = panel["files"]
                    for path in files:
                        name = os.path.basename(path)
                        if name not in panel["files"]:
                            panel["files"].append(name)
                        if chunk.get("panels") and name not in chunk["files"]:
                            chunk["files"].append(name)
                    for name in panel["files"]:
                        messages.put(json.dumps({"file_downloaded": {"chunk_id": chunk["id"], "filename": name, "type": search["type"], "preset": chunk.get("preset"), "asset": local_assets.get(name)}}))
                return chunk, local_assets, debug, {"requests_used": context["used"], "max_requests": context["limit"]}
            completed_shots = queue.Queue()
            def retrieve_group_shots(indices):
                previous_visual = None
                for index in indices:
                    original = normalized[index]
                    if missing_only and original["id"] in preserved_ids:
                        chunk, assets = original, existing_assets
                    else:
                        result = retrieve_chunk(original, previous_visual)
                        completed_shots.put(result)
                        chunk, assets = result[:2]
                    # The first candidate is the automatic selection, also used by the builder.
                    selected = session.get("file_overrides", {}).get(str(chunk["id"]), [])
                    name = next((n for n in selected if n in chunk.get("files", [])), None)
                    name = name or next(iter(chunk.get("files", [])), None)
                    path = _safe_media_path(session["scene_name"], name) if name else None
                    asset = assets.get(name, {})
                    previous_visual = ({"path": path, "description": json.dumps({
                        "query": chunk.get("query"), "shot_plan": chunk.get("shot_plan"),
                        "evidence": asset.get("vision_visual_evidence"),
                        "assessment": asset.get("vision_reason", "")}, ensure_ascii=False)} if path else None)
            def retrieve_group(indices):
                try:
                    retrieve_group_shots(indices)
                finally:
                    completed_shots.put(None)
            # Planned scene shots select sequentially; independent scenes still run in parallel.
            # Only this thread commits project.json.
            with ThreadPoolExecutor(max_workers=4 if session.get("processing_mode") == "fast" else 3) as pool:
                futures = [pool.submit(retrieve_group, indices) for indices in retrieval_groups(normalized)]
                finished = 0
                while finished < len(futures):
                    result = completed_shots.get()
                    if result is None:
                        finished += 1
                        continue
                    chunk, assets, debug, usage = result
                    normalized[chunk["id"]] = chunk
                    session["assets"].update({name: assets[name] for name in chunk["files"] if name in assets})
                    session.setdefault("retrieval_debug", {})[str(chunk["id"])] = debug
                    session.setdefault("retrieval_usage", {})[str(chunk["id"])] = usage
                    _save_project(session)
                for future in futures:
                    future.result()
            ordered_files = balance_sequence(normalized, session['assets'],session.get('file_overrides',{}),preserved_ids)
            session["downloads_complete"] = True
            missing = sum(not chunk.get("files") for chunk in normalized
                          if chunk.get("template") != "avatar_full" and chunk.get("media_origin") != "ai_image")
            progress(f"Материалы: {len(normalized)-missing} из {len(normalized)} кадров; без материала: {missing}")
            _save_assets(session)
            messages.put(json.dumps({"downloads_done": True, "scene_name": session["scene_name"],
                                     "ordered_files":ordered_files,
                                     "video_mode": session.get("video_mode", "faceless"), "missing_media_count": missing,
                                     "reserp_mode": session.get("reserp_mode",False), "brightdata_mode": session.get("brightdata_mode",False)}))
            # Always let the editor inspect the candidates before rendering.
        except Exception as exc:
            messages.put(json.dumps({"error": str(exc)}))
        finally:
            _release_session(session)
            messages.put(None)
    threading.Thread(target=worker, daemon=True).start()
    return _sse_response(session, messages)

def _prepare_build_chunks(session: dict, file_overrides: dict[int, list[str]] | None = None) -> list[dict]:
    if session.get("avatar_workflow") == "dreamina":
        validate_dreamina_chunks(session["chunks"], session["audio_duration"])
    overrides = {int(k):v for k,v in session.get("file_overrides", {}).items()}
    overrides.update(file_overrides or {})
    source_label = SOURCE_LABELS[session.get("language", DEFAULT_LANGUAGE)]
    result = []
    def available(names):
        return [name for name in names if isinstance(name, str) and _SAFE_FILE.fullmatch(name)
                and (path := os.path.realpath(os.path.join(session["scene_dir"], "downloads", name)))
                and os.path.commonpath([path, os.path.realpath(os.path.join(session["scene_dir"], "downloads"))]) == os.path.realpath(os.path.join(session["scene_dir"], "downloads"))
                and os.path.isfile(path)]
    for chunk in session["chunks"]:
        candidates = available(overrides.get(chunk["id"], chunk["files"]))
        panels = chunk.get("panels")
        if panels:
            selected = [next((name for name in candidates if name in panel.get("files", [])), None) for panel in panels]
        else:
            selected = candidates if chunk["id"] in overrides else candidates[:1]
        if chunk.get("music_insert") and len(selected)>1:
            raise ValueError(f"Музыкальная вставка {chunk['id']+1}: выбери ровно один видеоклип")
        entry = {key: chunk[key] for key in ("type", "query", "duration", "start", "end", "preset", "params", "effects", "layers", "panels", "template", "avatar", "media_origin", "ai_prompt", "music_insert", "scene_id", "shot_plan") if key in chunk}
        entry.update({"_chunk_id": chunk["id"], "_duration_override": chunk["duration"],
                      "_files": [os.path.join(session["scene_dir"], "downloads", name) if name else None for name in selected],
                      "credits": {name: f"{source_label}: {asset.get('source', 'Google Images')}"
                                  for name, asset in session.get("assets", {}).items()
                                  if name in selected and asset.get("rights_confirmed")}})
        result.append(entry)
    return resolve_avatar_chunks(result, session)

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/media/<scene_name>/<filename>")
def media(scene_name, filename):
    path = _safe_media_path(scene_name, filename)
    if not path or not os.path.exists(path):
        return {"error": "File not found"}, 404
    return send_file(path)


@app.route("/output/<scene_name>")
def output_video(scene_name):
    if not _SAFE_NAME.match(scene_name):
        return {"error": "Invalid name"}, 400
    path = os.path.join(OUTPUT_DIR, scene_name, "preview.mp4" if request.args.get("preview") == "1" else f"{scene_name}.mp4")
    if not os.path.exists(path):
        return {"error": "Video not found"}, 404
    return send_file(path)


@app.route("/delete_file", methods=["POST"])
def delete_file():
    data = request.json or {}
    scene_name = data.get("scene_name", "")
    chunk_id = data.get("chunk_id")
    filename = data.get("filename", "")

    if chunk_id is None or not scene_name or not filename:
        return jsonify({"error": "Missing parameters"}), 400

    session = _get_session(scene_name)
    if not session:
        return jsonify({"error": "Сессия не найдена"}), 404
    if session["busy"]:
        return jsonify({"error": "Сессия ещё обрабатывается"}), 409

    chunk = next((c for c in session["chunks"] if c["id"] == chunk_id), None)
    if not chunk:
        return jsonify({"error": "Chunk not found"}), 404

    path = _safe_media_path(scene_name, filename)
    if path and os.path.exists(path):
        os.remove(path)

    chunk["files"] = [f for f in chunk["files"] if f != filename]
    for panel in chunk.get("panels", []):
        panel["files"] = [f for f in panel.get("files", []) if f != filename]
    if str(chunk_id) in session.get("file_overrides", {}):
        session["file_overrides"][str(chunk_id)] = [f for f in session["file_overrides"][str(chunk_id)] if f != filename]
    _save_project(session)
    return jsonify({"ok": True})


@app.route("/confirm_asset", methods=["POST"])
def confirm_asset():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", ""))
    filename = data.get("filename", "")
    if not session or not _SAFE_FILE.match(filename):
        return jsonify({"error": "Ассет не найден"}), 404
    asset = session.get("assets", {}).get(filename)
    if not asset:
        return jsonify({"error": "У файла нет данных об источнике"}), 404
    if session["busy"]:
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    asset["rights_confirmed"] = bool(data.get("rights_confirmed"))
    _save_assets(session)
    return jsonify({"ok": True, "rights_confirmed": asset["rights_confirmed"]})


@app.route("/select_media", methods=["POST"])
def select_media():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Нужен JSON-объект"}), 400
    session = _get_session(data.get("scene_name", ""))
    chunk = next((c for c in session["chunks"] if c["id"] == data.get("chunk_id")), None) if session else None
    names = data.get("files")
    if (not chunk or not isinstance(names, list) or any(not isinstance(n, str) or n not in chunk["files"] for n in names)):
        return jsonify({"error": "Выбери материалы этой сцены"}), 400
    if not _claim_session(session):
        return jsonify({"error": "Проект ещё обрабатывается"}), 409
    previous = copy.deepcopy({key: session.get(key, [] if key=='editorial_corrections' else {})
                              for key in ('chunks','assets','file_overrides','editorial_corrections')})
    try:
        record_choice(session, chunk, names)
        session.setdefault("file_overrides", {})[str(chunk["id"])] = list(dict.fromkeys(names))
        related = propagate_choice(session, chunk, names)
        _save_assets(session)
        return jsonify({"ok": True, 'reused_chunks':related,
                        'confirmed_assets':{name:session['assets'][name] for name in names}})
    except OSError:
        session.update(previous)
        return jsonify({'error':'Не удалось сохранить выбор'}),500
    finally:
        _release_session(session)


@app.route("/cancel", methods=["POST"])
def cancel():
    data = request.get_json(silent=True) or {}
    session = _get_session(data.get("scene_name", ""))
    if session:
        session["cancel"].set()
    return jsonify({"ok": True})


@app.route("/assemble", methods=["POST"])
def assemble():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Нужен JSON-объект"}), 400
    session = _get_session(body.get("scene_name", ""))
    if not session:
        return jsonify({"error": "Сессия не найдена"}), 404

    if not check_ffmpeg():
        return jsonify({
            "error": (
                "ffmpeg не найден в PATH.\n"
                "1. Скачайте ffmpeg с ffmpeg.org\n"
                "2. Добавьте папку bin/ в системный PATH\n"
                "3. Перезапустите приложение"
            )
        }), 500

    if not isinstance(body.get("preview", False), bool):
        return jsonify({"error": "preview должен быть true/false"}), 400

    msg_queue: queue.Queue = queue.Queue()

    def progress(msg: str):
        msg_queue.put(json.dumps({"progress": msg}))

    scene_name = session["scene_name"]
    scene_dir = session["scene_dir"]

    raw_overrides = body.get("file_overrides", {})
    try:
        file_overrides = {int(k): v for k, v in raw_overrides.items()} if raw_overrides else {}
    except (AttributeError, TypeError, ValueError):
        return jsonify({"error": "Неверный формат file_overrides"}), 400
    if any(
        not isinstance(names, list)
        or any(not isinstance(name, str) for name in names)
        for names in file_overrides.values()
    ):
        return jsonify({"error": "Неверный формат file_overrides"}), 400
    errors = []
    try:
        require_text_exports(session["scene_dir"], session.get("text_cues", []))
    except ValueError as exc:
        errors.append(str(exc))
    try:
        build_chunks = _prepare_build_chunks(session, file_overrides)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    missing = [f"{chunk['_chunk_id'] + 1} ({chunk['start']:.2f}–{chunk['end']:.2f} с)"
               for chunk in build_chunks if not chunk["_files"] or any(path is None for path in chunk["_files"])]
    if missing:
        errors.append("Добавь фото или видео для кадров: " + ", ".join(missing))
    if errors:
        return jsonify({"error": "\n".join(errors)}), 400
    if not _claim_session(session):
        return jsonify({"error": "Сессия уже обрабатывается"}), 409

    def worker():
        try:
            _check_cancelled(session)
            session.setdefault("file_overrides", {}).update({str(k):v for k,v in file_overrides.items()})
            _save_project(session)
            def on_used_file(chunk_id, filename):
                msg_queue.put(json.dumps({
                    "chunk_used_file": {"chunk_id": chunk_id, "filename": filename}
                }))

            audio_path = session.get("audio_path")
            audio_duration = session.get("audio_duration")
            if audio_duration is not None:
                audio_duration += inserted_duration(build_chunks)
            output_path, chunk_used = build_video(
                build_chunks, scene_dir, scene_name,
                progress_callback=progress,
                audio_path=audio_path,
                audio_duration=audio_duration,
                used_file_callback=on_used_file,
                transitions=session.get("transitions", []),
                audio_tracks=session.get("audio_tracks", []),
                text_cues=session.get("text_cues", []),
                preview=body.get("preview", False),
                cancel_event=session["cancel"],
            )
            _generate_markers(session["chunks"], scene_dir, scene_name, progress)
            msg_queue.put(json.dumps({
                "done": True,
                "scene_name": scene_name,
                "path": output_path,
                "preview": body.get("preview", False),
            }))

        except Exception as e:
            msg_queue.put(json.dumps({"error": str(e)}))
        finally:
            _release_session(session)
            msg_queue.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        try:
            while True:
                msg = msg_queue.get()
                if msg is None:
                    break
                yield f"data: {msg}\n\n"
        except GeneratorExit:
            session["cancel"].set()
            raise

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/admin/reload", methods=["POST"])
def admin_reload():
    import stock_downloader as _sd, ffmpeg_builder as _fb
    importlib.reload(_sd)
    importlib.reload(_fb)
    return jsonify({"status": "reloaded", "modules": ["stock_downloader", "ffmpeg_builder"]})


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    app.run(debug=False, host="127.0.0.1", port=5000, threaded=True)
