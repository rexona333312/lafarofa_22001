"""Budget avatar compositions and planning contract; no generation or lip sync."""
import json
import math
import re
import subprocess
from pathlib import Path

AVATAR_TEMPLATES = {"avatar_full": "full", "avatar_left": "left", "avatar_right": "right"}
VIDEO_MODES = {"faceless", "ai_avatar"}
RULES_PATH = Path(__file__).parent / "reference_analysis/avatar_format/avatar_editorial_rules.json"
AVATAR_WORKFLOWS = {"library", "dreamina"}
AVATAR_TARGET = .044
AVATAR_MAX_SECONDS = 3


def validate_avatar_workflow(value):
    if not isinstance(value, str) or value not in AVATAR_WORKFLOWS:
        raise ValueError("Способ подготовки аватара: dreamina или library")
    return value


def avatar_interval(chunk, audio_duration):
    """Use the assembler's absolute frame boundaries for both WAV and video."""
    first, last = round(chunk["start"] * 30), round(chunk["end"] * 30)
    if abs(chunk["end"] - audio_duration) < .000001:
        last = math.ceil(audio_duration * 30)
    return first / 30, (last - first) / 30


def avatar_span(chunk):
    return {key: chunk.get(key) for key in ("start", "end", "text", "word_range")}


def validate_dreamina_chunks(chunks, audio_duration):
    run = 0
    for chunk in chunks:
        if chunk.get("template") not in AVATAR_TEMPLATES:
            run = 0
            continue
        _, duration = avatar_interval(chunk, audio_duration)
        if duration <= 0 or duration > AVATAR_MAX_SECONDS + .000001:
            raise ValueError(f"Вставка аватара №{chunk['id']+1}: нужна длительность от одного кадра до 3 секунд")
        spec = chunk.get("avatar", {})
        if spec.get("clip_id", "auto") != "auto" or spec.get("source_start", 0) != 0:
            raise ValueError("Dreamina: используй avatar:{clip_id:auto}; видео и его начало назначаются вставке в интерфейсе")
        run += duration
        if run > AVATAR_MAX_SECONDS + .000001:
            raise ValueError("Непрерывное появление аватара дольше 3 секунд: раздели вставки обычным видеорядом")


def avatar_tasks(session):
    root = Path(session["scene_dir"], "downloads").resolve()
    rows = []
    for chunk in session.get("chunks", []):
        if chunk.get("template") not in AVATAR_TEMPLATES:
            continue
        start, duration = avatar_interval(chunk, session["audio_duration"])
        entry = session.get("avatar_assignments", {}).get(str(chunk["id"]), {})
        name = entry.get("filename", "")
        path = (root / name).resolve()
        ready = (entry.get("span") == avatar_span(chunk) and bool(re.fullmatch(r"[a-zA-Z0-9_.-]+", name))
                 and path.is_relative_to(root) and path.is_file()
                 and entry.get("source_start", 0) + duration <= entry.get("duration", 0) + .001)
        rows.append({"chunk_id": chunk["id"], "text": chunk.get("text", ""), "start": start,
                     "end": start + duration, "duration": duration, "placement": AVATAR_TEMPLATES[chunk["template"]],
                     "status": "ready" if ready else "missing", "filename": name if ready else None,
                     "label": entry.get("label", "") if ready else "", "source_start": entry.get("source_start", 0) if ready else 0,
                     "clip_duration": entry.get("duration") if ready else None,
                     "zoom_percent": entry.get("zoom_percent", 100) if ready else None,
                     "tail_padding_seconds": entry.get("tail_padding_seconds", 0) if ready else 0})
    return rows


def validate_video_mode(value):
    if not isinstance(value, str) or value not in VIDEO_MODES:
        raise ValueError("Режим видео: faceless или ai_avatar")
    return value


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: число от {low} до {high}")


