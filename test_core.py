import io
import json
import os
import queue
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import stock_downloader
import vision_ranker
import app as app_module
from app import _keep_new_media, _prepare_build_chunks, _sessions, _sse_response, app
from clip_ranker import _order_by_scores
from ffmpeg_builder import _credit_filter, _probe_duration, _render_video_chunk, _template_whoosh
from presets import validate_scene
from whisperx_transcriber import _aligned_words, transcribe_audio


class ConfigTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Foreign Windows path applies to Mac/Linux")
    def test_output_directory_is_native_and_absolute(self):
        config_path = Path(app_module.__file__).with_name("config.py")
        expected = str(config_path.parent / "output")
        for configured, resolved in (("C:/video_assembler/output", expected),
                                     ("", expected), ("relative_output", os.path.abspath("relative_output"))):
            with self.subTest(configured=configured), patch.dict(os.environ, {"OUTPUT_DIR": configured}):
                self.assertEqual(runpy.run_path(str(config_path))["OUTPUT_DIR"], resolved)


class SessionTests(unittest.TestCase):
    def test_cancel_affects_only_requested_session(self):
        first = {"cancel": threading.Event()}
        second = {"cancel": threading.Event()}
        _sessions.update({"scene_001": first, "scene_002": second})
        try:
            response = app.test_client().post("/cancel", json={"scene_name": "scene_001"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(first["cancel"].is_set())
            self.assertFalse(second["cancel"].is_set())
        finally:
            _sessions.clear()

    def test_refreshing_progress_stream_does_not_cancel_session(self):
        session = {"scene_name": "scene_test", "cancel": threading.Event()}
        messages = queue.Queue()
        messages.put(json.dumps({"progress": "working"}))
        with app.test_request_context("/"):
            stream = iter(_sse_response(session, messages).response)
            next(stream)
        stream.close()
        self.assertFalse(session["cancel"].is_set())

    def test_restore_removes_small_stock_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            downloads = Path(folder, "downloads"); downloads.mkdir()
            (downloads / "small.jpg").touch()
            session = {"scene_name": "scene_quality", "scene_dir": folder,
                       "assets": {"small.jpg": {"source": "Pexels"}},
                       "chunks": [{"files": ["small.jpg"]}], "file_overrides": {}}
            with patch("app._safe_media_path", return_value=str(downloads / "small.jpg")), \
                    patch("app._has_minimum_image_resolution", return_value=False):
                app_module._discard_rejected_candidates(session)
            self.assertEqual(session["chunks"][0]["files"], [])
            self.assertEqual(session["assets"], {})


class TimelineTests(unittest.TestCase):
    def test_remotion_template_keeps_selected_media_and_whoosh(self):
        with tempfile.TemporaryDirectory() as scene_dir:
            downloads = Path(scene_dir, "downloads")
            downloads.mkdir()
            (downloads / "selected.jpg").touch()
            chunk = {"id": 0, "type": "photo", "query": "archive", "start": 0, "end": 5,
                     "duration": 5, "files": ["selected.jpg"], "template": "paper_card_bottom_left"}
            validate_scene(chunk)
            built = _prepare_build_chunks({"scene_dir": scene_dir, "chunks": [chunk], "assets": {}})[0]
            self.assertEqual(built["template"], "paper_card_bottom_left")
            self.assertEqual(built["_files"], [str(downloads / "selected.jpg")])
            self.assertIn(_template_whoosh().name, {"whoosh.mp3", "woosh1.wav", "woosh2.wav"})
            with self.assertRaisesRegex(ValueError, "Неизвестный Remotion-шаблон"):
                validate_scene({**chunk, "template": "other"})

    def test_duplicate_source_urls_are_hidden_from_later_scenes(self):
        files = ["old.jpg", "new.jpg", "local.jpg"]
        assets = {
            "old.jpg": {"original_url": "https://cdn.example/one.jpg"},
            "new.jpg": {"original_url": "https://cdn.example/two.jpg"},
            "local.jpg": {"source": "Локальный файл"},
        }
        self.assertEqual(_keep_new_media(files, assets, {"https://cdn.example/one.jpg"}), ["new.jpg", "local.jpg"])
        self.assertIn("editor_note_ru", app_module.LUNA_INSTRUCTIONS)
    def test_clip_orders_highest_score_first(self):
        self.assertEqual(_order_by_scores(["a", "b", "c"], [0.1, 0.9, 0.5]), ["b", "c", "a"])

    def test_credit_filter_is_optional_and_escapes_ffmpeg_colons(self):
        self.assertEqual(_credit_filter(None), "")
        self.assertIn("Источник\\: YouTube", _credit_filter("Источник: YouTube"))

    def test_missing_media_duration_is_kept(self):
        with tempfile.TemporaryDirectory() as scene_dir:
            downloads = os.path.join(scene_dir, "downloads")
            os.makedirs(downloads)
            for name in ("one.jpg", "two.jpg"):
                Path(downloads, name).touch()

            session = {
                "scene_dir": scene_dir,
                "chunks": [
                    {"id": 0, "type": "photo", "query": "a", "duration": 2, "files": []},
                    {"id": 1, "type": "photo", "query": "b", "duration": 3, "files": ["one.jpg"]},
                    {"id": 2, "type": "photo", "query": "c", "duration": 4, "files": []},
                    {"id": 3, "type": "photo", "query": "d", "duration": 5, "files": ["two.jpg"]},
                ],
            }

            chunks = _prepare_build_chunks(session)
            self.assertEqual([c["_chunk_id"] for c in chunks], [0, 1, 2, 3])
            self.assertEqual([c["_duration_override"] for c in chunks], [2, 3, 4, 5])
            self.assertEqual(chunks[0]["_files"], [])
            self.assertEqual(chunks[2]["_files"], [])

    def test_web_media_can_render_before_manual_rights_review(self):
        for source in ("reserp", "brightdata", "archive"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as scene_dir:
                downloads = Path(scene_dir, "downloads")
                downloads.mkdir()
                filename = f"chunk00_{source}_00.jpg"
                (downloads / filename).touch()
                (downloads / "chunk00_pexels_00.jpg").touch()
                session = {
                    "scene_dir": scene_dir,
                    f"{source}_mode": True,
                    "assets": {filename: {"source": "Example", "rights_confirmed": False}},
                    "chunks": [{"id": 0, "type": "photo", "query": "x", "duration": 3,
                                "files": [filename]}],
                }
                self.assertEqual(_prepare_build_chunks(session)[0]["_files"], [str(downloads / filename)])
                session["chunks"][0]["files"].append("chunk00_pexels_00.jpg")
                self.assertEqual(_prepare_build_chunks(session)[0]["_files"],
                                 [str(downloads / filename)])
                session["assets"][filename]["rights_confirmed"] = True
                for language, label in (("de", "Quelle"), ("en", "Source"),
                                        ("es", "Fuente"), ("pl", "Źródło")):
                    session["language"] = language
                    self.assertEqual(_prepare_build_chunks(session)[0]["credits"],
                                     {filename: f"{label}: Example"})

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
    def test_short_video_is_extended_to_requested_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "short.mp4")
            output = os.path.join(tmp, "extended.mp4")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "color=c=black:size=320x180:duration=0.4:rate=25",
                    "-c:v", "libx264", source,
                ],
                check=True,
                capture_output=True,
            )

            _render_video_chunk([source], output, 1.2)
            self.assertAlmostEqual(_probe_duration(output), 1.2, delta=0.08)


