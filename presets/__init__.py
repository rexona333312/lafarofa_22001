"""Code-driven FFmpeg compositions. Media textures stay in assets/, not here."""
from music_inserts import validate_music_insert
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS_ROOT = ROOT.parent / "assets"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff"}
MOTION_SUPERSAMPLE = 4
CATEGORIES = {
    "transitions": IMAGE_EXTENSIONS | VIDEO_EXTENSIONS,
    "overlays": IMAGE_EXTENSIONS | VIDEO_EXTENSIONS,
    "textures": IMAGE_EXTENSIONS | VIDEO_EXTENSIONS,
    "paper": IMAGE_EXTENSIONS,
    "backgrounds": IMAGE_EXTENSIONS,
    "frames": IMAGE_EXTENSIONS,
    "luts": {".cube"},
    "music": AUDIO_EXTENSIONS,
    "ambience": AUDIO_EXTENSIONS,
    "sfx": AUDIO_EXTENSIONS,
}
PRESETS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(ROOT.glob("*.json"))}
from narrative_templates import CAROUSEL_TEMPLATES, validate_narrative_scene
from reference_templates import REFERENCE_TEMPLATES, validate_reference_scene
from avatar_templates import AVATAR_TEMPLATES, validate_avatar_scene
from documentary_templates import DOCUMENTARY_TEMPLATES, validate_documentary_scene
from geographic_maps import validate_geo_scene

PERSON_TEMPLATES = {f"person_intro_{side}": side for side in ("left", "center", "right")}
REMOTION_TEMPLATES = {
    "paper_card_top_right": "top-right",
    "paper_card_bottom_left": "bottom-left",
    "paper_card_bottom": "bottom",
    **{name: name for name in ("blur-in", "fade-in", "scale-in", "spring-in")},
    **PERSON_TEMPLATES,
    "history_timeline": "history-timeline",
    **CAROUSEL_TEMPLATES,
    "map_annotations": "map-annotations",
    "map_geographic": "map-geographic",
    **DOCUMENTARY_TEMPLATES,
    **REFERENCE_TEMPLATES,
    **AVATAR_TEMPLATES,
}
REMOTION_SOUNDS = {name: {"asset": "sfx/whoosh.mp3", "start_frame": 0} for name in REMOTION_TEMPLATES}
REMOTION_SOUNDS["history_timeline"] = {"asset": "sfx/scrolling.mp3", "start_frame": 0}
for _name in (*CAROUSEL_TEMPLATES, "map_annotations", *REFERENCE_TEMPLATES, *AVATAR_TEMPLATES):
    REMOTION_SOUNDS[_name] = None
for _name in ('map_geographic', *DOCUMENTARY_TEMPLATES):
    REMOTION_SOUNDS[_name] = None
REMOTION_TRANSITIONS = {
    "blur-reveal": {"description": "Remotion: раскрытие через расфокусировку", "duration": .7},
    "frosted-glass-wipe": {"description": "Remotion: проход матового стекла", "duration": .8},
    "transition-fade": {"description": "Remotion: плавное смешивание", "duration": .6},
    "transition-wipe": {"description": "Remotion: направленная шторка", "duration": .7},
    "directional-wipe": {"description": "Remotion: мягкая шторка с глубиной", "duration": .7},
}
BLENDS = {"alpha", "screen", "multiply", "softlight", "overlay", "green"}
BUILTIN_TRANSITIONS = {
    **REMOTION_TRANSITIONS,
    "crossfade": {"description": "Плавное смешивание двух сцен без затемнения", "duration": .6},
}
TRANSITION_INSTRUCTIONS = (
    "transitions — отдельная дорожка с абсолютными start/end; kind cut|fade|overlay|crossfade|blur-reveal|frosted-glass-wipe|transition-fade|transition-wipe|directional-wipe. "
    "Remotion-переходы используют params.variant:editorial|linear|spring; шторки params.direction:from-left|from-right|from-top|from-bottom. "
    "fade — через чёрный. overlay требует asset/blend/opacity из library. crossfade смешивает соседние кадры. "
    "Кодовые переходы не требуют файлов: окно 0.2–2 секунды, рекомендуемая длительность в builtin_transitions. "
    "Окно fade и кодового перехода должно симметрично окружать один стык и помещаться в две соседние сцены. "
    "Окна кодовых переходов/fade не пересекаются; screen-overlay на стыке автоматически получает мягкий crossfade под ним. "
    "Для Light Leaks ставь opacity:1 (100%) с blend:screen; не ставь их подряд. Не меняй таймкоды ради эффектов. "
    "По умолчанию cut, в том числе при transitions:[]. Квоты эффектных или скачанных переходов нет. "
    "Внутри связанной сцены предпочитай cut. Crossfade задавай явно для смены времени или состояния. "
    "Эффектный переход уместен на смысловой границе разделов; наличие файла в library не обязывает его использовать. "
)


