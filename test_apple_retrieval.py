"""Bounded automatic recovery. All providers/models mocked; no network."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import clip_ranker
import stock_downloader as media
import vision_ranker as vision


class AppleRetrievalTests(unittest.TestCase):
    def test_rejected_stock_tries_another_provider_and_excludes_bad_url(self):
        with tempfile.TemporaryDirectory() as folder:
            context=media.retrieval_context(2);calls=[]
            def fetch(name):
                def provider(query,*args,**kwargs):
                    media._spend_query(context);calls.append((name,query,kwargs['excluded_urls']))
                    path=Path(folder,name+'.jpg');Image.new('RGB',(800,450),'navy').save(path)
                    args[-1](path.name,{'original_url':'https://example.org/'+name})
                    return [str(path)]
                return provider
            def judge(plan,files,assets):
                for p in files:assets[Path(p).name].update(vision_verified=True,vision_relevant=Path(p).stem=='good')
                return [p for p in files if Path(p).stem=='good']
            with patch.object(media,'_fetch_pexels',side_effect=fetch('bad')),patch.object(media,'_fetch_pixabay',side_effect=fetch('good')):
                result=media.download_for_chunk({'type':'photo','query':'bridge','search_mode':'broll',
                    'source_policy':['licensed_stock']},0,folder,candidate_ranker=judge,retrieval=context)
            self.assertEqual([Path(p).stem for p in result],['good'])
            self.assertEqual([n for n,q,e in calls],['bad','good'])
            self.assertIn('https://example.org/bad',calls[1][2])
            self.assertEqual(context['used'],2);self.assertFalse(Path(folder,'bad.jpg').exists())

    def test_rejection_uses_next_planned_query_before_giving_up(self):
        with tempfile.TemporaryDirectory() as folder:
            context=media.retrieval_context(2);queries=[]
            def fetch(query,*args,**kwargs):
                media._spend_query(context);queries.append(query)
                path=Path(folder,('good' if query=='bridge river' else 'bad')+'.jpg')
                Image.new('RGB',(800,450)).save(path)
                args[-1](path.name,{'original_url':'https://example.org/'+path.stem})
                return [str(path)]
            def judge(plan,files,assets):
                for p in files:assets[Path(p).name].update(vision_verified=True,vision_relevant=Path(p).stem=='good')
                return [p for p in files if Path(p).stem=='good']
            with patch.object(media,'_fetch_pexels',side_effect=fetch):
                result=media.download_for_chunk({'type':'photo','query':'bridge','search_mode':'broll',
                    'search_queries':['bridge steel','bridge river'],'source_policy':['licensed_stock']},
                    0,folder,candidate_ranker=judge,retrieval=context)
            self.assertEqual(queries,['bridge steel','bridge river']);self.assertTrue(result)

    def test_retry_limit_budget_and_unknown_assessment_do_not_trigger_extra_search(self):
        stage={'_source_class':'licensed_stock','_returned_sources':['Pexels'],
               '_used_query_keys':['bridge'],'_processing_mode':'quality'}
        rejected=[{'vision_verified':True,'vision_relevant':False}]
        for context,assets in [(dict(limit=1,used=1),rejected),
                               (dict(limit=6,used=1,visual_retries=2),rejected),
                               (dict(limit=6,used=1),[{'vision_verified':False,'vision_needs_review':True}])]:
            self.assertIsNone(media._retry_rejected_stage(stage,['bridge'],assets,context))
        # Relaxed fallbacks retain their original reserved budget.
        self.assertIsNone(media._retry_rejected_stage(stage,['bridge'],rejected,dict(limit=6,phase_limit=4,used=4)))

    def test_ranker_recovers_from_bad_metadata_shortlist_using_downloaded_reserve(self):
        paths=[f'{i}.jpg' for i in range(7)];assets={p:{'search_text':'bridge'} for p in paths};batches=[]
        def analyze(plan,pending,*args):
            batches.append(pending)
            return [dict(index=i,relevant=p=='4.jpg',score=.9 if p=='4.jpg' else .1,confidence=.9,
                         start=0,end=0,reason='Visible subject') for i,p in enumerate(pending)]
        with patch.object(clip_ranker,'is_available',return_value=True),patch.object(clip_ranker,'analyze_local',side_effect=analyze):
            result=clip_ranker.rank_files('bridge',paths,assets,plan={'query':'bridge'},reject_below_threshold=True)
        self.assertEqual(result,['4.jpg']);self.assertEqual(batches,[paths[:4],paths[4:6]])

    def test_extra_windows_cover_gaps_and_stay_inside_mapped_segments(self):
        coarse=vision._candidate_windows(15,2)
        extra=vision._refinement_windows(15,2,coarse,[{'relevant':False}]*3)
        self.assertEqual(len(extra),2)
        self.assertTrue(any(abs(w['start']-3.25)<.01 for w in extra))
        mappings=[dict(preview_start=0,preview_end=5),dict(preview_start=5,preview_end=10)]
        coarse=vision._candidate_windows(10,2,mappings)
        extra=vision._refinement_windows(10,2,coarse,[{'relevant':True,'score':.9,'confidence':.8},
                                                               {'relevant':False}],mappings)
        self.assertTrue(extra)
        self.assertTrue(all(w['start']>=0 and w['end']<=5 for w in extra))

    def test_optional_continuity_failure_keeps_verified_candidate(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            prior=Path(folder,'prior.jpg');current=Path(folder,'current.jpg')
            for p in [prior,current]:Image.new('RGB',(800,450),'blue').save(p)
            def fm(command,**kwargs):
                schema=Path(command[command.index('--schema')+1]).name
                if schema=='continuity_schema.json':raise subprocess.TimeoutExpired(command,45)
                data=({'description':'Blue image'} if schema=='evidence_schema.json' else
                      dict(relevant=True,score=.9,confidence=.9,start=0,end=0,reason='Blue image',subject_match='not_required',
                           visual_match='supported',context_match='not_required'))
                return subprocess.CompletedProcess(command,0,json.dumps(data),'')
            with patch.object(vision.subprocess,'run',side_effect=fm):
                result=vision._apple_rank({'query':'Blue image','_fast_vision':True,'shot_plan':{'role':'action'},
                    '_previous_visual':{'path':str(prior)}},[current],2)[0]
            self.assertTrue(result['relevant']);self.assertTrue(result['needs_review'])
            self.assertIn('continuity_error',result)

    def test_review_uses_actual_selection_and_shows_only_unresolved_shots(self):
        chunks=[dict(id=0,type='photo',start=0,end=2,files=['bad.jpg','good.jpg']),
                dict(id=1,type='video',start=2,end=4,files=[]),
                dict(id=2,type='photo',template='evidence_board',files=[])]
        assets={'bad.jpg':{'vision_verified':True,'vision_relevant':False,'vision_reason':'Wrong action'},
                'good.jpg':{'vision_verified':True,'vision_relevant':True}}
        report=clip_ranker.selection_review(chunks,assets,{'0':['good.jpg']})
        self.assertEqual(report['total'],1);self.assertEqual(report['items'][0]['chunk_id'],1)
        report=clip_ranker.selection_review(chunks,assets,{'0':['good.jpg','bad.jpg']})
        self.assertEqual(report['total'],2)
        report=clip_ranker.selection_review(chunks,assets)
        self.assertEqual(report['total'],2)
        many=[dict(id=i,type='photo',start=i,end=i+1,files=[]) for i in range(15)]
        report=clip_ranker.selection_review(many,{})
        self.assertEqual(len(report['items']),10);self.assertEqual(report['remaining'],5)

    def test_confident_match_is_not_rechecked_and_failed_refinement_preserves_choice(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            movie=Path(folder,'candidate.mp4');movie.touch()
            windows=vision._candidate_windows(15,2)
            def sheet(path,destination,*args):
                Image.new('RGB',(1440,918),'navy').save(destination);return windows.copy()
            for score in [.9,.7]:
                def fm(command,**kwargs):
                    data=({'description':'A bridge'} if 'evidence_schema.json' in command[command.index('--schema')+1]
                          else dict(relevant=True,score=score,confidence=.9,start=0,end=0,reason='Visible bridge',subject_match='not_required',
                                    visual_match='supported',context_match='not_required'))
                    return subprocess.CompletedProcess(command,0,json.dumps(data),'')
                with self.subTest(score=score),patch.object(vision,'_apple_window_sheet',side_effect=sheet),\
                     patch.object(vision,'_video_duration',return_value=15),\
                     patch.object(vision,'_draw_window_sheet',side_effect=RuntimeError('Optional refinement failed')) as refine,\
                     patch.object(vision.subprocess,'run',side_effect=fm):
                    result=vision._apple_rank({'query':'bridge'},[movie],2)[0]
                self.assertTrue(result['relevant']);self.assertEqual((result['start'],result['end']),(0,2))
                self.assertEqual(refine.call_count,0 if score==.9 else 1)
                self.assertEqual('refinement_error' in result,score==.7)


if __name__=='__main__':unittest.main()
