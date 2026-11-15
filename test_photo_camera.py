import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import ffmpeg_builder as builder


class PhotoCameraTests(unittest.TestCase):
    def test_ffmpeg_camera_directions_and_timing_at_three_and_seven_seconds(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder,'marker.png')
            image=Image.new('RGB',(1920,1080),'black')
            from PIL import ImageDraw
            ImageDraw.Draw(image).rectangle((1260,0,1299,1079),fill='white')
            image.save(source)
            for duration in (3,7):
                for preset,direction in [('PHOTO_SLOW_ZOOM',1),('PHOTO_SLOW_ZOOM_OUT',-1),('PHOTO_PAN',-1)]:
                    with self.subTest(duration=duration,preset=preset):
                        output=Path(folder,f'{preset}_{duration}.mp4')
                        scene={'type':'photo','preset':preset,'params':{'fit':'cover'}}
                        with patch.object(builder,'render_remotion',side_effect=AssertionError('Photo motion must use FFmpeg')):
                            used=builder._render_preset([str(source)],str(output),duration,scene,320,180)
                        self.assertEqual(used,[str(source)])
                        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-f','rawvideo','-pix_fmt','gray','-'])
                        frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,180,320).astype(float)
                        self.assertEqual(len(frames),duration*30)
                        weights=frames.sum(axis=1)
                        positions=(weights*np.arange(320)).sum(axis=1)/weights.sum(axis=1)
                        self.assertGreater(direction*(positions[-1]-positions[0]),2)
                        steps=np.diff(positions)
                        self.assertLess(np.max(np.abs(steps)),.8)
                        self.assertLess(np.max(-direction*steps),.2)
                        ease=.5-.5*np.cos(np.pi*np.arange(len(positions))/(len(positions)-1))
                        matrix=np.stack([np.ones(len(positions)),ease],axis=1)
                        fitted=matrix@np.linalg.lstsq(matrix,positions,rcond=None)[0]
                        self.assertLess(np.sqrt(np.mean((positions-fitted)**2)),.25)

    def test_photo_effects_and_attribution_share_one_ffmpeg_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder,'portrait.jpg');Image.new('RGB',(400,600),'#595').save(source)
            for preset in ('BLUR_BG_CENTER','ARCHIVE_PAPER','PHOTO_STATIC'):
                scene={'type':'photo','preset':preset,'credits':{'portrait.jpg':'Source A'}}
                output=Path(folder,f'{preset}.mp4')
                with patch.object(builder,'render_remotion',side_effect=AssertionError('Unexpected browser render')), \
                     patch.object(builder,'_run_ffmpeg',wraps=builder._run_ffmpeg) as render:
                    builder._render_preset([str(source)],str(output),.5,scene,320,180)
                self.assertEqual(render.call_count,1)
                graph=render.call_args.args[0]
                self.assertIn('credit.png', ' '.join(graph))
                self.assertAlmostEqual(builder._probe_duration(str(output)),.5,delta=.02)

    def test_small_static_photo_has_no_hidden_zoom(self):
        import presets
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder,'still.png');Image.new('RGB',(400,600),'#578').save(source)
            output=Path(folder,'still.mp4')
            with patch.object(builder,'render_remotion',side_effect=AssertionError('static must stay static')):
                builder._render_preset([str(source)],str(output),1,{'type':'photo','preset':'PHOTO_STATIC'},320,180)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-f','rawvideo','-pix_fmt','rgb24','-'])
            size=320*180*3
            self.assertEqual(raw[:size],raw[-size:])


if __name__=='__main__':unittest.main()
