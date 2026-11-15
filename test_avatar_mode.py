import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app as web
from avatar_templates import AVATAR_TEMPLATES, planner_payload, timeline_summary
from presets import REMOTION_TEMPLATES, validate_scene
from ffmpeg_builder import _render_remotion_template, _render_preset


class AvatarModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.name = 'scene_avatar_test'
        self.folder = self.root / self.name
        (self.folder / 'downloads').mkdir(parents=True)
        (self.folder / 'voice.wav').touch()
        self.session = {'scene_name': self.name, 'scene_dir': str(self.folder), 'chunks': [], 'assets': {},
                        'video_mode': 'ai_avatar', 'avatar_library': [], 'busy': False, 'cancel': threading.Event(),
                        'audio_path': str(self.folder / 'voice.wav'), 'audio_duration': 6, 'language': 'en'}
        web._sessions[self.name] = self.session
        self.output_patch = patch('app.OUTPUT_DIR', str(self.root))
        self.output_patch.start()
        self.client = web.app.test_client()

    def tearDown(self):
        web._sessions.pop(self.name, None)
        self.output_patch.stop()
        self.temp.cleanup()

    def chunk(self, template='avatar_full', **extra):
        return {'id': 0, 'type': 'video' if template == 'avatar_full' else 'photo', 'query': 'presenter',
                'search_mode': 'broll', 'start': 0, 'end': 3, 'duration': 3, 'text': 'test',
                'files': [], 'template': template, 'avatar': {'clip_id': 'auto'}, **extra}

    def library(self, count=3, duration=10):
        for i in range(count):
            name = f'avatar_{i}.mp4'
            (self.folder / 'downloads' / name).touch()
            self.session['avatar_library'].append({'id': f'avatar_{i}', 'filename': name,
                                                   'label': name, 'duration': duration, 'width': 640, 'height': 360})

    def test_registered_variants_and_bad_intervals(self):
        for template in AVATAR_TEMPLATES:
            validate_scene(self.chunk(template))
            self.assertIn(template, REMOTION_TEMPLATES)
            for invalid in ({'source_start': True}, {'source_start': -1}, {'source_start': float('nan')},
                            {'clip_id': '../voice'}, {'clip_id': []}, {'muted': False}):
                with self.subTest(template=template, invalid=invalid), self.assertRaises(ValueError):
                    validate_scene(self.chunk(template, avatar=invalid))
        with self.assertRaises(ValueError):
            validate_scene(self.chunk('avatar_full', type='photo'))
        with self.assertRaises(ValueError):
            validate_scene(self.chunk('avatar_left', params={'avatar_width': .95}))
        with self.assertRaises(ValueError):
            validate_scene(self.chunk('avatar_left', media_origin='ai_image'))

    def test_library_rotation_offsets_and_fullscreen_resolution(self):
        self.library()
        self.session['chunks'] = [self.chunk(id=i, start=i*3, end=(i+1)*3) for i in range(6)]
        built = web._prepare_build_chunks(self.session)
        self.assertEqual([c['_avatar_clip_id'] for c in built], ['avatar_0','avatar_1','avatar_2'] * 2)
        self.assertEqual([c['_avatar_source_start'] for c in built[:3]], [0,.5,1])
        self.assertEqual(built[0]['_files'], [str((self.folder / 'downloads/avatar_0.mp4').resolve())])
        self.assertEqual(web._prepare_build_chunks(self.session), built)

    def test_explicit_source_and_overrun_are_checked_before_render(self):
        self.library(1, 5)
        self.session['chunks'] = [self.chunk(avatar={'clip_id':'avatar_0','source_start':2})]
        self.assertEqual(web._prepare_build_chunks(self.session)[0]['_avatar_source_start'], 2)
        self.session['chunks'][0]['avatar']['source_start'] = 2.1
        with self.assertRaisesRegex(ValueError, 'нет подходящего клипа'):
            web._prepare_build_chunks(self.session)
        self.session['avatar_library'][0]['filename'] = '../voice.wav'
        with self.assertRaises(ValueError):
            web._prepare_build_chunks(self.session)

    def test_panel_preserves_background_and_checks_video_length(self):
        self.library(1)
        (self.folder/'downloads/photo.jpg').touch()
        self.session['chunks'] = [self.chunk('avatar_right', files=['photo.jpg'])]
        built = web._prepare_build_chunks(self.session)[0]
        self.assertEqual(built['_files'], [str(self.folder/'downloads/photo.jpg')])
        self.session['chunks'][0]['type'] = 'video'
        with patch('avatar_templates.probe_video', return_value={'duration':2}), self.assertRaisesRegex(ValueError, 'фоновое видео'):
            web._prepare_build_chunks(self.session)

    def test_exports_separate_faceless_and_avatar_instructions(self):
        (self.folder/'luna_input.json').write_text(json.dumps({'word_timestamps':[], 'instructions':'old real-only'}))
        with patch('app.library_catalog', return_value=[]):
            payload = self.client.get(f'/timeline_input/{self.name}').get_json()
        self.assertEqual(payload['video_mode'], 'ai_avatar')
        self.assertEqual(payload['avatar_editorial_rules']['status'], 'CONNECTED_TO_AI_AVATAR_PLANNING_EXPORT')
        self.assertIn('ai_prompt', payload['instructions'])
        self.assertNotIn('old real-only', payload['instructions'])
        face = planner_payload({'video_mode':'faceless'}, web.LUNA_INSTRUCTIONS, REMOTION_TEMPLATES)
        self.assertFalse(set(AVATAR_TEMPLATES) & set(face['remotion_templates']))
        self.assertEqual(face['instructions'], web.LUNA_INSTRUCTIONS)

    def test_library_upload_is_atomic_and_persists_with_project(self):
        with patch('app.probe_video', side_effect=[{'duration':10,'width':640,'height':360}, ValueError('bad')]):
            response = self.client.post('/upload_avatar', data={'scene_name':self.name, 'avatars':[
                (io.BytesIO(b'first'), 'one.mp4'), (io.BytesIO(b'bad'), 'two.mp4')]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session['avatar_library'], [])
        self.assertEqual(list((self.folder/'downloads').iterdir()), [])
        with patch('app.probe_video', return_value={'duration':10,'width':640,'height':360}):
            response = self.client.post('/upload_avatar', data={'scene_name':self.name,'avatars':(io.BytesIO(b'video'),'one.mp4')})
        self.assertEqual(response.status_code, 200)
        web._sessions.pop(self.name)
        restored = self.client.get(f'/project/{self.name}').get_json()
        self.assertEqual(restored['video_mode'], 'ai_avatar')
        self.assertEqual(restored['avatar_library'][0]['duration'], 10)

    def test_import_skips_search_for_full_avatar_and_manual_ai_images(self):
        chunks = [self.chunk(), self.chunk('avatar_left', id=1, start=3, end=6,
                    media_origin='ai_image', ai_prompt='A device on a desk, visible controls.')]
        with patch('app.download_for_chunk') as search, patch('app.library_catalog', return_value=[]):
            response = self.client.post('/import_timeline', data={'scene_name':self.name,
                'timeline':(io.BytesIO(json.dumps({'video_mode':'ai_avatar','chunks':chunks}).encode()),'timeline.json')}, buffered=True)
        self.assertEqual(response.status_code, 200, response.data.decode())
        self.assertIn('downloads_done', response.data.decode())
        search.assert_not_called()
        timeline = json.loads((self.folder/'timeline.json').read_text())
        self.assertEqual(timeline['video_mode'], 'ai_avatar')
        self.assertEqual(timeline['chunks'][1]['ai_prompt'], chunks[1]['ai_prompt'])
        prompts = self.client.get(f'/ai_prompts/{self.name}').get_json()['images']
        self.assertEqual(prompts[0]['chunk_id'], 1)
        self.assertEqual(prompts[0]['asset_id'], 'ai_0001')
        self.assertEqual(self.client.post('/assemble', json={'scene_name':self.name}).status_code, 400)

    def test_faceless_rejects_avatar_import_and_mode_change_with_avatar_scenes(self):
        response = self.client.post('/import_timeline', data={'scene_name':self.name,
            'timeline':(io.BytesIO(json.dumps({'video_mode':'faceless','chunks':[self.chunk(end=6,duration=6)]}).encode()),'timeline.json')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session['video_mode'], 'ai_avatar')
        self.session['chunks'] = [self.chunk()]
        response = self.client.post('/video_mode', json={'scene_name':self.name,'video_mode':'faceless'})
        self.assertEqual(response.status_code, 400)

    def test_render_receives_both_sources_and_offset_without_default_sound(self):
        self.library(1)
        (self.folder/'downloads/photo.jpg').touch()
        self.session['chunks'] = [self.chunk('avatar_left',files=['photo.jpg'],avatar={'clip_id':'auto','source_start':2})]
        c = web._prepare_build_chunks(self.session)[0]
        with patch('ffmpeg_builder.render_remotion') as render, patch('ffmpeg_builder._render_preset',
                  side_effect=lambda files, output, duration, scene, *args: validate_scene(scene)):
            _render_remotion_template(c['_files'][0],str(self.folder/'out.mp4'),3,c,960,540,[],None,None)
        args = render.call_args.args
        self.assertEqual(args[0], 'AvatarScene')
        self.assertEqual(args[5]['avatarStart'], 2)
        self.assertEqual(args[5]['placement'], 'left')
        self.assertEqual(args[6]['avatar'], c['_avatar_file'])
        self.assertEqual(args[6]['picture'], c['_files'][0])

    def test_generated_photo_uses_ffmpeg_without_losing_ai_metadata(self):
        from PIL import Image
        photo = self.folder/'downloads/ai.jpg'
        Image.new('RGB',(800,450),'blue').save(photo)
        scene = {'type':'photo','preset':'PHOTO_SLOW_ZOOM','media_origin':'ai_image','ai_prompt':'A blue object.'}
        validate_scene(scene)
        with patch('ffmpeg_builder.render_remotion',side_effect=AssertionError('AI photo must use FFmpeg')):
            self.assertEqual(_render_preset([str(photo)],str(self.folder/'out.mp4'),.5,scene,320,180), [str(photo)])
        self.assertEqual(scene['media_origin'],'ai_image')

    def test_ratio_counts_panel_background_once_and_excludes_full_avatar(self):
        rows = [self.chunk(), self.chunk('avatar_left',media_origin='ai_image',ai_prompt='example'),
                {'type':'photo','duration':3,'media_origin':'real'}]
        mix = timeline_summary(rows)
        self.assertEqual(mix['background_ai_percent'], 50)
        self.assertAlmostEqual(mix['avatar_percent'], 100*6/9)


if __name__ == '__main__':
    unittest.main()