def number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name}: нужно число")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}: число от {minimum} до {maximum}")
    return value


def asset_path(identifier, categories=None):
    if not isinstance(identifier, str) or not re.fullmatch(r"[\w ./-]+", identifier):
        raise ValueError("Неверное имя библиотечного файла")
    parts = Path(identifier).parts
    if len(parts) < 2 or parts[0] not in (categories or CATEGORIES):
        raise ValueError(f"Неверная категория ассета: {identifier}")
    path = (ASSETS_ROOT / identifier).resolve()
    if not path.is_relative_to(ASSETS_ROOT.resolve()) or path.suffix.lower() not in CATEGORIES[parts[0]]:
        raise ValueError(f"Недопустимый путь ассета: {identifier}")
    if parts[0] == "transitions" and "glitch" in path.stem.lower():
        raise ValueError("Glitch-переходы отключены в V2")
    if not path.is_file():
        raise ValueError(f"Нет файла assets/{identifier}")
    return path


def library_catalog():
    result = []
    for category, extensions in CATEGORIES.items():
        folder = ASSETS_ROOT / category
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in extensions:
                identifier = path.relative_to(ASSETS_ROOT).as_posix()
                try:
                    asset_path(identifier)
                except ValueError:
                    continue
                stat = path.stat()
                metadata = _metadata(str(path), stat.st_size, stat.st_mtime_ns)
                description = path.stem.replace("_", " ").replace("-", " ")
                entry = {"id": identifier, "category": category, "description": description, **metadata}
                if metadata.get("has_alpha"):
                    entry["blend"] = "alpha"
                elif category == "transitions" and path.stem.lower().startswith("light leaks"):
                    entry["blend"] = "screen"
                sidecar = Path(str(path)+".json")
                if sidecar.is_file() and sidecar.resolve().is_relative_to(ASSETS_ROOT.resolve()):
                    try:
                        info = json.loads(sidecar.read_text(encoding="utf-8"))
                        if isinstance(info, dict):
                            entry.update({key: info[key] for key in ("description", "blend") if isinstance(info.get(key), str)})
                    except (OSError, ValueError):
                        pass
                result.append(entry)
    return result


@lru_cache(maxsize=256)
def _metadata(path, size, mtime):
    if Path(path).suffix.lower() == ".cube":
        return {}
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration:stream=width,height,pix_fmt", "-of", "json", path],
                                capture_output=True, text=True, timeout=15, check=True)
        data = json.loads(result.stdout)
        entry = {}
        duration = float(data.get("format", {}).get("duration", 0))
        if math.isfinite(duration) and duration > 0:
            entry["duration"] = round(duration, 3)
        streams = data.get("streams", [])
        stream = next((stream for stream in streams if stream.get("width")), None)
        if stream:
            entry.update({key: stream[key] for key in ("width", "height")})
            fmt = stream.get("pix_fmt", "")
            entry["has_alpha"] = fmt in {"rgba", "bgra", "argb", "abgr", "ya8", "rgba64le", "bgra64le"} or fmt.startswith(("yuva", "gbrap"))
        return entry
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"probe_failed": True}


def validate_layer(layer):
    if not isinstance(layer, dict):
        raise ValueError("Слой должен быть объектом")
    asset_path(layer.get("asset"), {"transitions", "overlays", "textures", "frames"})
    if layer.get("blend", "alpha") not in BLENDS:
        raise ValueError("Неверный blend: alpha/screen/multiply/softlight/overlay/green")
    number(layer.get("opacity", 1), "opacity", 0, 1)