class UploadedAudioTests(unittest.TestCase):
    @staticmethod
    def _wav_bytes():
        data = io.BytesIO()
        with wave.open(data, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 32000)
        return data.getvalue()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
    def test_uploaded_voice_becomes_json_and_is_used_in_video(self):
        words = [{"word": "Морские", "start": 0.1, "end": 0.8},
                 {"word": "рыбы", "start": 0.9, "end": 1.8}]
        original = self._wav_bytes()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app_module, "OUTPUT_DIR", tmp), \
                patch("app.transcribe_audio", return_value=words) as transcribe:
            response = app.test_client().post("/prepare", data={
                "audio": (io.BytesIO(original), "../озвучка.WAV"), "youtube_mode": "1",
                "language": "en",
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn('"awaiting_timeline": true', response.get_data(as_text=True))
            scene_name = response.headers["X-Scene-Name"]
            session = _sessions[scene_name]
            try:
                voice = session["audio_path"]
                self.assertEqual(Path(voice).read_bytes(), original)
                self.assertEqual(Path(voice).name, "voiceover.wav")
                self.assertAlmostEqual(session["audio_duration"], 2.0)
                self.assertFalse(session["busy"])
                transcribe.assert_called_once()
                self.assertEqual(transcribe.call_args.kwargs["language"], "en")
                self.assertIs(transcribe.call_args.kwargs["cancel_event"], session["cancel"])
                exported = app.test_client().get(f"/timeline_input/{scene_name}")
                self.assertEqual(exported.status_code, 200)
                payload = json.loads(exported.get_data())
                exported.close()
                self.assertEqual(payload["text"], "Морские рыбы")
                self.assertEqual(payload["word_timestamps"], words)
                self.assertEqual(payload["audio_duration"], 2.0)
                self.assertEqual(payload["language"], "en")
                self.assertEqual(payload["transcriber"], "whisperx-large-v2")

                def download(chunk, index, scene_dir, **options):
                    path = Path(scene_dir, "downloads", "chunk00_pexels_00.jpg")
                    path.parent.mkdir(exist_ok=True)
                    path.touch()
                    return [str(path)]

                with patch("app.download_for_chunk", side_effect=download) as fetch, \
                        patch("app.rank_files", side_effect=lambda query, files, assets, progress: files), \
                        patch("app.build_video", return_value=(str(Path(tmp, "result.mp4")), {})) as build:
                    timeline = {"chunks": [{"type": "photo", "query": "reef fish", "start": 0, "end": 2}]}
                    imported = app.test_client().post("/import_timeline", data={
                        "scene_name": scene_name,
                        "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json"),
                    })
                    self.assertIn('"downloads_done": true', imported.get_data(as_text=True))
                    self.assertNotIn('"error"', imported.get_data(as_text=True))
                    self.assertTrue(fetch.call_args.kwargs["youtube_mode"])
                    build.assert_not_called()
                    assembled = app.test_client().post("/assemble", json={"scene_name": scene_name})
                    self.assertIn('"done": true', assembled.get_data(as_text=True))
                    build.assert_called_once()
                    self.assertEqual(build.call_args.kwargs["audio_path"], voice)
                    self.assertEqual(build.call_args.kwargs["audio_duration"], 2.0)
                    self.assertTrue(Path(session["scene_dir"], "timeline.json").is_file())
                    wrong_json = app.test_client().post("/import_timeline", data={
                        "scene_name": scene_name,
                        "timeline": (io.BytesIO(json.dumps({"word_timestamps": words}).encode()), "luna_input.json"),
                    })
                    self.assertEqual(wrong_json.status_code, 400)
                    self.assertIn("Загружен luna_input.json", wrong_json.get_json()["error"])
            finally:
                _sessions.pop(scene_name, None)

    def test_missing_unsupported_and_corrupt_uploads_are_rejected(self):
        client = app.test_client()
        self.assertEqual(client.post("/prepare", data={"text": "Без аудио"}).status_code, 400)
        self.assertEqual(client.post("/prepare", data={
            "audio": (io.BytesIO(b"not audio"), "notes.txt"),
        }).status_code, 400)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app_module, "OUTPUT_DIR", tmp), patch("app.check_ffmpeg", return_value=True), \
                patch("app.shutil.which", return_value="ffprobe"), \
                patch("app._probe_duration", return_value=None), patch("app.transcribe_audio") as transcribe:
            response = client.post("/prepare", data={"audio": (io.BytesIO(b"corrupt"), "voice.mp3")})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            transcribe.assert_not_called()

    def test_script_is_optional_and_transcription_failure_releases_session(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_module, "OUTPUT_DIR", tmp), \
                patch("app.check_ffmpeg", return_value=True), patch("app.shutil.which", return_value="ffprobe"), \
                patch("app._probe_duration", return_value=2.0), patch("app.transcribe_audio") as transcribe:
            for words, expected in (([{"word": "Рыбы", "start": 0, "end": 2}], "Точный текст"), ([], None)):
                with self.subTest(words=words):
                    transcribe.return_value = words
                    response = app.test_client().post("/prepare", data={
                        "audio": (io.BytesIO(self._wav_bytes()), "voice.wav"), "text": "Точный текст",
                    })
                    body = response.get_data(as_text=True)
                    scene_name = response.headers["X-Scene-Name"]
                    try:
                        self.assertFalse(_sessions[scene_name]["busy"])
                        path = Path(_sessions[scene_name]["scene_dir"], "luna_input.json")
                        if expected:
                            self.assertEqual(json.loads(path.read_text())["text"], expected)
                            self.assertIn('"awaiting_timeline": true', body)
                        else:
                            self.assertFalse(path.exists())
                            self.assertIn('"error"', body)
                    finally:
                        _sessions.pop(scene_name, None)

    def test_automatic_voice_and_anthropic_routes_are_removed(self):
        client = app.test_client()
        for endpoint in ("/process", "/voicer", "/voiceover"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(client.post(endpoint).status_code, 404)


class WhisperXTests(unittest.TestCase):
    def test_alignment_keeps_untimed_numbers_and_rejects_invalid_times(self):
        result = {"segments": [{"words": [
            {"word": "50"}, {"word": "fish", "start": 0.1, "end": 0.5},
            {"word": "2026", "start": None}, {"word": "swim", "start": 0.6, "end": 1.0},
        ]}]}
        self.assertEqual(_aligned_words(result), [
            {"word": "50 fish 2026", "start": 0.1, "end": 0.5},
            {"word": "swim", "start": 0.6, "end": 1.0},
        ])
        result["segments"][0]["words"] = [{"word": "fish", "start": 1, "end": 0}]
        with self.assertRaises(ValueError): _aligned_words(result)

    def test_language_is_validated_and_resume_cache_matches_language(self):
        with patch("app._create_scene") as create:
            response = app.test_client().post("/prepare", data={"language": "ru"})
            self.assertEqual(response.status_code, 400)
            create.assert_not_called()
        with tempfile.TemporaryDirectory() as folder, patch("app.transcribe_audio", return_value=[
                {"word": "Fish", "start": 0, "end": 1}]) as transcribe:
            voice = Path(folder, "voiceover.wav")
            voice.touch()
            session = {"scene_name": "scene_language", "scene_dir": folder, "audio_path": str(voice),
                       "audio_duration": 1, "chunks": [], "assets": {}, "language": "pl",
                       "busy": False, "cancel": threading.Event()}
            _sessions[session["scene_name"]] = session
            try:
                client = app.test_client()
                for language, expected_calls in (("en", 1), ("en", 1), ("de", 2), ("es", 3), ("pl", 4)):
                    response = client.post("/resume_prepare", json={"scene_name": session["scene_name"], "language": language})
                    self.assertIn('"awaiting_timeline": true', response.get_data(as_text=True))
                    self.assertEqual(transcribe.call_count, expected_calls)
                    self.assertEqual(transcribe.call_args.kwargs["language"], language)
                    self.assertEqual(json.loads(Path(folder, "luna_input.json").read_text())["language"], language)
                self.assertEqual(client.get("/project/scene_language").get_json()["language"], "pl")
            finally:
                _sessions.pop(session["scene_name"], None)

    def test_cancellation_terminates_running_whisperx_process(self):
        cancel, processes = threading.Event(), []
        real_popen = subprocess.Popen

        def start(command, **kwargs):
            self.assertIn("large-v2", command)
            self.assertIn("pl", command)
            process = real_popen([sys.executable, "-u", "-c",
                                  "import time; print('Performing transcription...', flush=True); time.sleep(30)"], **kwargs)
            processes.append(process)
            return process

        def progress(message):
            if message == "WhisperX: распознаю речь…": cancel.set()

        with tempfile.TemporaryDirectory() as folder, patch("whisperx_transcriber.subprocess.Popen", side_effect=start):
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                transcribe_audio(str(Path(folder, "voice.wav")), language="pl", progress_callback=progress, cancel_event=cancel)
            self.assertIsNotNone(processes[0].poll())
            self.assertEqual(list(Path(folder).iterdir()), [])


class EntityArchitectureTests(unittest.TestCase):
    CASES = [
        ("European eel", "species", "Anguilla anguilla", [], "Anguilla anguilla larva", "Anguilla rostrata larva"),
        ("Sigmund Freud", "person", None, [], "Freud, Sigmund — portrait 1876", "Anna Freud portrait"),
        ("Donald Trump", "person", None, [], "Trump, Donald — inauguration", "Donald Duck inauguration"),
        ("Aztecs", "culture", None, ["Aztec civilization"], "Aztec civilization codex", "Maya civilization codex"),
        ("Eiffel Tower", "object", None, [], "Eiffel steel tower in Paris", "Tokyo Tower"),
        ("Paris", "place", None, [], "Paris France map", "London England map"),
        ("Fall of the Berlin Wall", "event", None, [], "Berlin Wall fall November 1989", "Berlin Wall construction 1961"),
        ("International Council for the Exploration of the Sea", "organization", None, ["ICES"], "ICES scientific advice", "United Nations advice"),
    ]

    def test_explicit_entities_and_fallbacks_keep_local_identity_in_one_import(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_module, "OUTPUT_DIR", tmp):
            folder = Path(tmp, "scene_entities"); folder.mkdir()
            Path(folder, "luna_input.json").write_text('{"word_timestamps": []}')
            chunks = [{"type": "photo", "query": "main subject", "search_mode": "exact", "start": 0, "end": 1}]
            for index, (entity, kind, scientific, aliases, _, _) in enumerate(self.CASES, 1):
                chunk = {"type": "photo", "query": f"{entity} archive", "search_mode": "exact",
                         "entity": entity, "entity_type": kind, "entity_aliases": aliases,
                         "start": index, "end": index + 1,
                         "visual_fallbacks": [{"role": "illustration", "query": f"{entity} illustration"}]}
                if scientific:
                    chunk["scientific_name"] = scientific
                    chunk["negative_keywords"] = ["moray", "conger"]
                chunks.append(chunk)
            for entity, kind in (("Sigmund Freud", "person"), ("Paris", "place")):
                chunks.append({"type": "photo", "query": entity, "entity": entity, "entity_type": kind,
                               "start": len(chunks), "end": len(chunks) + 1, "preset": "PHOTO_STATIC"})
            session = {"scene_name": folder.name, "scene_dir": str(folder), "chunks": [], "assets": {},
                       "audio_duration": len(chunks), "busy": False, "cancel": threading.Event()}
            _sessions[folder.name] = session
            timeline = {"main_entity": "European eel", "main_entity_type": "species",
                        "scientific_name": "Anguilla anguilla", "chunks": chunks}
            plans = []
            try:
                with patch("app.download_for_chunk", side_effect=lambda plan, *args, **kwargs: plans.append(dict(plan)) or []):
                    response = app.test_client().post("/import_timeline", data={"scene_name": folder.name,
                        "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json")})
                    body = response.get_data(as_text=True)
                    self.assertIn('"downloads_done": true', body)
                    self.assertNotIn('"error"', body)
                self.assertEqual(plans[0]["entity"], "European eel")
                self.assertEqual(plans[0]["scientific_name"], "Anguilla anguilla")
                for plan, (entity, kind, scientific, _, metadata, wrong) in zip(plans[1:], self.CASES):
                    with self.subTest(entity=entity):
                        self.assertEqual(plan["entity"], entity)
                        self.assertEqual(plan["entity_type"], kind)
                        self.assertEqual(plan["entity_scope"], "context")
                        self.assertEqual(plan.get("scientific_name"), scientific)
                        stages = list(stock_downloader._retrieval_stages({**plan, "_retrieval": {}}))
                        for stage in stages:
                            self.assertEqual(stage["entity"], entity)
                            self.assertEqual(stage["entity_type"], kind)
                            self.assertEqual(stage.get("scientific_name"), scientific)
                        query = stock_downloader._planned_queries(stages[-1])[0]
                        if kind != "species":
                            self.assertNotIn("Anguilla", query)
                            self.assertNotIn("moray", query)
                            self.assertNotIn("conger", query)
                        self.assertTrue(stock_downloader._matches_plan(plan, metadata))
                        self.assertFalse(stock_downloader._matches_plan(plan, wrong))
                        self.assertTrue(stock_downloader._matches_plan(stages[-1], metadata + " illustration"))
                self.assertEqual([p["entity"] for p in plans[-2:]], ["Sigmund Freud", "Paris"])
                self.assertTrue(all("scientific_name" not in p for p in plans[-2:]))
                saved = json.loads(Path(folder, "timeline.json").read_text())
                self.assertEqual(saved["main_entity_type"], "species")
                self.assertEqual(saved["chunks"][2]["entity"], "Sigmund Freud")
                del _sessions[folder.name]
                restored = app.test_client().get(f"/project/{folder.name}").get_json()
                self.assertEqual(restored["chunks"][2]["entity_type"], "person")
                self.assertEqual(restored["main_entity_type"], "species")
                self.assertIn("entity_type", app.test_client().get(f"/timeline_input/{folder.name}").get_json()["instructions"])
            finally:
                _sessions.pop(folder.name, None)

    def test_explicit_entity_wins_even_with_main_scope_and_without_type(self):
        for entity, _, _, _, _, _ in self.CASES[1:]:
            with self.subTest(entity=entity):
                plan = stock_downloader.inherit_main_entity(
                    {"query": entity, "entity": entity, "entity_scope": "main"}, "European eel", "Anguilla anguilla", "species")
                self.assertEqual(plan["entity"], entity)
                self.assertEqual(plan["entity_type"], "generic")
                self.assertNotIn("scientific_name", plan)
        plan = stock_downloader.inherit_main_entity(
            {"query": "Lion", "search_mode": "exact", "entity": "Lion", "entity_type": "species", "scientific_name": "Panthera leo"},
            "European eel", "Anguilla anguilla", "species")
        self.assertEqual(plan["scientific_name"], "Panthera leo")
        self.assertTrue(stock_downloader._matches_plan(plan, "Panthera leo in Kenya"))
        self.assertFalse(stock_downloader._matches_plan(plan, "Panthera tigris"))
        unnamed = stock_downloader._search_plan({"query": "European eel larva"})
        self.assertNotIn("entity", unnamed)
        self.assertNotIn("scientific_name", unnamed)
        self.assertNotIn("negative_keywords", unnamed)

    def test_non_species_taxa_are_removed_and_independent_fallbacks_stay_independent(self):
        for kind in stock_downloader.ENTITY_TYPES - {"species"}:
            with self.subTest(kind=kind):
                plan = stock_downloader.inherit_main_entity({"query": "local subject", "search_mode": "exact", "entity": "Local subject",
                    "entity_type": kind, "scientific_name": "Anguilla anguilla"}, "European eel", "Anguilla anguilla")
                self.assertNotIn("scientific_name", plan)
                self.assertNotIn("Anguilla", stock_downloader._planned_queries(plan)[0])
                with self.assertRaisesRegex(ValueError, "scientific_name"):
                    stock_downloader.validate_search_plan({**plan, "scientific_name": "Anguilla anguilla"})
        plan = stock_downloader._search_plan({"query": "Eiffel Tower", "entity": "Eiffel Tower", "entity_type": "object",
            "negative_keywords": ["replica"], "visual_fallbacks": [
                {"role": "map", "query": "Paris map", "entity": "Paris", "entity_type": "place", "search_mode": "exact"},
                {"role": "environment", "query": "river water", "search_mode": "broll"},
                {"role": "illustration", "query": "Eiffel Tower illustration", "entity": "Eiffel Tower", "entity_type": "object"}]})
        stock_downloader.validate_search_plan(plan)
        stages = list(stock_downloader._retrieval_stages({**plan, "_retrieval": {}}))
        environment, map_plan, illustration = stages[2:]
        self.assertNotIn("entity", environment)
        self.assertNotIn("negative_keywords", environment)
        self.assertEqual(map_plan["entity"], "Paris")
        self.assertNotIn("negative_keywords", map_plan)
        self.assertTrue(stock_downloader._matches_plan(map_plan, "Paris map"))
        self.assertEqual(illustration["entity"], "Eiffel Tower")
        self.assertNotIn("negative_keywords", illustration)
        for invalid in ("animal", [], None):
            with self.assertRaises(ValueError):
                stock_downloader.validate_search_plan({"query": "subject", "entity_type": invalid})

    def test_changing_main_topic_drops_previous_project_taxon(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_module, "OUTPUT_DIR", tmp):
            folder = Path(tmp, "scene_topic"); folder.mkdir()
            session = {"scene_name": folder.name, "scene_dir": str(folder), "chunks": [], "assets": {},
                       "audio_duration": 1, "busy": False, "cancel": threading.Event(),
                       "main_entity": "European eel", "scientific_name": "Anguilla anguilla", "main_entity_type": "species"}
            _sessions[folder.name] = session
            try:
                for main, kind, scientific in [("Donald Trump", None, None), ("Aztecs", "culture", None),
                                                ("Lion", None, "Panthera leo"), ("Paris", "place", None)]:
                    with self.subTest(main=main), patch("app.download_for_chunk", return_value=[]) as download:
                        timeline = {"main_entity": main, "chunks": [{"type": "photo", "query": main, "start": 0, "end": 1}]}
                        if kind:
                            timeline["main_entity_type"] = kind
                        if scientific:
                            timeline["scientific_name"] = scientific
                        response = app.test_client().post("/import_timeline", data={"scene_name": folder.name,
                            "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json")})
                        self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                        plan = download.call_args.args[0]
                        self.assertEqual(plan["entity"], main)
                        self.assertEqual(plan["entity_type"], kind or ("species" if scientific else "generic"))
                        self.assertEqual(plan.get("scientific_name"), scientific)
            finally:
                _sessions.pop(folder.name, None)


