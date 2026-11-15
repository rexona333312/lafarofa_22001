"""Render a real Trump portrait through the full three-variant assembly pipeline."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image

from config import OUTPUT_DIR
import ffmpeg_builder as builder

ROOT = Path(__file__).resolve().parent
NAME = "scene_person_intro_trump"
PORTRAIT_URL = "https://upload.wikimedia.org/wikipedia/commons/5/52/President-Donald-Trump-Official-Presidential-Portrait.png"
BACKGROUND_URL = "https://upload.wikimedia.org/wikipedia/commons/4/4d/The_White_House_South_Portico.jpg"


def download(url, path):
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, headers={"User-Agent": "VideoAssembler/1.0 (local character template demonstration)"}, timeout=60)
    response.raise_for_status()
    staging = path.with_suffix(".download" + path.suffix)
    staging.write_bytes(response.content)
    with Image.open(staging) as image:
        image.verify()
    staging.replace(path)


def main():
    folder = Path(OUTPUT_DIR, NAME)
    portrait = folder / "downloads/trump.png"
    background = ROOT / "assets/backgrounds/white_house.jpg"
    download(PORTRAIT_URL, portrait)
    download(BACKGROUND_URL, background)
    sources = {
        "portrait": {"url": PORTRAIT_URL, "page": "https://commons.wikimedia.org/wiki/File:President-Donald-Trump-Official-Presidential-Portrait.png",
                     "author": "Daniel Torok / White House", "license": "Public domain (US federal government)"},
        "background": {"url": BACKGROUND_URL, "page": "https://commons.wikimedia.org/wiki/File:The_White_House_South_Portico.jpg",
                       "author": "Trendscope / Simon Gagner", "license": "CC BY 4.0",
                       "license_url": "https://creativecommons.org/licenses/by/4.0/",
                       "modifications": "Crop to 16:9, grayscale, darkening, blur, animated scaling"}
    }
    background.with_suffix(".jpg.json").write_text(json.dumps({"description": "White House — фон для политических персонажей",
        **sources["background"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    timeline = json.loads((ROOT / "examples/timeline_person_intro.json").read_text())
    for index, chunk in enumerate(timeline["chunks"]):
        chunk.update({"id": index, "duration": 5, "files": [portrait.name], "_chunk_id": index,
                      "_files": [str(portrait)], "credits": {portrait.name: "Background: Trendscope / Simon Gagner · CC BY 4.0"}})
        chunk["params"]["background"] = "backgrounds/white_house.jpg"
    voice = folder / "voice.wav"
    if not voice.is_file():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "15", str(voice)], check=True)
    # All three appearances use the same subtle SFX so placement is the only changing variable.
    with patch.object(builder, "_template_whoosh", return_value=ROOT / "assets/sfx/whoosh.mp3"):
        output, used = builder.build_video(timeline["chunks"], str(folder), NAME, audio_path=str(voice),
            audio_duration=15, transitions=timeline["transitions"], progress_callback=lambda msg: print(msg, flush=True))
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,avg_frame_rate,nb_frames,duration", "-of", "json", output],
        check=True, capture_output=True, text=True).stdout)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["avg_frame_rate"], int(video["nb_frames"])) == (1920, 1080, "30/1", 450), video
    assert abs(float(video["duration"]) - 15) < .001, video
    assert any(stream["codec_type"] == "audio" for stream in streams), streams
    clean_chunks = [{key: value for key, value in chunk.items() if not key.startswith("_")} for chunk in timeline["chunks"]]
    (folder / "timeline.json").write_text(json.dumps({**timeline, "chunks": clean_chunks}, ensure_ascii=False, indent=2), encoding="utf-8")
    assets = {portrait.name: {"source": "Wikimedia Commons", "source_url": sources["portrait"]["page"],
        "author": sources["portrait"]["author"], "license": sources["portrait"]["license"], "user_supplied": True}}
    (folder / "assets.json").write_text(json.dumps(assets, indent=2), encoding="utf-8")
    (folder / "project.json").write_text(json.dumps({"scene_name": NAME, "scene_dir": str(folder),
        "audio_path": str(voice), "audio_duration": 15, "language": "en", "chunks": clean_chunks,
        "assets": assets, "file_overrides": {str(k): v for k, v in used.items()}, "downloads_complete": True,
        "transitions": timeline["transitions"], "text_cues": [], "audio_tracks": [], "processing_mode": "fast"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    frames = []
    for index, side in enumerate(("left", "center", "right")):
        image = folder / f"{side}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(index * 5 + 2.5), "-i", output,
                        "-frames:v", "1", str(image)], check=True)
        with Image.open(image) as picture:
            frames.append(picture.resize((640, 360)))
    sheet = Image.new("RGB", (1920, 360))
    for index, frame in enumerate(frames):
        sheet.paste(frame, (index * 640, 0))
    sheet.save(folder / "three_variants.jpg")
    print(f"READY: {output}", flush=True)


if __name__ == "__main__":
    main()
