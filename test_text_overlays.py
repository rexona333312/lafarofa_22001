import io
import json
import array
import math
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import _sessions, app
from ffmpeg_builder import _mux_audio
from text_overlays import normalize_text_cues, text_sfx_tracks, render_text_scene
from retired_templates import REMOVED_TEXT


class TextOverlayTests(unittest.TestCase):
    def test_retired_text_is_skipped_without_sounds(self):
        raw = [{"id": f"T{i+1:03d}", "kind": "accent" if name.startswith('accent') else 'plain',
                "template": name, "start": 0, "end": 3, "text": "old text"}
               for i, name in enumerate(sorted(REMOVED_TEXT))]
        self.assertEqual(normalize_text_cues(raw, 3), [])
        self.assertEqual(text_sfx_tracks(raw), [])
        with patch('text_overlays.render_remotion') as render:
            self.assertFalse(render_text_scene('source.mp4', 'out.mp4', 0, 3, raw, 320, 180))
            render.assert_not_called()

    def test_retained_text_timing_and_normalization_are_idempotent(self):
        chunks = [{"start": 0, "end": 4.5}, {"start": 4.5, "end": 9.5}]
        cues = normalize_text_cues([
            {"id": "T001", "kind": "accent", "template": "marker_highlight", "text": "A fact", "chunk_index": 0},
            {"id": "T002", "kind": "accent", "template": "question_panel_top", "text": "A question?", "chunk_index": 1},
        ], 9.5, chunks)
        self.assertEqual([c['duration_frames'] for c in cues], [135, 150])
        self.assertEqual(normalize_text_cues(cues, 9.5, chunks), cues)
        tracks = text_sfx_tracks(cues)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]['asset'], 'sfx/marker_scribble.mp3')
        self.assertAlmostEqual(10 ** (tracks[0]['gain_db'] / 20), .3)

    def test_one_retained_cue_per_chunk(self):
        chunks = [{"start": 0, "end": 5}]
        with self.assertRaisesRegex(ValueError, 'одна текстовая вставка'):
            normalize_text_cues([
                {"id": "T001", "kind": "accent", "template": "marker_highlight", "text": "One", "start": 0, "end": 2},
                {"id": "T002", "kind": "accent", "template": "question_panel_top", "text": "Two", "start": 2, "end": 5}], 5, chunks)

    def test_retained_templates_cannot_request_deleted_capcut_path(self):
        with self.assertRaisesRegex(ValueError, 'только в Remotion'):
            normalize_text_cues([{"kind": "accent", "template": "marker_highlight", "renderer": "capcut",
                                  "text": "Fact", "start": 0, "end": 3}], 3)

    def test_retired_names_cannot_be_smuggled_back_through_default_plain(self):
        self.assertEqual(normalize_text_cues([{"kind": "plain", "text": "Old default", "start": 0, "end": 3}], 3), [])
        with self.assertRaises(ValueError):
            normalize_text_cues([{"kind": "accent", "template": [], "text": "Invalid", "start": 0, "end": 3}], 3)

    def test_import_removes_old_text_instead_of_requiring_external_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            name = 'scene_retired_text_import'
            _sessions[name] = {"scene_name": name, "scene_dir": folder, "chunks": [], "assets": {},
                "audio_duration": 4.5, "query_budget": 6, "busy": False, "cancel": threading.Event(), "file_overrides": {}}
            try:
                timeline = {"chunks": [{"type": "photo", "query": "archive portrait", "start": 0, "end": 4.5}],
                    "text_cues": [{"id": "T001", "renderer": "capcut", "kind": "accent", "template": "accent1", "text": "Old text", "chunk_index": 0}]}
                with patch('app.download_for_chunk', return_value=[]):
                    response = app.test_client().post('/import_timeline', data={'scene_name': name,
                        'timeline': (io.BytesIO(json.dumps(timeline).encode()), 'timeline.json')})
                    self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                self.assertEqual(_sessions[name]['text_cues'], [])
                self.assertEqual(app.test_client().get(f'/text_tasks/{name}').get_json()['tasks'], [])
            finally:
                _sessions.pop(name, None)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_capcut_sound_keeps_its_exported_gain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video, voice, sfx = (root / name for name in ("video.mp4", "voice.wav", "sfx.wav"))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=black:s=320x180:r=30:d=1", "-c:v", "libx264", str(video)], check=True)
            for path, freq, volume in ((voice, 440, "1"), (sfx, 880, "0.5")):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                f"sine=frequency={freq}:sample_rate=48000:duration=1", "-af", f"volume={volume}",
                                "-c:a", "pcm_s16le", str(path)], check=True)
            _mux_audio(str(video), str(voice), [{"_path": str(sfx), "start": 0, "end": 1,
                                                 "fade": 0, "preserve_gain": True}], 1)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0",
                                  "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"],
                                 check=True, capture_output=True).stdout
            samples = array.array("h")
            samples.frombytes(raw)
            first, last = 9600, 38400
            def amplitude(freq):
                return abs(2 * sum(samples[n] * math.sin(2 * math.pi * freq * n / 48000)
                                   for n in range(first, last)) / (last - first))
            self.assertAlmostEqual(amplitude(880) / amplitude(440), .5, delta=.05)


if __name__ == "__main__":
    unittest.main()