def validate_avatar_scene(scene):
    template = scene.get("template")
    if "avatar" in scene and template not in AVATAR_TEMPLATES:
        raise ValueError("avatar используется только с avatar_full/avatar_left/avatar_right")
    origin = scene.get("media_origin", "real")
    if origin not in ("real", "ai_image"):
        raise ValueError("media_origin: real или ai_image")
    if origin == "ai_image":
        if scene.get("type") != "photo" or template == "avatar_full":
            raise ValueError("ИИ-фото — только фотография фонового видеоряда")
        if not isinstance(scene.get("ai_prompt"), str) or not scene["ai_prompt"].strip() or len(scene["ai_prompt"]) > 6000:
            raise ValueError("Для ИИ-фото нужен ai_prompt до 6000 символов")
    if template not in AVATAR_TEMPLATES:
        return
    if template == "avatar_full" and scene.get("type") != "video":
        raise ValueError("avatar_full: type должен быть video")
    avatar = scene.get("avatar", {})
    if not isinstance(avatar, dict) or set(avatar) - {"clip_id", "source_start"}:
        raise ValueError("avatar: только clip_id и source_start; звук ведущей всегда выключен")
    clip = avatar.get("clip_id", "auto")
    if not isinstance(clip, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", clip):
        raise ValueError("avatar.clip_id: ID из библиотеки или auto")
    if "source_start" in avatar:
        _number(avatar["source_start"], "avatar.source_start", 0, 86400)
    p = scene.get("params", {})
    _number(p.get("avatar_width", .42), "avatar_width", .3, .6)
    for name in ("avatar_position", "media_position"):
        position = p.get(name, [.5, .5])
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError(f"{name}: [x,y] от 0 до 1")
        for v in position:
            _number(v, name, 0, 1)
    if p.get("avatar_fit", "cover") not in ("cover", "contain"):
        raise ValueError("avatar_fit: cover или contain")
    if p.get("media_fit", "contain") not in ("cover", "contain"):
        raise ValueError("media_fit: cover или contain")
    if "media_source_start" in p:
        _number(p["media_source_start"], "media_source_start", 0, 86400)


def probe_video(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, timeout=30, check=True)
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("В файле нет видео")
    duration = float(video.get("duration", data.get("format", {}).get("duration", 0)))
    if not math.isfinite(duration) or duration <= 0 or not video.get("width") or not video.get("height"):
        raise ValueError("Не удалось прочитать длительность видео")
    return {"duration": duration, "width": video["width"], "height": video["height"]}


def zoom_avatar_video(path, info, minimum_duration=None):
    """Zoom once; hold the last frame for a tiny Dreamina export shortfall."""
    source = Path(path)
    output = source.with_suffix(".zoom.mp4")
    width, height = info["width"], info["height"]
    filter_graph = ("scale=ceil(iw*1.1/2)*2:ceil(ih*1.1/2)*2:flags=lanczos,"
                    f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,setsar=1")
    padding = max(0, (minimum_duration or info["duration"]) - info["duration"])
    if padding > .1 + .000001:
        raise ValueError("Недостаёт больше 0,1 секунды видео; нужен более длинный клип")
    if padding:
        filter_graph += f",tpad=stop_mode=clone:stop_duration={padding:.9f}"
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source),
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", filter_graph,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-enc_time_base", "demux",
                        "-c:a", "aac", "-b:a", "192k", "-map_metadata", "0",
                        "-movflags", "+faststart", str(output)],
                       capture_output=True, text=True, timeout=300, check=True)
        zoomed = probe_video(output)
        duration_ok = (minimum_duration - .001 <= zoomed["duration"] <= minimum_duration + .1
                       if padding else abs(zoomed["duration"] - info["duration"]) <= .001)
        if ((zoomed["width"], zoomed["height"]) != (width, height) or not duration_ok):
            raise ValueError("Не удалось увеличить видео без изменения длительности или размера кадра")
        source.unlink()
        return output, zoomed
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def resolve_avatar_chunks(chunks, session):
    """Resolve only project-library IDs. Fail before rendering on exhausted clips."""
    library = session.get("avatar_library", [])
    root = Path(session["scene_dir"], "downloads").resolve()
    previous, ordinal = None, 0
    dreamina = session.get("avatar_workflow", "library") == "dreamina"
    tasks = {row["chunk_id"]: row for row in avatar_tasks(session)} if dreamina else {}
    for chunk in chunks:
        if chunk.get("template") not in AVATAR_TEMPLATES:
            continue
        if session.get("video_mode", "faceless") != "ai_avatar":
            raise ValueError("Для сцен с ведущей выбери режим ИИ-аватар")
        validate_avatar_scene(chunk)
        duration = (avatar_interval(chunk, session["audio_duration"])[1] if dreamina
                    else math.ceil(chunk["duration"] * 30 - 1e-6) / 30)
        spec = chunk.get("avatar", {})
        requested = spec.get("clip_id", "auto")
        if dreamina:
            task = tasks.get(chunk["_chunk_id"], {})
            if task.get("status") != "ready":
                raise ValueError(f"Вставка аватара №{chunk['_chunk_id']+1}: загрузи видео Dreamina для этой реплики")
            item = {"id": f"dreamina_{chunk['_chunk_id']}", "filename": task["filename"]}
            offset = task["source_start"]
            chunk["_avatar_lipsync"] = True
        else:
            item, offset = None, None
        eligible = []
        for candidate in library if not dreamina else []:
            name = candidate.get("filename", "")
            path = (root / name).resolve()
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name) or not path.is_relative_to(root) or not path.is_file():
                continue
            offset = spec.get("source_start", 0)
            if (requested == "auto" or candidate["id"] == requested) and offset + duration <= candidate["duration"] + .001:
                eligible.append(candidate)
        if not dreamina and not eligible:
            raise ValueError(f"Сцена {chunk['_chunk_id'] + 1}: нет подходящего клипа ведущей на {duration:.2f} с. Загрузи библиотеку или сократи сцену/смещение.")
        if not dreamina:
            item = eligible[ordinal % len(eligible)]
            if item["id"] == previous and len(eligible) > 1:
                item = eligible[(ordinal + 1) % len(eligible)]
            max_offset = max(0, item["duration"] - duration)
            offset = spec.get("source_start", min((ordinal % 3) * .5, max_offset))
        path = str(root / item["filename"])
        chunk.update(_avatar_file=path, _avatar_source_start=offset,
                     _avatar_clip_id=item["id"])
        if chunk["template"] == "avatar_full":
            chunk["_files"] = [path]
        else:
            p = chunk.get("params", {})
            background_files = chunk.get("_files", [])
            if chunk["type"] == "video" and background_files and background_files[0]:
                info = probe_video(background_files[0])
                if p.get("media_source_start", 0) + duration > info["duration"] + .001:
                    raise ValueError(f"Сцена {chunk['_chunk_id'] + 1}: фоновое видео короче нужного интервала")
        previous, ordinal = item["id"], ordinal + 1
    return chunks


