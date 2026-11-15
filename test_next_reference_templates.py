import copy
import unittest
from presets import validate_scene, REMOTION_TEMPLATES
from next_reference_templates import NEXT_TEMPLATES, next_motion_params, next_sfx


class NextReferenceTemplatesTest(unittest.TestCase):
    def scene(self, template, params, duration=6):
        return {'type':'photo','template':template,'start':0,'end':duration,'params':params}

    def test_interval_computes_difference_and_requires_both_dates(self):
        params = {'from_year':1918,'to_year':1963,'from_label':'story heard','to_label':'book published','difference':999}
        validate_scene(self.scene('date_interval',params))
        self.assertEqual(next_motion_params('date_interval',params,180)['difference'],45)
        for invalid in ({**params,'to_year':1917}, {**params,'from_year':True}, {**params,'from_year':None},
                        {**params,'difference_start':150,'to_start':80}, {**params,'to_start':179}):
            with self.assertRaises(ValueError): validate_scene(self.scene('date_interval',invalid))

    def test_pointer_requires_visible_image_coordinates_and_safe_tag_position(self):
        params = {'label':'detail','anchor':[.8,.5],'label_point':[0,1]}
        p=next_motion_params('object_pointer',params,180)
        self.assertEqual(p['label_point'],[.16,.94])
        for invalid in ({**params,'anchor':[float('nan'),.2]}, {**params,'label_point':[2,.5]},
                        {**params,'control_point':[False,.5]}, {**params,'anchor':None}):
            with self.assertRaises(ValueError): validate_scene(self.scene('object_pointer',invalid))

    def test_list_requires_ordered_real_onsets_and_rejects_reference_placeholder(self):
        params={'title':'open questions','items':[{'text':'how many?','start_frame':42}, {'text':'which depth?','start_frame':80}]}
        validate_scene(self.scene('bullet_panel',params))
        for change in ('missing', 'reversed','too_late','placeholder'):
            invalid=copy.deepcopy(params)
            if change=='missing': del invalid['items'][0]['start_frame']
            if change=='reversed': invalid['items'][1]['start_frame']=20
            if change=='too_late': invalid['items'][1]['start_frame']=179
            if change=='placeholder': invalid['title']='Bullet Point Overlay'
            with self.assertRaises(ValueError): validate_scene(self.scene('bullet_panel',invalid))
        cues=next_sfx('bullet_panel',params,180)
        self.assertEqual([c['start_frame'] for c in cues[1:]],[42,80])

    def test_short_defaults_fit_and_sounds_stop_at_animation_completion(self):
        cases=[('object_pointer',{'label':'detail','anchor':[.2,.4],'label_point':[.5,.6]}),
               ('corner_section',{'lines':[{'text':'first'},{'text':'second'},{'text':'third'}]}),
               ('date_interval',{'from_year':2000,'to_year':2001,'from_label':'start','to_label':'end'}),
               ('bullet_panel',{'title':'conditions','items':[{'text':'one','start_frame':1,'reveal_frames':8}, {'text':'two','start_frame':12,'reveal_frames':8}]}),
               ('echo_statement',{'text':'a qualified conclusion','echo':'conclusion'})]
        for template,params in cases:
            validate_scene(self.scene(template,params,1))
            for cue in next_sfx(template,params,30):
                self.assertLess(cue['end_frame'],30)
                self.assertGreater(cue['end_frame'],cue['start_frame'])
        for change in ({'camera_frames':60},{'camera_scale_start':float('nan')},{'camera_scale_end':True}):
            with self.assertRaises(ValueError):
                validate_scene(self.scene('echo_statement',{'text':'conclusion','echo':'conclusion',**change},1))
        with self.assertRaises(ValueError):
            validate_scene(self.scene('corner_section',{'lines':[{'text':'chapter','start_frame':29,'reveal_frames':24}]},1))

    def test_all_five_export_semantic_rules_and_reuse_production_renderer(self):
        import app
        self.assertTrue(set(NEXT_TEMPLATES) <= set(REMOTION_TEMPLATES))
        for template in NEXT_TEMPLATES: self.assertIn(template,app.LUNA_INSTRUCTIONS)
        self.assertIn('проверь скачанное медиа',app.LUNA_INSTRUCTIONS)
        self.assertIn('start_frame обязателен для каждого пункта',app.LUNA_INSTRUCTIONS)
        self.assertIn('Повторные карусели',app.LUNA_INSTRUCTIONS)

    def test_sidebar_stretches_motion_to_scene_without_changing_explicit_speech_times(self):
        p={'style':'torn_sidebar','title':'reported observations','timing_mode':'stretch',
           'items':[{'text':'first observation'},{'text':'second observation'},{'text':'third observation'}]}
        short=next_motion_params('bullet_panel',p,90)
        long=next_motion_params('bullet_panel',p,210)
        for key in ('arrival_frames','title_start','title_frames'):
            self.assertAlmostEqual(short[key]/90,long[key]/210,delta=.012)
        for a,b in zip(short['items'],long['items']):
            self.assertAlmostEqual(a['start_frame']/90,b['start_frame']/210,delta=.012)
            self.assertAlmostEqual(a['reveal_frames']/90,b['reveal_frames']/210,delta=.012)
        explicit=copy.deepcopy(p);explicit['items'][0].update(start_frame=50,reveal_frames=15)
        self.assertEqual(next_motion_params('bullet_panel',explicit,210)['items'][0]['start_frame'],50)
        for frames in (30,90,210):
            validate_scene(self.scene('bullet_panel',p,frames/30))
            self.assertTrue(all(c['end_frame']<frames for c in next_sfx('bullet_panel',p,frames)))
        for changes in ({'timing_mode':'invented'},{'title_start':89},{'arrival_frames':90}):
            with self.assertRaises(ValueError): next_motion_params('bullet_panel',{**p,**changes},90)
        spoken=copy.deepcopy(p);spoken['timing_mode']='speech'
        with self.assertRaises(ValueError):next_motion_params('bullet_panel',spoken,210)
        spoken.update(title_start=6,title_frames=12)
        for row,start in zip(spoken['items'],(23,74,150)):row.update(start_frame=start,reveal_frames=18)
        self.assertEqual([c['start_frame'] for c in next_sfx('bullet_panel',spoken,237)[1:]],[23,74,150])


if __name__=='__main__': unittest.main()
