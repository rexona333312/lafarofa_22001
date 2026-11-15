from music_inserts import pause_narration
import os
import math
import random
import json
import hashlib
import subprocess
import shutil
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from presets import (graph_for_scene, asset_path, PRESETS, ROOT, ASSETS_ROOT, dimensions,
                     BUILTIN_TRANSITIONS, REMOTION_TEMPLATES, REMOTION_SOUNDS, REMOTION_TRANSITIONS, AUDIO_EXTENSIONS,
                     validate_tracks, transition_boundary, validate_scene, PERSON_TEMPLATES)
from text_overlays import require_text_exports, render_text_scene, text_cache_key, text_sfx_tracks
from remotion_renderer import render_remotion, remotion_source_hash
from person_cutout import cutout_person
from motion_timing import timeline_scroll_frames
from narrative_templates import CAROUSEL_TEMPLATES, carousel_groups
from retired_templates import without_retired_templates
from reference_templates import REFERENCE_TEMPLATES, comparison_groups, motion_params, reference_sfx
from avatar_templates import AVATAR_TEMPLATES
from documentary_templates import DOCUMENTARY_TEMPLATES, documentary_params, documentary_sfx
from geographic_maps import is_geo_scene, geographic_params, graphic_placeholder, DATA as GEODATA_PATH
from editorial_planning import graphics_summary
from shot_planning import editing_summary
from automatic_sfx import extra_scene_sfx, transition_sfx, distribute_sfx


