"""General matching gates and recovery; no network or model calls."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import clip_ranker
import stock_downloader as media
import vision_ranker as vision
from media_matching import apply_apple_checks, match_key, requested_format, requested_work, source_identity_conflict


def choice(**changes):
    return dict(relevant=True, score=.95, confidence=.9, start=0, end=0,
                reason='Visible requested subject', subject_match='supported',
                visual_match='supported', context_match='supported', **changes)


class MediaMatchingTests(unittest.TestCase):
    def test_any_specific_conflict_overrules_high_aggregate_score(self):
        for key in ('subject_match', 'visual_match', 'context_match'):
            with self.subTest(key=key):
                raw=choice();raw[key]='conflict'
                item=vision._clean_results({'candidates':[dict(index=0,**raw)]},1,5)[0]
                apply_apple_checks(item,raw,dict(query='government negotiations',search_mode='broll'))
                self.assertFalse(item['relevant']);self.assertIn(key,item['reason'])

    def test_unknown_location_allowed_for_illustration_but_not_required_exact_context(self):
        raw=choice();raw['context_match']='unknown'
        for policy,expected in [('illustrative',True),('strict',False)]:
            plan=dict(query='soldiers marching',search_mode='broll',match_policy=policy)
            item=vision._clean_results({'candidates':[dict(index=0,**raw)]},1,5)[0]
            apply_apple_checks(item,raw,plan)
            self.assertEqual(item['relevant'],expected)
        raw['context_match']='not_required'
        item=dict(relevant=True,reason='Ignored date')
        apply_apple_checks(item,raw,dict(query='battle',required_terms=['1917']))
        self.assertFalse(item['relevant'])

    def test_unusable_pixels_and_wrong_format_cannot_be_rescued_by_metadata(self):
        for query,observed in [('Christian Anders Porträt Archiv','other'),
                               ('Daliah Lavi Single Cover','document'),
                               ('Prime Minister interview archive','performance')]:
            raw=choice(observed_format=observed)
            item=vision._clean_results({'candidates':[dict(index=0,**raw)]},1,5)[0]
            apply_apple_checks(item,raw,dict(query=query,search_mode='broll'))
            self.assertFalse(item['relevant']);self.assertIn('format',item['reason'])
        item=dict(relevant=True,reason='Metadata matches')
        apply_apple_checks(item,choice(),dict(query='factory'),{'usable':False})
        self.assertFalse(item['relevant'])

    def test_exact_work_does_not_accept_another_song_by_same_performer(self):
        plan=dict(query='Roy Black Du bist nicht allein performance',entity='Roy Black',
                  entity_type='person',search_mode='exact',music_insert=True,
                  visual_intent='Исполнение «Du bist nicht allein»')
        self.assertEqual(requested_work(plan),'Du bist nicht allein')
        self.assertFalse(media._matches_plan(plan,'Roy Black & Anita - Schön ist es, auf der Welt zu sein 1971'))
        self.assertTrue(media._matches_plan(plan,'Roy Black — Du bist nicht allein (1965)'))
        self.assertTrue(all('Du bist nicht allein' in q for q in media._planned_queries(plan)))
        # A portrait fallback is a different illustration, not an exact-song substitute.
        fallback=media._fallback_plan(plan,dict(role='photo',type='photo',query='Roy Black portrait',
                                              entity='Roy Black',entity_type='person'))
        self.assertFalse(requested_work(fallback))

    def test_full_alias_and_mandatory_context_survive_search_simplification(self):
        plan=dict(query='Heino portrait',entity='Heino',entity_type='person',search_mode='exact',
                  entity_aliases=['Heinz-Georg Kramm'],required_terms=['1965|1966'])
        queries=media._planned_queries(plan)
        self.assertIn('"Heinz-Georg Kramm"',queries[1])
        self.assertTrue(all('1965' in q for q in queries))
        self.assertFalse(media._matches_plan(plan,'Heino portrait 2020'))
        self.assertTrue(media._matches_plan(plan,'Heinz-Georg Kramm portrait 1966'))

    def test_names_cannot_be_assembled_from_unrelated_people_in_metadata(self):
        plan=dict(query='Donald Trump speech',entity='Donald Trump',entity_type='person',search_mode='exact')
        self.assertFalse(media._matches_plan(plan,'Donald Duck and Melania Trump'))
        self.assertTrue(media._matches_plan(plan,'Trump, Donald — speech'))

    def test_source_namesake_guard_preserves_full_names_and_alternate_order(self):
        for entity,aliases,subject,conflict in [
            ('Heino',['Heinz-Georg Kramm'],'Heino Pars',True),
            ('Heino',['Heinz-Georg Kramm'],'Heinz-Georg Kramm',False),
            ('Winston Churchill',[],'Winston Leonard Spencer Churchill',False),
            ('Donald Trump',[],'Trump, Donald',False),
            ('Winston Churchill',[],'Clementine Churchill',True),
            ('Ypres',[],'Ypres',False)]:
            plan=dict(entity=entity,entity_aliases=aliases,entity_type='person')
            self.assertEqual(source_identity_conflict(plan,subject),conflict)

    def test_old_selected_scores_are_visible_in_review_without_changing_selection(self):
        chunks=[dict(id=1,start=0,end=5,files=['old.jpg','other.jpg'])]
        assets={'old.jpg':dict(vision_model='apple-foundation-models',vision_verified=True,vision_relevant=True)}
        self.assertEqual(clip_ranker.selection_review(chunks,assets)['total'],1)
        self.assertEqual(chunks[0]['files'],['old.jpg','other.jpg'])

    def test_youtube_metadata_follows_downloaded_preview_indexes(self):
        plan=dict(query='speaker',entity='speaker')
        candidates=[dict(title='unavailable',webpage_url='https://example.org/0'),
                    dict(title='actual speech',webpage_url='https://example.org/1')]
        def preview(item,directory,index):
            if index==0: raise OSError('missing')
            return 'preview.mp4',[dict(preview_start=0,preview_end=3,source_start=10)]
        def analyze(local,paths,*args):
            self.assertEqual(local['_candidate_metadata'][0]['title'],'actual speech')
            self.assertEqual(paths,['preview.mp4'])
            return [{**choice(), 'index':0, 'end':2, 'model':'apple-foundation-models','match_key':match_key(local)}]
        with patch.object(vision,'is_available',return_value=True),patch.object(vision,'VISION_PROVIDER','apple'),\
             patch.object(vision,'analyze_local',side_effect=analyze):
            results=vision.analyze_youtube(plan,candidates,3,preview_loader=preview)
        self.assertFalse(results[0]['relevant']);self.assertEqual(results[1]['match_key'],match_key(plan))
        self.assertEqual(results[1]['start'],10)

    def test_historical_place_and_date_requirements_apply_to_different_topics(self):
        cases=[('Berlin Wall','event','1989','Berlin Wall construction 1961','Berlin Wall opening 1989'),
               ('Ypres','place','1917','Ypres memorial 2020','Ypres battle 1917'),
               ('United Nations','organization','Security Council|UNSC',
                'United Nations General Assembly','United Nations Security Council meeting')]
        for entity,kind,term,bad,good in cases:
            plan=dict(query=entity,entity=entity,entity_type=kind,search_mode='exact',required_terms=[term])
            self.assertFalse(media._matches_plan(plan,bad));self.assertTrue(media._matches_plan(plan,good))

    def test_new_fields_validate_and_reach_export_search_contract(self):
        for key,value in [('work_title','A specific treaty'),('required_format','document')]:
            plan=dict(query='signed treaty',**{key:value})
            media.validate_search_plan(plan);self.assertIn(key,media.SEARCH_FIELDS)
        for key,value in [('work_title',[]),('required_format','invented')]:
            with self.assertRaises(ValueError):media.validate_search_plan(dict(query='treaty',**{key:value}))
        self.assertEqual(requested_format(dict(query='album cover')),'record_cover')

    def test_source_namesake_is_rejected_before_image_work(self):
        with tempfile.TemporaryDirectory() as folder:
            picture=Path(folder,'never-open.jpg')
            def fm(command,**kwargs):
                self.assertEqual(Path(command[command.index('--schema')+1]).name,'source_schema.json')
                return subprocess.CompletedProcess(command,0,json.dumps(dict(subject_name='Heino Pars',
                    subject_role='director')),'')
            plan=dict(query='Heino portrait',entity='Heino',entity_type='person',
                entity_aliases=['Heinz-Georg Kramm'],_candidate_metadata=[dict(title='Heino Pars Archives')])
            with patch.object(vision.subprocess,'run',side_effect=fm) as run:
                result=vision._apple_rank(plan,[picture],5)[0]
            self.assertFalse(result['relevant']);self.assertEqual(run.call_count,1)
            self.assertFalse(result.get('needs_review',False))

    def test_rejection_searches_full_alias_and_keeps_original_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            context=media.retrieval_context(2);queries=[]
            def fetch(query,*args,**kwargs):
                media._spend_query(context);queries.append(query)
                path=Path(folder,f'{len(queries)}.jpg');Image.new('RGB',(800,450)).save(path)
                args[-1](path.name,dict(original_url='https://example.org/'+path.name))
                return [str(path)]
            def judge(plan,files,assets):
                good='Heinz-Georg Kramm' in queries[-1]
                for p in files:assets[Path(p).name].update(vision_verified=True,vision_relevant=good)
                return files if good else []
            with patch.object(media,'_fetch_reserp',side_effect=fetch):
                result=media.download_for_chunk(dict(type='photo',query='Heino portrait',entity='Heino',
                    entity_type='person',entity_aliases=['Heinz-Georg Kramm'],query_budget=2,
                    source_policy=['editorial']),0,folder,per_source=1,reserp_mode=True,
                    candidate_ranker=judge,retrieval=context)
            self.assertTrue(result);self.assertEqual(context['used'],2)
            self.assertIn('Heinz-Georg Kramm',queries[1])

    def test_old_apple_verdict_is_rechecked_but_current_verdict_is_cached(self):
        plan=dict(query='portrait',entity='person');key=match_key(plan)
        for stored,expected in [(None,1),(key,0)]:
            assets={'image.jpg':dict(vision_verified=True,vision_relevant=True,vision_model='apple-foundation-models',
                                     vision_match_key=stored)}
            def analyze(plan,pending,*args):
                return [dict(index=0,**choice(),match_key=key)] if pending else []
            with patch.object(clip_ranker,'is_available',return_value=True),\
                 patch.object(clip_ranker,'analyze_local',side_effect=analyze) as call:
                result=clip_ranker.rank_files('portrait',['image.jpg'],assets,plan=plan)
            self.assertEqual(len(call.call_args.args[1]),expected);self.assertEqual(result,['image.jpg'])
        self.assertNotEqual(key,match_key({**plan,'context':'Different event in 1917'}))
        assets={'image.jpg':dict(vision_verified=True,vision_relevant=True,vision_score=.99,
                                 vision_model='apple-foundation-models')}
        error=dict(index=0,relevant=False,score=0,confidence=0,start=0,end=0,
                   reason='Local model unavailable',needs_review=True)
        with patch.object(clip_ranker,'is_available',return_value=True),\
             patch.object(clip_ranker,'analyze_local',return_value=[error]):
            clip_ranker.rank_files('portrait',['image.jpg'],assets,plan=plan)
        self.assertFalse(assets['image.jpg']['vision_verified'])
        self.assertFalse(assets['image.jpg']['vision_relevant'])
        self.assertTrue(assets['image.jpg']['vision_needs_review'])


if __name__ == '__main__':
    unittest.main()
