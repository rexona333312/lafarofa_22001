import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from narrative_templates import carousel_groups, map_annotation_frames
from presets import validate_scene
from text_overlays import normalize_text_cues, text_sfx_tracks


class NarrativeTemplatesTest(unittest.TestCase):
    def setUp(self):
        self.words = [{"word": "a", "start": .2, "end": .4}, {"word": "new", "start": .7, "end": 1},
                      {"word": "policy", "start": 1.5, "end": 2}]
        self.chunk = {"id": 0, "type": "photo", "start": 0, "end": 4, "duration": 4}

    def test_impact_exact_speech_times_holds_until_cut_and_sfx_skips_pauses(self):
        cue = normalize_text_cues([{"kind": "accent", "template": "impact_typewriter", "text": "A NEW POLICY",
                                    "start": 0, "end": 2.1, "word_range": [0, 3]}], 4, [self.chunk], self.words)[0]
        self.assertEqual(cue["end"], 4)
        self.assertEqual([w["start_frame"] for w in cue["speech_words"]], [6, 21, 45])
        self.assertEqual(normalize_text_cues([cue], 4, [self.chunk]), [cue])
        tracks = text_sfx_tracks([cue])
        self.assertEqual([(t["start"], t["end"]) for t in tracks], [(.2, .4), (.7, 1), (1.5, 2)])
        for track in tracks:
            self.assertAlmostEqual(10 ** (track["gain_db"] / 20), .3)

    def test_word_by_word_requires_matching_real_words(self):
        for template in ("speech_words_grid", "speech_words_overlay"):
            raw = {"kind": "accent", "template": template, "text": "a new policy", "chunk_index": 0}
            cue = normalize_text_cues([raw], 4, [self.chunk], self.words)[0]
            self.assertEqual(cue["speech_words"][-1]["end_frame"], 60)
            sounds = text_sfx_tracks([cue])
            self.assertEqual(len(sounds), 1)
            self.assertEqual(sounds[0]['start'], .2)
            self.assertEqual(sounds[0]['asset'], 'sfx/text3.mp3')
            with self.assertRaises(ValueError):
                normalize_text_cues([{**raw, "text": "a better policy", "word_range": [0, 3]}], 4, [self.chunk], self.words)
            with self.assertRaises(ValueError):
                normalize_text_cues([raw], 4, [self.chunk])

    def test_selective_marker_one_sound_for_all_highlights(self):
        raw = {"kind": "accent", "template": "selective_marker", "text": "more power smaller chips faster connections",
               "start": 0, "end": 4, "params": {"highlight_ranges": [[0, 2], [2, 4], [4, 6]]}}
        cue = normalize_text_cues([raw], 4)[0]
        self.assertEqual(len(text_sfx_tracks([cue])), 1)
        self.assertEqual(cue["params"]["color"], "#ffffff")
        for ranges in ([[0, 3], [2, 4]], [[0, 9]], [[True, 2]], []):
            with self.assertRaises(ValueError):
                normalize_text_cues([{**raw, "params": {"highlight_ranges": ranges}}], 4)

    def test_carousel_groups_are_contiguous_two_to_five_and_same_style(self):
        chunks = [{"type": "photo", "template": "photo_carousel_dark", "start": i*2, "end": (i+1)*2,
                   "params": {"carousel_group": "chips", "archival": False}} for i in range(3)]
        for chunk in chunks:
            validate_scene(chunk)
        self.assertEqual(carousel_groups(chunks), [[0, 1, 2]])
        for invalid in (chunks[:1], chunks*2, [chunks[0], {"type": "photo"}, chunks[2]],
                        [chunks[0], {**chunks[1], "template": "photo_carousel_film"}]):
            with self.assertRaises(ValueError):
                carousel_groups(invalid)
        with self.assertRaises(ValueError):
            validate_scene({**chunks[0], "type": "video"})

    def test_maps_sequential_annotations_and_bounded_geometry(self):
        params = {"annotations": [
            {"kind": "route", "points": [[.2, .7], [.7, .4]], "label": "route"},
            {"kind": "boundary", "points": [[.5, .2], [.5, .8]], "label": "boundary"},
            {"kind": "region", "points": [[.6, .3], [.8, .3], [.8, .6]], "label": "region"},
            {"kind": "point", "points": [[.7, .5]], "label": "hub"}]}
        frames = map_annotation_frames(params, 240)
        self.assertEqual([a["start_frame"] for a in frames], [0, 30, 60, 90])
        for changes in ({"points": [[2, .5]]}, {"start_frame": -1}, {"draw_frames": 300}):
            with self.assertRaises(ValueError):
                map_annotation_frames({"annotations": [{**params["annotations"][0], **changes}]}, 240)
        with self.assertRaises(ValueError):
            map_annotation_frames(params, 60)

    def test_carousel_build_preparation_keeps_one_selected_photo_per_semantic_chunk(self):
        import app as module
        with tempfile.TemporaryDirectory() as folder:
            downloads = Path(folder, 'downloads'); downloads.mkdir()
            chunks = []
            for i in range(3):
                name = f'card{i}.jpg'; (downloads/name).write_bytes(b'fixture')
                chunks.append({'id': i, 'files': [name], 'type': 'photo', 'query': f'item{i}', 'duration': 2,
                               'start': i*2, 'end': (i+1)*2, 'template': 'photo_carousel_paper',
                               'params': {'carousel_group': 'group'}})
            session = {'chunks': chunks, 'assets': {}, 'scene_dir': folder, 'language': 'en'}
            prepared = module._prepare_build_chunks(session)
            self.assertEqual(len(carousel_groups(prepared)), 1)
            self.assertEqual([Path(c['_files'][0]).name for c in prepared], ['card0.jpg', 'card1.jpg', 'card2.jpg'])

    def test_import_uses_saved_whisperx_times_and_exports_new_templates(self):
        import app as module
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'OUTPUT_DIR', folder):
            name = 'scene_narrative_import_test'
            scene = Path(folder, name); (scene/'downloads').mkdir(parents=True)
            (scene/'luna_input.json').write_text(json.dumps({'word_timestamps': self.words}), encoding='utf-8')
            module._sessions[name] = {'scene_name': name, 'scene_dir': str(scene), 'audio_duration': 4,
                                     'chunks': [], 'assets': {}, 'busy': False, 'cancel': threading.Event()}
            payload = {'chunks': [{**self.chunk, 'query': 'government policy', 'search_mode': 'broll'}],
                       'text_cues': [{'kind': 'accent', 'template': 'impact_typewriter',
                                      'text': 'a new policy', 'chunk_index': 0, 'word_range': [0, 3]}]}
            try:
                client = module.app.test_client()
                self.assertEqual(client.get('/').status_code, 200)
                with patch.object(module, 'download_for_chunk', return_value=[]), patch.object(module, 'build_video') as render:
                    response = client.post('/import_timeline', data={'scene_name': name,
                        'timeline': (io.BytesIO(json.dumps(payload).encode()), 'timeline.json')})
                    self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                    self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                    render.assert_not_called()
                saved = json.loads((scene/'timeline.json').read_text())['text_cues'][0]
                self.assertEqual([word['start_frame'] for word in saved['speech_words']], [6, 21, 45])
                exported = client.get(f'/timeline_input/{name}').get_json()
                self.assertIn('map_annotations', exported['remotion_templates'])
                self.assertIn('photo_carousel_film', exported['remotion_templates'])
                self.assertIn('impact_typewriter', exported['text_templates'])
                self.assertIn('selective_marker', exported['instructions'])
                (scene/'luna_input.json').unlink()
                missing = client.post('/import_timeline', data={'scene_name': name,
                    'timeline': (io.BytesIO(json.dumps(payload).encode()), 'timeline.json')})
                self.assertEqual(missing.status_code, 400)
                self.assertIn('WhisperX', missing.get_json()['error'])
            finally:
                module._sessions.pop(name, None)


if __name__ == '__main__':
    unittest.main()
