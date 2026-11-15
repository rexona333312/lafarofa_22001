import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app as application
import ffmpeg_builder as builder
from presets import REMOTION_TEMPLATES, validate_scene
from text_overlays import TEXT_COMPONENTS
from retired_templates import REMOVED_TEXT, without_retired_templates


class RetiredTemplateTests(unittest.TestCase):
    def test_registry_and_planner_only_advertise_retained_templates(self):
        self.assertFalse(REMOVED_TEXT & TEXT_COMPONENTS.keys())
        self.assertEqual(len(TEXT_COMPONENTS), 7)
        self.assertNotIn('map_trace_camera', REMOTION_TEMPLATES)
        self.assertNotIn('map_annotations_image', REMOTION_TEMPLATES)
        self.assertIn('map_annotations', REMOTION_TEMPLATES)
        self.assertIn('map_geographic', REMOTION_TEMPLATES)
        for name in (*REMOVED_TEXT, 'map_trace_camera', 'map_annotations_image'):
            self.assertNotIn(name, application.LUNA_INSTRUCTIONS)

    def test_legacy_map_migration_preserves_media_timing_and_retained_effects(self):
        project = {'chunks': [{'id': 0, 'template': name, 'type': 'photo', 'start': i * 3, 'end': (i+1) * 3,
            'files': ['chosen.jpg'], 'params': {'annotations': [], 'camera_zoom': 1.2, 'zoom_end': .03}}
            for i, name in enumerate(('map_trace_camera', 'map_annotations_image', 'map_annotations'))],
            'text_cues': [{'template': name} for name in ('accent1', 'marker_highlight', 'plain2', 'selective_marker')]}
        original = copy.deepcopy(project)
        cleaned = without_retired_templates(project)
        self.assertEqual(project, original)
        self.assertEqual(without_retired_templates(cleaned), cleaned)
        for old, new in zip(original['chunks'], cleaned['chunks']):
            self.assertNotIn('template', new)
            self.assertEqual(new['files'], old['files'])
            self.assertEqual((new['start'], new['end']), (old['start'], old['end']))
            self.assertEqual(new['params'], {'zoom_end': .03})
        self.assertEqual([c['template'] for c in cleaned['text_cues']], ['marker_highlight', 'selective_marker'])

    def test_real_coordinate_maps_keep_geometry(self):
        from editorial_planning import CONTRACTS
        geo = copy.deepcopy(CONTRACTS['map_geographic']['params'])
        project = {'chunks': [{'template': 'map_trace_camera', 'params': geo, 'type': 'photo', 'start': 0, 'end': 6}]}
        migrated = without_retired_templates(project)['chunks'][0]
        self.assertEqual(migrated['template'], 'map_geographic')
        self.assertEqual(migrated['params'], geo)
        validate_scene(migrated)
        retained = {'chunks': [{'template': name, 'params': geo} for name in ('map_annotations', 'map_geographic')]}
        self.assertEqual(without_retired_templates(retained), retained)

    def test_project_restoration_does_not_rewrite_original_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(application, 'OUTPUT_DIR', folder):
            name = 'scene_retired_restore'; scene = Path(folder, name); scene.mkdir()
            project = {'chunks': [{'id': 0, 'type': 'photo', 'query': 'old map', 'template': 'map_trace_camera',
                'start': 0, 'end': 3, 'files': []}], 'assets': {}, 'voice_file': 'voice.wav',
                'text_cues': [{'template': 'accent1'}]}
            path = scene / 'project.json'; path.write_text(json.dumps(project)); before = path.read_bytes()
            try:
                restored = application._get_session(name)
                self.assertIsNotNone(restored)
                self.assertNotIn('template', restored['chunks'][0])
                self.assertEqual(restored['text_cues'], [])
                self.assertEqual(path.read_bytes(), before)
            finally:
                application._sessions.pop(name, None)

    def test_direct_builder_renders_old_map_as_ordinary_photo_without_old_text(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder, 'map.jpg'); Image.new('RGB', (320, 180), '#456789').save(image)
            chunk = {'id': 0, 'type': 'photo', 'query': 'old map', 'start': 0, 'end': 2, 'duration': 2,
                'template': 'map_annotations', 'preset': 'PHOTO_STATIC', 'params': {'annotations': []}, '_files': [str(image)]}
            with patch.object(builder, 'render_remotion', side_effect=AssertionError('Retired effect was rendered')):
                output, _ = builder.build_video([chunk], folder, 'retired_smoke', preview=True,
                    text_cues=[{'template': 'plain1', 'start': 0, 'end': 2}])
            self.assertTrue(Path(output).is_file())
            self.assertAlmostEqual(builder._probe_duration(output), 2, delta=.04)


if __name__ == '__main__':
    unittest.main()
