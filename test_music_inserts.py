import array
import json
import math
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from music_inserts import bind_music_words,inserted_duration,pause_narration,shifted_words


class MusicInsertTests(unittest.TestCase):
    def test_import_keeps_music_breaks_and_original_word_indices(self):
        import io,threading
        from unittest.mock import patch
        import app as editor
        with tempfile.TemporaryDirectory() as folder,patch.object(editor,'OUTPUT_DIR',folder):
            name='scene_music_insert_test';root=Path(folder,name);root.mkdir()
            words=[dict(word='eins',start=.1,end=.4),dict(word='zwei',start=.6,end=1.)]
            (root/'luna_input.json').write_text(json.dumps({'word_timestamps':words}))
            editor._sessions[name]=dict(scene_name=name,scene_dir=str(root),audio_duration=1.2,chunks=[],assets={},busy=False,cancel=threading.Event())
            raw=[dict(type='photo',query='Berlin',word_range=[0,1],search_mode='broll'),
                 dict(type='video',query='song',word_range=[1,1],music_insert=True,duration=5,search_mode='broll'),
                 dict(type='photo',query='Berlin',word_range=[1,2],search_mode='broll')]
            raw=bind_music_words(raw,words,1.2)
            try:
                with patch.object(editor,'download_for_chunk',return_value=[]) as fetch:
                    response=editor.app.test_client().post('/import_timeline',data={'scene_name':name,'timeline':(io.BytesIO(json.dumps({'chunks':raw}).encode()),'timeline.json')})
                    self.assertEqual(response.status_code,200,response.get_data(as_text=True))
                    self.assertIn('"downloads_done": true',response.get_data(as_text=True))
                    received=next(c.args[0] for c in fetch.call_args_list if c.args[0].get('music_insert'))
                    self.assertEqual(received['word_range'],[1,1]);self.assertEqual(received['duration'],5)
                    saved=json.loads((root/'timeline.json').read_text());self.assertEqual(saved['chunks'][-1]['end'],6.2)
            finally:editor._sessions.pop(name,None)

    def test_binding_and_limits(self):
        words=[dict(word='eins',start=.1,end=.4),dict(word='zwei',start=.6,end=1.)]
        chunks=[dict(type='photo',word_range=[0,1]),
                dict(type='video',music_insert=True,duration=5,word_range=[1,1]),
                dict(type='photo',word_range=[1,2])]
        result=bind_music_words(chunks,words,1.2)
        self.assertEqual([(c['start'],c['end']) for c in result],[(0,.6),(.6,5.6),(5.6,6.2)])
        self.assertEqual(shifted_words(words,result)[1]['start'],5.6)
        self.assertEqual(words[1]['start'],.6)
        for bad in [True,0,5.01,6,float('nan')]:
            with self.assertRaises(ValueError):inserted_duration([{**chunks[1],'duration':bad}])
        with self.assertRaises(ValueError):bind_music_words([{**c,'word_range':[1,2]} if c.get('music_insert') else c for c in chunks],words,1.2)

    def test_pcm_is_preserved_across_multiple_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a.wav',Path(tmp)/'b.wav'
            raw=array.array('h',range(1000)).tobytes()
            with wave.open(str(a),'wb') as f:
                f.setparams((1,2,1000,0,'NONE','not compressed'));f.writeframes(raw)
            pause_narration(a,b,[dict(start=.25,duration=1),dict(start=1.75,duration=2)])
            with wave.open(str(b),'rb') as f:actual=f.readframes(f.getnframes())
            self.assertEqual(actual,raw[:500]+bytes(2000)+raw[500:1500]+bytes(4000)+raw[1500:])

    def test_native_render_keeps_song_and_pauses_voice(self):
        import numpy as np
        from PIL import Image
        from ffmpeg_builder import build_video
        with tempfile.TemporaryDirectory(prefix='music_insert_render_') as tmp:
            root=Path(tmp);photo=root/'photo.png';voice=root/'voice.wav';clip=root/'song.mp4'
            Image.new('RGB',(960,540),(45,50,55)).save(photo)
            def run(args):subprocess.run(['ffmpeg','-y','-v','error',*args],check=True,capture_output=True)
            run(['-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=1.2',str(voice)])
            run(['-f','lavfi','-i','color=c=blue:s=960x540:r=30:d=1','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=1','-shortest','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(clip)])
            def chunk(i,start,end,path,kind='photo',**kw):
                return dict(_chunk_id=i,type=kind,query='test',start=start,end=end,duration=end-start,preset='PHOTO_STATIC',params={'fit':'contain'},_files=[str(path)],**kw)
            chunks=[chunk(0,0,.6,photo),chunk(1,.6,1.6,clip,'video',music_insert=True),chunk(2,1.6,2.2,photo)]
            path,_=build_video(chunks,tmp,'music_test',audio_path=str(voice),audio_duration=2.2,preview=True,
                              transitions=[dict(kind='cut',start=.6,end=.6),dict(kind='cut',start=1.6,end=1.6)],
                              audio_tracks=[dict(asset='music/leberch-documentary-calm-603945.mp3',start=0,end=2.2,gain_db=-5,fade=.1)])
            output=root/'decoded.wav';run(['-i',path,'-vn','-ac','1','-ar','48000',str(output)])
            with wave.open(str(output),'rb') as f:samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float);rate=f.getframerate()
            def energy(a,b,hz):
                x=samples[round(a*rate):round(b*rate)];t=np.arange(len(x))/rate
                return abs(np.sum(x*np.exp(-2j*np.pi*hz*t)))
            self.assertGreater(energy(.2,.5,220),10*energy(.2,.5,880))
            self.assertGreater(energy(.8,1.3,880),10*energy(.8,1.3,220))
            self.assertGreater(energy(1.8,2.1,220),10*energy(1.8,2.1,880))
            duration=float(json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',path]))['format']['duration'])
            self.assertAlmostEqual(duration,2.2,delta=.05)
            # A silent candidate must fail before rendering rather than becoming silent music.
            run(['-i',str(clip),'-an','-c:v','copy',str(root/'silent.mp4')])
            chunks[1]['_files']=[str(clip),str(clip)]
            with self.assertRaisesRegex(ValueError,'ровно один'):
                build_video(chunks,tmp,'many_test',audio_path=str(voice),audio_duration=2.2)
            chunks[1]['_files']=[str(root/'silent.mp4')]
            with self.assertRaisesRegex(ValueError,'нет звука'):
                build_video(chunks,tmp,'silent_test',audio_path=str(voice),audio_duration=2.2)


if __name__=='__main__':unittest.main()
