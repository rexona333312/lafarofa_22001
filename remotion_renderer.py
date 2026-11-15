"""Shared local Remotion runner for cards, text and transition windows."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REMOTION_PROJECT = Path(__file__).resolve().parent / "assets/remotion/paper_card"


def remotion_source_hash():
    paths = [REMOTION_PROJECT / "render.mjs", REMOTION_PROJECT / "package-lock.json",
             REMOTION_PROJECT / "tsconfig.json", REMOTION_PROJECT / "remotion.config.js",
             *sorted((REMOTION_PROJECT / "src").rglob("*")),
             *sorted((REMOTION_PROJECT / "public/fonts").rglob("*"))]
    digest = hashlib.sha256()
    digest.update(Path(__file__).read_bytes())
    for path in paths:
        if path.is_file():
            digest.update(str(path.relative_to(REMOTION_PROJECT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def render_remotion(composition, output, frames, width, height, props, media):
    if not shutil.which("node") or not (REMOTION_PROJECT / "node_modules/.bin/remotion").is_file():
        raise ValueError("Для Remotion установите Node.js и выполните npm ci в assets/remotion/paper_card")
    with tempfile.TemporaryDirectory(prefix=".remotion_", dir=Path(output).parent) as folder:
        job = Path(folder) / "job.json"
        rendered = Path(folder) / "rendered.mp4"
        supersample = 2 if composition == "PhotoCamera" or (composition == "PaperCard" and props.get("from") in {"top-right", "top-left", "bottom-right", "bottom-left", "top", "bottom", "left", "right"}) else 1
        job.write_text(json.dumps({"composition": composition, "output": str(rendered.resolve()),
                                   "frames": frames, "width": width * supersample, "height": height * supersample,
                                   "props": props, "media": {key: str(Path(path).resolve()) for key, path in media.items()}},
                                  ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(["node", str(REMOTION_PROJECT / "render.mjs"), "--job", str(job.resolve())],
                                capture_output=True, text=True, errors="replace", timeout=3600)
        if result.returncode:
            raise RuntimeError(f"Remotion не смог собрать {composition}: {(result.stderr or result.stdout)[-2500:]}")
        # Match FFmpeg's 30-fps MP4 time base; concat-copy cannot mix it with Remotion's 1/90000.
        encoding = (["-vf", f"scale={width}:{height}:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
                    if supersample > 1 else ["-c:v", "copy"])
        result = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(rendered), "-map", "0:v:0",
                                 *encoding, "-an", "-video_track_timescale", "15360",
                                 "-movflags", "+faststart", str(output)], capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise RuntimeError(f"Не удалось подготовить Remotion-клип: {result.stderr[-2000:]}")