W, H = 1920, 1080
FPS = 30
REMOTION_CARD = ASSETS_ROOT / "remotion" / "paper_card"


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def build_video(
    chunks: list[dict],
    scene_dir: str,
    scene_name: str,
    progress_callback=None,
    audio_path: str | None = None,
    audio_duration: float | None = None,
    used_file_callback=None,
    transitions=None,
    audio_tracks=None,
    text_cues=None,
    preview=False,
    cancel_event=None,
) -> tuple[str, dict[int, list[str]]]:
    active = without_retired_templates({'chunks': chunks, 'text_cues': text_cues})
    chunks, text_cues = active['chunks'], active['text_cues']
    if not chunks:
        raise ValueError("Пустой таймлайн")
    if audio_path and not os.path.isfile(audio_path):
        raise ValueError("Исходная озвучка проекта не найдена")
    groups = carousel_groups(chunks)
    pairs = comparison_groups(chunks)
    internal_carousel_boundaries = {i for group in [*groups, *pairs] for i in group[:-1]}
    resolved_files, missing_media = {}, []
    for index, chunk in enumerate(chunks):
        validate_scene(chunk)
        if is_geo_scene(chunk) or chunk.get('template')=='data_comparison':
            chunk = dict(chunk)
            chunk['_files'] = [graphic_placeholder(chunk, Path(scene_dir)/'downloads')]
        files = chunk.get("_files")
        if files is None:
            files = _collect_files(os.path.join(scene_dir, "downloads"), chunk.get("_chunk_id", index), chunk["type"])[:1]
        resolved_files[index] = files
        if chunk.get("template") in AVATAR_TEMPLATES:
            avatar = chunk.get("_avatar_file")
            if not avatar or not _filter_valid_files([avatar]):
                raise ValueError(f"Сцена {chunk.get('_chunk_id', index) + 1}: добавь клип ведущей в библиотеку")
        if not files or any(not path or not _filter_valid_files([path]) for path in files):
            missing_media.append(chunk.get("_chunk_id", index) + 1)
    if missing_media:
        raise ValueError("Добавь фото или видео для кадров: " + ", ".join(map(str, missing_media)))
    music_clips=[]
    for index,chunk in enumerate(chunks):
        if not chunk.get('music_insert'):continue
        if len(resolved_files[index])!=1:
            raise ValueError(f'Музыкальная вставка {index+1}: выбери ровно один видеоклип')
        path=resolved_files[index][0]
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type:format=duration','-of','json',path],text=True))
        if not any(s.get('codec_type')=='audio' for s in info.get('streams',[])):
            raise ValueError(f'Музыкальная вставка {index+1}: в выбранном клипе нет звука; выбери видео с оригинальным звуком')
        if float(info.get('format',{}).get('duration',0))<chunk['duration']-.04:
            raise ValueError(f'Музыкальная вставка {index+1}: выбранный клип слишком короткий')
        music_clips.append({'_path':path,'start':chunk['start'],'end':chunk['end'],'duration':chunk['duration'],
                            '_music_insert':True,'fade':.12,'gain_db':0})
    if music_clips and not audio_path:
        raise ValueError('Для музыкальных пауз нужна исходная озвучка проекта')
    text_rows = require_text_exports(scene_dir, text_cues or [])
    transitions = list(transitions or [])
    if all("start" in c and "end" in c for c in chunks):
        boundaries = [float(chunk["end"]) for chunk in chunks[:-1]]
        covered = {index for index, boundary in enumerate(boundaries) for cue in transitions
                   if cue.get("kind") != "overlay"
                   and abs((float(cue["start"])+float(cue["end"]))/2-boundary) <= .001}
        for overlay in list(transitions):
            if overlay.get("kind") != "overlay" or overlay.get("blend") != "screen":
                continue
            midpoint = (float(overlay["start"])+float(overlay["end"]))/2
            index = next((i for i, boundary in enumerate(boundaries) if abs(midpoint-boundary) <= .001), None)
            if index is None or index in covered or index in internal_carousel_boundaries:
                continue
            left, right, boundary = chunks[index], chunks[index+1], boundaries[index]
            if left.get("_avatar_lipsync") or right.get("_avatar_lipsync"):
                continue
            half = min(.2, (boundary-float(left["start"]))/4, (float(right["end"])-boundary)/4)
            if half >= 2/FPS:
                transitions.append({"kind": "crossfade", "start": boundary-half, "end": boundary+half,
                                    "strength": .45})
                covered.add(index)
    native_cues = []
    if all("start" in chunk and "end" in chunk for chunk in chunks):
        validate_tracks({"transitions": transitions}, audio_duration or float(chunks[-1]["end"]), chunks)
    for transition in transitions:
        if transition.get("kind") not in ("cut", "overlay") and any(
                abs((float(transition["start"])+float(transition["end"]))/2 - float(chunks[i]["end"])) <= .001
                for i in internal_carousel_boundaries):
            raise ValueError("Внутри серии фото или пары используй cut: непрерывную анимацию делает сам шаблон")
        if transition.get("kind") in BUILTIN_TRANSITIONS:
            native_cues.append((transition_boundary(transition, chunks), transition))
    native_scenes = {index for boundary, _ in native_cues for index in (boundary, boundary+1)}
    width, height = (960, 540) if preview else (W, H)
    cache = Path(scene_dir, ".render_cache")
    cache.mkdir(exist_ok=True)
    definitions = (json.dumps(PRESETS, sort_keys=True) + (ROOT / "__init__.py").read_text()
                   + Path(__file__).read_text() + (REMOTION_CARD / "src" / "index.jsx").read_text()
                   + (REMOTION_CARD / "render.mjs").read_text() + remotion_source_hash()
                   + Path(__file__).with_name("person_cutout.py").read_text()
                   + Path(__file__).with_name("motion_timing.py").read_text()
                   + Path(__file__).with_name("narrative_templates.py").read_text()
                   + Path(__file__).with_name("reference_templates.py").read_text()
                   + Path(__file__).with_name("next_reference_templates.py").read_text()
                   + Path(__file__).with_name("late_reference_templates.py").read_text())
    definitions += Path(__file__).with_name("avatar_templates.py").read_text()
    definitions += Path(__file__).with_name('documentary_templates.py').read_text()
    definitions += Path(__file__).with_name('geographic_maps.py').read_text()
    definitions += Path(__file__).with_name("shot_planning.py").read_text()
    definitions += GEODATA_PATH.read_text()
    definitions += (REMOTION_CARD/'map-tiles.mjs').read_text()
    renderer_hash = hashlib.sha256(definitions.encode()).hexdigest()
    rendered, warnings, missing, frame_ranges, finishing = [], [], [], [], []
    template_tracks = []
    chunk_used_files: dict[int, list[str]] = {}
    cursor = 0.0
    def progress(message):
        if progress_callback:
            progress_callback(message)
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Сессия отменена; готовые сцены сохранены в кэше")
    for i, chunk in enumerate(chunks):
        check_cancelled()
        downloads_dir = os.path.join(scene_dir, "downloads")
        chunk_idx = chunk.get("_chunk_id", i)
        start = float(chunk.get("start", cursor))
        end = float(chunk.get("end", start + float(chunk.get("_duration_override") or chunk.get("duration", 5))))
        if abs(start - cursor) > .001 or not math.isfinite(end) or end <= start:
            raise ValueError("Таймлайн должен идти от 0 без пропусков и пересечений")
        start = cursor
        # Quantize absolute boundaries, not each duration: rounding must not accumulate.
        first_frame, last_frame = round(start * FPS), round(end * FPS)
        if i == len(chunks) - 1 and audio_duration:
            if abs(end - audio_duration) > .05:
                raise ValueError("Конец таймлайна не совпадает с длительностью озвучки")
            last_frame = math.ceil(audio_duration * FPS)
        duration = (last_frame - first_frame) / FPS
        if duration <= 0:
            raise ValueError("Сцена короче одного кадра")
        cursor = end
        frame_ranges.append((first_frame, last_frame))
        files = resolved_files[i]
        files = [path if path and _filter_valid_files([path]) else None for path in files]
        if chunk.get("template") and (not files or files[0] is None):
            raise ValueError(f"Сцена {chunk_idx + 1}: для Remotion-шаблона нужен выбранный материал")
        sound_info = REMOTION_SOUNDS[chunk["template"]] if chunk.get("template") else None
        sound = (asset_path(sound_info["asset"], {"sfx"}) if chunk.get("template") == "history_timeline"
                 else _template_whoosh()) if sound_info else None
        sound_duration = _probe_duration(str(sound)) if sound else None
        if sound and not sound_duration:
            raise ValueError(f"Не удалось прочитать звук {sound.name}")
        local_transitions = []
        scene_start = first_frame / FPS
        for transition in transitions:
            if transition.get("kind") in BUILTIN_TRANSITIONS:
                continue
            ts, te = float(transition["start"]), float(transition["end"])
            if ts < last_frame / FPS and te > scene_start:
                midpoint = (ts+te)/2
                if transition.get("kind") == "fade":
                    boundaries = [float(c["end"]) for c in chunks[:-1] if "end" in c]
                    if boundaries:
                        midpoint = min(boundaries,key=lambda point:abs(point-midpoint))
                    midpoint = round(midpoint*FPS)/FPS
                local_transitions.append({**transition, "kind": transition.get("kind", "overlay"),
                                          "_start": ts-scene_start, "_end": te-scene_start,
                                          "_mid": midpoint-scene_start,
                                          "_seek": max(scene_start-ts, 0)})
        finishing.append(local_transitions if i in native_scenes else [])
        # Native patches mix clean scene renders; downloaded overlays are applied above them.
        if i in native_scenes:
            local_transitions = []
        signature = {"renderer": renderer_hash, "scene": chunk, "files": files,
                     "duration": duration, "size": [width, height], "transitions": local_transitions}
        group = next((group for group in groups if i in group), None)
        carousel = None
        if group:
            anchor = round(float(chunks[group[0]]["start"]) * FPS)
            carousel = {"files": [resolved_files[g][0] for g in group],
                        "starts": [round(float(chunks[g]["start"])*FPS)-anchor for g in group],
                        "frameOffset": first_frame-anchor,
                        "captions": [chunks[g].get("params", {}).get("caption", "") for g in group],
                        "style": CAROUSEL_TEMPLATES[chunk["template"]],
                        "archival": chunk.get("params", {}).get("archival", False),
                        "paper": chunks[group[0]].get("params", {}).get("paper", "paper/paper1.jpg")}
            signature["carousel"] = carousel
        pair = next((pair for pair in pairs if i in pair), None)
        comparison = None
        if pair:
            anchor = round(float(chunks[pair[0]]["start"])*FPS)
            comparison = {"files": [resolved_files[g][0] for g in pair],
                          "frameOffset": first_frame-anchor,
                          "groupFrames": round(float(chunks[pair[-1]]["end"])*FPS)-anchor,
                          "labels": [chunks[g]["params"]["label"] for g in pair],
                          "credits": [chunks[g].get("credits", {}).get(os.path.basename(resolved_files[g][0]), "") for g in pair],
                          "motionParams": chunks[pair[0]]["params"]}
            signature["comparison"] = comparison
        fingerprints = []
        params = chunk.get("params", {})
        background = (asset_path(carousel["paper"] if carousel else params.get("background") or params.get("paper", "paper/paper1.jpg"),
                                 {"backgrounds", "paper"} if chunk.get("template") in PERSON_TEMPLATES else {"paper"})
                      if chunk.get("template") and chunk["template"] not in AVATAR_TEMPLATES else None)
        for path in [p for p in files if p] + ([chunk["_avatar_file"]] if chunk.get("_avatar_file") else []) + (carousel["files"] if carousel else []) + (comparison["files"] if comparison else []) + [str(ASSETS_ROOT / a["id"]) for a in _scene_assets(chunk, local_transitions)] + ([str(background)] if background else []):
            stat = os.stat(path)
            fingerprints.append([path, stat.st_size, stat.st_mtime_ns])
        signature["fingerprints"] = fingerprints
        digest = hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        temp_path = str(cache / f"chunk{chunk_idx:03d}_{digest}.mp4")
        if os.path.exists(temp_path) and abs((_probe_duration(temp_path) or 0)-duration) < .04:
            progress(f"Сцена {i+1}/{len(chunks)}: использую готовый рендер")
            used = [p for p in files if p]
            try:
                with open(temp_path+".json", encoding="utf-8") as file:
                    warnings.extend(json.load(file))
            except (OSError, ValueError):
                pass
        else:
            progress(f"Рендерю сцену {i+1}/{len(chunks)}: {chunk.get('preset', 'auto')}...")
            def warn(message):
                warnings.append({"chunk_id": chunk_idx, "message": message}); progress(message)
            before = len(warnings)
            used = (_render_remotion_template(files[0], temp_path, duration, chunk, width, height,
                                              local_transitions, warn, background, progress, carousel, comparison)
                    if chunk.get("template") else
                    _render_preset(files, temp_path, duration, chunk, width, height, local_transitions, warn))
            with open(temp_path+".json", "w", encoding="utf-8") as file:
                json.dump(warnings[before:], file, ensure_ascii=False)
        used_names = [os.path.basename(f) for f in used]
        chunk_used_files[chunk_idx] = used_names
        if used_file_callback:
            for fname in used_names:
                used_file_callback(chunk_idx, fname)
        rendered.append(temp_path)
        if chunk.get("template") in DOCUMENTARY_TEMPLATES:
            for cue in documentary_sfx(chunk['template'],params,last_frame-first_frame):
                template_tracks.append({'_path':str(asset_path(cue['asset'],{'sfx'})),
                    'start':scene_start+cue['start_frame']/FPS,'end':scene_start+cue['end_frame']/FPS,
                    'preserve_gain':True,'gain_db':20*math.log10(.3),'loop':cue['loop'],'fade':0})
        if chunk.get("template") in REFERENCE_TEMPLATES and not is_geo_scene(chunk) and (not pair or i == pair[0]):
            frames = comparison["groupFrames"] if comparison else last_frame-first_frame
            for cue in reference_sfx(chunk["template"], params, frames):
                template_tracks.append({"_path": str(asset_path(cue["asset"], {"sfx"})),
                                        "start": scene_start+cue["start_frame"]/FPS,
                                        "end": scene_start+cue["end_frame"]/FPS,
                                        "preserve_gain": True, "gain_db": 20*math.log10(.3),
                                        "loop": cue["loop"], "fade": 0})
        event_params = (motion_params(chunk['template'], params, last_frame-first_frame)
                        if chunk.get('template') in ('text_highlight_split','lower_third_contrast') else params)
        for cue in extra_scene_sfx(chunk.get('template') or '', event_params, last_frame-first_frame):
            template_tracks.append({'asset':cue['asset'],'start':scene_start+cue['start_frame']/FPS,
                'end':scene_start+cue['end_frame']/FPS,'preserve_gain':True,'gain_db':20*math.log10(.3),
                'loop':cue['loop'],'fade':0})
        if sound:
            sound_start = scene_start + sound_info["start_frame"] / FPS
            if sound_start >= last_frame / FPS:
                raise ValueError(f"{chunk['template']}: SFX начинается после конца сцены")
            template_tracks.append({"_path": str(sound), "preserve_gain": True, "gain_db": 20 * math.log10(.3), "start": sound_start,
                                    "end": (sound_start + timeline_scroll_frames(last_frame-first_frame, chunk.get("params", {})) / FPS
                                            if chunk.get("template") == "history_timeline"
                                            else min(last_frame / FPS, sound_start + sound_duration)),
                                    "loop": chunk.get("template") == "history_timeline", "fade": 0})
    check_cancelled()
    if native_cues:
        rendered = _finish_builtin_transitions(rendered, frame_ranges, native_cues, finishing,
                                              cache, width, height, renderer_hash, progress, check_cancelled)
    for index, (source, (first, last)) in enumerate(zip(rendered, frame_ranges)):
        check_cancelled()
        scene_start, scene_end = first / FPS, last / FPS
        relevant = [cue for cue in text_rows if cue["start"] < scene_end and cue["end"] > scene_start]
        if not relevant:
            continue
        digest = text_cache_key(source, relevant, width, height)
        text_path = str(cache / f"text{index:03d}_{digest}.mp4")
        if not os.path.isfile(text_path) or abs((_probe_duration(text_path) or 0) - (scene_end-scene_start)) > .04:
            progress(f"Накладываю текст на сцену {index+1}/{len(chunks)}...")
            staging_text = text_path + ".building.mp4"
            render_text_scene(source, staging_text, scene_start, scene_end, relevant, width, height)
            if abs((_probe_duration(staging_text) or 0) - (scene_end-scene_start)) > .04:
                raise RuntimeError("Наложение текста изменило длительность сцены")
            os.replace(staging_text, text_path)
        rendered[index] = text_path
    progress("Собираю сцены без сдвига таймкодов...")
    output_path = os.path.join(scene_dir, "preview.mp4" if preview else f"{scene_name}.mp4")
    staging = output_path + ".building.mp4"
    _concat_with_xfade(rendered, staging)
    automatic_tracks = distribute_sfx([*template_tracks, *text_sfx_tracks(text_rows), *transition_sfx(transitions)],
        math.ceil(cursor*FPS)/FPS, seed=scene_name, manual_tracks=audio_tracks or [])
    if audio_path and os.path.exists(audio_path):
        progress("Смешиваю голос, музыку, ambience и SFX...")
        embedded = [{"_path": cue["path"], "start": cue["start"], "end": cue["end"],
                     "fade": 0, "preserve_gain": True} for cue in text_rows if cue["audio"] and cue.get("has_audio")]
        _mux_audio(staging, audio_path, [*(audio_tracks or []), *automatic_tracks, *embedded, *music_clips],
                   math.ceil(cursor * FPS) / FPS, music_clips)
    check_cancelled()
    actual_duration = _probe_duration(staging)
    if actual_duration is None or abs(actual_duration - math.ceil(cursor * FPS) / FPS) > .1:
        raise RuntimeError("Длительность готового MP4 не совпадает с таймлайном; предыдущий экспорт сохранён")
    os.replace(staging, output_path)
    with open(os.path.join(scene_dir, "render_report.json"), "w", encoding="utf-8") as report:
        json.dump({"preview": preview, "missing_chunks": missing, "warnings": warnings,
                   "graphics_coverage": {key:value for key,value in graphics_summary(chunks,text_cues or []).items() if key!='target_percent'},
                   "shot_editing": editing_summary(chunks, transitions),
                   "used_files": chunk_used_files, "fps": FPS,
                   "avatar_clips": [{"chunk_id": c.get("_chunk_id", i), "clip_id": c["_avatar_clip_id"],
                                     "source_start": c["_avatar_source_start"], "placement": AVATAR_TEMPLATES[c["template"]],
                                     "muted": True} for i, c in enumerate(chunks) if c.get("_avatar_file")],
                   "builtin_transitions": [cue["kind"] for _, cue in native_cues],
                   "automatic_sfx": [{"asset":track.get('asset') or 'sfx/'+Path(track['_path']).name,
                        "start":track['start'],"end":track['end'],"gain_db":track.get('gain_db',0),
                        "source_start":track.get('_source_start',0)} for track in automatic_tracks],
                   "photo_camera_backend": "ffmpeg"}, report, ensure_ascii=False, indent=2)
    return output_path, chunk_used_files


