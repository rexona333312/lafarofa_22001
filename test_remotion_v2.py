"""Runnable V2 integration check; --preview DIR keeps the checked showcase."""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageChops, ImageStat
import ffmpeg_builder as builder
import text_overlays
from presets import REMOTION_TRANSITIONS, validate_scene, validate_tracks
from text_overlays import normalize_text_cues, require_text_exports, text_cache_key


def frame(path, at):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path),
                          "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                         capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(raw)).convert("RGB")


def probe(path):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,nb_frames,duration,start_time", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout)["streams"]


def check(root):
    root.mkdir(parents=True, exist_ok=True)
    motions = ["blur-in", "fade-in", "paper_card_top_right", "scale-in", "spring-in", "paper_card_bottom"]
    templates = ["marker_highlight", "question_panel_bottom", "question_panel_top", "marker_highlight", "question_panel_bottom"]
    dimensions = [(800, 450), (400, 650), (550, 550), (900, 350), (400, 600), (800, 450)]
    chunks = []
    for index, (motion, size) in enumerate(zip(motions, dimensions)):
        image = Image.new("RGB", size, "#208cc0")
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, size[0]-4, size[1]-4), outline="white", width=5)
        draw.text((size[0]//3, size[1]//2), motion, fill="white", font_size=24)
        path = root / f"photo{index}.png"
        image.save(path)
        chunks.append({"type": "photo", "query": "local test", "start": index * 2,
                       "end": (index+1) * 2, "template": motion, "params": {"paper": "paper/paper1.jpg"},
                       "_files": [str(path.resolve())]})
    raw = [{"id": f"T{index+1:03d}", "kind": "accent", "template": template,
            "text": ["Фокус на главном", "История начинается", "Шаг за шагом", "Новая версия", "Текст появляется"][index],
            "bottom_text": "Remotion V2" if index >= 3 else "", "start": index*2+.2, "end": index*2+1.8}
           for index, template in enumerate(templates)]
    cues = normalize_text_cues(raw, 12, chunks)
    assert normalize_text_cues(cues, 12, chunks) == cues
    assert all(row["status"] == "ready" for row in require_text_exports(root, cues))
    transitions = [{"kind": kind, "start": (index+1)*2-.3, "end": (index+1)*2+.3}
                   for index, kind in enumerate(REMOTION_TRANSITIONS)]
    transitions[-1]["params"] = {"direction": "from-right"}
    for chunk in chunks:
        validate_scene(chunk)
    validate_tracks({"transitions": transitions}, 12, chunks)
    for bad in ({"variant": "invalid"}, {"variant": []}, {"depth": -1}, {"direction": "left"}, {"blur": float("nan")}):
        try:
            validate_tracks({"transitions": [{**transitions[0], "params": bad}]}, 12, chunks)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid transition params: {bad}")
    voice = root / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=12", str(voice)], check=True)
    (root / "timeline.json").write_text(json.dumps({"chunks": chunks, "text_cues": raw,
        "transitions": transitions}, ensure_ascii=False, indent=2), encoding="utf-8")
    output, _ = builder.build_video(chunks, str(root), "remotion_v2", audio_path=str(voice),
        audio_duration=12, transitions=transitions, text_cues=cues, preview=True, progress_callback=lambda message: print(message, flush=True))
    streams = probe(output)
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    assert (video["width"], video["height"], int(video["nb_frames"])) == (960, 540, 360), video
    assert abs(float(video["duration"])-12) < .001
    assert any(stream["codec_type"] == "audio" for stream in streams)
    for path in root.glob(".render_cache/transition_*.mp4"):
        video = probe(path)[0]
        assert int(video["nb_frames"]) == 18, video
    windows = sorted(root.glob(".render_cache/transition_*.mp4"), key=lambda p: p.stat().st_mtime_ns)[-5:]
    cards = [max(root.glob(f".render_cache/chunk{i:03d}_*.mp4"), key=lambda p: p.stat().st_mtime_ns) for i in range(6)]
    for index, window in enumerate(windows):
        for at, source, source_at in ((0, cards[index], 1.7), (17/30, cards[index+1], 8/30)):
            difference = ImageChops.difference(frame(window, at), frame(source, source_at))
            assert max(ImageStat.Stat(difference).mean) < 4, f"Transition endpoint changed the image: {window}"
    # Card pixels must retain the source aspect ratio after the entrance settles.
    for index, size in enumerate(dimensions):
        source = max(root.glob(f".render_cache/chunk{index:03d}_*.mp4"), key=lambda p: p.stat().st_mtime_ns)
        image = frame(source, 1.2)
        pixels = image.load()
        coordinates = [(x, y) for y in range(image.height) for x in range(image.width)
                       if pixels[x, y][2] > 140 and pixels[x, y][1] > 85 and pixels[x, y][0] < 70]
        assert coordinates, f"Card missing: {motions[index]}"
        xs, ys = zip(*coordinates)
        ratio = (max(xs)-min(xs)+1)/(max(ys)-min(ys)+1)
        assert abs(ratio/(size[0]/size[1])-1) < .04, (motions[index], ratio, size)
    # A repeat must reuse cards, transitions and text. Text edits must invalidate the text cache.
    with patch.object(builder, "render_remotion", side_effect=AssertionError("Remotion cache missed")), \
         patch.object(text_overlays, "render_remotion", side_effect=AssertionError("Text cache missed")):
        builder.build_video(chunks, str(root), "remotion_v2", audio_path=str(voice), audio_duration=12,
                            transitions=transitions, text_cues=cues, preview=True)
    rows = require_text_exports(root, cues)
    source = next(root.glob(".render_cache/chunk000_*.mp4"))
    key = text_cache_key(source, [rows[0]], 960, 540)
    assert key != text_cache_key(source, [{**rows[0], "text": "Другой текст"}], 960, 540)
    print(f"OK: 4 motions, original paper cards, 5 text variants, 5 transitions, 360 frames, audio, cache. {output}", flush=True)
    return output


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        check(Path(sys.argv[2]).resolve())
    else:
        with tempfile.TemporaryDirectory() as folder:
            check(Path(folder))
