import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch, Mock

import app as web
from varagent_import import inspect_project, apply_motion_plan, planning_input, codex_plan, _run
from ffmpeg_builder import _probe_duration


def sample_plan():
    return {"scene_updates": [{"chunk_id": 0, "template": "date_countback",
                              "params_json": '{"year":1349,"from_year":1349}',
                              "media_mode": "video", "frame_offset": 0, "reason": "Год из речи"}],
            "text_cues": [{"chunk_id": 1, "template": "marker_highlight", "text": "muchas vidas",
                           "start": 2, "end": 4, "word_start": -1, "word_end": -1,
                           "params_json": "{}", "reason": "Главный смысловой акцент"}],
            "transitions": [{"boundary_index": 0, "kind": "blur-reveal", "duration": .4,
                             "params_json": "{}", "asset": "", "blend": "alpha", "opacity": 1,
                             "reason": "Смена смысловой сцены"}]}


class VarAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "VarAgent project"
        (self.root / "_READY").mkdir(parents=True)
        (self.root / "_READY" / "final.mp4").touch()
        (self.root / "vid_img").mkdir()
        for name in ('001.mp4','002.mp4'):
            (self.root / "vid_img" / name).touch()
        (self.root / "voice.wav").touch()
        self.montage = {"audioDuration": 4, "theme": "История", "chapters": [], "clips": [
            {"id": 1, "file": "1.mp4", "startTime": 0, "endTime": 2, "visual_intent": "поле", "reason": "год"},
            {"id": 2, "file": "2.mp4", "startTime": 2, "endTime": 4, "visual_intent": "город"}]}
        self.transcript = {"language": "es", "words": [
            {"text": "Año", "start": .1, "end": .5}, {"text": "1349", "start": .6, "end": 1.5},
            {"text": "muchas", "start": 2.1, "end": 2.8}, {"text": "vidas", "start": 2.9, "end": 3.7}]}
        self.write_inputs()

    def write_inputs(self):
        for name, data in (("montage_plan.json", self.montage), ("transcription.json", self.transcript)):
            (self.root / name).write_text(json.dumps(data), encoding="utf-8")

    def session(self):
        info = inspect_project(str(self.root))
        folder = Path(self.temp.name) / "session"
        (folder / "downloads").mkdir(parents=True, exist_ok=True)
        chunks = info["chunks"]
        for c in chunks:
            c["files"] = [f"source{c['id']}.mp4"]
            (folder / "downloads" / c["files"][0]).touch()
        return {"scene_dir": str(folder), "audio_duration": 4, "chunks": copy.deepcopy(chunks), "assets": {},
                "varagent": {"base_chunks": chunks, "words": info["words"], "theme": "test", "chapters": []},
                "language": "es", "cancel": threading.Event()}

    def test_imported_words_and_trial_use_existing_cut(self):
        info = inspect_project(str(self.root), minutes=.01)
        self.assertEqual(info["duration"], 2)
        self.assertEqual(len(info["chunks"]), 1)
        self.assertEqual([w["word"] for w in info["words"]], ["Año", "1349"])
        self.assertEqual(info["chunks"][0]["text"], "Año 1349")

    def test_rejects_gaps_and_invalid_words(self):
        self.montage["clips"][1]["startTime"] = 2.1
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "пропуск"):
            inspect_project(str(self.root))
        self.montage["clips"][1]["startTime"] = 2
        self.transcript["words"][0]["start"] = float("nan")
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "word.start"):
            inspect_project(str(self.root))

    def test_does_not_use_baked_final_when_clean_media_missing(self):
        (self.root/'vid_img'/'001.mp4').unlink()
        with self.assertRaisesRegex(ValueError, "Нет чистого исходника"):
            inspect_project(str(self.root))
        (self.root/'generated').mkdir()
        (self.root/'generated'/'001.webp').touch()
        self.assertTrue(inspect_project(str(self.root))['source_files'][0].endswith('001.webp'))

    def test_plan_changes_graphics_without_changing_footage_or_timing(self):
        session = self.session()
        original = copy.deepcopy(session["varagent"]["base_chunks"])
        chunks, transitions, text = apply_motion_plan(session, sample_plan())
        for before, after in zip(original, chunks):
            for key in ("start", "end", "duration", "files", "text"):
                self.assertEqual(before[key], after[key])
        self.assertEqual(chunks[0]["template"], "date_countback")
        self.assertEqual(text[0]["template"], "marker_highlight")
        self.assertAlmostEqual((transitions[0]["start"]+transitions[0]["end"])/2, 2)
        self.assertEqual(session["varagent"]["base_chunks"], original)

    def test_invalid_plan_is_not_committed(self):
        session = self.session()
        before = copy.deepcopy(session["chunks"])
        plan = sample_plan()
        plan["transitions"][0]["boundary_index"] = 1
        with self.assertRaisesRegex(ValueError, "нет стыка"):
            apply_motion_plan(session, plan)
        self.assertEqual(session["chunks"], before)
        self.assertNotIn("motion_planned", session["varagent"])

    def test_speech_text_requires_exact_words_and_times(self):
        session = self.session()
        plan = sample_plan()
        plan["text_cues"][0].update(template="speech_words_overlay", word_start=2, word_end=4)
        _, _, cues = apply_motion_plan(session, plan, dry_run=True)
        self.assertEqual([w["text"] for w in cues[0]["speech_words"]], ["muchas", "vidas"])
        plan["text_cues"][0]["text"] = "other words"
        with self.assertRaisesRegex(ValueError, "дословно"):
            apply_motion_plan(session, plan, dry_run=True)

    def test_rejects_unknown_templates_and_unsafe_assets(self):
        session = self.session()
        for params, template in (("{}", "invented"), ('{"paper":"../../secret"}', "date_countback")):
            plan = sample_plan()
            plan["scene_updates"][0].update(template=template, params_json=params)
            with self.assertRaises(ValueError):
                apply_motion_plan(session, plan, dry_run=True)

    def test_photo_template_takes_frame_only_after_all_validation(self):
        session = self.session()
        plan = sample_plan()
        plan["scene_updates"][0].update(template="portrait_profile", media_mode="frame", frame_offset=.5,
                                        params_json='{"name":"Perrine","description":"героиня рассказа"}')
        with patch("varagent_import._run") as runner:
            chunks, _, _ = apply_motion_plan(session, plan)
        self.assertEqual(chunks[0]["type"], "photo")
        self.assertEqual(runner.call_args.args[0][6], "0.5")
        self.assertEqual(session["varagent"]["base_chunks"][0]["type"], "video")
        plan["scene_updates"][0]["frame_offset"] = 3
        with self.assertRaisesRegex(ValueError, "frame_offset"):
            apply_motion_plan(session, plan)

    def test_planner_gets_words_scene_descriptions_and_template_catalog(self):
        session = self.session()
        payload = planning_input(session, {"instructions": "existing rules", "remotion_templates": ["date_countback"]})
        self.assertEqual(payload["words"][1]["index"], 1)
        self.assertEqual(payload["chunks"][0]["visual_intent"], "поле")
        self.assertEqual(payload["template_rules"], "existing rules")
        self.assertNotIn("files", payload["chunks"][0])

    def test_cli_returns_schema_json_with_tools_disabled_and_no_shell(self):
        session = self.session()
        commands = []
        def execute(command, **kwargs):
            commands.append((command, kwargs))
            Path(command[command.index("--output-last-message")+1]).write_text(json.dumps(sample_plan()))
            return Mock(returncode=0, poll=Mock(return_value=0))
        with patch("varagent_import.shutil.which", return_value="/local/codex"), \
                patch("varagent_import.subprocess.Popen", side_effect=execute):
            self.assertEqual(codex_plan({"words": []}, session["scene_dir"]), sample_plan())
        command, kwargs = commands[0]
        self.assertIn("--ignore-user-config", command)
        self.assertEqual(command[command.index("--sandbox")+1], "read-only")
        self.assertIn("shell_tool", command)
        self.assertNotIn("shell", kwargs)

    def test_cancelled_work_does_not_start_external_process(self):
        cancel = threading.Event(); cancel.set()
        with patch("varagent_import.subprocess.Popen") as execute:
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                _run(["ffmpeg"], cancel)
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                codex_plan({}, self.temp.name, cancel)
        execute.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_real_import_endpoint_and_saved_project_never_search_or_retranscribe(self):
        video = self.root / "_READY" / "final.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=4",
                        "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(video)], check=True)
        for name in ('001.mp4','002.mp4'):
            shutil.copyfile(video,self.root/'vid_img'/name)
        with wave.open(str(self.root / "voice.wav"), "wb") as wav:
            wav.setparams((1, 2, 48000, 0, "NONE", "not compressed")); wav.writeframes(b"\0\0" * 48000 * 4)
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        output = Path(self.temp.name) / "output"
        with patch("app.OUTPUT_DIR", str(output)), patch("app.codex_plan", return_value=sample_plan()), \
                patch("app.download_for_chunk", side_effect=AssertionError("No search")), \
                patch("app.transcribe_audio", side_effect=AssertionError("No transcription")):
            with web.app.test_client() as client:
                response = client.post("/import_varagent", json={"folder": str(self.root), "minutes": 0}, buffered=True)
                events = [json.loads(line[6:]) for line in response.data.decode().splitlines() if line.startswith("data: ")]
                self.assertFalse([e for e in events if "error" in e], events)
                name = response.headers["X-Scene-Name"]
                self.addCleanup(web._sessions.pop, name, None)
                self.assertTrue(events[-1]["varagent_ready"])
                project = client.get("/project/"+name).get_json()
                self.assertTrue(project["varagent"]["motion_planned"])
                for path in (output / name / "downloads").glob("*.mp4"):
                    self.assertAlmostEqual(_probe_duration(str(path)), 2, delta=1/30)
                self.assertTrue((output / name / "varagent_motion_plan.json").is_file())
                # Manual plans use the same locked path rather than triggering the search importer.
                plan = sample_plan(); plan["transitions"] = []
                result = client.post("/import_timeline", data={"scene_name": name, "timeline":
                                     (io.BytesIO(json.dumps(plan).encode()), "motion.json")})
                self.assertTrue(result.get_json()["varagent_ready"])
                plan["scene_updates"][0].update(template="portrait_profile", media_mode="frame", frame_offset=.5,
                                                params_json='{"name":"Perrine","description":"героиня"}')
                result = client.post("/import_timeline", data={"scene_name": name, "timeline":
                                     (io.BytesIO(json.dumps(plan).encode()), "motion.json")})
                self.assertTrue(result.get_json()["varagent_ready"])
                self.assertTrue((output / name / "downloads" / "varagent_frame_0000_000015.jpg").is_file())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob("*.json")})


if __name__ == "__main__":
    unittest.main()
