import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app as module


class ResearchSelectionTests(unittest.TestCase):
    def test_search_adds_candidates_without_discarding_selection(self):
        for result in ('new', 'empty', 'error'):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as folder:
                name = 'scene_research_test'
                root = Path(folder, name)
                downloads = root / 'downloads'
                downloads.mkdir(parents=True)
                Image.new('RGB', (64, 64), '#678').save(downloads / 'chosen.jpg')
                session = {'scene_name': name, 'scene_dir': str(root), 'busy': False,
                           'cancel': threading.Event(), 'audio_duration': 3, 'language': 'en',
                           'video_mode': 'faceless', 'processing_mode': 'fast',
                           'query_budget': 1, 'main_entity_type': 'generic',
                           'chunks': [{'id': 0, 'type': 'photo', 'query': 'perfume bottle',
                                       'start': 0, 'end': 3, 'duration': 3, 'files': ['chosen.jpg']}],
                           'assets': {'chosen.jpg': {'source': 'Локальный файл'}},
                           'file_overrides': {'0': ['chosen.jpg']}}
                session['chunks'][0] = module.inherit_main_entity(session['chunks'][0], '', '', 'generic')

                def download(*args, **kwargs):
                    if result == 'error':
                        raise RuntimeError('Search provider unavailable')
                    if result == 'empty':
                        return []
                    path = downloads / 'alternative.jpg'
                    Image.new('RGB', (64, 64), '#987').save(path)
                    kwargs['asset_callback'](path.name, {'source': 'Локальный файл'})
                    return [str(path)]

                module._sessions[name] = session
                try:
                    with patch.object(module, 'OUTPUT_DIR', folder), \
                         patch.object(module, 'download_for_chunk', side_effect=download) as search:
                        response = module.app.test_client().post('/resume_search',
                                                                json={'scene_name': name, 'chunk_id': 0})
                        body = response.get_data(as_text=True)
                    self.assertEqual(response.status_code, 200, body)
                    search.assert_called_once()
                    self.assertFalse(session['busy'])
                    self.assertEqual(session['file_overrides'], {'0': ['chosen.jpg']})
                    self.assertIn('chosen.jpg', session['chunks'][0]['files'])
                    saved = json.loads((root / 'project.json').read_text())
                    self.assertEqual(saved['file_overrides'], {'0': ['chosen.jpg']})
                    if result == 'new':
                        self.assertEqual(session['chunks'][0]['files'], ['chosen.jpg', 'alternative.jpg'])
                        self.assertIn('"filename": "chosen.jpg"', body)
                    elif result == 'empty':
                        self.assertIn('"downloads_done": true', body)
                    else:
                        self.assertIn('Search provider unavailable', body)
                finally:
                    module._sessions.pop(name, None)


if __name__ == '__main__':
    unittest.main()
