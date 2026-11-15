"""Automatic Remotion text; optional legacy CapCut exports."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from presets import number
from remotion_renderer import render_remotion, remotion_source_hash
from motion_timing import marker_window
from narrative_templates import NARRATIVE_TEXT, SPEECH_TEXT, speech_words, validate_highlights
from retired_templates import active_text_cues

FPS = 30
_ALPHA_FORMATS = {"rgba", "bgra", "argb", "abgr", "yuva420p", "yuva444p10le", "yuva444p12le"}
TEXT_TEMPLATES = {"accent": set(), "plain": set()}
TEXT_COMPONENTS = {}
EDITORIAL_TEXT = {"marker_highlight", "question_panel_bottom", "question_panel_top"}
TEXT_TEMPLATES["accent"].update(EDITORIAL_TEXT)
TEXT_COMPONENTS.update({name: name for name in EDITORIAL_TEXT})
TEXT_TEMPLATES["accent"].update(NARRATIVE_TEXT)
TEXT_COMPONENTS.update({name: name for name in sorted(NARRATIVE_TEXT)})


def text_sfx_tracks(cues):
    """Quiet original-level SFX at the first frame of supported Remotion text."""
    tracks = []
    for cue in cues:
        if cue.get("renderer", "remotion") != "remotion":
            continue
        template = cue["template"]
        end = cue["end"]
        start = cue["start"]
        if template == "impact_typewriter":
            for word in cue["speech_words"]:
                tracks.append({"asset": "sfx/typewrite.WAV", "start": start + word["start_frame"] / FPS,
                               "end": start + word["end_frame"] / FPS, "loop": True, "fade": 0,
                               "preserve_gain": True, "gain_db": 20 * math.log10(.3)})
            continue
        if template in ("marker_highlight", "selective_marker"):
            delay, sweep = marker_window(cue["duration_frames"])
            delay = cue.get("params", {}).get("marker_delay_frames", delay)
            sweep = cue.get("params", {}).get("marker_frames", sweep)
            asset = "sfx/marker_scribble.mp3"
            start += delay / FPS
            end = start + sweep / FPS
        elif template in ("question_panel_top", "question_panel_bottom"):
            asset = "sfx/whoosh.mp3"
            end = min(end, start + .7)
        elif template in ("speech_words_grid", "speech_words_overlay"):
            asset = "sfx/text3.mp3"
            start += cue["speech_words"][0]["start_frame"] / FPS
            end = min(end, start + .4)
        else:
            continue
        tracks.append({"asset": asset, "start": start, "end": end, "loop": template in ("marker_highlight", "selective_marker"),
                       "fade": 0, "preserve_gain": True, "gain_db": 20 * math.log10(.3)})
    return tracks


def normalize_text_cues(raw, total_duration, chunks=None, word_timestamps=None):
    raw = active_text_cues(raw)
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 200:
        raise ValueError("text_cues: нужен массив, максимум 200 вставок")
    cues, seen, used_chunks = [], set(), set()
    total_frames = round(total_duration * FPS)
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Текстовая вставка {index}: нужен объект")
        cue_id = item.get("id", f"T{index:03d}")
        kind = item.get("kind")
        if not isinstance(cue_id, str) or not re.fullmatch(r"T\d{3,4}", cue_id) or cue_id in seen:
            raise ValueError(f"Текстовая вставка {index}: уникальный id вида T001")
        if not isinstance(kind, str) or kind not in {"accent", "plain"}:
            raise ValueError(f"{cue_id}: kind должен быть accent или plain")
        template = item.get("template", "marker_highlight" if kind == "accent" else None)
        if not isinstance(template, str) or template not in TEXT_TEMPLATES[kind]:
            raise ValueError(f"{cue_id}: неизвестный текстовый шаблон {template}")
        renderer = item.get("renderer", "remotion")
        if not isinstance(renderer, str) or renderer not in {"remotion", "capcut"}:
            raise ValueError(f"{cue_id}: renderer должен быть remotion или capcut")
        if renderer == "capcut" and template in {*EDITORIAL_TEXT, *NARRATIVE_TEXT}:
            raise ValueError(f"{template} доступен только в Remotion")
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise ValueError(f"{cue_id}: params должен быть объектом")
        for field, low, high in (("font_size", 16, 160), ("reveal_frames", 1, 120)):
            if field in params:
                number(params[field], field, low, high)
        if params.get("position", "center") not in ("top", "center", "bottom"):
            raise ValueError("text.params.position: top/center/bottom")
        if "color" in params and (not isinstance(params["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", params["color"])):
            raise ValueError("text.params.color: #RRGGBB")
        if "font_family" in params and (not isinstance(params["font_family"], str) or len(params["font_family"]) > 100):
            raise ValueError("text.params.font_family: строка до 100 символов")
        if kind == "accent":
            value = item.get("text")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{cue_id}: нужен text")
            top, bottom = "", ""
        else:
            top = item.get("top_text", item.get("text", ""))
            bottom = item.get("bottom_text", "")
            if not isinstance(top, str) or not isinstance(bottom, str) or not (top.strip() or bottom.strip()):
                raise ValueError(f"{cue_id}: нужен top_text или bottom_text")
            value = " / ".join(part for part in (top.strip(), bottom.strip()) if part)
        chunk_index = item.get("chunk_index")
        if chunk_index is not None:
            if (type(chunk_index) is not int or chunks is None or not 0 <= chunk_index < len(chunks)):
                raise ValueError(f"{cue_id}: неверный chunk_index")
            start, end = float(chunks[chunk_index]["start"]), float(chunks[chunk_index]["end"])
            if "start" in item or "end" in item:
                try:
                    start, end = float(item["start"]), float(item["end"])
                except (KeyError, TypeError, ValueError):
                    raise ValueError(f"{cue_id}: нужны оба start/end") from None
        else:
            if isinstance(item.get("start"), bool) or isinstance(item.get("end"), bool):
                raise ValueError(f"{cue_id}: укажи start и end в секундах")
            try:
                start, end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"{cue_id}: укажи start и end в секундах") from None
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end > total_frames / FPS + .000001:
            raise ValueError(f"{cue_id}: таймкод выходит за пределы видео")
        first, last = round(start * FPS), round(end * FPS)
        if last <= first or last > total_frames:
            raise ValueError(f"{cue_id}: длительность должна быть не меньше одного кадра")
        if template in EDITORIAL_TEXT or template == "selective_marker":
            if last - first < 42:
                raise ValueError(f"{cue_id}: для {template} нужно минимум 1,4 секунды")
            params = {**params, "color": "#ffffff", "font_family": "coolvetica", "position": "center"}
            if template in ("marker_highlight", "selective_marker"):
                delay, sweep = marker_window(last - first)
                params.update(marker_delay_frames=delay, marker_frames=sweep)
            if template == "selective_marker":
                validate_highlights(value, params)
        if chunks is not None:
            matching = [i for i, chunk in enumerate(chunks)
                        if round(float(chunk["start"]) * FPS) <= first
                        and last <= round(float(chunk["end"]) * FPS)]
            if len(matching) != 1 or (chunk_index is not None and matching[0] != chunk_index) or matching[0] in used_chunks:
                raise ValueError(f"{cue_id}: одна текстовая вставка на один chunk, внутри его времени")
            used_chunks.add(matching[0])
            chunk_index = matching[0]
            if template == "impact_typewriter":
                last = round(float(chunks[chunk_index]["end"]) * FPS)
        timed_words = None
        if template in SPEECH_TEXT:
            params = {**params, "color": "#ffffff", "font_family": "coolvetica", "position": "center"}
            timed_words = speech_words({**item, "template": template}, value, first, last, word_timestamps)
        audio = item.get("audio", True)
        if not isinstance(audio, bool):
            raise ValueError(f"{cue_id}: audio должен быть true или false")
        seen.add(cue_id)
        cues.append({"id": cue_id, "kind": kind, "template": template, "renderer": renderer, "params": params, "text": value.strip(),
                     **({"top_text": top.strip(), "bottom_text": bottom.strip()} if kind == "plain" else {}),
                     "start": first / FPS, "end": last / FPS,
                     "scene_start": round(float(chunks[chunk_index]["start"]) * FPS) / FPS if chunks is not None else first / FPS,
                     "scene_end": round(float(chunks[chunk_index]["end"]) * FPS) / FPS if chunks is not None else last / FPS,
                     "duration_frames": last - first, "audio": audio,
                     **({"speech_words": timed_words} if timed_words is not None else {}),
                     **({"word_range": item["word_range"]} if "word_range" in item else {}),
                     **({"chunk_index": chunk_index} if chunk_index is not None else {})})
    return sorted(cues, key=lambda cue: (cue["start"], cue["id"]))


def export_folder(scene_dir):
    return Path(scene_dir) / "text_overlays"


def _probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration:stream=codec_name,codec_type,pix_fmt,width,height,r_frame_rate,duration,nb_frames",
                             "-of", "json", str(path)], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError(f"Не удалось прочитать {Path(path).name}")
    info = json.loads(result.stdout)
    video = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video:
        raise ValueError(f"{Path(path).name}: нет видеопотока")
    return float(video.get("duration") or info["format"]["duration"]), video, any(
        stream.get("codec_type") == "audio" for stream in info.get("streams", []))


def task_status(scene_dir, cues):
    folder = export_folder(scene_dir)
    rows = []
    for cue in cues:
        if cue.get("renderer", "remotion") == "remotion":
            rows.append({**cue, "renderer": "remotion", "filename": "Remotion · " + TEXT_COMPONENTS[cue["template"]],
                         "seconds": cue["duration_frames"] / FPS, "status": "ready", "error": "", "has_audio": False})
            continue
        path = folder / f"{cue['id']}.mov"
        row = {**cue, "filename": path.name, "path": str(path), "seconds": cue["duration_frames"] / FPS,
               "status": "missing", "error": "Файл ещё не экспортирован"}
        if path.is_file():
            try:
                actual, video, has_audio = _probe(path)
                expected = cue["duration_frames"] / FPS
                frames = int(video.get("nb_frames") or round(actual * FPS))
                if frames != cue["duration_frames"]:
                    raise ValueError(f"Длительность {actual:.2f} с; нужна {expected:.2f} с ({cue['duration_frames']} кадров)")
                if abs(float(Fraction(video.get("r_frame_rate", "0/1"))) - FPS) > .01:
                    raise ValueError(f"Нужен экспорт 30 fps; у {path.name} другая частота кадров")
                if (video.get("width"), video.get("height")) != (1920, 1080):
                    raise ValueError(f"{path.name}: нужен экспорт 1920×1080")
                if cue["kind"] == "plain" and video.get("codec_name") != "prores":
                    raise ValueError(f"{path.name}: для plain нужен ProRes 4444")
                fmt = video.get("pix_fmt", "")
                if video.get("codec_name") != "hevc" and fmt not in _ALPHA_FORMATS and not fmt.startswith(("yuva", "gbrap")):
                    raise ValueError(f"{path.name}: нет альфа-канала")
                row.update({"status": "ready", "error": "", "has_audio": has_audio,
                            "audio_warning": "В MOV нет аудиодорожки" if cue["audio"] and not has_audio else "",
                            "width": video["width"], "height": video["height"]})
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                row.update({"status": "invalid", "error": str(exc)})
        rows.append(row)
    return rows


def require_text_exports(scene_dir, cues):
    rows = task_status(scene_dir, cues)
    bad = [f"{row['filename']}: {row['error']}" for row in rows if row["status"] != "ready"]
    if bad:
        raise ValueError("Текстовые вставки не готовы: " + "; ".join(bad))
    return rows


def write_task_list(scene_dir, cues):
    remotion = [cue for cue in cues if cue.get("renderer", "remotion") == "remotion"]
    if remotion:
        export_folder(scene_dir).mkdir(exist_ok=True)
        (export_folder(scene_dir) / "remotion_text.json").write_text(json.dumps(remotion, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        (export_folder(scene_dir) / "remotion_text.json").unlink(missing_ok=True)
    cues = [cue for cue in cues if cue.get("renderer") == "capcut"]
    if not cues:
        (export_folder(scene_dir) / "ЗАДАНИЯ_ДЛЯ_CAPCUT.txt").unlink(missing_ok=True)
        return
    folder = export_folder(scene_dir)
    folder.mkdir(exist_ok=True)
    lines = [f"Папка экспорта: {folder.resolve()}",
             "CapCut: прозрачный ProRes 4444 MOV, 1920×1080, 30 fps. Время ЧЧ:ММ:СС:КК — правая граница ВСЕГО проекта; обрежь до неё все дорожки, включая фон и звук.", ""]
    for row in task_status(scene_dir, cues):
        clip = row["chunk_index"] + 1 if "chunk_index" in row else "—"
        seconds, frames = divmod(row["duration_frames"], FPS)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        capcut_time = f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"
        lines.append(f"{row['id']} · {row['template']} · клип {clip} · сцена {row['scene_start']:.3f}–{row['scene_end']:.3f} с · "
                     f"шаблон {row['start']:.3f}–{row['end']:.3f} с · РЕНДЕРИТЬ {row['seconds']:.3f} с "
                     f"({row['duration_frames']} кадров) · CapCut {capcut_time} · {row['filename']}")
        if row["kind"] == "plain":
            lines.append(f"Сверху: {row['top_text'] or '—'}")
            lines.append(f"Снизу: {row['bottom_text'] or '—'}")
        else:
            lines.append(f"Текст: {row['text']}")
        lines.append("")
    (folder / "ЗАДАНИЯ_ДЛЯ_CAPCUT.txt").write_text("\n".join(lines), encoding="utf-8")


def _alpha_source(path, folder):
    _, video, _ = _probe(path)
    if video.get("pix_fmt") in _ALPHA_FORMATS or video.get("pix_fmt", "").startswith(("yuva", "gbrap")):
        return path
    if video.get("codec_name") != "hevc" or not shutil.which("avconvert"):
        raise ValueError(f"{path.name}: нет доступного альфа-канала; экспортируй HEVC с альфой или ProRes 4444")
    converted = folder / f"{path.stem}_alpha.mov"
    result = subprocess.run(["avconvert", "--source", str(path), "--preset",
                             "PresetAppleProRes4444LPCM", "--output", str(converted), "--replace"],
                            capture_output=True, text=True, timeout=3600)
    if result.returncode or not converted.is_file():
        raise RuntimeError(f"Не удалось преобразовать {path.name} в ProRes 4444: {(result.stderr or result.stdout)[-1000:]}")
    _, converted_video, _ = _probe(converted)
    if not converted_video.get("pix_fmt", "").startswith(("yuva", "gbrap")):
        raise ValueError(f"{path.name}: после конвертации альфа-канал не обнаружен")
    return converted


def render_text_scene(source, output, scene_start, scene_end, cues, width, height):
    relevant = [cue for cue in active_text_cues(cues) if cue["start"] < scene_end and cue["end"] > scene_start]
    if not relevant:
        return False
    with tempfile.TemporaryDirectory(prefix=".text_", dir=str(Path(output).parent)) as temporary:
        folder = Path(temporary)
        automatic = [cue for cue in relevant if cue.get("renderer", "remotion") == "remotion"]
        legacy = [cue for cue in relevant if cue.get("renderer") == "capcut"]
        if automatic:
            local = [{**cue, "local_start_frame": round((cue["start"] - scene_start) * FPS)} for cue in automatic]
            remotion_output = folder / "text.mp4" if legacy else output
            render_remotion("TextScene", remotion_output, round((scene_end - scene_start) * FPS), width, height,
                            {"cues": local}, {"source": source})
            if not legacy:
                return True
            source = remotion_output
        relevant = legacy
        inputs, filters, previous = ["-i", str(source)], [], "0:v"
        for index, cue in enumerate(relevant, 1):
            path = _alpha_source(Path(cue["path"]), folder)
            seek = max(0, scene_start - cue["start"])
            offset = max(0, cue["start"] - scene_start)
            stop = min(scene_end, cue["end"]) - scene_start
            inputs.extend(["-ss", f"{seek:.6f}", "-i", str(path)])
            filters.append(f"[{index}:v:0]fps={FPS},scale=iw*{width}/1920:ih*{height}/1080:flags=lanczos,format=rgba,setpts=PTS-STARTPTS+{offset:.6f}/TB[txt{index}]")
            filters.append(f"[{previous}][txt{index}]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass:repeatlast=0:format=auto:enable='gte(t,{offset:.6f})*lt(t,{stop:.6f})'[mix{index}]")
            previous = f"mix{index}"
        filters.append(f"[{previous}]format=yuv420p[vout]")
        frames = round((scene_end - scene_start) * FPS)
        command = ["ffmpeg", "-y", *inputs, "-filter_complex_threads", "2", "-filter_complex", ";".join(filters),
                   "-map", "[vout]", "-frames:v", str(frames), "-r", str(FPS), "-an", "-c:v", "libx264",
                   "-threads", "4", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=3600)
        if result.returncode:
            raise RuntimeError(f"FFmpeg не смог наложить текст: {result.stderr[-2000:]}")
    return True


def text_cache_key(source, cues, width, height):
    stat = Path(source).stat()
    files = [(cue["path"], Path(cue["path"]).stat().st_size, Path(cue["path"]).stat().st_mtime_ns)
             for cue in cues if cue.get("renderer") == "capcut"]
    payload = [str(source), stat.st_size, stat.st_mtime_ns, cues, files, width, height,
               Path(__file__).stat().st_mtime_ns, remotion_source_hash()]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:24]