def _finish_builtin_transitions(rendered, frame_ranges, cues, finishing, cache, width, height,
                                renderer_hash, progress, check_cancelled):
    patches = {index: [] for boundary, _ in cues for index in (boundary, boundary+1)}
    for boundary, cue in cues:
        check_cancelled()
        start, end = round(float(cue["start"])*FPS), round(float(cue["end"])*FPS)
        cut = frame_ranges[boundary][1]
        left_frames, right_frames = cut-start, end-cut
        if min(left_frames, right_frames) < 2:
            raise ValueError("Переход слишком короткий после округления к 30 FPS")
        signature = [renderer_hash, rendered[boundary:boundary+2], cue, start, cut, end]
        digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
        path = str(cache / f"transition_{digest}.mp4")
        duration = (end-start)/FPS
        if not os.path.isfile(path) or abs((_probe_duration(path) or 0)-duration) > .02:
            progress(f"Переход {cue['kind']} на {cut/FPS:.2f} сек...")
            _render_transition_window(rendered[boundary], rendered[boundary+1], path, cue,
                                      (start-frame_ranges[boundary][0])/FPS,
                                      left_frames, right_frames, width, height)
        else:
            progress(f"Переход {cue['kind']}: использую кэш")
        for index in (boundary, boundary+1):
            scene_first, scene_last = frame_ranges[index]
            first, last = max(scene_first, start), min(scene_last, end)
            patches[index].append({"path": path, "source_frame": first-start,
                                   "start_frame": first-scene_first, "frames": last-first})
    result = list(rendered)
    for index, pieces in patches.items():
        check_cancelled()
        assets = []
        for entry in _scene_assets({}, finishing[index]):
            path = ASSETS_ROOT / entry["id"]
            stat = path.stat()
            assets.append([str(path), stat.st_size, stat.st_mtime_ns])
        signature = [renderer_hash, rendered[index], pieces, finishing[index], assets]
        digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
        path = str(cache / f"finished{index:03d}_{digest}.mp4")
        duration = (frame_ranges[index][1]-frame_ranges[index][0])/FPS
        if not os.path.isfile(path) or abs((_probe_duration(path) or 0)-duration) > .02:
            progress(f"Накладываю дорожку переходов на сцену {index+1}...")
            _render_preset([rendered[index]], path, duration,
                           {"type": "video", "preset": "PHOTO_STATIC", "params": {"fit": "cover"}},
                           width, height, finishing[index], native_patches=pieces)
        else:
            progress(f"Сцена {index+1} с переходами: использую кэш")
        result[index] = path
    return result


