import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image
import app as module
import stock_downloader as sd


class SearchSpeedTests(unittest.TestCase):
    def test_google_precedes_archive_including_fallback(self):
        plan = {"type": "photo", "query": "Heino portrait", "entity": "Heino",
                "source_policy": ["archive", "editorial"]}
        self.assertEqual(sd._search_plan(plan)["source_policy"], ["editorial", "archive"])
        fallback = sd._fallback_plan(plan, {"type": "photo", "role": "photo", "query": "Heino",
                                          "source_policy": ["archive", "editorial"]})
        self.assertEqual(fallback["source_policy"], ["editorial", "archive"])
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sd, "_fetch_reserp", return_value=[str(Path(folder)/f"found{i}.jpg") for i in range(3)]) as google, \
             patch.object(sd, "_fetch_wikimedia") as archive:
            self.assertTrue(sd.download_for_chunk(plan, 0, folder, reserp_mode=True))
            google.assert_called_once()
            archive.assert_not_called()

    def test_transient_errors_do_not_disable_later_scenes(self):
        health = {}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(sd, "_fetch_reserp", side_effect=requests.Timeout("temporary")) as fetch:
            for index in range(7):
                context = sd.retrieval_context()
                context["provider_failures"] = health
                plan = {"type": "photo", "query": "portrait", "entity": "Heino", "source_policy": ["editorial"]}
                self.assertEqual(sd.download_for_chunk(plan, index, folder, reserp_mode=True, retrieval=context), [])
            self.assertGreaterEqual(fetch.call_count, 7)
            self.assertEqual(health, {})

    def test_api_retry_and_cache_share_the_request_budget(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sd, "OUTPUT_DIR", folder), \
             patch.object(sd.time, "sleep"):
            fetch = unittest.mock.Mock(side_effect=[requests.Timeout("temporary"), [{"image": "ok"}]])
            context = sd.retrieval_context(3)
            self.assertEqual(sd._cached_json("ReSERP-test", "portrait", fetch, None, context), [{"image": "ok"}])
            self.assertEqual(context["used"], 2)
            fresh = sd.retrieval_context(3)
            self.assertEqual(sd._cached_json("ReSERP-test", "portrait", fetch, None, fresh), [{"image": "ok"}])
            self.assertEqual(fresh["used"], 0)
            self.assertEqual(fetch.call_count, 2)

    def test_missing_only_keeps_completed_shot_and_manual_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            name = "scene_missing_test"
            root = Path(folder, name); downloads = root / "downloads"; downloads.mkdir(parents=True)
            Image.new("RGB", (640, 360), "blue").save(downloads / "chosen.jpg")
            chunks = []
            for index in range(2):
                chunk = {"id": index, "type": "photo", "query": "Heino portrait", "entity": "Heino",
                         "entity_type": "person", "entity_scope": "context", "search_mode": "exact",
                         "source_policy": ["archive", "editorial"], "start": index*3, "end": (index+1)*3,
                         "duration": 3, "preset": "PHOTO_STATIC", "files": ["chosen.jpg"] if index==0 else []}
                module.validate_scene(chunk); module.validate_search_plan(chunk); chunks.append(chunk)
            original = copy.deepcopy(chunks[0])
            asset = {"source": "Local", "perceptual_hash": "0123456789abcdef"}
            session = {"scene_name": name, "scene_dir": str(root), "busy": False, "cancel": threading.Event(),
                       "audio_duration": 6, "language": "en", "video_mode": "faceless", "processing_mode": "quality",
                       "query_budget": 6, "main_entity_type": "generic", "chunks": chunks,
                       "assets": {"chosen.jpg": copy.deepcopy(asset)}, "file_overrides": {"0": ["chosen.jpg"]},
                       "retrieval_debug": {"0": [{"source": "original"}]}}
            def download(plan, cid, *args, **kwargs):
                self.assertEqual(cid, 1)
                self.assertEqual(plan["source_policy"], ["editorial", "archive"])
                self.assertEqual(plan["_processing_mode"], "fast")
                path = downloads/"new.jpg"; Image.new("RGB", (640, 360), "red").save(path)
                kwargs["asset_callback"](path.name, {"source": "Google"})
                return [str(path)]
            module._sessions[name] = session
            try:
                with patch.object(module, "OUTPUT_DIR", folder), patch.object(module, "download_for_chunk", side_effect=download) as search:
                    response = module.app.test_client().post("/resume_search", json={"scene_name": name, "missing_only": True, "processing_mode": "fast"})
                    body = response.get_data(as_text=True)
                    self.assertNotIn('"error"', body)
                    search.assert_called_once()
                self.assertEqual(session["chunks"][0], original)
                self.assertEqual(session["assets"]["chosen.jpg"], asset)
                self.assertEqual(session["file_overrides"], {"0": ["chosen.jpg"]})
                self.assertEqual(session["retrieval_debug"]["0"], [{"source": "original"}])
                self.assertEqual(session["chunks"][1]["files"], ["new.jpg"])
                self.assertFalse(session["busy"])
                saved = json.loads((root/"project.json").read_text())
                self.assertEqual(saved["chunks"][0], original)
            finally:
                module._sessions.pop(name, None)


if __name__ == "__main__":
    unittest.main()
