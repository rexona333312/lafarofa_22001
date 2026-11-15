import copy
import io
import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from presets import validate_scene, REMOTION_TEMPLATES
from reference_templates import REFERENCE_TEMPLATES, comparison_groups, motion_params, reference_sfx


class ReferenceTemplatesTest(unittest.TestCase):
    def pair(self):
        return [{'id': i, 'type': 'photo', 'start': i*1.5, 'end': (i+1)*1.5,
                 'template': 'paired_evidence', 'params': {'comparison_group': 'versions', 'label': f'version {i}'}}
                for i in range(2)]

    def test_retired_map_template_cannot_be_selected(self):
        self.assertNotIn('map_trace_camera', REMOTION_TEMPLATES)
        with self.assertRaises(ValueError):
            validate_scene({'type': 'photo', 'template': 'map_trace_camera', 'start': 0, 'end': 4, 'params': {}})

    def test_date_requires_explicit_year_and_never_invents_counter_start(self):
        scene = {'type': 'photo', 'template': 'date_countback', 'start': 0, 'end': 7, 'params': {'year': 1918}}
        validate_scene(scene)
        self.assertNotIn('from_year', motion_params('date_countback', scene['params'], 210))
        for params in ({}, {'year': True}, {'year': 1918, 'from_year': 1900}):
            with self.assertRaises(ValueError): validate_scene({**scene, 'params': params})

    def test_pair_requires_two_adjacent_queries_and_consistent_shared_motion(self):
        pair = self.pair()
        for c in pair: validate_scene(c)
        self.assertEqual(comparison_groups(pair), [[0,1]])
        for invalid in (pair[:1], pair*2, [pair[0], {'type': 'photo'}, pair[1]],
                        [pair[0], {**pair[1], 'params': {**pair[1]['params'], 'archival': True}}]):
            with self.assertRaises(ValueError): comparison_groups(invalid)
        invalid = copy.deepcopy(pair); invalid[1]['params']['arrival_frames'] = 20
        with self.assertRaises(ValueError): comparison_groups(invalid)

    def test_short_scenes_fit_but_explicit_oversized_windows_are_rejected(self):
        for template, params in [('chapter_heading', {'text':'chapter'}), ('editorial_statement', {'text':'source says'}),
                                 ('date_countback', {'year':1918})]:
            scene = {'type':'video', 'template':template, 'start':0, 'end':1, 'params':params}
            validate_scene(scene)
            for sfx in reference_sfx(template, params, 30):
                self.assertLessEqual(sfx['end_frame'], 30)
        with self.assertRaises(ValueError):
            motion_params('chapter_heading', {'underline_start':29, 'underline_frames':15}, 30)
        static_year = reference_sfx('date_countback', {'year':1918}, 210)
        self.assertEqual(static_year[0]['asset'], 'sfx/text3.mp3')

    def test_pair_builder_passes_both_photos_and_continues_motion_with_single_sfx(self):
        import ffmpeg_builder as builder
        with tempfile.TemporaryDirectory() as folder:
            photos = [Path(folder, f'{i}.jpg') for i in range(2)]
            for p in photos: Image.new('RGB', (64,64), '#555').save(p)
            chunks = self.pair()
            for c, p in zip(chunks, photos): c['_files'] = [str(p)]
            voice = Path(folder, 'voice.wav'); voice.write_bytes(b'mocked')
            def render(source, output, *args):
                Path(output).write_bytes(b'mocked mp4'); return [source]
            def concat(sources, output): Path(output).write_bytes(b'mocked concat')
            with patch.object(builder, '_render_remotion_template', side_effect=render) as renderer, \
                 patch.object(builder, '_concat_with_xfade', side_effect=concat), \
                 patch.object(builder, '_probe_duration', side_effect=lambda p: 3 if '.building.' in p else 1.5), \
                 patch.object(builder, '_mux_audio') as mixer:
                builder.build_video(chunks, folder, 'paired', audio_path=str(voice), audio_duration=3)
                for offset, call in zip((0,45), renderer.call_args_list):
                    comparison = call.args[-1]
                    self.assertEqual(comparison['frameOffset'], offset)
                    self.assertEqual(comparison['files'], list(map(str, photos)))
                tracks = mixer.call_args.args[2]
                self.assertEqual(len(tracks), 1)
                self.assertLessEqual(10**(tracks[0]['gain_db']/20), .3)
                self.assertLess(tracks[0]['end']-tracks[0]['start'], .8)
                self.assertLessEqual(tracks[0]['end'], 3)

    def test_import_export_includes_semantic_rules_and_rejects_broken_pair(self):
        import app as module
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'OUTPUT_DIR', folder):
            name = 'scene_reference_test'; scene = Path(folder, name); (scene/'downloads').mkdir(parents=True)
            (scene/'luna_input.json').write_text(json.dumps({'word_timestamps': []}))
            module._sessions[name] = {'scene_name':name, 'scene_dir':str(scene), 'audio_duration':3,
                                     'chunks':[], 'assets':{}, 'busy':False, 'cancel':threading.Event()}
            try:
                client = module.app.test_client()
                export = client.get(f'/timeline_input/{name}').get_json()
                self.assertTrue(set(REFERENCE_TEMPLATES) <= set(export['remotion_templates']))
                self.assertIn('Оба фото видны весь общий интервал', export['instructions'])
                self.assertIn('дату без предмета', export['instructions'])
                payload = {'chunks':[{**c, 'query':f'version {i}', 'search_mode':'broll'} for i,c in enumerate(self.pair())]}
                with patch.object(module, 'download_for_chunk', return_value=[]):
                    result = client.post('/import_timeline', data={'scene_name':name,
                        'timeline':(io.BytesIO(json.dumps(payload).encode()), 'timeline.json')})
                    self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
                self.assertEqual(comparison_groups(json.loads((scene/'timeline.json').read_text())['chunks']), [[0,1]])
                payload['chunks'][1]['params']['comparison_group'] = 'different'
                broken = client.post('/import_timeline', data={'scene_name':name,
                    'timeline':(io.BytesIO(json.dumps(payload).encode()), 'timeline.json')})
                self.assertEqual(broken.status_code, 400)
                self.assertIn('два последовательных', broken.get_json()['error'])
            finally: module._sessions.pop(name, None)


if __name__ == '__main__': unittest.main()