def _render_transition_window(left, right, output, cue, left_seek, left_frames, right_frames, width, height):
    frames = left_frames+right_frames
    duration, last_time = frames/FPS, (frames-1)/FPS
    # ponytail: hold edge frames inside the overlap; source pre/post-roll can replace holds if needed.
    graph = [
        f"[0:v]fps={FPS},trim=end_frame={left_frames},setpts=N/({FPS}*TB),tpad=stop_mode=clone:stop={right_frames},trim=end_frame={frames},settb=1/{FPS},format=yuv444p[a]",
        f"[1:v]fps={FPS},trim=end_frame={right_frames},setpts=N/({FPS}*TB),tpad=start_mode=clone:start={left_frames},trim=end_frame={frames},settb=1/{FPS},format=yuv444p[b]",
    ]
    kind = cue["kind"]
    if kind not in BUILTIN_TRANSITIONS:
        raise ValueError(f"Неизвестный переход: {kind}")
    if kind in REMOTION_TRANSITIONS:
        with tempfile.TemporaryDirectory(prefix=".transition_", dir=Path(output).parent) as folder:
            left_clip, right_clip = Path(folder) / "left.mp4", Path(folder) / "right.mp4"
            _run_ffmpeg(["-y", "-ss", str(left_seek), "-i", left, "-i", right,
                         "-filter_complex_threads", "2", "-filter_complex", ";".join(graph),
                         "-map", "[a]", "-frames:v", str(frames), "-c:v", "libx264", "-an", str(left_clip),
                         "-map", "[b]", "-frames:v", str(frames), "-c:v", "libx264", "-an", str(right_clip)])
            staging = output + ".part.mp4"
            render_remotion("TransitionWindow", staging, frames, width, height,
                            {"kind": kind, "params": cue.get("params", {})}, {"left": left_clip, "right": right_clip})
            if abs((_probe_duration(staging) or 0) - duration) > .02:
                raise RuntimeError("Remotion-переход изменил длительность")
            os.replace(staging, output)
        return
    left_label, right_label, transition = "a", "b", "fade"
    graph.append(f"[{left_label}][{right_label}]xfade=transition={transition}:duration={last_time}:offset=0,"
                 f"tpad=stop_mode=clone:stop=2,trim=end_frame={frames},setpts=N/({FPS}*TB),format=yuv420p[vout]")
    staging = output+".part.mp4"
    _run_ffmpeg(["-y", "-ss", str(left_seek), "-i", left, "-i", right,
                 "-filter_complex_threads", "2", "-filter_complex", ";".join(graph), "-map", "[vout]",
                 "-frames:v", str(frames), "-r", str(FPS), "-c:v", "libx264", "-threads", "4",
                 "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", staging])
    if abs((_probe_duration(staging) or 0)-duration) > .02:
        raise RuntimeError("Переход изменил длительность; финальная сборка остановлена")
    os.replace(staging, output)


