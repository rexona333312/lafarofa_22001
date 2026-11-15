import copy
import math
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from automatic_sfx import POOLS, distribute_sfx, extra_scene_sfx, sound_profile, transition_sfx


class AutomaticSfxTests(unittest.TestCase):
    def events(self, family, count=12):
        return [dict(asset=POOLS[family][0],start=i,end=i+.7) for i in range(count)]

    def test_every_variant_is_used_without_adjacent_repeats_and_is_reproducible(self):
        for group in POOLS:
            raw=self.events(group);before=copy.deepcopy(raw)
            tracks=distribute_sfx(raw,12,seed='same-project')
            self.assertEqual(distribute_sfx(raw,12,seed='same-project'),tracks)
            self.assertEqual(raw,before)
            assets=[t['asset'] for t in tracks]
            self.assertEqual(Counter(assets),Counter({a:4 for a in POOLS[group]}))
            self.assertTrue(all(a!=b for a,b in zip(assets,assets[1:])))

    def test_active_transients_are_balanced_without_boosting_above_thirty_percent(self):
        for group in POOLS:
            tracks=distribute_sfx(self.events(group,3),3,seed='levels')
            levels=[]
            for track in tracks:
                gain=10**(track['gain_db']/20)
                self.assertLessEqual(gain,.30000001)
                profile=sound_profile(track['asset'])
                levels.append(profile['level']*gain)
                self.assertGreater(track['end'],track['start'])
                self.assertLess(track['end']-track['start'],.7)
            self.assertLess(max(levels)-min(levels),1e-8)

    def test_dense_or_simultaneous_events_do_not_stack_and_manual_sfx_wins(self):
        raw=[dict(asset=POOLS['text'][0],start=1,end=1.5),dict(asset=POOLS['whoosh'][0],start=1,end=1.7),
             dict(asset=POOLS['text'][0],start=1.04,end=1.5),dict(asset=POOLS['text'][0],start=2,end=2.6)]
        tracks=distribute_sfx(raw,3,manual_tracks=[dict(asset='sfx/custom_hit.wav',start=2,end=2.3)])
        self.assertEqual(len(tracks),1)
        self.assertIn(tracks[0]['asset'],POOLS['whoosh'])

    def test_overlapping_strokes_merge_and_typing_pauses_stay_silent(self):
        raw=[dict(asset='sfx/marker_scribble.mp3',start=0,end=.8,loop=True),
             dict(asset='sfx/marker_scribble.mp3',start=.2,end=1,loop=True),
             dict(asset='sfx/typewrite.WAV',start=1.2,end=1.4,loop=True),
             dict(asset='sfx/typewrite.WAV',start=1.8,end=2,loop=True)]
        result=distribute_sfx(raw,2)
        self.assertEqual([(t['start'],t['end']) for t in result],[(0,1),(1.2,1.4),(1.8,2)])

    def test_sounds_follow_actual_map_events_and_card_changes(self):
        p={'geo':{'markers':[{'start_frame':45}], 'routes':[{'start_frame':80,'draw_frames':30}]}}
        cues=extra_scene_sfx('map_geographic',p,150)
        self.assertEqual([(c['start_frame'],c['end_frame']) for c in cues],[(45,69),(80,110)])
        self.assertEqual(extra_scene_sfx('map_geographic',{'geo':{}},150),[])
        for name in ('evidence_board','photo_carousel_paper','photo_carousel_film'):
            self.assertEqual(len(extra_scene_sfx(name,{},60)),1)
        self.assertEqual(extra_scene_sfx('',{},90),[])
        transitions=[dict(kind=name,start=1,end=1.8) for name in ('cut','crossfade','fade','transition-fade','directional-wipe')]
        self.assertEqual(len(transition_sfx(transitions)),1)

    def test_source_offset_reaches_the_actual_mixer_and_manual_gain_is_unchanged(self):
        import ffmpeg_builder as builder
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder,'out.mp4'))
            auto=distribute_sfx(self.events('whoosh',1),1,seed='offset')[0]
            with patch.object(builder,'_run_ffmpeg') as run,patch.object(builder.os,'replace'):
                builder._mux_pcm_audio(path,'voice.wav',[auto,dict(asset='sfx/text1.wav',start=0,end=.5,preserve_gain=True,gain_db=-5)],1)
            command=run.call_args.args[0];graph=command[command.index('-filter_complex')+1]
            self.assertIn(f"atrim=start={auto['_source_start']}",graph)
            self.assertIn('volume=-5.0dB',graph)


if __name__=='__main__':
    unittest.main()
