"""Contracts for speech-bound text, photo series and schematic map annotations."""
import math
import re

FPS = 30
SPEECH_TEXT = {"impact_typewriter", "speech_words_grid", "speech_words_overlay"}
NARRATIVE_TEXT = SPEECH_TEXT | {"selective_marker"}
CAROUSEL_TEMPLATES = {f"photo_carousel_{style}": style for style in ("paper", "editorial", "dark", "film")}
CAROUSEL_TEMPLATES['evidence_board'] = 'board'


def _token(text):
    return re.sub(r"[^\w]", "", text.casefold())


def speech_words(item, text, first, last, timestamps=None):
    """Resolve actual transcript words; never estimate speech speed from a phrase."""
    if timestamps is None:
        records = item.get("speech_words")
        if not isinstance(records, list) or not records:
            raise ValueError("Текст по речи: нужны word_timestamps WhisperX и word_range")
    else:
        expanded = []
        for word in timestamps:
            tokens = word["word"].split()
            start, end = float(word["start"]), float(word["end"])
            expanded.extend({"text": token, "start": start + (end-start)*i/len(tokens),
                             "end": start + (end-start)*(i+1)/len(tokens)} for i, token in enumerate(tokens))
        span = item.get("word_range")
        if span is not None:
            if (not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span)
                    or not 0 <= span[0] < span[1] <= len(timestamps)):
                raise ValueError("text_cue.word_range: [first,last_exclusive] из word_timestamps")
            # Ranges refer to original WhisperX entries, including entries with several tokens.
            lo = sum(len(w["word"].split()) for w in timestamps[:span[0]])
            hi = lo + sum(len(w["word"].split()) for w in timestamps[span[0]:span[1]])
            chosen = expanded[lo:hi]
        else:
            wanted = [_token(w) for w in text.split()]
            matches = [i for i in range(len(expanded)-len(wanted)+1)
                       if [_token(w["text"]) for w in expanded[i:i+len(wanted)]] == wanted
                       and round(expanded[i]["start"]*FPS) >= first
                       and round(expanded[i+len(wanted)-1]["start"]*FPS) < last]
            if len(matches) != 1:
                raise ValueError("Текст по речи: укажи однозначный word_range для точной фразы из озвучки")
            chosen = expanded[matches[0]:matches[0]+len(wanted)]
        records = [{"text": w["text"], "start_frame": round(w["start"]*FPS)-first,
                    "end_frame": min(last-first, max(round(w["start"]*FPS)+1, round(w["end"]*FPS))-first)} for w in chosen]
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("speech_words: массив до 100 слов")
    previous = -1
    for word in records:
        if (not isinstance(word, dict) or not isinstance(word.get("text"), str)
                or type(word.get("start_frame")) is not int or type(word.get("end_frame")) is not int
                or not 0 <= word["start_frame"] < word["end_frame"] <= last-first
                or word["start_frame"] < previous):
            raise ValueError("Таймкоды слов должны идти по порядку внутри текстовой вставки")
        previous = word["start_frame"]
    if [_token(w["text"]) for w in records] != [_token(w) for w in text.split()]:
        raise ValueError("Текст по речи должен дословно совпадать с выбранными словами озвучки")
    if item["template"] == "impact_typewriter" and len(records) > 4:
        raise ValueError("impact_typewriter: одно слово или короткая фраза до четырёх слов")
    return records


def validate_highlights(text, params):
    ranges = params.get("highlight_ranges")
    count, previous = len(text.split()), 0
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= 10:
        raise ValueError("selective_marker: нужны highlight_ranges, 1..10 диапазонов слов")
    for span in ranges:
        if (not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span)
                or not previous <= span[0] < span[1] <= count):
            raise ValueError("highlight_ranges: непересекающиеся [first,last_exclusive] по порядку")
        previous = span[1]