def _scene_assets(scene, transitions):
    result = []
    for key in ("paper", "lut"):
        if scene.get("params", {}).get(key): result.append({"id": scene["params"][key]})
    for effect in scene.get("effects", []):
        if effect.get("lut"): result.append({"id": effect["lut"]})
        result.extend({"id": layer["asset"]} for layer in effect.get("layers", []))
    result.extend({"id": layer["asset"]} for layer in [*scene.get("layers", []), *transitions] if layer.get("asset"))
    return result


def _render_preset(files, output, duration, scene, width=W, height=H, transitions=(), progress=None, native_patches=()):
    preset = scene.get("preset", "PHOTO_SLOW_ZOOM" if scene["type"] == "photo" else "PHOTO_STATIC")
    if len(files) > 1 and PRESETS[preset]["kind"] != "composition":
        with tempfile.TemporaryDirectory(dir=os.path.dirname(output)) as folder:
            renders, used = [], []
            total = round(duration*FPS)
            for index, source in enumerate(files):
                first, last = round(index*total/len(files)), round((index+1)*total/len(files))
                if last <= first:
                    raise ValueError("Слишком много выбранных файлов для длительности сцены")
                offset, span = first/FPS, (last-first)/FPS
                layers = [{**layer, "_start": layer["_start"]-offset, "_end": layer["_end"]-offset,
                           "_mid": layer["_mid"]-offset,
                           "_seek": layer["_seek"]+max(offset-max(layer["_start"],0),0)}
                          for layer in transitions if layer["_start"] < offset+span and layer["_end"] > offset]
                path = os.path.join(folder, f"sub{index}.mp4")
                used.extend(_render_preset([source], path, span, scene, width, height, layers, progress))
                renders.append(path)
            _concat_with_xfade(renders, output+".part.mp4")
            os.replace(output+".part.mp4", output)
            return used
    inputs, graph, used = graph_for_scene(files, scene, duration, width, height, FPS, transitions, progress, native_patches)
    credits = list(dict.fromkeys(scene.get("credits", {}).get(os.path.basename(path)) for path in used))
    credits = [credit for credit in credits if credit]
    staging = output + ".part.mp4"
    # Pillow preserves attribution even when FFmpeg was built without drawtext.
    with tempfile.TemporaryDirectory(dir=os.path.dirname(output)) as folder:
        if credits:
            credit_file = os.path.join(folder, "credit.png")
            _credit_image(" | ".join(credits), credit_file, width)
            index = inputs.count("-i")
            inputs.extend(["-loop", "1", "-framerate", str(FPS), "-i", credit_file])
            graph = graph.replace("null[vout]", f"[{index}:v]overlay=x=12:y=H-h-12:shortest=1[vout]")
        _run_ffmpeg(["-y", *inputs, "-filter_complex_threads", "2", "-filter_complex", graph,
                     "-map", "[vout]", "-t", str(duration), "-r", str(FPS),
                     "-c:v", "libx264", "-threads", "4", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", staging])
    os.replace(staging, output)
    if abs((_probe_duration(output) or 0)-duration) > .02:
        raise RuntimeError("Рендер сцены изменил длительность; финальная сборка остановлена")
    return used


def _template_whoosh():
    # Final audio scheduling rotates the complete whoosh family deterministically.
    return asset_path('sfx/whoosh.mp3', {'sfx'})


def _render_remotion_template(source, output, duration, scene, width, height, transitions, progress, background, cutout_progress=None, carousel=None, comparison=None):
    template = scene["template"]
    if template not in REMOTION_TEMPLATES:
        raise ValueError(f"Неизвестный Remotion-шаблон: {template}")
    if not shutil.which("node") or not (REMOTION_CARD / "node_modules" / ".bin" / "remotion").exists():
        raise RuntimeError("Для Remotion установите Node.js и выполните npm ci в assets/remotion/paper_card")
    with tempfile.TemporaryDirectory(dir=os.path.dirname(output)) as folder:
        card = os.path.join(folder, "card.mp4")
        if is_geo_scene(scene):
            render_remotion('GeographicMap',card,round(duration*FPS),width,height,
                {'geo':geographic_params(scene.get('params',{}),round(duration*FPS))},{})
        elif template in DOCUMENTARY_TEMPLATES:
            render_remotion('DocumentaryScene',card,round(duration*FPS),width,height,
                {'variant':template,'motionParams':documentary_params(template,scene.get('params',{}),round(duration*FPS))},
                {'picture':source,'background':background})
        elif template in AVATAR_TEMPLATES:
            media = {"avatar": scene["_avatar_file"]}
            if template != "avatar_full":
                media["picture"] = source
            render_remotion("AvatarScene", card, round(duration * FPS), width, height,
                            {"placement": AVATAR_TEMPLATES[template], "avatarStart": scene["_avatar_source_start"],
                             "motionParams": scene.get("params", {})}, media)
        elif template in REFERENCE_TEMPLATES:
            frames = comparison["groupFrames"] if comparison else round(duration*FPS)
            props = {"variant": template, "motionParams": motion_params(template, scene.get("params", {}) if not comparison else comparison["motionParams"], frames),
                     "groupFrames": frames, "frameOffset": comparison["frameOffset"] if comparison else 0}
            media = {"picture": source, "background": background}
            if comparison:
                props["labels"] = comparison["labels"]
                media.update(dict(zip(("left", "right"), comparison["files"])))
            render_remotion("ReferenceScene", card, round(duration*FPS), width, height, props, media)
        elif template in CAROUSEL_TEMPLATES:
            render_remotion("PhotoCarousel", card, round(duration * FPS), width, height,
                            {key: value for key, value in carousel.items() if key not in ("files", "paper")},
                            {"background": background, **{f"picture{i}": path for i, path in enumerate(carousel["files"])}})
        elif template in PERSON_TEMPLATES:
            picture = cutout_person(source, Path(output).parent, cutout_progress)
            params = scene.get("params", {})
            render_remotion("PersonIntro", card, round(duration * FPS), width, height,
                            {"placement": PERSON_TEMPLATES[template], "personName": params["person_name"],
                             "personRole": params.get("person_role", ""), "motionParams": params},
                            {"background": background, "picture": picture})
        elif template == "history_timeline":
            params = scene.get("params", {})
            render_remotion("HistoryTimeline", card, round(duration * FPS), width, height,
                            {"year": params["year"], "fromYear": params.get("from_year", max(1, params["year"] - 3)),
                             "label": params["label"], "scrollFrames": timeline_scroll_frames(round(duration * FPS), params)},
                            {"background": background, "picture": source})
        else:
            render_remotion("PaperCard", card, round(duration * FPS), width, height,
                            {"from": REMOTION_TEMPLATES[template], "motionParams": scene.get("params", {})},
                            {"background": background, "picture": source})
        # Existing FFmpeg graph applies attribution, looks, and timeline overlays to the card.
        credit = ("; ".join(c for c in comparison["credits"] if c) if comparison
                  else scene.get("credits", {}).get(os.path.basename(source)))
        card_scene = {**scene, "type": "video", "preset": "PHOTO_STATIC",
                      "params": {**scene.get("params", {}), "fit": "cover"},
                      "credits": {"card.mp4": credit} if credit else {}}
        card_scene.pop("template", None)
        if template in AVATAR_TEMPLATES:
            card_scene["params"].update(zoom_start=0, zoom_end=0)
        # The composed MP4 is now a regular video, not a new avatar/AI input scene.
        for key in ("avatar", "media_origin", "ai_prompt"):
            card_scene.pop(key, None)
        _render_preset([card], output, duration, card_scene, width, height, transitions, progress)
    return [source]


# ── Chunk renderers ───────────────────────────────────────────────────────────

def _credit_image(text, output, width):
    size = max(12, round(24 * width / W))
    for name in ("Arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            font = ImageFont.load_default(size=size)
    lines, line = [], ""
    for char in text:
        if char == "\n" or font.getlength(line + char) > width - 44:
            lines.append(line); line = ""
        if char != "\n":
            line += char
    text = "\n".join([*lines, line])
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.multiline_textbbox((0, 0), text, font=font, spacing=4)
    image = Image.new("RGBA", (math.ceil(box[2]-box[0])+20, math.ceil(box[3]-box[1])+20), (0, 0, 0, 166))
    ImageDraw.Draw(image).multiline_text((10-box[0], 10-box[1]), text, font=font, fill="white", spacing=4)
    image.save(output)


def _credit_filter(credit: str | None) -> str:
    if not credit:
        return ""
    safe_credit = credit.replace("\\", "\\\\").replace("'", "\\\\'").replace(":", "\\:")
    return f",drawtext=text='{safe_credit}':x=24:y=h-th-24:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=10"


def _render_video_chunk(files: list[str], output: str, duration: float, credits: dict[str, str] | None = None) -> list[str]:
    if len(files) > 1:
        _render_multi_files(files, output, duration, credits)
        return files
    return _render_preset(files, output, duration, {"type": "video", "preset": "PHOTO_STATIC", "credits": credits or {}})

def _render_photo_chunk(files: list[str], output: str, duration: float, credits: dict[str, str] | None = None) -> list[str]:
    if len(files) > 1:
        _render_multi_files(files, output, duration, credits)
        return files
    _render_single_photo(files[0], output, duration, (credits or {}).get(os.path.basename(files[0])))
    return [files[0]]


def _render_single_photo(photo: str, output: str, duration: float, credit: str | None = None):
    _render_preset([photo], output, duration, {"type": "photo", "preset": "PHOTO_SLOW_ZOOM",
                                             "credits": {os.path.basename(photo): credit} if credit else {}})

def _render_multi_files(files: list[str], output: str, duration: float, credits: dict[str, str] | None = None):
    return _render_preset(files, output, duration, {"type": "photo", "preset": "PHOTO_SLOW_ZOOM",
                                                 "credits": credits or {}})


# ── Concat with xfade ─────────────────────────────────────────────────────────

def _concat_with_xfade(temp_files: list[str], output: str):
    # Name retained for old callers; transitions live on a separate timed track.
    if len(temp_files) == 1:
        shutil.copy2(temp_files[0], output)
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", dir=os.path.dirname(output), encoding="utf-8") as listing:
        for path in temp_files:
            listing.write("file '" + os.path.abspath(path).replace("'", "'\\''") + "'\n")
        listing.flush()
        _run_ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", listing.name,
                     "-c:v", "copy", "-an", "-movflags", "+faststart", output])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _mux_audio(video_path: str, audio_path: str, tracks=None, duration=None, music_clips=None):
    # Some MP3s switch mono/stereo mid-file. FFmpeg then resets stateful filters
    # (apad/atrim/loudnorm), repeating padding or dropping samples. Decode first.
    with tempfile.TemporaryDirectory(prefix=".voice_", dir=os.path.dirname(video_path) or ".") as folder:
        pcm = os.path.join(folder, "voice.wav")
        _run_ffmpeg(["-y", "-i", audio_path, "-map", "0:a:0", "-vn", "-ar", "48000",
                     "-ac", "2", "-c:a", "pcm_s16le", pcm])
        if music_clips:
            paused=os.path.join(folder,'paused.wav')
            pause_narration(pcm,paused,music_clips);pcm=paused
        _mux_pcm_audio(video_path, pcm, tracks, duration)


def _mux_pcm_audio(video_path: str, audio_path: str, tracks=None, duration=None):
    tmp = video_path + ".mux.mp4"
    duration = duration or _probe_duration(video_path)
    # Keep the uploaded narration's samples/level; rebuild timestamps before padding.
    voice_filter = f"aresample=48000,asetpts=N/SR/TB,apad,atrim=duration={duration},asetpts=N/SR/TB"
    if not tracks:
        _run_ffmpeg([
            "-y", "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-af", voice_filter,
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp,
        ])
        os.replace(tmp, video_path)
        return
    inputs, parts, beds, extras = [], [], [], []
    parts.append(f"[1:a]{voice_filter},aformat=channel_layouts=stereo,asplit=2[voice][side]")
    for index, track in enumerate(tracks):
        path = track.get("_path") or asset_path(track["asset"], {"music", "ambience", "sfx"})
        category = "sfx" if track.get("_path") else track["asset"].split("/")[0]
        inputs.extend((["-stream_loop", "-1"] if category != "sfx" or track.get("loop") else []) + ["-i", str(path)])
        start, end = float(track.get("start", 0)), float(track.get("end", duration))
        span = min(end, duration) - start
        fade = min(float(track.get("fade", 1)), span / 2)
        target = -18 if track.get("_music_insert") else -25 if category == "music" else (-32 if category == "ambience" else -24)
        label = f"a{index}"
        level = "" if track.get("preserve_gain") else f"loudnorm=I={target}:TP=-2:LRA=7,"
        fades = f"afade=t=in:d={fade},afade=t=out:st={span-fade}:d={fade}," if fade else ""
        parts.append(f"[{index+2}:a]aresample=48000,aformat=channel_layouts=stereo,{level}atrim=start={float(track.get('_source_start',0))}:duration={span},asetpts=PTS-STARTPTS,volume={float(track.get('gain_db',0))}dB,{fades}adelay={round(start*1000)}:all=1[{label}]")
        (beds if category == "music" else extras).append(label)
    if beds:
        parts.append("".join(f"[{label}]" for label in beds)+f"amix=inputs={len(beds)}:normalize=0:duration=longest[music]")
        gaps=[t for t in tracks if t.get('_music_insert')]
        music_label='music'
        if gaps:
            condition='+'.join(f"between(t,{g['start']},{g['end']})" for g in gaps)
            parts.append(f"[music]volume=0:enable='{condition}'[music_gapped]")
            music_label='music_gapped'
        parts.append(f"[{music_label}][side]sidechaincompress=threshold=0.025:ratio=6:attack=15:release=350[duck]")
        extras.append("duck")
    else:
        parts.append("[side]anullsink")
    parts.append("[voice]"+"".join(f"[{label}]" for label in extras)+f"amix=inputs={1+len(extras)}:normalize=0:duration=longest,atrim=duration={duration},alimiter=limit=0.89:level=false:latency=true[mix]")
    _run_ffmpeg([
        "-y", "-i", video_path, "-i", audio_path, *inputs,
        "-filter_complex_threads", "2", "-filter_complex", ";".join(parts),
        "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", tmp,
    ])
    os.replace(tmp, video_path)

def _collect_files(downloads_dir: str, chunk_index: int, media_type: str) -> list[str]:
    if not os.path.isdir(downloads_dir):
        return []
    prefix = f"chunk{chunk_index:02d}_"
    ext = (".mp4", ".mov", ".webm") if media_type == "video" else (".jpg", ".jpeg", ".png", ".webp")
    return [
        os.path.join(downloads_dir, f)
        for f in sorted(os.listdir(downloads_dir))
        if f.startswith(prefix) and f.lower().endswith(ext)
    ]


def _filter_valid_files(files: list[str]) -> list[str]:
    valid = []
    for f in files:
        if not os.path.exists(f):
            continue
        try:
            if os.path.getsize(f) == 0:
                continue
            dimensions(f)
            valid.append(f)
        except Exception:
            pass
    return valid


def _probe_duration(path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _run_ffmpeg(args: list[str]):
    cmd = ["ffmpeg"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg ошибка:\n{result.stderr[-2000:]}")
