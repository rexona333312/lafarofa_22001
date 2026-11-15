"""Correction memory, search disambiguation and final sequence; offline."""
import copy
import io
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import app as api
import editorial_learning as learning
import footage_sequence as sequence
import stock_downloader as media
import vision_ranker as vision
from media_matching import requested_creator, requested_kind, requested_work, apply_apple_checks


def portrait(cid=0, **updates):
    return dict(id=cid,type='photo',entity='Ronny',entity_type='person',query='Ronny Porträt Archiv',
        visual_intent='Verified portrait of the singer',entity_aliases=['Wolfgang Roloff'],match_policy='strict',files=[],**updates)


def project(root):
    source=Path(root,'old');(source/'downloads').mkdir(parents=True)
    path=source/'downloads/user_portrait.jpg';Image.linear_gradient('L').resize((800,600)).convert('RGB').save(path)
    c=portrait();c['files']=[path.name]
    data=dict(chunks=[c],assets={path.name:dict(source='Original source',rights_confirmed=False)},
              file_overrides={'0':[path.name]})
    (source/'project.json').write_text(json.dumps(data))
    return data,path


class EditorialLearningTests(unittest.TestCase):
    def test_reuses_compatible_manual_photo_once_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as root:
            data,source=project(root);before=source.read_bytes();entries=learning.load_approved(root)
            self.assertEqual(len(entries),1)
            used=set();result=learning.reuse_approved(portrait(2),entries,Path(root,'new'),2,used)
            self.assertIsNotNone(result)
            path,asset=result
            self.assertEqual(Path(path).read_bytes(),before);self.assertEqual(source.read_bytes(),before)
            self.assertFalse(asset['rights_confirmed']);self.assertTrue(asset['editor_confirmed'])
            self.assertEqual(asset['approved_from']['scene'],'old')
            self.assertIsNone(learning.reuse_approved(portrait(3),entries,Path(root,'new'),3,used))
            p=portrait(4);p['match_policy']='illustrative'
            self.assertIsNotNone(learning.reuse_approved(p,entries,Path(root,'new'),4,set()))
            entries[0]['match_policy']='illustrative'
            self.assertIsNone(learning.reuse_approved(portrait(5),entries,Path(root,'new'),5,set()))

    def test_date_context_action_format_and_entity_prevent_unsafe_reuse(self):
        baseline=learning.request_profile(portrait())
        for changes in [dict(entity='Other Ronny'),dict(context='Another country'),
                        dict(visual_intent='Portrait taken at a specific battle'),
                        dict(text='In 1940'),dict(required_terms=['1940']),
                        dict(shot_plan={'scale':'detail'}),dict(query='Ronny interview')]:
            p=portrait();p.update(changes)
            self.assertNotEqual(learning.request_profile(p),baseline)
        p=portrait();p['type']='video';self.assertIsNone(learning.request_profile(p))

    def test_unselected_upload_missing_file_and_symlink_are_not_library_entries(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            data,path=project(root);p=Path(root,'old/project.json')
            data['file_overrides']={};p.write_text(json.dumps(data))
            self.assertEqual(learning.load_approved(root),[])
            data['file_overrides']={'0':[path.name]};p.write_text(json.dumps(data))
            path.unlink();self.assertEqual(learning.load_approved(root),[])
            other=Path(outside,'image.jpg');Image.new('RGB',(800,600)).save(other);path.symlink_to(other)
            self.assertEqual(learning.load_approved(root),[])

    def test_ambiguous_short_name_and_unverified_exact_work_are_not_propagated(self):
        p=portrait();p['entity_aliases']=[]
        self.assertIsNone(learning.request_profile(p))
        source=dict(id=0,type='photo',query='Gitte My Kind of World album cover',entity='My Kind of World',
                    entity_type='object',visual_intent='Record cover',files=['user_album.jpg'])
        session=dict(chunks=[source,{**source,'id':2}],assets={'user_album.jpg':{'editor_confirmed':True}},file_overrides={})
        self.assertEqual(learning.propagate_choice(session,source,['user_album.jpg']),[])

    def test_record_and_propagate_respects_explicit_choices_constraints_and_neighbours(self):
        chunks=[portrait(i) for i in range(8)]
        chunks[3]['context']='Other event'
        chunks[4]['files']=['fresh.jpg']
        session=dict(chunks=chunks,assets={'user_good.jpg':{},'fresh.jpg':dict(vision_verified=True,
            vision_relevant=True,vision_match_key='current')},file_overrides={'5':['pinned.jpg']})
        learning.record_choice(session,chunks[0],['user_good.jpg'])
        session['file_overrides']['0']=['user_good.jpg']
        changes=learning.propagate_choice(session,chunks[0],['user_good.jpg'])
        self.assertEqual([c['id'] for c in changes],[2,6])
        self.assertEqual(chunks[1]['files'],[]);self.assertEqual(chunks[3]['files'],[])
        self.assertEqual(chunks[4]['files'],['fresh.jpg'])
        self.assertEqual(session['file_overrides']['5'],['pinned.jpg'])
        self.assertEqual(session['editorial_corrections'][0]['classification'],'editor_choice_reason_unspecified')

    def test_upload_persists_confirmation_log_and_related_updates(self):
        with tempfile.TemporaryDirectory() as root:
            session=dict(scene_name='demo',scene_dir=root,busy=False,cancel=threading.Event(),
                         chunks=[portrait(i) for i in range(5)],assets={},file_overrides={})
            buffer=io.BytesIO();Image.new('RGB',(800,600),'green').save(buffer,'PNG');buffer.seek(0)
            with patch.object(api,'_get_session',return_value=session):
                response=api.app.test_client().post('/upload_media',data={'scene_name':'demo','chunk_id':'0',
                    'media':(buffer,'correct.png')})
            self.assertEqual(response.status_code,200,response.data)
            body=response.get_json();self.assertEqual([c['id'] for c in body['reused_chunks']],[2,4])
            saved=json.loads(Path(root,'project.json').read_text())
            self.assertTrue(saved['assets'][body['filename']]['editor_confirmed'])
            self.assertEqual(len(saved['editorial_corrections']),1)

    def test_real_search_worker_uses_approved_photo_without_external_search(self):
        with tempfile.TemporaryDirectory() as root:
            project(root)
            target=Path(root,'new');target.mkdir()
            session=dict(scene_name='new',scene_dir=str(target),busy=False,cancel=threading.Event(),
                         chunks=[],assets={},file_overrides={},audio_duration=2)
            chunk=portrait();chunk.update(start=0,end=2)
            with patch.object(api,'OUTPUT_DIR',root),patch.object(api,'download_for_chunk') as search,\
                 api.app.test_request_context():
                response=api.import_timeline(session,io.StringIO(json.dumps(dict(chunks=[chunk]))))
                body=response.get_data(as_text=True)
            self.assertIn('"downloads_done": true',body,body)
            search.assert_not_called()
            self.assertTrue(session['chunks'][0]['files'][0].startswith('approved_'))
            self.assertEqual(session['retrieval_usage']['0']['requests_used'],0)

    def test_failed_save_rolls_back_confirmation_and_related_edits(self):
        session=dict(scene_name='demo',busy=False,cancel=threading.Event(),chunks=[portrait(i) for i in range(4)],
                     assets={'good.jpg':{}},file_overrides={})
        session['chunks'][0]['files']=['good.jpg']
        before=copy.deepcopy(session['chunks'])
        with patch.object(api,'_get_session',return_value=session),patch.object(api,'_save_assets',side_effect=OSError('disk')):
            response=api.app.test_client().post('/select_media',json=dict(scene_name='demo',chunk_id=0,files=['good.jpg']))
        self.assertEqual(response.status_code,500)
        self.assertEqual(session['chunks'],before);self.assertEqual(session['file_overrides'],{})
        self.assertEqual(session['assets'],{'good.jpg':{}})

    def test_same_album_title_requires_correct_creator_and_musical_is_not_hair(self):
        plan=dict(type='photo',query='Gitte My Kind of World Kenny Clarke 1968 cover',
            entity='My Kind of World',entity_type='object',search_mode='exact',
            visual_intent='Подлинная обложка джазового альбома My Kind of World.')
        self.assertEqual(requested_creator(plan),'Gitte');self.assertEqual(requested_work(plan),'My Kind of World')
        self.assertFalse(media._matches_plan(plan,'Review: Amber, My Kind of World'))
        self.assertTrue(media._matches_plan(plan,'Gitte - My Kind of World - 1968'))
        self.assertEqual(requested_creator({**plan,'query':'1968 Gitte My Kind of World cover'}),'')
        musical=dict(query='Hair München 1968 deutsches Musical Programm Plakat',entity='Hair',
                     entity_type='culture',search_mode='exact')
        self.assertEqual(requested_kind(musical),'musical')
        self.assertFalse(media._matches_plan(musical,'Pure Wavy Hair Extensions'))
        self.assertTrue(media._matches_plan(musical,'Hair - Musical München - Programm 1968'))
        musical['query']='Hair München Theater Archiv'
        self.assertFalse(media._matches_plan(musical,'Black Hair Care Methods'))

    def test_work_fields_validate_and_survive_query_simplification(self):
        plan=dict(type='photo',query='treaty document',entity='Treaty',entity_type='object',search_mode='exact',
                  work_title='Treaty',work_creator='Council',work_kind='document')
        media.validate_search_plan(plan)
        self.assertTrue(all('Council' in q for q in media._planned_queries(plan)))
        for key,value in [('work_creator',[]),('work_kind','invalid')]:
            with self.assertRaises(ValueError):media.validate_search_plan({**plan,key:value})

    def test_sequence_uses_only_confirmed_alternative_and_preserves_manual_selection(self):
        chunks=[dict(id=i,type='photo',files=['same.jpg','good.jpg','bad.jpg']) for i in range(3)]
        assets={'same.jpg':dict(vision_verified=True,vision_relevant=True),
                'good.jpg':dict(editor_confirmed=True),'bad.jpg':dict(vision_verified=True,vision_relevant=False)}
        changes=sequence.balance_sequence(chunks,assets,{'2':['same.jpg']})
        self.assertEqual(changes,{1:['good.jpg','same.jpg','bad.jpg']})
        self.assertEqual(chunks[2]['files'][0],'same.jpg')
        self.assertEqual(len(sequence.sequence_issues(chunks,assets,{'2':['same.jpg']})),1)

    def test_near_duplicate_stills_and_actual_scale_are_checked_after_selection(self):
        self.assertTrue(sequence.same_photo('a','b',{'a':{'perceptual_hash':'0000000000000000'},
                                                   'b':{'perceptual_hash':'0000000000000001'}}))
        chunks=[dict(id=i,type='photo',scene_id='one',files=[str(i)],shot_plan={'scale':s})
                for i,s in enumerate(['wide','medium','detail'])]
        assets={str(i):{'vision_visual_evidence':{'shot_scale':'medium'}} for i in range(3)}
        self.assertTrue(any('крупности' in issue['reason'] for issue in sequence.sequence_issues(chunks,assets)))

    def test_frame_difference_ignores_timestamp_labels(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root,'sheet.jpg');im=Image.new('RGB',(1440,306),'red');im.save(path)
            self.assertLess(vision._window_difference(path),.001)
            im.paste('blue',(480,36,960,306));im.save(path)
            self.assertGreater(vision._window_difference(path),.01)

    def test_long_archive_description_cannot_overflow_model_context(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root,'photo.jpg');Image.new('RGB',(800,600),'blue').save(path)
            def fm(command,**kwargs):
                prompt=command[-1]
                self.assertLess(len(prompt),9000)
                if Path(command[command.index('--schema')+1]).name=='source_schema.json':
                    data={'subject_name':'A named subject','subject_role':''}
                else:
                    data=dict(relevant=True,score=.9,confidence=.9,start=0,end=0,reason='Landscape',
                        subject_match='supported',visual_match='supported',context_match='not_required',observed_format='other')
                return subprocess.CompletedProcess(command,0,json.dumps(data),'')
            plan=dict(query='landscape',entity='A named subject',_fast_vision=True,
                      _candidate_metadata=[dict(title='Archive title '+('unrelated tags '*10000))])
            with patch.object(vision.subprocess,'run',side_effect=fm):
                result=vision._apple_rank(plan,[path],2)[0]
            self.assertTrue(result['relevant'])

    def test_moving_interview_closeup_is_not_confused_with_static_portrait(self):
        plan=dict(type='video',query='interview',required_format='interview')
        choice=dict(subject_match='supported',visual_match='supported',context_match='not_required',observed_format='interview')
        for observed in ['person_portrait','other']:
            for motion,expected in [('real_action',True),('static_image',False)]:
                item=dict(relevant=True,reason='Interview closeup')
                apply_apple_checks(item,choice,plan,dict(format=observed,motion_type=motion))
                self.assertEqual(item['relevant'],expected)

    def test_static_performance_or_silent_music_cannot_pass_high_model_score(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root,'preview.mp4');path.touch()
            def sheet(path,destination,*args):
                Image.new('RGB',(1440,918),'navy').save(destination)
                return vision._candidate_windows(6,2)
            for music in [False,True]:
                def fm(command,**kwargs):
                    if Path(command[command.index('--schema')+1]).name=='evidence_schema.json':
                        data=dict(description='A performer',format='performance',
                                  motion_type='real_action' if music else 'static_image',usable=True)
                    else:
                        data=dict(relevant=True,score=.99,confidence=.99,start=0,end=0,reason='Metadata matches',
                            subject_match='supported',visual_match='supported',context_match='supported',observed_format='performance')
                    return subprocess.CompletedProcess(command,0,json.dumps(data),'')
                plan=dict(query='performance',type='video',required_format='performance',music_insert=music,_fast_vision=True)
                with patch.object(vision,'_apple_window_sheet',side_effect=sheet),\
                     patch.object(vision.subprocess,'run',side_effect=fm),\
                     patch.object(vision,'_window_audio',return_value={'available':True,'audible':False}):
                    result=vision._apple_rank(plan,[path],2)[0]
                self.assertFalse(result['relevant'])
                self.assertIn('звука' if music else 'статичная',result['reason'])

    def test_music_activity_distinguishes_silence_and_sound_with_real_ffmpeg(self):
        with tempfile.TemporaryDirectory() as root:
            for label,source,expected in [('silent','anullsrc=r=48000:cl=mono',False),
                                          ('sound','sine=frequency=440:sample_rate=48000',True)]:
                path=Path(root,label+'.wav')
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',source,'-t','1',str(path)],
                               capture_output=True,check=True)
                result=vision._window_audio(path,dict(start=0,end=1))
                self.assertEqual(result['audible'],expected)
                self.assertAlmostEqual(result['audible_fraction'],1 if expected else 0,delta=.05)

    def test_youtube_music_preview_retains_real_audio_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            fixture=Path(root,'fixture.mp4')
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=320x180:r=12:d=2',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                '-c:v','libx264','-c:a','aac','-shortest',str(fixture)],capture_output=True,check=True)
            options=[]
            class FakeYoutube:
                def __init__(self,config):self.config=config;options.append(config)
                def __enter__(self):return self
                def __exit__(self,*args):return False
                def extract_info(self,url,download):
                    if download:shutil.copy2(fixture,self.config['outtmpl'].replace('%(ext)s','mp4'))
                    return dict(duration=2)
            with patch('yt_dlp.YoutubeDL',FakeYoutube),patch.object(media,'_preview_windows',return_value=[0]):
                for i,music in enumerate([False,True]):
                    path,_=media._youtube_preview(dict(webpage_url='https://example.org/fixture'),root,i,{},
                        dict(query='performance',music_insert=music,_processing_mode='fast'),2)
                    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',path],text=True))
                    self.assertEqual(any(s['codec_type']=='audio' for s in probe['streams']),music)
            self.assertTrue(any('bestaudio' in opt.get('format','') for opt in options))


if __name__=='__main__':unittest.main()