def carousel_groups(chunks):
    groups = {}
    for index, chunk in enumerate(chunks):
        if chunk.get("template") in CAROUSEL_TEMPLATES:
            key = chunk.get("params", {}).get("carousel_group")
            if not isinstance(key, str) or not key.strip() or len(key) > 50:
                raise ValueError("Серия фото: нужен params.carousel_group до 50 символов")
            groups.setdefault(key, []).append(index)
    for indices in groups.values():
        if not 2 <= len(indices) <= 5 or indices != list(range(indices[0], indices[-1]+1)):
            raise ValueError("Серия фото: от 2 до 5 последовательных chunks одной группы")
        signature = {(chunks[i]["template"], chunks[i].get("params", {}).get("archival", False)) for i in indices}
        if len(signature) != 1:
            raise ValueError("Серия фото: оформление и archival должны совпадать внутри группы")
    return list(groups.values())


def map_annotation_frames(params, frames):
    annotations = params.get("annotations")
    if not isinstance(annotations, list) or not 1 <= len(annotations) <= 12:
        raise ValueError("map_annotations: annotations — 1..12 линий/районов/точек")
    result, cursor = [], 0
    default_draw = min(30, max(21, (frames-15)//len(annotations)))
    for item in annotations:
        if not isinstance(item, dict) or item.get("kind") not in {"route", "boundary", "region", "point"}:
            raise ValueError("Карта: kind route/boundary/region/point")
        points = item.get("points")
        minimum = {"route": 2, "boundary": 2, "region": 3, "point": 1}[item["kind"]]
        if not isinstance(points, list) or not minimum <= len(points) <= 100 or (item["kind"] == "point" and len(points) != 1):
            raise ValueError("Карта: неверное число points")
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point)):
                raise ValueError("Карта: points — пары [x,y] в пределах 0..1")
        if not isinstance(item.get("label"), str) or not item["label"].strip() or len(item["label"]) > 80:
            raise ValueError("Карта: label — подпись до 80 символов")
        start, draw = item.get("start_frame", cursor), item.get("draw_frames", default_draw)
        if type(start) is not int or type(draw) is not int or start < cursor or draw < 1 or start+draw > frames-10:
            raise ValueError("Карта: последовательные start_frame/draw_frames должны помещаться в сцену с запасом 10 кадров для подписи")
        label_point = item.get("label_point")
        if label_point is not None and (not isinstance(label_point, list) or len(label_point) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in label_point)):
            raise ValueError("Карта: label_point — [x,y] в пределах 0..1")
        result.append({**item, "start_frame": start, "draw_frames": draw})
        cursor = start + draw
    zoom = params.get("camera_zoom", 1.22)
    if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not math.isfinite(zoom) or not 1 <= zoom <= 1.5:
        raise ValueError("Карта: camera_zoom 1..1.5")
    return result


def validate_narrative_scene(scene):
    template, params = scene.get("template"), scene.get("params", {})
    if template not in {*CAROUSEL_TEMPLATES, "map_annotations"}:
        return
    if template == 'map_annotations' and 'geo' in params:
        return  # Validated by the real-coordinate map contract.
    if template == 'map_annotations':
        raise ValueError('Старая карта-картинка удалена: используй map_annotations с params.geo или map_geographic')
    if scene.get("type") != "photo":
        raise ValueError(f"{template}: нужна фотография/карта")
    duration = float(scene["end"])-float(scene["start"]) if "start" in scene and "end" in scene else float(scene.get("duration", 5))
    if duration < (1 if template in CAROUSEL_TEMPLATES else 2):
        raise ValueError(f"{template}: слишком короткая сцена")
    if template in CAROUSEL_TEMPLATES:
        group = params.get("carousel_group")
        if not isinstance(group, str) or not group.strip() or len(group) > 50:
            raise ValueError("Серия фото: нужен params.carousel_group")
        if type(params.get("archival", False)) is not bool:
            raise ValueError("Серия фото: archival должен быть true или false")
        if not isinstance(params.get("caption", ""), str) or len(params.get("caption", "")) > 160:
            raise ValueError("Серия фото: caption — строка до 160 символов")
        if template=='evidence_board' and (not params.get('caption','').strip() or len(params['caption'])>60):
            raise ValueError('evidence_board: нужна короткая caption до 60 символов')
    else:
        if not isinstance(params.get("title", ""), str) or len(params.get("title", "")) > 160:
            raise ValueError("Карта: title — строка до 160 символов")
        map_annotation_frames(params, round(duration*FPS))
