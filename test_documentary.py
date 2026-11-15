"""Run: .venv/bin/python -m unittest test_documentary -v"""
import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app as editor
import stock_downloader as media
import vision_ranker as vision
from ffmpeg_builder import build_video, _mux_audio
from presets import graph_for_scene


class DocumentaryTests(unittest.TestCase):
    def test_shared_candidate_pool_can_choose_second_real_source(self):
        with tempfile.TemporaryDirectory() as folder:
            def fetch(name):
                def provider(query, *args, **kwargs):
                    file = Path(folder, name)
                    Image.new("RGB", (800, 450), "red" if name == "web.jpg" else "blue").save(file)
                    args[-1](name, {"source": name, "original_url": "https://example.org/"+name})
                    return [str(file)]
                return provider
            def choose(plan, files, assets):
                self.assertEqual({Path(file).name for file in files}, {"web.jpg", "archive.jpg"})
                self.assertEqual(set(assets), {"web.jpg", "archive.jpg"})
                return [file for file in files if file.endswith("archive.jpg")]
            with patch.object(media, "_fetch_reserp", side_effect=fetch("web.jpg")), \
                    patch.object(media, "_fetch_wikimedia", side_effect=fetch("archive.jpg")), \
                    patch.object(media, "_fetch_pexels") as stock:
                files = media.download_for_chunk({"type": "photo", "query": "Berlin", "entity": "Berlin",
                    "source_policy": ["editorial", "archive", "licensed_stock"]}, 0, folder,
                    reserp_mode=True, pool_sources=True, candidate_ranker=choose)
            self.assertEqual([Path(file).name for file in files], ["archive.jpg"])
            stock.assert_not_called()

    def test_mp3_channel_changes_do_not_reset_audio_padding_or_lose_voice(self):
        import array
        import math
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            def run(args):
                return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, check=True).stdout
            parts = []
            for index, channels in enumerate([1, 2, 1]):
                path = folder / f"{index}.mp3"
                run(["-f", "lavfi", "-i", f"sine=frequency={440+index*220}:duration=1.2", "-ac", str(channels),
                     "-c:a", "libmp3lame", "-write_xing", "0", str(path)])
                parts.append(path.read_bytes())
            voice = folder / "changing_channels.mp3"
            voice.write_bytes(b"".join(parts))
            movie = folder / "video.mp4"
            run(["-f", "lavfi", "-i", "color=navy:s=160x90:r=30:d=5", "-c:v", "libx264", str(movie)])
            _mux_audio(str(movie), str(voice), duration=5)
            def samples(path):
                values = array.array("f")
                values.frombytes(run(["-i", str(path), "-vn", "-ar", "8000", "-ac", "1", "-f", "f32le", "-"]))
                return values
            original, rendered = samples(voice), samples(movie)
            self.assertLess(abs(len(rendered)/8000 - 5), .03)
            # A format change can alter the resampler delay by a few milliseconds.
            # Check all three distinct tones with <=5 ms tolerance, well below one video frame.
            for start in (2400, 12800, 23200):
                a = original[start:start+2400]
                similarities = []
                for shift in range(-40, 41):
                    b = rendered[start+shift:start+shift+2400]
                    similarities.append(sum(x*y for x,y in zip(a,b)) /
                                        math.sqrt(sum(x*x for x in a)*sum(y*y for y in b)))
                self.assertGreater(max(similarities), .98)

    def test_word_ranges_cover_the_voice_without_estimated_timings(self):
        with tempfile.TemporaryDirectory() as folder:
            words = [{"word": "One", "start": .2, "end": .8}, {"word": "two", "start": 1.7, "end": 2.1}]
            Path(folder, "luna_input.json").write_text(json.dumps({"word_timestamps": words}))
            session = {"scene_dir": folder, "audio_duration": 2.5}
            chunks = editor._bind_shots_to_words([{"word_range": [0, 1]}, {"word_range": [1, 2]}], session)
            self.assertEqual([(c["start"], c["end"], c["text"]) for c in chunks], [(0, 1.7, "One"), (1.7, 2.5, "two")])
            with self.assertRaises(ValueError):
                editor._bind_shots_to_words([{"word_range": [0, 1]}], session)

    def test_medium_photo_is_accepted_and_partial_download_is_not_published(self):
        buffer = io.BytesIO()
        Image.new("RGB", (800, 450), "red").save(buffer, "JPEG")
        payload = buffer.getvalue()
        class Response:
            headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(payload))}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): return iter([payload])
            def close(self): pass
        with tempfile.TemporaryDirectory() as folder, patch.object(media.requests, "get", return_value=Response()):
            destination = Path(folder, "photo.jpg")
            self.assertTrue(media._download_file("https://example.org/photo", str(destination)))
            with Image.open(destination) as image:
                self.assertEqual(image.size, (800, 450))
            original = destination.read_bytes()
            Response.headers["Content-Length"] = str(len(payload)+1)
            self.assertFalse(media._download_file("https://example.org/photo", str(destination)))
            self.assertEqual(destination.read_bytes(), original)
            self.assertFalse(Path(str(destination)+".part").exists())

    def test_replace_one_shot_preserves_other_candidates_and_saved_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(editor, "OUTPUT_DIR", folder):
            name = "scene_documentary_test"
            path = Path(folder, name); (path/"downloads").mkdir(parents=True)
            editor._sessions[name] = {"scene_name": name, "scene_dir": str(path), "audio_duration": 4,
                                     "chunks": [], "assets": {}, "busy": False, "cancel": threading.Event()}
            timeline = {"chunks": [{"type": "photo", "query": query, "search_mode": "broll", "start": n*2, "end": n*2+2}
                                   for n, query in enumerate(["Berlin parliament", "German chancellery"])]}
            def download(plan, index, directory, **kwargs):
                file = Path(directory, "downloads", f"chunk{index:02d}_{kwargs['file_offset']}.jpg")
                Image.new("RGB", (800, 450), "red").save(file)
                kwargs["asset_callback"](file.name, {"source": "Test", "original_url": "https://example.org/"+file.name})
                return [str(file)]
            try:
                with patch.object(editor, "download_for_chunk", side_effect=download) as fetch, patch.object(editor, "build_video") as render:
                    client = editor.app.test_client()
                    response = client.post("/import_timeline", data={"scene_name": name, "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json")})
                    self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                    render.assert_not_called()
                    first = editor._sessions[name]["chunks"][0]["files"][:]
                    saved = client.post("/select_media", json={"scene_name": name, "chunk_id": 0, "files": first})
                    self.assertEqual(saved.status_code, 200)
                    fetch.reset_mock()
                    response = client.post("/resume_search", json={"scene_name": name, "chunk_id": 1})
                    self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                    self.assertEqual([call.args[1] for call in fetch.call_args_list], [1])
                    self.assertEqual(editor._sessions[name]["chunks"][0]["files"], first)
                    disk = json.loads((path/"project.json").read_text())
                    self.assertEqual(disk["file_overrides"]["0"], first)
                    self.assertEqual(client.post("/select_media", json={"scene_name": name, "chunk_id": 0, "files": ["../voice.mp3"]}).status_code, 400)
            finally:
                editor._sessions.pop(name, None)

    def test_low_resolution_render_has_blur_zoom_default_cuts_and_full_hd(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder, "small.jpg")
            Image.new("RGB", (800, 450), "navy").save(photo)
            chunks = [{"type": "photo", "start": n, "end": n+1, "_files": [str(photo)]} for n in range(2)]
            _, graph, _ = graph_for_scene([str(photo)], chunks[0], 1, 1920, 1080, 30)
            self.assertIn("gblur", graph)
            self.assertIn("zoompan", graph)
            self.assertIn("cos(PI*on/", graph)
            output, _ = build_video(chunks, folder, "check", preview=False)
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_frames", "-of", "json", output]))["streams"][0]
            self.assertEqual((info["width"], info["height"], int(info["nb_frames"])), (1920, 1080, 60))
            self.assertEqual(json.loads(Path(folder, "render_report.json").read_text())["builtin_transitions"], [])

    def test_daily_quota_is_not_retried_as_a_minute_limit(self):
        class Response:
            status_code = 429
            def json(self):
                return {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
        with patch.object(vision, "_DAILY_QUOTA_EXHAUSTED", False), patch.object(vision, "GEMINI_API_KEY", "configured"), patch.object(vision, "VISION_PROVIDER", "gemini"):
            with self.assertRaisesRegex(RuntimeError, "Суточная квота"):
                vision._check_daily_quota(Response())
            self.assertFalse(vision.is_available())


if __name__ == "__main__":
    unittest.main()