def validate_scene(scene):
    from shot_planning import validate_shot_plan
    validate_shot_plan(scene)
    validate_music_insert(scene)
    if scene.get("template") is not None and (not isinstance(scene["template"], str)
                                              or scene["template"] not in REMOTION_TEMPLATES):
        raise ValueError(f"Неизвестный Remotion-шаблон: {scene['template']}")
    preset = scene.get("preset", "PHOTO_SLOW_ZOOM" if scene["type"] == "photo" else "PHOTO_STATIC")
    if preset not in PRESETS:
        raise ValueError(f"Неизвестный пресет: {preset}")
    params = scene.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params должен быть объектом")
    validate_narrative_scene(scene)
    validate_reference_scene(scene)
    validate_avatar_scene(scene)
    validate_documentary_scene(scene)
    validate_geo_scene(scene)
    if params.get("fit", "auto") not in {"auto", "contain", "cover"}:
        raise ValueError("fit: auto/contain/cover")
    if params.get("direction", "right") not in {"left", "right", "up", "down"}:
        raise ValueError("Неверное направление pan")
    for field, default, low, high in (("zoom_start", 0, 0, .2), ("zoom_end", .06, 0, .2),
                                     ("blur", 28, 0, 80)):
        number(params.get(field, default), field, low, high)
    if params.get("paper"):
        asset_path(params["paper"], {"paper"})
    if scene.get("template"):
        number(params.get("arrival_frames", 27), "arrival_frames", 1, 120)
        number(params.get("corner_radius", 28), "corner_radius", 0, 60)
    if scene.get("template") == "history_timeline":
        if scene.get("type") != "photo":
            raise ValueError("history_timeline: нужна фотография предмета")
        for field in ("year", "from_year"):
            value = params.get(field, max(1, params.get("year", 4) - 3) if field == "from_year" else None)
            if type(value) is not int or not 1 <= value <= 9999:
                raise ValueError(f"history_timeline: params.{field} — целый год 1..9999")
        if not isinstance(params.get("label"), str) or not params["label"].strip() or len(params["label"]) > 120:
            raise ValueError("history_timeline: params.label — название предмета до 120 символов")
        if "scroll_frames" in params and (type(params["scroll_frames"]) is not int or not 21 <= params["scroll_frames"] <= 180):
            raise ValueError("history_timeline: scroll_frames — целое 21..180")
        duration = (float(scene["end"]) - float(scene["start"]) if "start" in scene and "end" in scene
                    else float(scene.get("duration", 3)))
        if duration < 3:
            raise ValueError("history_timeline: нужно минимум 3 секунды")
    if scene.get("template") in PERSON_TEMPLATES:
        if scene.get("type") != "photo":
            raise ValueError("Представление персонажа работает только с фотографиями")
        name = params.get("person_name")
        role = params.get("person_role", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Представление персонажа: params.person_name — имя до 100 символов")
        if not isinstance(role, str) or len(role) > 160:
            raise ValueError("Представление персонажа: params.person_role — подпись до 160 символов")
        if params.get("background"):
            asset_path(params["background"], {"backgrounds", "paper"})
        number(params.get("background_blur", 8), "background_blur", 0, 40)
    if params.get("lut"):
        asset_path(params["lut"], {"luts"})
    effects = scene.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError("effects должен быть массивом")
    if effects:
        raise ValueError("Обработки effects отключены в V2")
    layers = scene.get("layers", [])
    if not isinstance(layers, list):
        raise ValueError("layers должен быть массивом")
    for layer in layers:
        validate_layer(layer)
    if scene.get("panels") is not None:
        raise ValueError("Панели split-screen/collage отключены в V2")


def transition_boundary(transition, chunks):
    start, end = float(transition["start"]), float(transition["end"])
    midpoint = (start + end) / 2
    for index, (left, right) in enumerate(zip(chunks, chunks[1:])):
        if abs(float(left["end"]) - midpoint) <= .001 and start >= float(left["start"]) and end <= float(right["end"]):
            return index
    raise ValueError("Переход должен симметрично окружать один стык и помещаться в две соседние сцены")


def validate_tracks(data, audio_duration, chunks=None):
    transitions = data.get("transitions", [])
    if not isinstance(transitions, list) or len(transitions) > 2000:
        raise ValueError("transitions: массив, максимум 2000 событий")
    windows = []
    for transition in transitions:
        if not isinstance(transition, dict):
            raise ValueError("Переход должен быть объектом")
        start = number(transition.get("start"), "transition.start", 0, audio_duration)
        end = number(transition.get("end"), "transition.end", 0, audio_duration)
        kind = transition.get("kind", "overlay")
        if end < start or (end == start and kind != "cut") or end - start > 10:
            raise ValueError("Переход: длительность от 0 до 10 секунд")
        if kind not in {"overlay", "fade", "cut", *BUILTIN_TRANSITIONS}:
            raise ValueError("Неизвестный kind перехода")
        if kind == "overlay":
            validate_layer(transition)
        if kind in BUILTIN_TRANSITIONS:
            if not .2 <= end-start <= 2:
                raise ValueError("Кодовый переход: длительность 0.2–2 секунды")
            number(transition.get("strength", .65), "strength", 0, 1)
            if kind in REMOTION_TRANSITIONS:
                params = transition.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError("transition.params должен быть объектом")
                if params.get("variant", "editorial") not in ("editorial", "linear", "spring"):
                    raise ValueError("transition.params.variant: editorial/linear/spring")
                if params.get("direction", "from-left") not in ("from-left", "from-right", "from-top", "from-bottom"):
                    raise ValueError("transition.params.direction: from-left/from-right/from-top/from-bottom")
                for field, default, low, high in (("maxBlur", 24, 0, 80), ("blur", 20, 0, 80),
                                                 ("scaleBy", .03, 0, .2), ("panelWidth", .14, .01, 1),
                                                 ("edgeSoftness", .12, 0, 1), ("depth", .08, 0, .2)):
                    number(params.get(field, default), field, low, high)
                for field in ("dipTo", "frostColor"):
                    if field in params and (not isinstance(params[field], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", params[field])):
                        raise ValueError(f"{field}: цвет #RRGGBB")
                if "shouldBlurOutExitingScene" in params and type(params["shouldBlurOutExitingScene"]) is not bool:
                    raise ValueError("shouldBlurOutExitingScene: true/false")
        if kind in BUILTIN_TRANSITIONS or kind == "fade":
            if chunks is not None:
                transition_boundary(transition, chunks)
            windows.append((start, end))
    windows.sort()
    if any(left[1] > right[0] + .001 for left, right in zip(windows, windows[1:])):
        raise ValueError("Окна кодовых переходов/fade не должны пересекаться")
    tracks = data.get("audio_tracks", [])
    if not isinstance(tracks, list) or len(tracks) > 64:
        raise ValueError("audio_tracks: массив, максимум 64 дорожки")
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError("Аудиодорожка должна быть объектом")
        asset_path(track.get("asset"), {"music", "ambience", "sfx"})
        start = number(track.get("start", 0), "audio.start", 0, audio_duration)
        end = number(track.get("end", audio_duration), "audio.end", 0, audio_duration)
        if end <= start:
            raise ValueError("Аудиодорожка: end должен быть больше start")
        number(track.get("gain_db", 0), "gain_db", -60, 6)
        number(track.get("fade", 1), "fade", 0, 10)


def dimensions(path):
    stat = Path(path).stat()
    info = _metadata(str(path), stat.st_size, stat.st_mtime_ns)
    if not info.get("width") or not info.get("height"):
        raise ValueError(f"Не удалось прочитать визуальный материал: {Path(path).name}")
    return info["width"], info["height"]



def graph_for_scene(files, scene, duration, width, height, fps, transitions=(), progress=None, native_patches=()):
    validate_scene(scene)
    """Return input args, a normalized filter graph, and selected real sources."""
    inputs, graph, used = [], [], []
    serial = 0

    def label():
        nonlocal serial
        serial += 1
        return f"p{serial}"

    def input_media(path, loop=True, seek=0):
        idx = inputs.count("-i")
        if Path(path).suffix.lower() in IMAGE_EXTENSIONS:
            inputs.extend(["-loop", "1", "-framerate", str(fps)])
        elif loop:
            inputs.extend(["-stream_loop", "-1"])
        if seek:
            inputs.extend(["-ss", str(seek)])
        inputs.extend(["-i", str(path)])
        return f"{idx}:v"

    def emit(source, filters):
        out = label()
        graph.append(f"[{source}]{filters}[{out}]")
        return out

    def normalize_cfr(source, hold=False):
        """Make every moving input use the composition's frame clock before effects."""
        filters = (f"settb=AVTB,fps=fps={fps}:round=near:start_time=0,"
                   f"settb=1/{fps},setpts=N/({fps}*TB)")
        if hold:
            filters += f",tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration}"
        return emit(source, filters)

    def cover(source, w, h, lanczos=False):
        flags = ":flags=lanczos" if lanczos else ""
        return emit(source, f"scale={w}:{h}:force_original_aspect_ratio=increase{flags},crop={w}:{h},setsar=1")

    def cell(path, w, h, zoom_a=0, zoom_b=0, pan=None, preserve=True):
        w, h = max(2, w // 2 * 2), max(2, h // 2 * 2)
        if not path:
            out = label()
            graph.append(f"color=c=0x303846:s={w}x{h}:r={fps}:d={duration}[{out}]")
            return out
        used.append(str(path))
        src = normalize_cfr(input_media(path, loop=False), hold=True)
        iw, ih = dimensions(path)
        photo = Path(path).suffix.lower() in IMAGE_EXTENSIONS
        moving = photo or zoom_a != zoom_b or pan
        if preserve:
            a, b = label(), label()
            graph.append(f"[{src}]split[{a}][{b}]")
            bg = cover(a, w, h)
            bg = emit(bg, f"gblur=sigma={float(params.get('blur', 28))},eq=brightness=-0.08")
            scale = min(w / iw, h / ih)
            fw, fh = max(2, int(iw * scale) // 2 * 2), max(2, int(ih * scale) // 2 * 2)
            fg = motion(b, fw, fh, zoom_a, zoom_b, pan) if moving else cover(b, fw, fh)
            return emit(f"{bg}][{fg}", "overlay=x=(W-w)/2:y=(H-h)/2:shortest=1")
        return motion(src, w, h, zoom_a, zoom_b, pan) if moving else cover(src, w, h)

    def motion(source, w, h, zoom_a, zoom_b, pan=None):
        frames = max(round(duration * fps) - 1, 1)
        work_w, work_h = w * MOTION_SUPERSAMPLE, h * MOTION_SUPERSAMPLE
        source = cover(source, work_w, work_h, lanczos=True)
        # Ease the virtual camera in and out. A linear one-frame step is most visible on still photos.
        progress = f"(0.5-0.5*cos(PI*on/{frames}))"
        z = f"1+{zoom_a}+({zoom_b}-{zoom_a})*{progress}"
        x, y = "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
        if pan in {"left", "right"}:
            x = f"(iw-iw/zoom)*{'(1-'+progress+')' if pan == 'left' else progress}"
        if pan in {"up", "down"}:
            y = f"(ih-ih/zoom)*{'(1-'+progress+')' if pan == 'up' else progress}"
        moved = emit(source, f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={work_w}x{work_h}:fps={fps},setsar=1")
        return emit(moved, f"scale={w}:{h}:flags=lanczos,setsar=1")

    preset = PRESETS[scene.get("preset", "PHOTO_SLOW_ZOOM" if scene["type"] == "photo" else "PHOTO_STATIC")]
    params = scene.get("params", {})
    a = float(params.get("zoom_start", preset["zoom_start"]))
    b = float(params.get("zoom_end", preset["zoom_end"]))
    pan = params.get("direction", "right") if preset["id"] == "PHOTO_PAN" else None
    layout = preset["layout"]
    # Compare with final Full HD, so preview and export use the same framing.
    if layout == "full" and files and files[0] and params.get("fit", "auto") == "auto":
        iw, ih = dimensions(files[0])
        if iw < 1920 or ih < 1080:
            layout = "blur"
            if b > a and "zoom_end" not in params:
                b = .04
    if layout in {"blur", "paper"}:
        source = files[0] if files else None
        bg = label()
        if layout == "paper" and params.get("paper"):
            bg = cover(input_media(asset_path(params["paper"], {"paper"})), width, height)
        elif layout == "blur" and source:
            bg_source = normalize_cfr(input_media(source, loop=False), hold=True)
            bg = cover(bg_source, width, height)
            bg = emit(bg, f"gblur=sigma={float(params.get('blur',28))},eq=brightness=-0.08")
        else:
            graph.append(f"color=c=0xe6dfd0:s={width}x{height}:r={fps}:d={duration}[{bg}]")
            if layout == "paper" and progress:
                progress("ARCHIVE_PAPER: бумага не выбрана — используется нейтральный фон")
        fw, fh = int(width * .82), int(height * .82)
        if source:
            iw, ih = dimensions(source)
            scale = min(fw / iw, fh / ih)
            fw, fh = int(iw * scale) // 2 * 2, int(ih * scale) // 2 * 2
        card = cell(source, fw, fh, a, b, preserve=False)
        if layout == "paper":
            card = emit(card, "pad=iw+12:ih+12:6:6:color=white")
            bg = emit(bg, f"drawbox=x=(iw-{fw+12})/2+10:y=(ih-{fh+12})/2+10:w={fw+12}:h={fh+12}:color=black@0.18:t=fill")
        bg = emit(f"{bg}][{card}", "overlay=x=(W-w)/2:y=(H-h)/2:shortest=1")
    else:
        source = files[0] if files else None
        preserve = params.get("fit", "auto") == "contain"
        if source and params.get("fit", "auto") == "auto":
            iw, ih = dimensions(source)
            preserve = abs(iw / ih - width / height) > .06
        bg = cell(source, width, height, a, b, pan, preserve)

    layers = list(scene.get("layers", []))

    for patch in native_patches:
        fg = input_media(patch["path"], loop=False)
        fg = emit(fg, f"trim=start_frame={patch['source_frame']}:end_frame={patch['source_frame']+patch['frames']},setpts=(N+{patch['start_frame']})/({fps}*TB)")
        enable = f"gte(t,{patch['start_frame']/fps})*lt(t,{(patch['start_frame']+patch['frames'])/fps})"
        bg = emit(f"{bg}][{fg}", f"overlay=eof_action=pass:repeatlast=0:enable='{enable}'")

    for layer in [*layers, *transitions]:
        start, end = float(layer.get("_start", 0)), float(layer.get("_end", duration))
        if layer.get("kind") == "cut":
            continue
        if layer.get("kind") == "fade":
            midpoint = float(layer["_mid"])
            if start < midpoint and midpoint <= duration:
                bg = emit(bg, f"fade=t=out:st={max(start,0)}:d={midpoint-max(start,0)}")
            elif midpoint <= 0 < end:
                bg = emit(bg, f"fade=t=in:st=0:d={end}")
            continue
        path = asset_path(layer["asset"], {"transitions", "overlays", "textures", "frames"})
        fg = normalize_cfr(input_media(path, loop=layer.get("kind") != "overlay" or layer not in transitions,
                                       seek=float(layer.get("_seek", 0))))
        fg = cover(fg, width, height)
        opacity, blend = float(layer.get("opacity",1)), layer.get("blend","alpha")
        if layer in transitions and Path(layer["asset"]).stem.lower().startswith("light leaks"):
            opacity = 1.0
        if blend == "screen" and layer in transitions:
            span, seek = end-start, float(layer.get("_seek", 0))
            edge = min(.12, span/4)
            fades = []
            if seek < .001:
                fades.append(f"fade=t=in:st=0:d={edge}:color=black")
            fade_out = span-edge-seek
            if fade_out >= 0:
                fades.append(f"fade=t=out:st={fade_out}:d={edge}:color=black")
            if fades:
                fg = emit(fg, ",".join(fades))
        fg = emit(fg, f"setpts=PTS-STARTPTS+{max(start,0)}/TB,format=rgba")
        enable = f"between(t,{max(start,0)},{min(end,duration)})"
        if blend in {"alpha", "green"}:
            if blend == "green":
                fg = emit(fg, "colorkey=0x00FF00:0.2:0.08")
            fg = emit(fg, f"colorchannelmixer=aa={opacity}")
            bg = emit(f"{bg}][{fg}", f"overlay=eof_action=pass:repeatlast=0:enable='{enable}'")
        else:
            fg = emit(fg, "format=gbrp")
            bg = emit(bg, "format=gbrp")
            bg = emit(f"{bg}][{fg}", f"blend=all_mode={blend}:all_opacity={opacity}:eof_action=pass:repeatlast=0:enable='{enable}'")
    bg = emit(bg, f"settb=AVTB,fps=fps={fps}:round=near:start_time=0,settb=1/{fps},"
                   f"tpad=stop_mode=clone:stop_duration={2/fps},trim=end_frame={round(duration*fps)},"
                   f"setpts=N/({fps}*TB),setsar=1,format=yuv420p")
    graph.append(f"[{bg}]null[vout]")
    return inputs, ";".join(graph), list(dict.fromkeys(used))
