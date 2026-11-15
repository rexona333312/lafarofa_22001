import copy
import unittest
from presets import validate_scene, REMOTION_TEMPLATES
from reference_templates import comparison_groups, motion_params, reference_sfx
from late_reference_templates import LATE_TEMPLATES


class LateReferenceTemplatesTest(unittest.TestCase):
    def scene(self,name,p,frames=180):
        return {'type':'photo','template':name,'start':0,'end':frames/30,'params':p}

    def test_split_text_orders_three_phases_and_preserves_caption(self):
        p={'text':'not common here','caption':'cooler months'}
        validate_scene(self.scene('text_highlight_split',p))
        for changes in ({'split_start':40},{'highlight_start':1},{'split_frames':180},{'caption_start':True}):
            with self.assertRaises(ValueError): validate_scene(self.scene('text_highlight_split',{**p,**changes}))
        sound=reference_sfx('text_highlight_split',p,180)
        self.assertEqual([s['asset'] for s in sound],['sfx/marker_scribble.mp3','sfx/whoosh.mp3'])

    def test_split_pair_continues_across_chunk_boundary_and_requires_same_family(self):
        p={'comparison_group':'versions','label':'first'}
        first=self.scene('split_verdict',p,90)
        second={**self.scene('split_verdict',{**p,'label':'second'},90),'start':3,'end':6}
        validate_scene(first);validate_scene(second)
        self.assertEqual(comparison_groups([first,second]),[[0,1]])
        for changes in ({'template':'paired_evidence'},{'params':{**p,'label':'second','right_start':120}},
                        {'params':{**p,'label':'second','archival':True}}):
            with self.assertRaises(ValueError): comparison_groups([first,{**second,**changes}])
        with self.assertRaises(ValueError): comparison_groups([first])

    def test_callouts_require_real_bounded_anchors_and_local_speech_times(self):
        row={'label':'visible feature','anchor':[.5,.4],'label_point':[.3,.2],'start_frame':20}
        p={'annotations':[row,{**row,'start_frame':60}]}
        validate_scene(self.scene('detail_callouts',p))
        for changes in ({'anchor':[float('nan'),.2]},{'start_frame':None},{'draw_frames':160}):
            q=copy.deepcopy(p);q['annotations'][0].update(changes)
            with self.assertRaises(ValueError):validate_scene(self.scene('detail_callouts',q))
        self.assertEqual([s['start_frame'] for s in reference_sfx('detail_callouts',p,180)],[20,60])

    def test_lower_contrast_only_highlighted_parts_make_marker_sound(self):
        p={'heading':'ordinary explanations','segments':[
            {'text':'fits one clue','start_frame':30,'highlight':True},
            {'text':'and','start_frame':50},
            {'text':'fails another','start_frame':60,'highlight':True}]}
        validate_scene(self.scene('lower_third_contrast',p))
        self.assertEqual([s['start_frame'] for s in reference_sfx('lower_third_contrast',p,180)],[30,60])
        for changes in ({'start_frame':10},{'highlight':'yes'},{'reveal_frames':150}):
            q=copy.deepcopy(p);q['segments'][2].update(changes)
            with self.assertRaises(ValueError):validate_scene(self.scene('lower_third_contrast',q))

    def test_report_is_existing_panel_variant_and_all_new_families_have_planner_rules(self):
        import app
        p={'title':'three arguments','style':'report','items':[{'text':'one','start_frame':20},{'text':'two','start_frame':70}]}
        validate_scene(self.scene('bullet_panel',p))
        with self.assertRaises(ValueError):validate_scene(self.scene('bullet_panel',{**p,'style':'invented'}))
        self.assertTrue(set(LATE_TEMPLATES)<=set(REMOTION_TEMPLATES))
        for name in LATE_TEMPLATES:self.assertIn(name,app.LUNA_INSTRUCTIONS)
        for name,p in [('text_highlight_split',{'text':'limited range'}),
                       ('split_verdict',{}),
                       ('detail_callouts',{'annotations':[{'label':'one','anchor':[.4,.3],'label_point':[.2,.1],'start_frame':1,'draw_frames':8},
                                                        {'label':'two','anchor':[.7,.3],'label_point':[.8,.2],'start_frame':15,'draw_frames':8}]}),
                       ('lower_third_contrast',{'heading':'reason','segments':[{'text':'one','start_frame':4,'reveal_frames':8},
                                                                          {'text':'two','start_frame':16,'reveal_frames':8,'highlight':True}]})]:
            motion_params(name,p,30)
            for sound in reference_sfx(name,p,30):self.assertLess(sound['end_frame'],30)


if __name__=='__main__':unittest.main()