class BrightDataTests(unittest.TestCase):
    def test_adaptive_early_stop_uses_one_two_or_three_requests_and_six_only_for_empty_exact(self):
        plan = {"type": "photo", "query": "European eel larva", "search_mode": "exact",
                "entity": "European eel", "scientific_name": "Anguilla anguilla", "required_terms": ["larva"],
                "search_queries": ["European eel larva", "European eel leptocephalus", "European eel unused_variant"],
                "visual_fallbacks": [{"role": "environment", "search_mode": "broll", "query": "river water"}]}
        def image(name, title="Anguilla anguilla larva"):
            url = f"https://research.example/{name}.jpg"
            return {"image_url": url, "original_image": url, "title": title,
                    "url": "https://research.example/animal", "link": "https://research.example/animal"}
        a, b, c = [image(name) for name in "abc"]
        cases = [
            ([[image("wrong", "moray larva"), a, a, b, c]], 1, 3, "exact"),
            ([[a], [a, b, c]], 2, 3, "exact"),
            ([[a], [], [b, c]], 3, 3, "exact"),
            ([[], [], [a]], 3, 1, "exact"),
            ([[], [], [], [], [], [image(name, "river water") for name in "def"]], 6, 3, "environment"),
        ]
        for batches, expected_requests, expected_files, role in cases:
            with self.subTest(requests=expected_requests, role=role), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                    patch.object(stock_downloader, "RESERP_API_KEY", "test-key"), \
                    patch.object(stock_downloader, "BRIGHTDATA_API_KEY", "test-key"), \
                    patch.object(stock_downloader.requests, "post") as post, \
                    patch.object(stock_downloader, "_download_file", return_value=True), \
                    patch.object(stock_downloader, "_fetch_pexels") as pexels:
                post.return_value.json.side_effect = [{"ok": True, "results": {"images": batch}, "images": batch}
                                                      for batch in batches]
                rows, messages = [], []
                context = stock_downloader.retrieval_context(debug_callback=rows.append)
                chunk = dict(plan)
                files = stock_downloader.download_for_chunk(chunk, 0, tmp, reserp_mode=True, brightdata_mode=True,
                                                            retrieval=context, progress_callback=messages.append)
                self.assertEqual(len(files), expected_files)
                self.assertEqual(chunk["visual_role"], role)
                self.assertEqual(post.call_count, expected_requests)
                self.assertEqual(context["used"], expected_requests)
                self.assertEqual(rows[-1]["requests_used"], expected_requests)
                self.assertEqual(rows[-1]["max_requests"], 6)
                self.assertIn("requests_used / max_requests", messages[-1])
                pexels.assert_not_called()
                self.assertTrue(all("unused_variant" not in call.kwargs["json"]["url"] for call in post.call_args_list))
                if expected_requests >= 3:
                    self.assertIn("api.reserp.ai", post.call_args_list[0].args[0])
                    self.assertIn("api.reserp.ai", post.call_args_list[1].args[0])
                    self.assertIn("api.brightdata.com", post.call_args_list[2].args[0])
                if expected_requests == 1:
                    # Already sufficient cached candidates need zero external requests.
                    cached = stock_downloader.retrieval_context(debug_callback=rows.append)
                    stock_downloader.download_for_chunk(dict(plan), 1, tmp, reserp_mode=True, brightdata_mode=True,
                                                        retrieval=cached)
                    self.assertEqual(post.call_count, 1)
                    self.assertEqual(rows[-1]["requests_used"], 0)
                    self.assertTrue(rows[-1]["cache_hit"])

    def test_shared_budget_cache_and_strict_fallback_order(self):
        plan = {"type": "photo", "query": "European eel swimming", "search_mode": "exact",
                "entity": "European eel", "scientific_name": "Anguilla anguilla", "required_terms": ["swimming"],
                "search_queries": ["European eel swimming", "European eel underwater"],
                "visual_fallbacks": [
                    {"role": "broll", "type": "video", "search_mode": "broll", "query": "river water"},
                    {"role": "illustration", "search_mode": "exact", "query": "eel diagram"},
                    {"role": "environment", "search_mode": "broll", "query": "river current"}]}
        rows, context = [], stock_downloader.retrieval_context(3)
        context["debug"] = rows.append
        stock_downloader.validate_search_plan(plan)
        stages = list(stock_downloader._retrieval_stages({**stock_downloader._search_plan(plan), "_retrieval": context}))
        self.assertEqual([s["role"] for s in stages], ["exact", "exact_no_action", "environment", "illustration", "broll"])
        self.assertEqual(stages[1]["required_terms"], ["swimming"])
        self.assertEqual(stages[3]["scientific_name"], "Anguilla anguilla")
        self.assertNotIn("scientific_name", stages[2])
        # A context entity must not acquire the animal's taxon from stale query text.
        self.assertNotIn("scientific_name", stock_downloader._search_plan({"entity": "Aristotle", "query": "Aristotle European eel"}))
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader, "RESERP_API_KEY", "test-key"), \
                patch.object(stock_downloader, "BRIGHTDATA_API_KEY", "test-key"), \
                patch.object(stock_downloader.requests, "post") as post, \
                patch.object(stock_downloader, "_download_file") as download, \
                patch.object(stock_downloader, "_fetch_pexels", return_value=[]) as pexels, \
                patch.object(stock_downloader, "_fetch_pixabay", return_value=[]), \
                patch.object(stock_downloader, "_fetch_unsplash", return_value=[]), \
                patch.object(stock_downloader, "_fetch_wikimedia", return_value=[]):
            post.return_value.json.return_value = {"ok": True, "results": {"images": []}, "images": []}
            options = {"reserp_mode": True, "brightdata_mode": True, "retrieval": context, "per_source": 3}
            self.assertEqual(stock_downloader.download_for_chunk(dict(plan), 0, tmp, **options), [])
            self.assertEqual(post.call_count, 3)
            self.assertEqual(context["used"], 3)
            self.assertTrue(any("error" in row and "Лимит" in row["error"] for row in rows))
            self.assertEqual(pexels.call_args.kwargs["plan"]["role"], "broll")
            # Another panel shares the exhausted budget. Cache hits remain usable.
            cache_info = {}
            stock_downloader._cached_json("ReSERP-v2", post.call_args_list[0].kwargs["json"]["url"],
                                         lambda: self.fail("cache miss"), None, context, cache_info)
            self.assertTrue(cache_info["hit"])
            stock_downloader.download_for_chunk(dict(plan), 1, tmp, **options)
            self.assertEqual(post.call_count, 3)
            download.assert_not_called()
            self.assertTrue(all(row["received"] == row["accepted"] + row["rejected"] + row["not_selected"] for row in rows))
        # Sequential generic sources share the same hard limit.
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "PEXELS_API_KEY", "test-key"), \
                patch.object(stock_downloader, "PIXABAY_API_KEY", "test-key"), \
                patch.object(stock_downloader, "UNSPLASH_ACCESS_KEY", "test-key"), \
                patch.object(stock_downloader.requests, "get") as get:
            get.return_value.json.return_value = {"photos": [], "hits": [], "results": [], "query": {"search": []}}
            context = stock_downloader.retrieval_context(1)
            stock_downloader.download_for_chunk({"type": "photo", "query": "river water", "search_mode": "broll"},
                                                0, tmp, retrieval=context)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(context["used"], 1)

    def test_perceptual_dedup_anti_repeat_url_normalization_and_source_score(self):
        import random
        from PIL import Image, ImageEnhance
        from clip_ranker import rank_files
        canonical = stock_downloader.canonical_media_url
        self.assertEqual(canonical("http://CDN.example/fish.jpg?id=2&w=600&utm_source=a#x"),
                         canonical("https://cdn.example/fish.jpg?id=2&w=1920"))
        self.assertNotEqual(canonical("https://cdn.example/fish?id=2"), canonical("https://cdn.example/fish?id=3"))
        with tempfile.TemporaryDirectory() as tmp:
            original, near, other = [str(Path(tmp, name)) for name in ("original.jpg", "near.jpg", "other.jpg")]
            image = Image.frombytes("L", (144, 128), random.Random(17).randbytes(144*128)).resize((1920, 1080))
            image.save(original, quality=90)
            ImageEnhance.Brightness(image).enhance(1.02).save(near, quality=88)
            Image.frombytes("L", (144, 128), random.Random(99).randbytes(144*128)).resize((1920, 1080)).save(other, quality=90)
            hash_image = stock_downloader.image_perceptual_hash
            self.assertLessEqual((int(hash_image(original), 16)^int(hash_image(near), 16)).bit_count(), 4)
            self.assertGreater((int(hash_image(original), 16)^int(hash_image(other), 16)).bit_count(), 4)
            def download(url, dest, **kwargs):
                shutil.copyfile(original if "preferred" in url else near if "variant" in url else other, dest)
                return True
            assets, rows, hashes = {}, [], set()
            context = stock_downloader.retrieval_context(6, image_hashes=hashes, debug_callback=rows.append)
            plan = {"query": "European eel", "search_mode": "exact", "entity": "European eel", "_retrieval": context}
            def record(name, domain="unknown.example"):
                return {"image_url": f"https://cdn.example/{name}.jpg", "page_url": f"https://{domain}/eel",
                        "source": domain, "search_text": "European eel", "width": 1920, "height": 1080}
            with patch.object(stock_downloader, "_download_file", side_effect=download) as fetch:
                files = stock_downloader._download_google_images(
                    [record("variant"), record("preferred", "research.gov"), record("other")], plan["query"], "reserp",
                    0, tmp, None, 3, 0, lambda name, asset: assets.update({name: asset}), plan)
                self.assertEqual(len(files), 2)
                self.assertIn("preferred", assets[os.path.basename(files[0])]["original_url"])
                self.assertEqual(rows[-1]["reasons"]["near_duplicate"], 1)
                self.assertEqual(len(hashes), 2)
                self.assertEqual(rank_files(plan["query"], list(reversed(files)), assets), files)
                # A later scene rejects a resized/tracked URL before download and a different URL by dHash.
                fetch.reset_mock()
                next_plan = {**plan, "_retrieval": stock_downloader.retrieval_context(6, context["seen"], hashes, rows.append)}
                tracked = record("preferred"); tracked["image_url"] += "?w=640&utm_source=test"
                result = stock_downloader._download_google_images([tracked, record("variant")], plan["query"], "reserp",
                    1, tmp, None, 3, 0, None, next_plan, context["seen"])
                self.assertEqual(result, [])
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(rows[-1]["reasons"]["duplicate_url"], 1)
                self.assertEqual(rows[-1]["reasons"]["near_duplicate"], 1)

    def test_project_entity_budget_and_debug_survive_restore_without_transcription(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_module, "OUTPUT_DIR", tmp):
            folder = Path(tmp, "scene_retrieval"); folder.mkdir()
            Path(folder, "luna_input.json").write_text('{"word_timestamps": []}')
            session = {"scene_name": folder.name, "scene_dir": str(folder), "chunks": [], "assets": {},
                       "audio_duration": 2, "reserp_mode": True, "busy": False, "cancel": threading.Event()}
            _sessions[folder.name] = session
            timeline = {"main_entity": "European eel", "scientific_name": "Anguilla anguilla", "query_budget": 3,
                        "chunks": [{"type": "photo", "query": "eel", "entity": "moray", "search_mode": "exact",
                                    "query_budget": 1, "start": 0, "end": .6},
                                   {"type": "photo", "query": "Aristotle portrait", "search_mode": "exact",
                                    "entity_scope": "context", "entity": "Aristotle", "start": .6, "end": 1.2},
                                   {"type": "photo", "query": "eel", "search_mode": "exact", "start": 1.2, "end": 2}]}
            plans, contexts = [], []
            def download(plan, *args, **options):
                plans.append(plan); contexts.append(options["retrieval"])
                stock_downloader._spend_query(options["retrieval"])
                stock_downloader._report_results({**plan, "_retrieval": options["retrieval"]}, None, "test", plan["query"], 0, [])
                return []
            client = app.test_client()
            try:
                with patch("app.transcribe_audio") as transcribe, patch("app.download_for_chunk", side_effect=download), \
                        patch("app.build_video") as build:
                    response = client.post("/import_timeline", data={"scene_name": folder.name,
                        "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json")})
                    self.assertIn('"downloads_done": true', response.get_data(as_text=True))
                    self.assertNotIn('"error"', response.get_data(as_text=True))
                    transcribe.assert_not_called(); build.assert_not_called()
                self.assertEqual(plans[0]["entity"], "moray")
                self.assertNotIn("scientific_name", plans[0])
                self.assertEqual(plans[1]["entity"], "Aristotle")
                self.assertNotIn("scientific_name", plans[1])
                self.assertEqual(plans[2]["scientific_name"], "Anguilla anguilla")
                self.assertIsNot(contexts[1], contexts[2])
                self.assertEqual(contexts[0]["limit"], 1)
                self.assertEqual(contexts[1]["used"], 1)
                self.assertEqual(json.loads(Path(folder, "timeline.json").read_text())["main_entity"], "European eel")
                del _sessions[folder.name]  # reload the persisted project, as after a server restart
                self.assertEqual(client.get(f"/project/{folder.name}").get_json()["query_budget"], 3)
                debug = client.get(f"/retrieval_debug/{folder.name}").get_json()
                self.assertEqual(debug["scientific_name"], "Anguilla anguilla")
                self.assertEqual(len(debug["scenes"]["1"]), 1)
                self.assertEqual(debug["request_usage"]["1"], {"requests_used": 1, "max_requests": 3})
                self.assertEqual(client.get(f"/timeline_input/{folder.name}").get_json()["main_entity"], "European eel")
                for invalid in (0, 7, 13, True, "6"):
                    bad = {**timeline, "query_budget": invalid}
                    response = client.post("/import_timeline", data={"scene_name": folder.name,
                        "timeline": (io.BytesIO(json.dumps(bad).encode()), "timeline.json")})
                    self.assertEqual(response.status_code, 400)
            finally:
                _sessions.pop(folder.name, None)

    def test_exact_search_routes_filters_caches_and_falls_back_without_vision(self):
        plan = {"type": "photo", "query": "European eel larva", "search_mode": "exact",
                "entity": "European eel", "scientific_name": "Anguilla anguilla", "required_terms": ["larva|larvae|leptocephalus"],
                "negative_keywords": ["moray", "conger", "electric eel", "Anguilla rostrata", "Anguilla japonica"]}
        assets, messages = {}, []
        def image(number, title="Anguilla anguilla larva", **extra):
            return {"image_url": f"https://research.example/asset-{number}.jpg", "title": title,
                    "url": "https://research.example/Anguilla_anguilla", **extra}
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader, "RESERP_API_KEY", "test-key"), \
                patch.object(stock_downloader, "BRIGHTDATA_API_KEY", "test-key"), \
                patch.object(stock_downloader.requests, "post") as post, \
                patch.object(stock_downloader, "_download_file", side_effect=lambda url, dest, **kwargs: "bad-size" not in url) as download, \
                patch.object(stock_downloader, "_fetch_brightdata", return_value=[]) as bright, \
                patch.object(stock_downloader, "_fetch_pexels", return_value=[]) as pexels, \
                patch.object(stock_downloader, "_fetch_pixabay", return_value=[]) as pixabay:
            post.return_value.json.return_value = {"ok": True, "results": {"images": [
                image("wrong", "European eel and moray larvae"), image("adult", "Anguilla anguilla adult"),
                image("known-small", original_width=320, original_height=180), image("bad-size"),
                image(1), image(2, "European eel leptocephalus"), image(3), image(4),
                image(5, image_url="https://c8.alamy.com/Anguilla-anguilla-larva.jpg"),
            ]}}
            options = {"per_source": 3, "reserp_mode": True, "brightdata_mode": True,
                       "asset_callback": lambda name, asset: assets.update({name: asset}), "progress_callback": messages.append}
            files = stock_downloader.download_for_chunk(dict(plan), 0, tmp, **options)
            self.assertEqual(len(files), 3)
            bright.assert_not_called(); pexels.assert_not_called(); pixabay.assert_not_called()
            self.assertEqual(post.call_count, 1)
            self.assertEqual(download.call_count, 5)  # two bounded waves, one invalid original
            queried = post.call_args.kwargs["json"]["url"]
            self.assertIn("Anguilla+anguilla", queried)
            self.assertIn("moray", queried)
            self.assertTrue(all(a["entity"] == "Anguilla anguilla" and not a["rights_confirmed"] for a in assets.values()))
            # Same query across scenes uses cache and skips already used URLs BEFORE download.
            excluded = {asset["original_url"] for asset in assets.values()}
            download.reset_mock()
            files = stock_downloader.download_for_chunk(dict(plan), 1, tmp, excluded_urls=excluded, **options)
            self.assertEqual(post.call_count, 2)  # cached R1, then one new alternate exact query
            self.assertEqual(len(files), 1)
            self.assertEqual(download.call_count, 2)  # the known-bad URL is skipped on the second exact query
            self.assertEqual(bright.call_args.args[4], 2)  # only missing candidates
            self.assertTrue(any("кэш" in message for message in messages))
            # Missing exact entity never becomes broad stock search.
            bright.reset_mock()
            self.assertEqual(stock_downloader.download_for_chunk({"type": "photo", "query": "unknown object"}, 2, tmp, **options), [])
            pexels.assert_not_called(); pixabay.assert_not_called(); bright.assert_not_called()
            # Explicit environment fallback is independent, not a substitute animal.
            environment = {"role": "environment", "type": "video", "query": "river water current", "search_mode": "broll"}
            fallback_plan = {**plan, "visual_fallbacks": [environment, {**environment, "role": "broll"}]}
            pexels.return_value = [os.path.join(tmp, "river.mp4")]
            with patch.object(stock_downloader, "_fetch_reserp", return_value=[]), \
                    patch.object(stock_downloader, "_fetch_unsplash", return_value=[]), \
                    patch.object(stock_downloader, "_fetch_wikimedia", return_value=[]):
                result = stock_downloader.download_for_chunk(fallback_plan, 3, tmp, **options)
            self.assertEqual(len(result), 1)
            self.assertEqual(fallback_plan["type"], "video")
            self.assertEqual(fallback_plan["visual_role"], "broll")
            self.assertEqual(pexels.call_args.kwargs["plan"]["role"], "broll")
            self.assertEqual(pexels.call_args.kwargs["plan"].get("entity"), None)
            # No vision imports/downloads even when ranking multiple images.
            import clip_ranker
            with patch("builtins.__import__", wraps=__import__) as imports:
                clip_ranker.rank_files(plan["query"], result * 2, assets)
            self.assertFalse(any(call.args[0] in {"torch", "transformers"} for call in imports.call_args_list))
            with self.assertRaises(ValueError):
                stock_downloader.validate_search_plan({**plan, "search_queries": ["a"] * 4})

    def test_explicit_video_photo_fallback_and_failed_requests_are_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader, "_fetch_youtube", return_value=[]), \
                patch.object(stock_downloader, "_fetch_reserp", side_effect=[["exact.jpg"], []]), \
                patch.object(stock_downloader, "_fetch_brightdata") as bright:
            plan = {"type": "video", "query": "European eel underwater", "entity": "European eel", "entity_type": "species", "scientific_name": "Anguilla anguilla",
                    "visual_fallbacks": [{"role": "photo", "type": "photo", "query": "European eel", "source_policy": ["editorial"]}]}
            self.assertEqual(stock_downloader.download_for_chunk(plan, 0, tmp, reserp_mode=True, youtube_mode=True), ["exact.jpg"])
            self.assertEqual(plan["type"], "photo")
            bright.assert_not_called()
            def fail(): raise ValueError("API failure")
            for _ in range(2):
                with self.assertRaises(ValueError): stock_downloader._cached_json("test", "query", fail, None)
            self.assertEqual(stock_downloader._cached_json("test", "query", lambda: ["success"], None), ["success"])
            self.assertFalse(stock_downloader._matches_plan(stock_downloader._search_plan({**plan, "negative_keywords": ["conger"]}), "Anguilla anguilla conger"))

    def test_original_images_and_source_are_saved_without_exposing_api_key(self):
        assets = {}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader, "BRIGHTDATA_API_KEY", "test-key"), \
                patch.object(stock_downloader, "BRIGHTDATA_SERP_ZONE", "test-zone"), \
                patch.object(stock_downloader.requests, "post") as post, \
                patch.object(stock_downloader, "_download_file", return_value=True) as download:
            post.return_value.json.return_value = {"images": [
                {"original_image": "https://c8.alamy.com/comp/watermarked.jpg", "source": "Alamy"},
                {"image": "data:image/jpeg;base64,thumbnail-only"},
                {"original_image": "file:///not-an-image"},
                None,
                {"original_image": "https://example.com/fish.PNG?size=original",
                 "link": "https://example.com/reef", "source": "Ocean Research"},
                {"original_image": "https://example.com/second.jpg"},
            ]}
            files = stock_downloader._fetch_brightdata(
                "fish & reef", 2, tmp, None, 1, 4, lambda name, asset: assets.update({name: asset}),
            )
            self.assertEqual(files, [os.path.join(tmp, "chunk02_brightdata_04.png")])
            download.assert_called_once_with("https://example.com/fish.PNG?size=original", files[0], headers={"Referer": "https://example.com/reef"})
            self.assertEqual(assets["chunk02_brightdata_04.png"], {
                "source": "Ocean Research", "page_url": "https://example.com/reef",
                "search_text": "",
                "image_url": "https://example.com/fish.PNG?size=original",
                "original_url": "https://example.com/fish.PNG?size=original", "rights_confirmed": False,
                "source_score": 0, "visual_role": "broll",
            })
            request = post.call_args.kwargs
            self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(request["json"], {
                "zone": "test-zone", "format": "raw",
                "url": "https://www.google.com/search?q=fish+%26+reef&tbm=isch&brd_json=json",
            })
            post.return_value.raise_for_status.assert_called_once()
            post.return_value.json.return_value = {"images": "unexpected HTML"}
            with self.assertRaises(ValueError):
                stock_downloader._fetch_brightdata("fish", 0, tmp, None, 1, 0, None)

    def test_commercial_previews_and_small_images_are_rejected(self):
        self.assertEqual(
            stock_downloader.normalize_search_query(
                "European eel natural history, documentary frame 004"
            ),
            "European eel natural history",
        )
        self.assertTrue(stock_downloader.is_rejected_stock_preview("https://www.shutterstock.com/image.jpg"))
        self.assertFalse(stock_downloader.is_rejected_stock_preview("https://commons.wikimedia.org/image.jpg"))
        self.assertFalse(stock_downloader.is_relevant_search_result("European eel underwater close up", "moray eels swimming"))
        self.assertFalse(stock_downloader.is_relevant_search_result("European eel underwater close up", "woman wrapping a flag"))
        self.assertFalse(stock_downloader.is_relevant_search_result("German Bundestag exterior Berlin evening", "german shorthaired pointer dog"))
        self.assertFalse(stock_downloader.is_relevant_search_result("Germany election weekend ballot box voters", "carousel dresden saxony germany"))
        self.assertTrue(stock_downloader.is_relevant_search_result("German Bundestag exterior Berlin evening", "Bundestag exterior Berlin"))
        un_plan = stock_downloader._search_plan({"type": "video", "query": "United Nations building New York",
                                                 "search_mode": "broll", "required_terms": ["United Nations|UN"]})
        self.assertFalse(stock_downloader._matches_plan(un_plan, "statue of liberty united states New York"))
        self.assertTrue(stock_downloader._matches_plan(un_plan, "United Nations headquarters building New York"))
        class Response:
            def close(self): pass
            headers = {"Content-Length": "4"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): return iter([b"test"])
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader.requests, "get", return_value=Response()), \
                patch.object(stock_downloader, "_is_valid_file", return_value=True), \
                patch.object(stock_downloader, "_has_minimum_image_resolution", return_value=False):
            destination = os.path.join(tmp, "small.jpg")
            self.assertFalse(stock_downloader._download_file("https://example.com/small.jpg", destination))
            self.assertFalse(os.path.exists(destination))

        class HtmlResponse:
            def close(self): pass
            headers = {"Content-Type": "text/html", "Content-Length": "12"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): return iter([b"not an image"])
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader.requests, "get", return_value=HtmlResponse()):
            destination = os.path.join(tmp, "page.jpg")
            self.assertFalse(stock_downloader._download_file("https://example.com/page.jpg", destination))
            self.assertFalse(os.path.exists(destination))

    def test_failed_google_url_is_not_downloaded_twice(self):
        failed = set()
        plan = {"query": "eel", "search_mode": "broll",
                "_retrieval": stock_downloader.retrieval_context(failed_urls=failed)}
        item = {"image_url": "https://example.com/eel.jpg", "page_url": "https://example.com/eel",
                "source": "Example", "search_text": "eel", "width": 1920, "height": 1080}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader, "_download_file", return_value=False) as download:
            stock_downloader._download_google_images([item], "eel", "reserp", 0, tmp, None, 1, 0, None, plan)
            rows = []
            plan["_retrieval"]["debug"] = rows.append
            stock_downloader._download_google_images([item], "eel", "reserp", 0, tmp, None, 1, 0, None, plan)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(rows[0]["reasons"]["failed_url_cache"], 1)

    def test_youtube_stops_after_three_empty_scenes(self):
        chunk = {"query": "European eel", "type": "video", "search_mode": "exact", "entity": "European eel"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader, "_fetch_youtube") as youtube:
            stock_downloader.download_for_chunk(chunk, 0, tmp, youtube_mode=True,
                                                youtube_health={"failures": 3})
        youtube.assert_not_called()

    def test_person_broll_requires_the_named_person(self):
        plan = {"type": "video", "query": "Friedrich Merz CDU speech", "entity": "Friedrich Merz",
                "entity_type": "person", "search_mode": "broll"}
        self.assertTrue(stock_downloader._matches_plan(plan, "Friedrich Merz speaks at CDU event"))
        self.assertFalse(stock_downloader._matches_plan(plan, "CDU speech by Boris Pistorius"))
        self.assertFalse(stock_downloader._matches_plan(plan, "Mercedes CDU event coverage"))

    def test_empty_official_tier_does_not_disable_youtube_for_later_tiers(self):
        chunk = {"query": "Friedrich Merz statement", "type": "video", "search_mode": "broll",
                 "source_policy": ["official", "youtube"]}
        health = {"failures": 0}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader, "YOUTUBE_TRUSTED_CHANNELS", set()), \
                patch.object(stock_downloader, "YOUTUBE_ALLOW_CREATIVE_COMMONS", True), \
                patch.object(stock_downloader, "_fetch_youtube", return_value=[]) as youtube:
            stock_downloader.download_for_chunk(chunk, 0, tmp, youtube_mode=True, youtube_health=health)
        youtube.assert_called_once()
        self.assertEqual(health["failures"], 0)

    def test_missing_key_does_not_make_a_request(self):
        with patch.object(stock_downloader, "BRIGHTDATA_API_KEY", ""), \
                patch.object(stock_downloader.requests, "post") as post:
            self.assertEqual(stock_downloader._fetch_brightdata("fish", 0, "unused", None, 1, 0, None), [])
            post.assert_not_called()

    def test_import_timeline_passes_brightdata_mode_and_waits_for_selection(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("app.download_for_chunk", return_value=[]) as download, \
                patch("app.rank_files", return_value=[]), patch("app.build_video") as build:
            Path(tmp, "downloads").mkdir()
            Path(tmp, "downloads", "old.jpg").touch()
            _sessions["scene_brightdata"] = {
                "scene_name": "scene_brightdata", "scene_dir": tmp,
                "chunks": [{"id": 0, "type": "photo", "query": "reef fish", "files": ["old.jpg"]}], "assets": {},
                "busy": False, "cancel": threading.Event(), "elderly_mode": False,
                "reserp_mode": False, "youtube_mode": False, "brightdata_mode": False,
            }
            try:
                timeline = {"chunks": [{"type": "photo", "query": "reef fish", "start": 0, "end": 3}]}
                response = app.test_client().post("/import_timeline", data={
                    "scene_name": "scene_brightdata",
                    "timeline": (io.BytesIO(json.dumps(timeline).encode()), "timeline.json"),
                    "brightdata_mode": "1",
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn('"brightdata_mode": true', response.get_data(as_text=True))
                self.assertTrue(download.call_args.kwargs["brightdata_mode"])
                self.assertEqual(_sessions["scene_brightdata"]["chunks"][0]["files"], [])
                build.assert_not_called()
            finally:
                _sessions.pop("scene_brightdata", None)


class SourcePolicyTests(unittest.TestCase):
    def test_gemini_rate_limit_waits_once_then_retries(self):
        class Response:
            def close(self): pass
            def __init__(self, status_code, text, headers=None):
                self.status_code, self.text, self.headers = status_code, text, headers or {}
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.text)
            def json(self): return json.loads(self.text)

        limited = Response(429, '{"error":{"message":"retry in 31s"}}')
        success = Response(200, json.dumps({"steps": [{"type": "model_output", "content": [
            {"type": "text", "text": '{"candidates": []}'}]}]}))
        with patch.object(vision_ranker, "_request_slot"), \
                patch.object(vision_ranker.requests, "post", side_effect=[limited, success]), \
                patch.object(vision_ranker.time, "sleep") as sleep:
            self.assertEqual(vision_ranker._interaction([], {}, 5), {"candidates": []})
        sleep.assert_called_once_with(31.0)

    def test_archive_precedes_stock_and_youtube_and_empty_tier_advances(self):
        for archive_files in (["archive.mp4"], []):
            with self.subTest(archive=archive_files), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(stock_downloader, "_fetch_archive", return_value=archive_files) as archive, \
                    patch.object(stock_downloader, "_fetch_pexels", return_value=["stock.mp4"]) as stock, \
                    patch.object(stock_downloader, "_fetch_pixabay") as pixabay, \
                    patch.object(stock_downloader, "_fetch_youtube") as youtube:
                plan = {"type": "video", "query": "Berlin 1945", "entity": "Berlin",
                        "source_policy": ["archive", "licensed_stock", "youtube"]}
                result = stock_downloader.download_for_chunk(plan, 0, tmp, youtube_mode=True)
                self.assertEqual(result, archive_files or ["stock.mp4"])
                self.assertEqual(plan["type"], "video")
                if archive_files:
                    archive.assert_called_once()
                    stock.assert_not_called()
                else:
                    self.assertEqual(archive.call_count, 2)  # exact, then same entity without action
                    stock.assert_called_once()
                pixabay.assert_not_called()
                youtube.assert_not_called()

    def test_visual_gate_rejects_archive_then_advances_to_stock(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader, "_fetch_archive", return_value=[os.path.join(tmp, "wrong.mp4")]) as archive, \
                patch.object(stock_downloader, "_fetch_pexels", return_value=[os.path.join(tmp, "right.mp4")]) as stock, \
                patch.object(stock_downloader, "_fetch_pixabay") as pixabay, \
                patch.object(stock_downloader, "_fetch_youtube") as youtube:
            def visual_gate(plan, files, assets):
                return [] if plan["_source_class"] == "archive" else files
            plan = {"type": "video", "query": "Berlin 1945", "entity": "Berlin",
                    "source_policy": ["archive", "licensed_stock", "youtube"]}
            result = stock_downloader.download_for_chunk(
                plan, 0, tmp, youtube_mode=True, candidate_ranker=visual_gate)
            self.assertEqual(result, [os.path.join(tmp, "right.mp4")])
            self.assertEqual(archive.call_count, 2)
            stock.assert_called_once()
            pixabay.assert_not_called()
            youtube.assert_not_called()

    def test_vision_ranker_rejects_bad_candidate_and_saves_evidence(self):
        import clip_ranker
        paths = ["wrong.jpg", "right.jpg"]
        assets = {name: {"search_text": "United Nations New York"} for name in paths}
        results = [
            {"score": .12, "relevant": False, "reason": "Statue of Liberty", "start": 0, "end": 0},
            {"score": .91, "relevant": True, "reason": "UN Secretariat building", "start": 0, "end": 0},
        ]
        with patch.object(clip_ranker, "is_available", return_value=True), \
                patch.object(clip_ranker, "analyze_local", return_value=results):
            ranked = clip_ranker.rank_files(
                "United Nations headquarters building New York", paths, assets,
                plan={"query": "United Nations headquarters building New York", "duration": 5},
                reject_below_threshold=True)
        self.assertEqual(ranked, ["right.jpg"])
        self.assertFalse(assets["wrong.jpg"]["vision_relevant"])
        self.assertEqual(assets["right.jpg"]["vision_score"], .91)
        self.assertEqual(assets["right.jpg"]["vision_reason"], "UN Secretariat building")

    def test_youtube_all_mode_uses_vision_timestamp_and_marks_rights_unconfirmed(self):
        from types import SimpleNamespace
        entries = [{"title": "Friedrich Merz speech in Berlin", "uploader": "Official Channel",
                    "webpage_url": "https://www.youtube.com/watch?v=test"}]
        detailed = {**entries[0], "duration": 300, "license": "Standard YouTube License"}
        options = []

        class YoutubeDL:
            def __init__(self, config): self.config = config; options.append(config)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, url, download=False):
                if url.startswith("ytsearch"):
                    return {"entries": entries}
                if download:
                    Path(self.config["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"x" * 20000)
                return detailed

        class DownloadRange:
            def __init__(self, chapters, ranges): self.ranges = ranges

        def ffmpeg(args, **kwargs):
            Path(args[-1]).write_bytes(b"x" * 20000)
            return SimpleNamespace(stdout="")

        assets = {}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {"yt_dlp": SimpleNamespace(YoutubeDL=YoutubeDL),
                                         "yt_dlp.utils": SimpleNamespace(download_range_func=DownloadRange)}), \
                patch.object(stock_downloader, "YOUTUBE_TRUSTED_CHANNELS", {"all"}), \
                patch.object(stock_downloader, "vision_available", return_value=True), \
                patch.object(stock_downloader, "analyze_youtube", return_value=[
                    {"relevant": True, "score": .94, "start": 42, "end": 47, "reason": "Merz is speaking"}]), \
                patch.object(stock_downloader.subprocess, "run", side_effect=ffmpeg), \
                patch.object(stock_downloader, "_is_valid_file", return_value=True), \
                patch.object(stock_downloader, "_make_contact_sheet", return_value=None):
            plan = {"query": "Friedrich Merz speech", "search_mode": "broll", "_source_class": "youtube",
                    "_retrieval": stock_downloader.retrieval_context(2)}
            files = stock_downloader._fetch_youtube(
                plan["query"], 0, tmp, None, 1, 0, 9,
                lambda name, asset: assets.update({name: asset}), plan=plan)
        self.assertEqual(len(files), 1)
        ranged = next(config for config in options if "download_ranges" in config)
        self.assertEqual(ranged["download_ranges"].ranges, [(42.0, 47.0)])
        asset = next(iter(assets.values()))
        self.assertTrue(asset["vision_verified"])
        self.assertEqual(asset["source_start"], 42.0)
        self.assertEqual(asset["source_end"], 47.0)
        self.assertFalse(asset["rights_confirmed"])

    def test_video_never_calls_image_search_without_explicit_fallback(self):
        for policy in (None, ["editorial", "youtube", "ai_fallback"]):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(stock_downloader, "_fetch_youtube", return_value=[]), \
                    patch.object(stock_downloader, "_fetch_reserp") as reserp, \
                    patch.object(stock_downloader, "_fetch_brightdata") as bright:
                plan = {"type": "video", "query": "Berlin", "entity": "Berlin"}
                if policy:
                    plan["source_policy"] = policy
                self.assertEqual(stock_downloader.download_for_chunk(
                    plan, 0, tmp, youtube_mode=True, reserp_mode=True, brightdata_mode=True), [])
                self.assertEqual(plan["type"], "video")
                reserp.assert_not_called()
                bright.assert_not_called()

    def test_policy_defaults_and_validation(self):
        for kind, mode, expected in [
                ("video", "exact", ["youtube"]), ("photo", "exact", ["editorial"]),
                ("video", "broll", ["youtube", "archive", "licensed_stock"]),
                ("photo", "broll", ["editorial", "archive", "licensed_stock"])]:
            plan = {"type": kind, "query": "river", "entity": "river", "search_mode": mode}
            stock_downloader.validate_search_plan(plan)
            self.assertEqual(plan["source_policy"], expected)
        for invalid in ([], "archive", ["unknown"], ["archive", "archive"], [None], [["archive"]]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "source_policy"):
                stock_downloader.validate_search_plan({"query": "river", "source_policy": invalid})
        plan = {"query": "Berlin", "entity": "Berlin", "visual_fallbacks": [
            {"role": "photo", "query": "Berlin", "source_policy": ["unknown"]}]}
        with self.assertRaisesRegex(ValueError, "source_policy"):
            stock_downloader.validate_search_plan(plan)
        self.assertIn("source_policy", app_module.LUNA_INSTRUCTIONS)
        self.assertIn("source_policy", stock_downloader.SEARCH_FIELDS)


    def test_legacy_cached_media_and_manual_choices_survive_policy_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app_module, "OUTPUT_DIR", tmp):
            folder = Path(tmp, "scene_legacy"); (folder / "downloads").mkdir(parents=True)
            panels = [{"type": "photo", "query": "Berlin", "entity": "Berlin", "entity_type": "place",
                       "entity_scope": "context", "files": [f"local{i}.jpg"],
                       "visual_fallbacks": [{"role": "illustration", "query": "Berlin illustration"}]}
                      for i in range(2)]
            for panel in panels: (folder / "downloads" / panel["files"][0]).touch()
            chunk = {"id": 0, "type": "photo", "query": "Berlin", "entity": "Berlin", "entity_type": "place",
                     "entity_scope": "context", "start": 0, "end": 2, "duration": 2,
                     "preset": "PHOTO_STATIC", "files": ["local0.jpg", "local1.jpg"]}
            session = {"scene_name": folder.name, "scene_dir": str(folder), "chunks": [chunk], "assets": {},
                       "busy": False, "cancel": threading.Event(), "audio_duration": 2, "reserp_mode": True,
                       "file_overrides": {"0": ["local1.jpg"]}}
            _sessions[folder.name] = session
            try:
                with patch("app.download_for_chunk") as download:
                    response = app.test_client().post("/resume_search", json={"scene_name": folder.name})
                    self.assertNotIn('"error"', response.get_data(as_text=True))
                    download.assert_not_called()
                self.assertEqual(session["file_overrides"], {"0": ["local1.jpg"]})
                saved = json.loads((folder / "timeline.json").read_text())
                self.assertEqual(saved["chunks"][0]["source_policy"], ["editorial"])
                self.assertEqual(saved["chunks"][0]["files"], ["local0.jpg", "local1.jpg"])
            finally:
                _sessions.pop(folder.name, None)

    def test_official_tier_does_not_accept_cc_from_unapproved_channels(self):
        with patch.object(stock_downloader, "YOUTUBE_TRUSTED_CHANNELS", set()), \
                patch.object(stock_downloader, "YOUTUBE_ALLOW_CREATIVE_COMMONS", True), \
                patch.object(stock_downloader, "_spend_query") as spend:
            result = stock_downloader._fetch_youtube("Berlin", 0, "unused", None, 3, 0, 5, None,
                                                     plan={"_source_class": "official"})
        self.assertEqual(result, [])
        spend.assert_not_called()

    def test_archive_metadata_cache_budget_dedup_and_rights(self):
        metadata = {"metadata": {"mediatype": "movies", "title": "Berlin 1945",
                    "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/",
                    "rights": "Uploader statement", "creator": "Archive creator", "collection": ["wwIIarchive"]},
                    "files": [{"name": "../bad.mp4", "size": "20000"},
                              {"name": "private.mp4", "size": "20000", "private": "true"},
                              {"name": "too-big.mp4", "size": str(stock_downloader.MAX_FILE_BYTES + 1)},
                              {"name": "Berlin film.mp4", "size": "20000"}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader.requests, "get") as get, \
                patch.object(stock_downloader, "_download_file", return_value=True) as download, \
                patch.object(stock_downloader, "_probe_duration", return_value=20):
            get.return_value.json.side_effect = [
                {"response": {"docs": [{"identifier": "berlin1945", "title": "Berlin 1945"}]}}, metadata]
            assets, rows = {}, []
            context = stock_downloader.retrieval_context(1, debug_callback=rows.append)
            plan = {"type": "video", "query": "Berlin 1945", "entity": "Berlin", "search_mode": "exact",
                    "_retrieval": context, "_source_class": "archive"}
            options = (plan["query"], 0, tmp, None, 3, 0, lambda n, a: assets.update({n: a}))
            files = stock_downloader._fetch_archive(*options, plan=plan, excluded_urls=context["seen"])
            self.assertEqual(len(files), 1)
            self.assertEqual(get.call_count, 2)  # search + bounded item metadata, only search spends budget
            self.assertEqual(context["used"], 1)
            download.assert_called_once_with("https://archive.org/download/berlin1945/Berlin%20film.mp4", files[0],
                                             min_video_size=(640, 360))
            from urllib.parse import parse_qs, urlsplit
            search_query = parse_qs(urlsplit(get.call_args_list[0].args[0]).query)["q"][0]
            self.assertIn("mediatype:movies", search_query)
            self.assertNotIn("collection:", search_query)
            asset = next(iter(assets.values()))
            self.assertEqual(asset["license_url"], metadata["metadata"]["licenseurl"])
            self.assertEqual(asset["rights"], "Uploader statement")
            self.assertEqual(asset["source_class"], "archive")
            self.assertFalse(asset["rights_confirmed"])
            self.assertEqual(asset["original_url"], "https://archive.org/details/berlin1945")
            self.assertEqual(stock_downloader._fetch_archive(*options, plan=plan, excluded_urls=context["seen"]), [])
            self.assertEqual(download.call_count, 1)
            self.assertTrue(rows[-1]["cache_hit"])
            self.assertEqual(rows[-1]["reasons"], {"duplicate_url": 1})
            # A fresh scene can use both caches even after its search budget is exhausted.
            cached_context = stock_downloader.retrieval_context(1)
            cached_context["used"] = 1
            files = stock_downloader._fetch_archive(*options, plan={**plan, "_retrieval": cached_context})
            self.assertEqual(len(files), 1)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(context["used"], 1)

    def test_archive_empty_search_and_failures_preserve_cache_contract(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stock_downloader, "OUTPUT_DIR", tmp), \
                patch.object(stock_downloader.requests, "get") as get:
            plan = {"_retrieval": stock_downloader.retrieval_context(3)}
            get.return_value.json.side_effect = [
                {"error": "temporarily unavailable"}, {"response": {"docs": []}}]
            with self.assertRaises(ValueError):
                stock_downloader._fetch_archive("Berlin", 0, tmp, None, 3, 0, None, plan=plan)
            for _ in range(2):
                self.assertEqual(stock_downloader._fetch_archive("Berlin", 0, tmp, None, 3, 0, None, plan=plan), [])
            self.assertEqual(get.call_count, 2)
            self.assertEqual(plan["_retrieval"]["used"], 2)

    def test_video_download_rejects_low_resolution_and_non_video_response(self):
        with patch.object(stock_downloader.subprocess, "run") as probe:
            probe.return_value.stdout = "640x480\n"
            self.assertFalse(stock_downloader._has_minimum_video_resolution("film.mp4"))
            self.assertTrue(stock_downloader._has_minimum_video_resolution("film.mp4", (640, 360)))
            probe.return_value.stdout = "320x240\n"
            self.assertFalse(stock_downloader._has_minimum_video_resolution("film.mp4", (640, 360)))
        class Response:
            def close(self): pass
            headers = {"Content-Length": "20000", "Content-Type": "video/mp4"}
            def raise_for_status(self): pass
            def iter_content(self, chunk_size): return iter([b"x" * 20000])
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stock_downloader.requests, "get", return_value=Response()), \
                patch.object(stock_downloader, "_is_valid_file", return_value=True), \
                patch.object(stock_downloader, "_has_minimum_video_resolution", return_value=False):
            dest = str(Path(tmp, "archive.mp4"))
            self.assertFalse(stock_downloader._download_file("https://archive.org/download/item/film.mp4", dest))
            self.assertFalse(Path(dest).exists())
            Response.headers["Content-Type"] = "text/html"
            self.assertFalse(stock_downloader._download_file("https://archive.org/download/item/film.mp4", dest))
            self.assertFalse(Path(dest).exists())


if __name__ == "__main__":
    unittest.main()