def planner_payload(session, faceless_instructions, templates):
    from editorial_planning import planning_payload, PLANNER_RULES
    from shot_planning import editing_payload, EDITING_RULES
    mode = session.get("video_mode", "faceless")
    common = {**planning_payload(session), **editing_payload(), "video_mode": mode,
              "remotion_templates": [name for name in templates if mode == "ai_avatar" or name not in AVATAR_TEMPLATES]}
    if mode == "faceless":
        return {**common, "instructions": faceless_instructions}
    rules = json.loads(RULES_PATH.read_text())
    # These rules are now included in every avatar-mode planning export.
    rules = {**rules, "status": "CONNECTED_TO_AI_AVATAR_PLANNING_EXPORT"}
    workflow = session.get("avatar_workflow", "library")
    instructions = (
        "Ты монтажёр ролика с бюджетной ИИ-ведущей. Верни timeline JSON: video_mode:ai_avatar, chunks, transitions, audio_tracks, text_cues. "
        "Примени avatar_editorial_rules. Сначала выдели смысловые главы и роли фраз, потом подбери видеоряд, ведущую и графику. "
        "Не меняй текст, факты, отрицания и порядок озвучки. Тайминг из word_timestamps: предпочтительно непрерывные word_range:[first,last_exclusive], "
        "покрывающие все слова; первый start=0, последний end=audio_duration. Один chunk — один кадр, scene_id объединяет кадры одной мысли. "
        "Ритм по смыслу, а не через равные интервалы. Не навязывай автомобильную тему, обратный отсчёт или одинаковую длину глав. "
        "Ведущая — одна женщина в никабе из 3–5 коротких готовых видео. Рот скрыт, lip-sync и API генерации не нужны. "
        "Ведущая на обращении, предупреждении, выводе или переходе; при показе деталей освобождай весь экран. Цель 20–25%, ориентир 22%, не квота. "
        "Три шаблона: avatar_full (type:video, без поиска фона), avatar_left и avatar_right (type:photo|video описывает фон). "
        "chunk.avatar:{clip_id:auto|ID_из_avatar_library,source_start:секунды_необязательно}. Без звука, без циклов, без заморозки или замедления. "
        "Сцена и source_start обязаны помещаться в длину выбранного файла. Если библиотека пуста, запланируй короткие появления 3–5 с с clip_id:auto; "
        "пользователь добавит библиотеку перед сборкой. Сторона панели стабильна в проекте; не отражай видео. "
        "params: avatar_width:.42 (0.3..0.6), avatar_fit:cover|contain, avatar_position:[.5,.5], "
        "media_fit:contain|cover, media_position:[.5,.5], zoom_start:0, zoom_end:.04, arrival_frames:18. "
        "По умолчанию фон помещается целиком с размытыми полями. Для видеофона media_source_start:секунды, проверь длину найденного видео. "
        "Для каждого chunk нужны type, query (для avatar_full: 'ведущая'), text, visual_intent, editor_note_ru. "
        "Обычные реальные материалы: media_origin:real, search_mode:exact|broll, entity, entity_type, search_queries, "
        "source_policy:[editorial,archive] для фото/[youtube,archive] для видео; licensed_stock последним. "
        "Каждая сущность и действие из текущей фразы; смотри полученное медиа, не подменяй устройство совпадением одного слова. "
        "ИИ-фото: type:photo, media_origin:ai_image, ai_prompt:подробный_промпт_для_Google_Flow. "
        "Опиши предмет, действие, место/эпоху, ракурс, важную деталь и свободную область рядом с ведущей. Такие сцены не ищутся в интернете; "
        "пользователь генерирует и загружает изображение вручную в нужный кадр. Не делай ai_fallback. "
        "Цель 50% real / 50% ai_image ПО ВРЕМЕНИ фонового видеоряда; картинки рядом с ведущей включай, avatar_full и самостоятельную графику исключай. "
        "Политика/конкретное устройство/место/событие — реальные материалы; ИИ для обобщённых ситуаций и иллюстраций. "
        "Нужные текст, схема или сравнение выбираются из remotion_templates/text_templates. Не требуется 30–34% графики. "
        "Coolvetica; обычный текст строчными, impact_typewriter капсом. Числа и надписи из своего сценария, отдельными текстовыми слоями. "
        "text_cues по действующему каталогу, у шаблонов по речи точный word_range. Не дублируй автоматические SFX шаблонов; ручные SFX 30%. "
        "transitions с абсолютными start/end: по умолчанию cut; явные переходы по смыслу из builtin_transitions/library, без квоты. "
        "Не переносить биографию, фотографии и цифры чужого ведущего. effects и panels запрещены; боковая композиция делается avatar_left/right."
    )
    if workflow == "dreamina":
        instructions = instructions.replace(
            "Ведущая — одна женщина в никабе из 3–5 коротких готовых видео. Рот скрыт, lip-sync и API генерации не нужны. ",
            "Говорящий аватар создаётся пользователем в Dreamina из изображения и точного WAV исходной озвучки. Для каждой вставки своё видео. ")
        instructions = instructions.replace("Цель 20–25%, ориентир 22%, не квота.",
            "Цель 4–5% общей длительности, ориентир 4.4%. Каждое непрерывное появление не больше 3 секунд; не дели длинное появление на соседние avatar chunks.")
        instructions = instructions.replace(
            "chunk.avatar:{clip_id:auto|ID_из_avatar_library,source_start:секунды_необязательно}.",
            "chunk.avatar:{clip_id:auto}. Пользователь загружает отдельный клип в конкретный chunk после импорта таймлайна.")
        instructions = instructions.replace(
            "Сцена и source_start обязаны помещаться в длину выбранного файла. Если библиотека пуста, запланируй короткие появления 3–5 с с clip_id:auto; пользователь добавит библиотеку перед сборкой.",
            "Планируй вставки до 3 секунд по реальным таймкодам слов, с целыми словами и естественными паузами. Не обрезай слова. Общая озвучка и word_timestamps сохраняются; повторная транскрибация не нужна. Стыки аватара — cut.")
        instructions += " Верни avatar_workflow:dreamina. Язык текста и надписей — язык текущей озвучки, включая чешский; editor_note_ru по-русски."
        rules["avatar"] = {**rules["avatar"], "proposed_default_coverage_target": AVATAR_TARGET,
                           "proposed_budget_range": [.04, .05], "library": "One Dreamina lip-sync clip per planned chunk; original master narration stays unchanged.",
                           "hold_duration": "Maximum continuous avatar appearance: 3 seconds; whole words and natural pauses.",
                           "coverage_is": "Current user target; older reference percentages are historical observations."}
        rules["planning_order"][-1] = "Export exact master-audio WAV per avatar slot; upload one Dreamina video per slot. Check 4–5% avatar coverage and duration-based background mix."
        rules["review"] = [r for r in rules["review"] if "identical avatar gesture" not in r]
    return {**common, "avatar_workflow": workflow, "instructions": instructions+PLANNER_RULES+EDITING_RULES, "avatar_editorial_rules": rules,
            "avatar_plan": {"target_percent": round(AVATAR_TARGET * 100, 1), "range_percent": [4, 5], "max_clip_seconds": AVATAR_MAX_SECONDS} if workflow == "dreamina" else None,
            "avatar_templates": AVATAR_TEMPLATES, "avatar_library": session.get("avatar_library", [])}


