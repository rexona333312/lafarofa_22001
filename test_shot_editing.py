"""Scene planning and sampled action selection, without network/model calls."""
import copy
import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import app as editor
import clip_ranker
import vision_ranker as vision
from avatar_templates import planner_payload
from presets import validate_scene, TRANSITION_INSTRUCTIONS
from shot_planning import (validate_shot_plan, retrieval_groups, apply_photo_intent,
                           editing_summary, visual_context)


def shot(role='action', scale='medium', relation='new_scene', **extra):
    return dict(role=role,scale=scale,relation=relation,pace='normal',
                goal='Explain the manufacturing process',action='Hands handle a sheet',**extra)


class ShotEditingTests(unittest.TestCase):
    def test_contract_is_exported_and_invalid_links_are_rejected(self):
        payload=planner_payload({'video_mode':'faceless'},editor.LUNA_INSTRUCTIONS,[])
        self.assertEqual(payload['shot_editing_contract']['transitions_default'],'cut')
        self.assertIn('shot_plan',payload['instructions'])
        self.assertNotIn('40%',TRANSITION_INSTRUCTIONS)
        valid=dict(type='video',scene_id='process',shot_plan=shot())
        validate_scene(valid)
        validate_scene({'type':'video'})  # Old JSON remains supported.
        for changes in ({'scene_id':True},{'scene_id':''},{'template':'evidence_board'},
                        {'shot_plan':shot(relation='contrast')},{'shot_plan':shot(scale='invented')},
                        {'shot_plan':{**shot(),'pace':'made_up'}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_shot_plan({**valid,**changes})

    def test_groups_photo_intent_and_rhythm_do_not_retime_voice(self):
        chunks=[dict(type='photo',scene_id='a',start=0,end=3,shot_plan=shot(role='establishing',scale='wide')),
                dict(type='photo',scene_id='a',start=3,end=5,shot_plan=shot(role='detail',scale='detail',relation='continue')),
                dict(type='video',start=5,end=7),
                dict(type='photo',scene_id='a',start=7,end=11,shot_plan=shot(role='breathing',scale='wide'))]
        before=copy.deepcopy(chunks)
        self.assertEqual(retrieval_groups(chunks),[[0,1],[2],[3]])
        self.assertEqual([apply_photo_intent(c).get('preset') for c in chunks],
                         ['PHOTO_SLOW_ZOOM_OUT','PHOTO_STATIC',None,'PHOTO_STATIC'])
        explicit={**chunks[0],'preset':'PHOTO_PAN'}
        self.assertEqual(apply_photo_intent(explicit)['preset'],'PHOTO_PAN')
        self.assertEqual(editing_summary(chunks)['sequences'],[[1,2]])
        self.assertEqual(chunks,before)

    def test_window_bounds_and_concatenated_preview_boundaries(self):
        self.assertEqual(vision._candidate_windows(9,2),
                         [{'start':0.,'end':2.},{'start':3.5,'end':5.5},{'start':7.,'end':9.}])
        self.assertEqual(vision._candidate_windows(.7,3),[{'start':0.,'end':.7}])
        mappings=[{'preview_start':0,'preview_end':4},{'preview_start':4,'preview_end':8}]
        windows=vision._candidate_windows(8,3,mappings)
        self.assertTrue(all(any(w['start']>=m['preview_start'] and w['end']<=m['preview_end']
                                for m in mappings) for w in windows))
        for value in (0,float('nan')):
            with self.assertRaises(ValueError):vision._candidate_windows(value,2)

    def test_apple_uses_selected_window_and_actual_previous_image(self):
        with tempfile.TemporaryDirectory() as folder:
            previous=Path(folder,'previous.jpg');Image.new('RGB',(800,450),'blue').save(previous)
            candidate=Path(folder,'candidate.mp4');candidate.touch()
            windows=vision._candidate_windows(9,2)
            def sheet(path,destination,*args):
                Image.new('RGB',(1440,918),'red').save(destination)
                return windows
            reply=dict(relevant=True,score=.9,confidence=.8,start=999,end=1000,
                       reason='Visible requested action', subject_match='not_required',
                       visual_match='supported', context_match='not_required')
            calls=[]
            def fm(command,**kwargs):
                calls.append(command)
                if Path(command[command.index('--schema')+1]).name=='evidence_schema.json':
                    return subprocess.CompletedProcess(command,0,json.dumps({'description':'Actual selected wide view'}),'')
                if Path(command[command.index('--schema')+1]).name=='continuity_schema.json':
                    return subprocess.CompletedProcess(command,0,json.dumps({'compatible':True,'reason':'Compatible action'}),'')
                score=[.2,.9,.1][(len(calls)-2)%3]
                return subprocess.CompletedProcess(command,0,json.dumps({**reply,'score':score,'relevant':score>.5}),'')
            plan={'query':'paper process','shot_plan':shot(), '_fast_vision':True,
                  '_previous_visual':{'path':str(previous),'description':'Actual selected wide view'}}
            with patch.object(vision,'_apple_window_sheet',side_effect=sheet),patch.object(vision.subprocess,'run',side_effect=fm):
                result=vision._apple_rank(plan,[str(candidate)],2)[0]
            self.assertEqual((result['start'],result['end']),(3.5,5.5))
            self.assertEqual(len(calls),5)
            self.assertTrue(all(c.count('--image')==1 for c in calls[:4]))
            self.assertNotIn('--image',calls[4])
            self.assertNotIn('--label',calls[0])
            self.assertNotIn('Actual selected wide view',calls[1][-1])
            self.assertIn('Actual selected wide view',calls[4][-1])
            self.assertTrue(result['continuity_matches'])
            self.assertEqual(result['model'],'apple-foundation-models')
            without_previous={k:v for k,v in plan.items() if k!='_previous_visual'}
            with patch.object(vision,'_apple_window_sheet',side_effect=sheet),patch.object(vision.subprocess,'run',
                    return_value=subprocess.CompletedProcess([],0,'malformed JSON','')):
                result=vision._apple_rank(without_previous,[str(candidate)],2)[0]
            self.assertFalse(result['relevant']);self.assertTrue(result['needs_review'])

    def test_selected_half_second_action_is_really_trimmed(self):
        with tempfile.TemporaryDirectory() as folder:
            movie=Path(folder,'action.mp4')
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:s=320x180:r=30:d=1',
                '-f','lavfi','-i','color=blue:s=320x180:r=30:d=1','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                '-map','[v]','-c:v','libx264',str(movie)],check=True,capture_output=True)
            self.assertTrue(clip_ranker._trim_to_moment(str(movie),1.2,1.7))
            frame=Path(folder,'result.png')
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(movie),'-frames:v','1',str(frame)],check=True,capture_output=True)
            with Image.open(frame) as im:r,g,b=im.getpixel((160,90))
            self.assertGreater(b,200);self.assertLess(r,20)
            self.assertAlmostEqual(vision._video_duration(movie),.5,delta=.04)

    def test_scene_retrieval_receives_actual_previous_selection_and_survives_restore(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(editor,'OUTPUT_DIR',folder):
            name='scene_shot_test';root=Path(folder,name);(root/'downloads').mkdir(parents=True)
            session={'scene_name':name,'scene_dir':str(root),'audio_duration':6,'chunks':[],
                     'assets':{},'busy':False,'cancel':threading.Event()}
            editor._sessions[name]=session
            chunks=[dict(type='photo',query='manufacturing',search_mode='broll',scene_id='process',
                         start=2*i,end=2*i+2,shot_plan=shot(role=r,scale=s,relation='new_scene' if not i else 'continue'))
                    for i,(r,s) in enumerate([('establishing','wide'),('action','medium'),('detail','detail')])]
            seen=[]
            expected_previous={1:'candidate_0.jpg',2:'candidate_1.jpg'}
            def download(plan,index,directory,**kwargs):
                seen.append((index,copy.deepcopy(plan)))
                if index:
                    self.assertEqual(Path(plan['_previous_visual']['path']).name,expected_previous[index])
                path=Path(directory,'downloads',f'candidate_{index}.jpg')
                Image.new('RGB',(800,450),'navy').save(path)
                kwargs['asset_callback'](path.name,{'source':'Test','vision_reason':f'Selected view {index}'})
                return [str(path)]
            try:
                with patch.object(editor,'download_for_chunk',side_effect=download):
                    response=editor.app.test_client().post('/import_timeline',data={'scene_name':name,
                        'timeline':(io.BytesIO(json.dumps({'chunks':chunks,'transitions':[]}).encode()),'timeline.json')})
                    self.assertIn('"downloads_done": true',response.get_data(as_text=True))
                self.assertEqual([i for i,p in seen],[0,1,2])
                self.assertIn('Selected view 0',seen[1][1]['_previous_visual']['description'])
                built=editor._prepare_build_chunks(session)
                self.assertEqual(built[2]['shot_plan']['scale'],'detail')
                self.assertEqual(built[0]['preset'],'PHOTO_SLOW_ZOOM_OUT')
                disk=json.loads((root/'project.json').read_text())
                self.assertEqual(disk['chunks'][2]['shot_plan'],chunks[2]['shot_plan'])
                self.assertNotIn('_previous_visual',disk['chunks'][1])
                alternate=root/'downloads'/'user_alternate.jpg'
                Image.new('RGB',(800,450),'green').save(alternate)
                session['chunks'][0]['files'].append(alternate.name)
                session['assets'][alternate.name]={'source':'Test'}
                client=editor.app.test_client()
                self.assertEqual(client.post('/select_media',json={'scene_name':name,'chunk_id':0,
                    'files':[alternate.name]}).status_code,200)
                expected_previous[1]=alternate.name
                with patch.object(editor,'download_for_chunk',side_effect=download):
                    response=client.post('/resume_search',json={'scene_name':name,'chunk_id':1})
                    self.assertIn('"downloads_done": true',response.get_data(as_text=True))
                self.assertEqual(Path(editor._prepare_build_chunks(session)[0]['_files'][0]).name,alternate.name)
            finally:editor._sessions.pop(name,None)

    def test_interrupted_group_keeps_completed_shots_on_disk(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(editor,'OUTPUT_DIR',folder):
            name='scene_interrupted';root=Path(folder,name);(root/'downloads').mkdir(parents=True)
            editor._sessions[name]={'scene_name':name,'scene_dir':str(root),'audio_duration':4,
                'chunks':[],'assets':{},'busy':False,'cancel':threading.Event()}
            chunks=[dict(type='photo',query='workshop',search_mode='broll',scene_id='one',start=i*2,end=i*2+2,
                shot_plan=shot(relation='new_scene' if not i else 'continue')) for i in range(2)]
            def download(plan,index,directory,**kwargs):
                if index:raise RuntimeError('Interrupted after first shot')
                file=Path(directory,'downloads','completed.jpg');Image.new('RGB',(800,450),'red').save(file)
                kwargs['asset_callback'](file.name,{'source':'Test'})
                return [str(file)]
            try:
                with patch.object(editor,'download_for_chunk',side_effect=download):
                    response=editor.app.test_client().post('/import_timeline',data={'scene_name':name,
                        'timeline':(io.BytesIO(json.dumps({'chunks':chunks}).encode()),'timeline.json')})
                    self.assertIn('Interrupted after first shot',response.get_data(as_text=True))
                saved=json.loads((root/'project.json').read_text())
                self.assertEqual(saved['chunks'][0]['files'],['completed.jpg'])
                self.assertEqual(saved['chunks'][1]['files'],[])
                self.assertFalse(editor._sessions[name]['busy'])
            finally:editor._sessions.pop(name,None)


if __name__=='__main__':unittest.main()
