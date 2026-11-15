import io
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import app as module


def check():
    with tempfile.TemporaryDirectory() as folder:
        session = {'scene_name': 'upload_check', 'scene_dir': folder, 'busy': False,
                   'cancel': threading.Event(), 'chunks': [{'id': 0, 'files': []}],
                   'assets': {}, 'file_overrides': {'0': []}}
        with patch.object(module, '_get_session', return_value=session), patch.object(module, 'dimensions'):
            response = module.app.test_client().post('/upload_media', data={
                'scene_name': 'upload_check', 'chunk_id': '0',
                'media': (io.BytesIO(b'test'), 'photo.jpg')})
        assert response.status_code == 200, response.data
        filename = response.get_json()['filename']
        saved = json.loads((Path(folder) / 'project.json').read_text())
        assert saved['file_overrides']['0'] == [filename]
        assert filename in saved['chunks'][0]['files']
    print('OK: uploaded file is selected and persisted')


if __name__ == '__main__':
    check()
