import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from documentary_templates import documentary_params, DOCUMENTARY_TEMPLATES
from editorial_planning import graphics_summary, graphics_target, CONTRACTS
from geographic_maps import geographic_params
from narrative_templates import carousel_groups
from presets import validate_scene, REMOTION_TEMPLATES


class SwissPackTests(unittest.TestCase):
    def scene(self,name,params,kind='photo'):
        return dict(type=kind,template=name,start=0,end=6,params=params,query='Switzerland',search_mode='broll')

    def test_contracts_registered_and_exported_to_planner(self):
        import app
        from avatar_templates import planner_payload
        self.assertTrue(set(CONTRACTS)<=set(REMOTION_TEMPLATES))
        payload=planner_payload({'motion_graphics_target':55},app.LUNA_INSTRUCTIONS,REMOTION_TEMPLATES)
        self.assertEqual(payload['editorial_policy']['motion_graphics_target'],55)
        for name in CONTRACTS:self.assertIn(name,payload['instructions'])
        self.assertNotIn('цель — 30–34%',payload['instructions'])

    def test_data_values_and_document_bounds(self):
        for name in DOCUMENTARY_TEMPLATES:
            validate_scene(self.scene(name,CONTRACTS[name]['params']))
        p=copy.deepcopy(CONTRACTS['data_comparison']['params'])
        for v in [True,-1,float('nan')]:
            p['items'][0]['value']=v
            with self.assertRaises(ValueError):validate_scene(self.scene('data_comparison',p))
        for rect in [[.9,.2,.5,.1],[0,0,0,.2],[0,0,float('inf'),1]]:
            with self.assertRaises(ValueError):validate_scene(self.scene('document_focus',{'focus_rect':rect}))
        with self.assertRaises(ValueError):
            validate_scene(self.scene('stat_callout',{'value':'42','label':'count'},'video'))

    def test_maps_and_legacy_aliases(self):
        p=CONTRACTS['map_geographic']['params']
        for name in ['map_geographic','map_annotations']:
            validate_scene(self.scene(name,p))
        geo=geographic_params(p,180)
        self.assertEqual(geo['features'][0]['properties']['code'],'CHE')
        for change in [{'highlights':[{'country':'MADE_UP'}]}, {'historical_year':1940},
                       {'camera':[{'frame':0,'center':[500,46]},{'frame':179,'center':[8,46]}]}]:
            with self.assertRaises(ValueError):geographic_params({'geo':{**p['geo'],**change}},180)
        with self.assertRaises(ValueError):
            validate_scene(self.scene('map_annotations',{'annotations':[{'kind':'route','points':[[.2,.2],[.8,.8]],'label':'legacy'}]}))

    def test_graphics_union_and_footage_are_measured_by_duration(self):
        chunks=[dict(start=0,end=10,type='photo'),
                dict(start=10,end=16,type='video',template='stat_callout',params={'layout':'overlay','start_frame':60}),
                dict(start=16,end=20,type='photo',template='portrait_profile')]
        cues=[dict(start=11,end=14),dict(start=13,end=17)]
        s=graphics_summary(chunks,cues,70)
        self.assertEqual(s['graphics_seconds'],9)
        self.assertEqual(s['graphics_percent'],45)
        for v in [True,-1,101,float('nan')]:
            with self.assertRaises(ValueError):graphics_target(v)

    def test_board_group_retains_all_media_and_requires_contiguous_chunks(self):
        chunks=[self.scene('evidence_board',dict(carousel_group='list',caption=str(i))) for i in range(3)]
        self.assertEqual(carousel_groups(chunks),[[0,1,2]])
        with self.assertRaises(ValueError):carousel_groups([chunks[0],{'type':'video'},chunks[1]])

    def test_import_map_skips_stock_search_and_setting_survives_export(self):
        import app as editor
        with tempfile.TemporaryDirectory() as folder,patch.object(editor,'OUTPUT_DIR',folder):
            name='scene_swiss_contract';root=Path(folder,name);root.mkdir()
            editor._sessions[name]=dict(scene_name=name,scene_dir=str(root),audio_duration=12,chunks=[],assets={},busy=False,cancel=threading.Event())
            try:
                chart={**self.scene('data_comparison',CONTRACTS['data_comparison']['params']),'start':6,'end':12}
                raw={'motion_graphics_target':60,'chunks':[self.scene('map_annotations',CONTRACTS['map_geographic']['params']),chart]}
                client=editor.app.test_client()
                with patch.object(editor,'download_for_chunk',return_value=[]) as fetch:
                    r=client.post('/import_timeline',data={'scene_name':name,'timeline':(io.BytesIO(json.dumps(raw).encode()),'timeline.json')})
                    self.assertEqual(r.status_code,200,r.get_data(as_text=True))
                    self.assertIn('"downloads_done": true',r.get_data(as_text=True))
                    fetch.assert_not_called()
                s=editor._sessions[name]
                self.assertTrue((root/'downloads'/s['chunks'][0]['files'][0]).is_file())
                self.assertTrue((root/'downloads'/s['chunks'][1]['files'][0]).is_file())
                r=client.post('/motion_graphics',json={'scene_name':name,'motion_graphics_target':45})
                self.assertEqual(r.status_code,200)
                self.assertEqual(json.loads((root/'project.json').read_text())['motion_graphics_target'],45)
                s['busy']=True
                self.assertEqual(client.post('/motion_graphics',json={'scene_name':name,'motion_graphics_target':10}).status_code,409)
                self.assertEqual(s['motion_graphics_target'],45)
            finally:editor._sessions.pop(name,None)


if __name__=='__main__':unittest.main()
