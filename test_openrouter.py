"""Offline regression checks: python -m unittest test_openrouter -v."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image

import clip_ranker
import stock_downloader as media
import vision_ranker as vision


def result(index, score, confidence=.95, relevant=True):
    return dict(index=index, score=score, confidence=confidence, relevant=relevant,
                start=0., end=5., reason="visible evidence")


class OpenRouterTests(unittest.TestCase):
    def test_apple_provider_uses_local_fm_with_images_and_schema(self):
        from unittest.mock import Mock
        schema = vision._apple_schema()
        self.assertEqual(schema["x-order"], ["candidates"])
        self.assertEqual(schema["$defs"]["Candidate"]["x-order"],
                         ["index", "relevant", "score", "confidence", "start", "end", "reason"])
        evidence = vision._apple_evidence_schema()
        self.assertEqual(evidence["x-order"][0], "description")
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder, "photo.png")
            Image.new("RGB", (800, 450), "navy").save(photo)
            described = Mock(returncode=0, stdout='{"description":"blue image","scene_type":"graphic","visible_subjects":"blue","visible_actions":"none","visible_text":"none","quality":0.9,"usable":true}', stderr="")
            selected = Mock(returncode=0, stdout='{"relevant":true,"score":0.9,"confidence":0.8,"start":0,"end":0,"reason":"match","subject_match":"not_required","visual_match":"supported","context_match":"not_required"}', stderr="")
            with patch.object(vision.subprocess, "run", side_effect=[described, selected]) as call:
                output = vision._apple_rank({"query": "navy image"}, [photo], 5)
            command = call.call_args_list[0].args[0]
            self.assertIn("--image", command)
            self.assertIn("--schema", command)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(output[0]["model"], "apple-foundation-models")
            self.assertTrue(output[0]["relevant"])

    def test_primary_only_and_conditional_fallback(self):
        cases = [([result(0, .92), result(1, .62)], None),
                 ([result(0, .92, .55), result(1, .62)], "low_confidence"),
                 ([result(0, .92), result(1, .90)], "close_scores")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "photo.jpg")
            Image.new("RGB", (800, 450)).save(path)
            for primary, reason in cases:
                with self.subTest(reason=reason), patch.object(vision, "_openrouter_request", side_effect=[
                        primary, [result(0, .5, relevant=False), result(1, .96)]]) as call:
                    ranked = vision._openrouter_rank({}, [path, path], 5)
                    self.assertEqual(call.call_count, 2 if reason else 1)
                    self.assertEqual(call.call_args_list[0].args[0], "qwen/qwen3.7-flash")
                    if reason:
                        self.assertEqual(call.call_args_list[1].args[0], "qwen/qwen3.8-flash")
                        self.assertEqual(ranked[0]["fallback_reason"], reason)
                        self.assertEqual(ranked[1]["primary_score"], primary[1]["score"])
                        self.assertEqual(ranked[1]["score"], .96)

    def test_primary_error_never_triggers_expensive_fallback(self):
        with patch.object(vision, "_openrouter_request", side_effect=requests.HTTPError("402")) as call:
            with self.assertRaises(requests.HTTPError): vision._openrouter_rank({}, [], 5)
            self.assertEqual(call.call_count, 1)

    def test_payment_error_pauses_requests_without_fallback(self):
        from unittest.mock import Mock
        with patch.object(vision, "_OPENROUTER_BLOCKED", False), patch.object(vision, "VISION_PROVIDER", "openrouter"), \
                patch.object(vision.requests, "post", return_value=Mock(status_code=402)) as call:
            with self.assertRaisesRegex(RuntimeError, "402"):
                vision._openrouter_request("qwen/qwen3.7-flash", [], {}, 1, 5)
            self.assertFalse(vision.is_available())
            with self.assertRaisesRegex(RuntimeError, "приостановлен"):
                vision._openrouter_request("qwen/qwen3.7-flash", [], {}, 1, 5)
            self.assertEqual(call.call_count, 1)

    def test_malformed_reply_is_repaired_by_same_model(self):
        import json
        from unittest.mock import Mock
        bad, good = Mock(status_code=200), Mock(status_code=200)
        bad.json.return_value = {"choices": [{"message": {"content": '{"properties": {}}'}}]}
        good.json.return_value = {"choices": [{"message": {"content": json.dumps({"candidates": [result(0, .9)]})}}]}
        with patch.object(vision.requests, "post", side_effect=[bad, good]) as call:
            output = vision._openrouter_request("qwen/qwen3.7-flash", [], {}, 1, 5)
        self.assertEqual([item.kwargs["json"]["model"] for item in call.call_args_list], ["qwen/qwen3.7-flash"]*2)
        self.assertTrue(output[0]["relevant"])

    def test_invalid_json_and_nonfinite_numbers_are_not_visual_evidence(self):
        from unittest.mock import Mock
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"candidates": []}'}}]}
        with patch.object(vision.requests, "post", return_value=response):
            with self.assertRaisesRegex(ValueError, "некорректный JSON"):
                vision._openrouter_request("qwen/qwen3.7-flash", [], {}, 2, 5)
        self.assertFalse(vision._clean_results({"candidates": [result(0, float("nan"))]}, 1, 5)[0]["relevant"])

    def test_metadata_shortlist_precedes_vision(self):
        paths = [f"{i}.jpg" for i in range(8)]
        assets = {path: {"search_text": "Berlin" if path in paths[4:] else "unrelated"} for path in paths}
        for available in (True, False):
            with self.subTest(available=available), \
                    patch.object(clip_ranker, "is_available", return_value=available), \
                    patch.object(clip_ranker, "analyze_local", return_value=None) as call:
                output = clip_ranker.rank_files("Berlin", paths, assets, plan={"query": "Berlin"})
                self.assertEqual(output, paths[4:])
                if available:
                    self.assertEqual(call.call_args.args[1], paths[4:])
                else:
                    call.assert_not_called()

    def test_fast_mode_checks_only_two_candidates(self):
        paths = [f"{i}.jpg" for i in range(6)]
        assets = {path: {"search_text": "Berlin parliament " + path} for path in paths}
        checked = [result(0, .9), result(1, .8)]
        with patch.object(clip_ranker, "is_available", return_value=True), \
                patch.object(clip_ranker, "analyze_local", return_value=checked) as call:
            output = clip_ranker.rank_files("Berlin parliament", paths, assets,
                                            plan={"query": "Berlin", "_processing_mode": "fast"})
        self.assertEqual(len(output), 2)
        self.assertEqual(len(call.call_args.args[1]), 2)
        self.assertTrue(call.call_args.args[0]["_fast_vision"])

    def test_fast_apple_mode_uses_one_short_request_per_candidate(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder, "photo.png")
            Image.new("RGB", (800, 450), "navy").save(photo)
            selected = Mock(returncode=0, stdout='{"relevant":true,"score":0.9,"confidence":0.8,"start":0,"end":0,"reason":"match","subject_match":"not_required","visual_match":"supported","context_match":"not_required"}', stderr="")
            with patch.object(vision.subprocess, "run", return_value=selected) as call:
                output = vision._apple_rank({"query": "navy image", "_fast_vision": True}, [photo], 5)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["timeout"], 45)
        self.assertIn("--image", call.call_args.args[0])
        self.assertTrue(output[0]["relevant"])

    def test_unverified_guardrail_candidate_precedes_verified_rejection(self):
        paths = ["guardrail.jpg", "rejected.jpg"]
        assets = {
            "guardrail.jpg": {"search_text": "DNA laboratory", "vision_verified": False,
                              "vision_needs_review": True},
            "rejected.jpg": {"search_text": "TED talk", "vision_verified": True,
                             "vision_relevant": False, "vision_score": .1},
        }
        with patch.object(clip_ranker, "is_available", return_value=False):
            ranked = clip_ranker.rank_files("DNA laboratory", paths, assets, plan={"query": "DNA laboratory"})
        self.assertEqual(ranked[0], "guardrail.jpg")

    def test_youtube_preview_timestamps_map_to_source_and_stop_at_cut(self):
        mappings = [{"preview_start": 0, "preview_end": 12, "source_start": 100},
                    {"preview_start": 12, "preview_end": 24, "source_start": 500}]
        with patch.object(vision, "VISION_PROVIDER", "openrouter"), \
                patch.object(vision, "is_available", return_value=True), \
                patch.object(vision, "analyze_local", return_value=[{**result(0, .92), "start": 10, "end": 16}]):
            output = vision.analyze_youtube({}, [{"webpage_url": "https://youtube.com/watch?v=example"}],
                                           preview_loader=lambda *args: ("preview.mp4", mappings))
        self.assertEqual((output[0]["start"], output[0]["end"]), (110, 112))
        self.assertEqual(output[0]["coverage"], "sampled_windows")

    def test_subtitles_choose_relevant_windows(self):
        cues = [(0, "weather today"), (110, "Friedrich Merz in Berlin parliament"), (600, "sport report")]
        starts = media._preview_windows(cues, [], {"query": "Friedrich Merz Berlin parliament"}, 900, 15)
        self.assertIn(109, starts)
        self.assertLessEqual(len(starts), 3)

    def test_unavailable_youtube_candidate_does_not_cancel_other_previews(self):
        windows = [{"preview_start": 0, "preview_end": 12, "source_start": 100}]
        def loader(item, directory, index):
            if index == 0: raise RuntimeError("Video unavailable")
            return "available.mp4", windows
        with patch.object(vision, "VISION_PROVIDER", "openrouter"), patch.object(vision, "is_available", return_value=True), \
                patch.object(vision, "analyze_local", return_value=[result(0, .9)]):
            output = vision.analyze_youtube({}, [{}, {}], preview_loader=loader)
        self.assertFalse(output[0]["relevant"])
        self.assertTrue(output[1]["relevant"])
        self.assertEqual(output[1]["start"], 100)


if __name__ == "__main__": unittest.main()