def ai_prompt_manifest(chunks):
    return [{"asset_id": f"ai_{c['id']:04d}", "scene_ids": [c.get("scene_id", c["id"])],
             "chunk_id": c["id"], "voiceover_excerpt": c.get("text", ""), "prompt": c["ai_prompt"],
             "aspect_ratio": "16:9", "framing_notes": c.get("visual_intent", ""),
             "avatar_placement": AVATAR_TEMPLATES.get(c.get("template"))}
            for c in chunks if c.get("media_origin") == "ai_image"]


def timeline_summary(chunks):
    total = sum(c.get("duration", c.get("end", 0) - c.get("start", 0)) for c in chunks)
    avatar = sum(c.get("duration", c.get("end", 0) - c.get("start", 0)) for c in chunks if c.get("template") in AVATAR_TEMPLATES)
    backgrounds = [c for c in chunks if c.get("template") not in {
        "avatar_full", "chapter_heading", "date_countback", "editorial_statement", "date_interval", "echo_statement"}]
    ai = sum(c.get("duration", c.get("end", 0) - c.get("start", 0)) for c in backgrounds if c.get("media_origin") == "ai_image")
    real = sum(c.get("duration", c.get("end", 0) - c.get("start", 0)) for c in backgrounds if c.get("media_origin", "real") == "real")
    return {"avatar_seconds": avatar, "avatar_percent": 100 * avatar / total if total else 0,
            "background_real_seconds": real, "background_ai_seconds": ai,
            "background_ai_percent": 100 * ai / (real + ai) if real + ai else 0,
            "measure": "planned scene duration; excludes full avatar and standalone text cards; panel backgrounds included"}
