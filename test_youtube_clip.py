"""Run: .venv/bin/python test_youtube_clip.py (no network requests)."""
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import app as module
import stock_downloader as downloader


def check():
    url = 'https://www.youtube.com/watch?v=4yKUBuKNRQc'
    for duration, expected in [(3.06, 4), (3.23, 4), (3.54, 4), (3.01, 4), (8.01, 9), (2.34, 3), (3, 3)]:
        assert downloader.youtube_clip_request(url, '1:23', duration) == (url, 83, expected)
    for start in ['83', '01:23', '0:01:23']:
        assert downloader.youtube_clip_request('https://youtu.be/4yKUBuKNRQc?t=83', start, 3.04) == (url, 83, 4)
    assert downloader.youtube_clip_request('https://www.youtube.com/shorts/4yKUBuKNRQc', '1:23.5', 3)[1] == 83.5
    for invalid_url, start in [(url, '-1'), (url, '1:60'), (url, ''), (url, 'nan'),
                               ('https://youtube.com.evil.test/watch?v=4yKUBuKNRQc', '0'),
                               ('http://127.0.0.1/video', '0'), ('https://youtube.com/playlist?list=x', '0')]:
        try:
            downloader.youtube_clip_request(invalid_url, start, 3)
            raise AssertionError((invalid_url, start))
        except ValueError:
            pass

    with tempfile.TemporaryDirectory() as folder:
        # Exercise the real downloader flow with only yt-dlp and ffprobe replaced.
        calls = []
        class YoutubeDL:
            def __init__(self, options): self.options = options
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, source, download):
                assert source == url
                calls.append(download)
                if download:
                    assert list(self.options['download_ranges']({}, self)) == [{'start_time': 83, 'end_time': 87}]
                    assert self.options['force_keyframes_at_cuts']
                    Path(self.options['outtmpl']).write_bytes(b'video')
                return {'duration': 100, 'uploader': 'Test'}
        path = str(Path(folder) / 'clip.mp4')
        with patch('yt_dlp.YoutubeDL', YoutubeDL), patch.object(downloader, '_probe_duration', return_value=4):
            asset = downloader.download_youtube_clip(url, 83, 4, path)
            assert Path(path).exists() and asset['source_end'] == 87
            calls.clear()
            try:
                downloader.download_youtube_clip(url, 98, 4, path)
                raise AssertionError('Short remainder was accepted')
            except ValueError:
                assert calls == [False]
        Path(path).unlink()

        session = {'scene_name': 'check', 'scene_dir': folder, 'busy': False,
                   'cancel': threading.Event(), 'chunks': [{'id': 0, 'type': 'photo', 'duration': 3.04, 'files': []}],
                   'assets': {}, 'file_overrides': {}}
        body = {'scene_name': 'check', 'chunk_id': 0, 'url': url, 'start': '1:23'}
        def download(source, start, length, destination):
            assert (source, start, length) == (url, 83, 4)
            Path(destination).write_bytes(b'video')
            return asset
        client = module.app.test_client()
        with patch.object(module, '_get_session', return_value=session), patch.object(module, 'dimensions'), \
                patch.object(module, 'download_youtube_clip', side_effect=download) as fetch:
            result = client.post('/youtube_clip', json=body)
            assert result.status_code == 200, result.data
            filename = result.json['filename']
            saved = json.loads((Path(folder) / 'project.json').read_text())
            assert saved['chunks'][0]['files'] == [filename]
            assert saved['file_overrides']['0'] == [filename]
            assert not session['busy']
            build = module._prepare_build_chunks(session)[0]
            assert build['_files'][0].endswith('.mp4') and build['_duration_override'] == 3.04
            session['busy'] = True
            assert client.post('/youtube_clip', json=body).status_code == 409
            session['busy'] = False
            fetch.side_effect = ValueError('Слишком короткий остаток')
            assert client.post('/youtube_clip', json=body).status_code == 400
            assert not session['busy'] and session['chunks'][0]['files'] == [filename]
            assert list((Path(folder) / 'downloads').iterdir()) == [Path(folder) / 'downloads' / filename]
            assert client.post('/youtube_clip', json={**body, 'start': '-1'}).status_code == 400
            before = (Path(folder) / 'project.json').read_bytes()
            original_files = list(session['chunks'][0]['files'])
            def incomplete_download(source, start, length, destination):
                Path(destination).write_bytes(b'partial')
                raise ValueError('Interrupted download')
            fetch.side_effect = incomplete_download
            assert client.post('/youtube_clip', json=body).status_code == 400
            assert (Path(folder) / 'project.json').read_bytes() == before
            assert session['chunks'][0]['files'] == original_files
            assert session['file_overrides']['0'] == [filename]
            assert not session['busy']
            assert list((Path(folder) / 'downloads').iterdir()) == [Path(folder) / 'downloads' / filename]
            for key, value in [('template', 'avatar_full'), ('media_origin', 'ai_image')]:
                session['chunks'][0][key] = value
                fetch.reset_mock()
                assert client.post('/youtube_clip', json=body).status_code == 400
                fetch.assert_not_called()
                del session['chunks'][0][key]

    print('OK: rounding, timecodes, URL validation, download range, photo slot, persistence and errors')


if __name__ == '__main__':
    check()
