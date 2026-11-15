import unittest
from pathlib import Path
from presets import validate_scene, REMOTION_SOUNDS, asset_path
from text_overlays import normalize_text_cues, text_sfx_tracks
from motion_timing import marker_window, timeline_scroll_frames


class EditorialTemplatesTest(unittest.TestCase):
    def test_marker_sound_matches_brush_window_and_original_gain(self):
        cues = normalize_text_cues([{"kind": "accent", "template": "marker_highlight", "text": "a key fact",
                                    "start": 1, "end": 4, "params": {"color": "#000000"}}], 5)
        cue = cues[0]
        self.assertEqual(normalize_text_cues(cues, 5), cues)
        self.assertEqual(cue["params"]["color"], "#ffffff")
        track = text_sfx_tracks(cues)[0]
        delay, sweep = marker_window(90)
        self.assertEqual(track["start"], 1 + delay / 30)
        self.assertAlmostEqual(track["end"], track["start"] + sweep / 30)
        self.assertAlmostEqual(10 ** (track["gain_db"] / 20), .3)
        self.assertTrue(track["preserve_gain"])
        self.assertTrue(asset_path(track["asset"]).is_file())

    def test_panels_sound_follows_entrance_and_requires_reading_time(self):
        for name in ("question_panel_top", "question_panel_bottom"):
            cue = {"kind": "accent", "template": name, "text": "why?", "start": 0, "end": 3}
            tracks = text_sfx_tracks(normalize_text_cues([cue], 3))
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0]['asset'], 'sfx/whoosh.mp3')
            self.assertEqual((tracks[0]['start'], tracks[0]['end']), (0, .7))
            with self.assertRaises(ValueError):
                normalize_text_cues([{**cue, "end": .6}], 3)
            with self.assertRaises(ValueError):
                normalize_text_cues([{**cue, "renderer": "capcut"}], 3)

    def test_timeline_rejects_malformed_date_and_video(self):
        scene = {"type": "photo", "template": "history_timeline", "duration": 7,
                 "params": {"year": 1918, "from_year": 1913, "label": "fishing trap"}}
        validate_scene(scene)
        for value in ("1918", True, -1, 10000):
            with self.assertRaises(ValueError):
                validate_scene({**scene, "params": {**scene["params"], "year": value}})
        with self.assertRaises(ValueError):
            validate_scene({**scene, "type": "video"})
        with self.assertRaises(ValueError):
            validate_scene({**scene, "duration": 2})
        with self.assertRaises(ValueError):
            validate_scene({**scene, "start": 0, "end": 2})
        self.assertEqual(timeline_scroll_frames(90, {"scroll_frames": 180}), 45)
        self.assertEqual(timeline_scroll_frames(210, {}), 72)

    def test_required_scrolling_asset_is_exact_user_file(self):
        self.assertEqual(REMOTION_SOUNDS["history_timeline"]["asset"], "sfx/scrolling.mp3")
        original = Path('/Users/ilia/Desktop/scrolling.MP3')
        if original.is_file():
            self.assertEqual(original.read_bytes(), asset_path('sfx/scrolling.mp3').read_bytes())

    def test_codex_receives_semantic_rules_and_template_names(self):
        from app import LUNA_INSTRUCTIONS
        for token in ('marker_highlight', 'question_panel_top', 'question_panel_bottom',
                      'history_timeline', 'params.from_year', 'Фотография остаётся целиком в рамке',
                      'sfx/scrolling.mp3', 'ключевых слов и фактов', 'противопоставлений'):
            self.assertIn(token, LUNA_INSTRUCTIONS)


if __name__ == '__main__':
    unittest.main()
