import io
import json
import struct
import subprocess
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import app as web
from avatar_templates import avatar_interval, avatar_tasks, planner_payload, validate_dreamina_chunks, probe_video
from presets import REMOTION_TEMPLATES
from whisperx_transcriber import LANGUAGES


class DreaminaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.name = 'scene_dreamina_test'
        self.folder = self.root / self.name
        (self.folder / 'downloads').mkdir(parents=True)
        self.audio = b''.join(struct.pack('<h', (i % 20001) - 10000) for i in range(6 * 48000))
        with wave.open(str(self.folder / 'voice.wav'), 'wb') as audio:
            audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            audio.writeframes(self.audio)
        self.chunks = [self.chunk(0, 0, 2), self.chunk(1, 2, 4, avatar=False), self.chunk(2, 4, 6)]
        self.session = {'scene_name': self.name, 'scene_dir': str(self.folder), 'chunks': self.chunks,
                        'assets': {}, 'video_mode': 'ai_avatar', 'avatar_workflow': 'dreamina',
                        'avatar_assignments': {}, 'avatar_library': [], 'busy': False,
                        'cancel': threading.Event(), 'audio_path': str(self.folder / 'voice.wav'),
                        'audio_duration': 6, 'language': 'cs'}
        self.words = [{'word': 'Ahoj', 'start': .1, 'end': .8}, {'word': 'světe', 'start': 1, 'end': 1.8}]
        (self.folder / 'luna_input.json').write_text(json.dumps({'word_timestamps': self.words, 'language': 'cs'}))
        web._sessions[self.name] = self.session
        self.output_patch = patch('app.OUTPUT_DIR', str(self.root))
        self.output_patch.start()
        self.client = web.app.test_client()

    def tearDown(self):
        web._sessions.pop(self.name, None)
        self.output_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def chunk(index, start, end, avatar=True):
        row = {'id': index, 'type': 'video' if avatar else 'photo', 'query': 'presenter' if avatar else 'photo',
               'search_mode': 'broll', 'start': start, 'end': end, 'duration': end-start,
               'text': f'Česká věta {index}', 'files': []}
        if avatar:
            row.update(template='avatar_full', avatar={'clip_id': 'auto'})
        else:
            row.update(media_origin='ai_image', ai_prompt='A device on a desk.')
        return row

    def upload(self, cid=0, duration=2, offset=0):
        def zoom(path, info):
            output = Path(path).with_suffix('.zoom.mp4')
            Path(path).rename(output)
            return output, info
        with patch('app.probe_video', return_value={'duration': duration, 'width': 320, 'height': 180}), \
                patch('app.zoom_avatar_video', side_effect=zoom):
            return self.client.post('/avatar_clip', data={'scene_name': self.name, 'chunk_id': str(cid),
                                    'source_start': str(offset), 'video': (io.BytesIO(b'video'), 'avatar.mp4')})

    def test_wav_matches_original_samples_and_absolute_video_frames(self):
        self.session['chunks'] = [self.chunk(0, 0, 2.017, avatar=False), self.chunk(1, 2.017, 4.017),
                                  self.chunk(2, 4.017, 6, avatar=False)]
        original_json = (self.folder / 'luna_input.json').read_bytes()
        with patch('app.transcribe_audio', side_effect=AssertionError('No retranscription')):
            response = self.client.get(f'/avatar_audio/{self.name}/1')
        self.assertEqual(response.status_code, 200, response.data[:200])
        start, duration = avatar_interval(self.session['chunks'][1], 6)
        with wave.open(io.BytesIO(response.data)) as audio:
            self.assertEqual(audio.getframerate(), 48000)
            self.assertEqual(audio.getnframes(), round(duration * 48000))
            self.assertEqual(audio.readframes(audio.getnframes()), self.audio[round(start*48000)*2:round((start+duration)*48000)*2])
        self.assertEqual(original_json, (self.folder / 'luna_input.json').read_bytes())
        with patch('app.subprocess.run', side_effect=AssertionError('Cached WAV must be reused')):
            repeated = self.client.get(f'/avatar_audio/{self.name}/1')
            self.assertEqual(repeated.data, response.data)
            repeated.close()
        response.close()

    def test_unique_clip_per_slot_and_no_library_fallback(self):
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(avatar_tasks(self.session)[0]['zoom_percent'], 110)
        with self.assertRaisesRegex(ValueError, '№3'):
            web._prepare_build_chunks(self.session)
        self.assertEqual(self.upload(2, duration=3, offset=.5).status_code, 200)
        built = web._prepare_build_chunks(self.session)
        self.assertNotEqual(built[0]['_avatar_file'], built[2]['_avatar_file'])
        self.assertEqual(built[0]['_avatar_source_start'], 0)
        self.assertEqual(built[2]['_avatar_source_start'], .5)
        self.assertTrue(built[0]['_avatar_lipsync'])
        web._sessions.pop(self.name)
        project = self.client.get(f'/project/{self.name}').get_json()
        self.assertEqual(project['language'], 'cs')
        self.assertEqual([t['status'] for t in project['avatar_tasks']], ['ready', 'ready'])

    def test_failed_replacement_keeps_previous_clip_and_timeline(self):
        self.upload()
        old = dict(self.session['avatar_assignments'])
        response = self.upload(duration=1.5)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session['avatar_assignments'], old)
        self.assertEqual(len(list((self.folder / 'downloads').iterdir())), 1)
        self.assertEqual(self.session['chunks'], self.chunks)

    def test_dreamina_60fps_rounding_shortfall_is_padded_without_retiming(self):
        # Real exporter case: 2.900 s of video for a 2.967 s source WAV.
        boundary = 89 / 30
        self.session['chunks'] = [self.chunk(0, 0, boundary), self.chunk(1, boundary, 4, avatar=False),
                                  self.chunk(2, 4, 6)]
        before = json.dumps(self.session['chunks'], ensure_ascii=False)
        original_json = (self.folder / 'luna_input.json').read_bytes()
        source = self.root / 'short.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=60',
                        '-t', '2.9', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                       check=True, capture_output=True, timeout=30)
        self.assertAlmostEqual(probe_video(source)['duration'], 2.9, places=5)
        with patch('app.transcribe_audio', side_effect=AssertionError('No retranscription')):
            response = self.client.post('/avatar_clip', data={'scene_name': self.name, 'chunk_id': '0',
                                        'source_start': '0', 'video': (io.BytesIO(source.read_bytes()), 'short.mp4')})
        self.assertEqual(response.status_code, 200, response.data)
        task = response.get_json()['avatar_tasks'][0]
        self.assertEqual(task['status'], 'ready')
        self.assertEqual(task['zoom_percent'], 110)
        self.assertAlmostEqual(task['tail_padding_seconds'], 1/15, places=5)
        info = probe_video(self.folder / 'downloads' / task['filename'])
        self.assertGreaterEqual(info['duration'] + .001, boundary)
        self.assertEqual((info['width'], info['height']), (320, 180))
        self.assertEqual(json.dumps(self.session['chunks'], ensure_ascii=False), before)
        self.assertEqual((self.folder / 'luna_input.json').read_bytes(), original_json)

    def test_padding_does_not_accept_large_shortfall_or_bad_offset(self):
        self.upload(duration=3)
        old = dict(self.session['avatar_assignments'])
        files = set((self.folder / 'downloads').iterdir())
        for duration, offset in [(1.89, 0), (1.94, .05), (3, 1.11)]:
            response = self.upload(duration=duration, offset=offset)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('нужно 2.000 с', response.get_json()['error'])
            self.assertEqual(self.session['avatar_assignments'], old)
            self.assertEqual(set((self.folder / 'downloads').iterdir()), files)

    def test_offset_updates_and_removal_do_not_retime_or_delete_old_media(self):
        self.upload(duration=3)
        filename = self.session['avatar_assignments']['0']['filename']
        with patch('app.probe_video', return_value={'duration': 3, 'width': 320, 'height': 180}), \
                patch('app.zoom_avatar_video', side_effect=AssertionError('Do not zoom again')):
            response = self.client.post('/avatar_clip', data={'scene_name': self.name, 'chunk_id': 0, 'source_start': .5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(avatar_tasks(self.session)[0]['source_start'], .5)
        self.assertEqual(avatar_tasks(self.session)[0]['zoom_percent'], 110)
        self.assertEqual(avatar_tasks(self.session)[0]['filename'], filename)
        response = self.client.delete('/avatar_clip', json={'scene_name': self.name, 'chunk_id': 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(avatar_tasks(self.session)[0]['status'], 'missing')
        self.assertTrue((self.folder / 'downloads' / filename).is_file())

    def test_failed_zoom_preserves_previous_assignment_and_cleans_upload(self):
        self.upload()
        old = dict(self.session['avatar_assignments'])
        files = set((self.folder / 'downloads').iterdir())
        with patch('app.probe_video', return_value={'duration': 3, 'width': 320, 'height': 180}), \
                patch('app.zoom_avatar_video', side_effect=subprocess.CalledProcessError(1, ['ffmpeg'])):
            response = self.client.post('/avatar_clip', data={'scene_name': self.name, 'chunk_id': '0',
                                       'video': (io.BytesIO(b'bad video'), 'avatar.mp4')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session['avatar_assignments'], old)
        self.assertEqual(set((self.folder / 'downloads').iterdir()), files)
        self.assertEqual(self.session['chunks'], self.chunks)

    def test_more_than_five_slots_are_supported(self):
        self.session['audio_duration'] = 24
        self.session['chunks'] = [self.chunk(i, i*2, (i+1)*2, avatar=i%2==0) for i in range(12)]
        for cid in range(0, 12, 2):
            self.assertEqual(self.upload(cid).status_code, 200)
        self.assertEqual(len(self.session['avatar_assignments']), 6)
        self.assertTrue(all(t['status'] == 'ready' for t in avatar_tasks(self.session)))

    def test_changed_replica_invalidates_binding_without_destroying_clip(self):
        self.upload()
        self.session['chunks'][0]['text'] = 'Jiná věta'
        self.assertEqual(avatar_tasks(self.session)[0]['status'], 'missing')
        with self.assertRaises(ValueError):
            web._prepare_build_chunks(self.session)

    def test_import_retains_exact_replica_bindings_and_rejects_long_appearance(self):
        self.upload()
        def imported(chunks):
            return self.client.post('/import_timeline', data={'scene_name': self.name,
                'timeline': (io.BytesIO(json.dumps({'video_mode': 'ai_avatar', 'avatar_workflow': 'dreamina', 'chunks': chunks}).encode()), 'timeline.json')}, buffered=True)
        with patch('app.download_for_chunk') as search, patch('app.library_catalog', return_value=[]):
            response = imported(self.chunks)
        self.assertEqual(response.status_code, 200, response.data)
        search.assert_not_called()
        self.assertEqual(avatar_tasks(self.session)[0]['status'], 'ready')
        self.assertEqual(json.loads((self.folder / 'timeline.json').read_text())['avatar_workflow'], 'dreamina')
        response = imported([self.chunk(0, 0, 3.1), self.chunk(1, 3.1, 6, avatar=False)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session['chunks'][0]['end'], 2)

    def test_contiguous_appearance_cannot_bypass_three_second_limit(self):
        with self.assertRaisesRegex(ValueError, 'Непрерывное'):
            validate_dreamina_chunks([self.chunk(0, 0, 2), self.chunk(1, 2, 4)], 4)
        with self.assertRaises(ValueError):
            validate_dreamina_chunks([self.chunk(0, 0, 3.1)], 3.1)
        validate_dreamina_chunks(self.chunks, 6)

    def test_planner_exports_current_targets_and_original_czech_text(self):
        payload = planner_payload(self.session, web.LUNA_INSTRUCTIONS, REMOTION_TEMPLATES)
        self.assertEqual(payload['avatar_plan']['target_percent'], 4.4)
        self.assertEqual(payload['avatar_plan']['max_clip_seconds'], 3)
        self.assertEqual(payload['avatar_editorial_rules']['avatar']['proposed_budget_range'], [.04, .05])
        for stale in ('никабе', '20–25%', '3–5 с', 'source_start:секунды_необязательно'):
            self.assertNotIn(stale, payload['instructions'])
        self.assertIn('чешский', payload['instructions'])
        self.assertIn('cs', LANGUAGES)
        self.assertEqual(web.SOURCE_LABELS['cs'], 'Zdroj')

    def test_wrong_slot_busy_project_and_bad_file_are_rejected(self):
        self.assertEqual(self.upload(1).status_code, 400)
        self.assertEqual(self.upload(99).status_code, 400)
        self.assertEqual(self.upload(offset=float('nan')).status_code, 400)
        self.session['busy'] = True
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.client.get(f'/avatar_audio/{self.name}/0').status_code, 409)
        self.session['busy'] = False
        self.assertEqual(self.client.delete('/avatar_clip', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/upload_avatar', data={'scene_name': self.name}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
