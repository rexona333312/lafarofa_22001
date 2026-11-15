import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from person_cutout import cutout_person
from presets import PERSON_TEMPLATES, REMOTION_TEMPLATES, validate_scene
from app import LUNA_INSTRUCTIONS, _prepare_build_chunks, _sessions, app


class PersonIntroTests(unittest.TestCase):
    def test_variants_are_registered_and_validated(self):
        for template in PERSON_TEMPLATES:
            scene = {"type": "photo", "template": template, "params": {"person_name": "Donald Trump"}}
            validate_scene(scene)
            self.assertIn(template, REMOTION_TEMPLATES)
            self.assertIn(template, LUNA_INSTRUCTIONS)
            for overrides in ({"type": "video"}, {"params": {}},
                              {"params": {"person_name": "Trump", "person_role": []}},
                              {"params": {"person_name": "Trump", "background_blur": float("nan")}}):
                with self.subTest(template=template, overrides=overrides), self.assertRaises(ValueError):
                    validate_scene({**scene, **overrides})

    def test_transparent_png_is_cropped_and_cached_without_a_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "person.png"
            image = Image.new("RGBA", (200, 300))
            ImageDraw.Draw(image).rectangle((40, 30, 159, 299), fill=(100, 150, 200, 255))
            image.save(source)
            original = source.read_bytes()
            with patch.dict(sys.modules, {"rembg": None}):
                output = cutout_person(source, root / "cache")
                timestamp = output.stat().st_mtime_ns
                self.assertEqual(cutout_person(source, root / "cache"), output)
            self.assertEqual(output.stat().st_mtime_ns, timestamp)
            self.assertEqual(source.read_bytes(), original)
            with Image.open(output) as result:
                self.assertEqual(result.size, (120, 270))
                self.assertEqual(result.mode, "RGBA")

    def test_rgb_photo_uses_local_cpu_model_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "photo.jpg"
            Image.new("RGB", (200, 300), "white").save(source)
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            extracted = Image.new("RGBA", (200, 300))
            ImageDraw.Draw(extracted).rectangle((30, 20, 169, 299), fill="red")
            fake = types.SimpleNamespace(new_session=Mock(return_value=object()), remove=Mock(return_value=extracted))
            with patch.dict(sys.modules, {"rembg": fake}), patch("person_cutout._session", None):
                first = cutout_person(source, root / "cache")
                self.assertEqual(first, cutout_person(source, root / "cache"))
            fake.new_session.assert_called_once_with("u2net_human_seg", providers=["CPUExecutionProvider"])
            fake.remove.assert_called_once()
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)

    def test_blank_cutout_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "empty.png")
            Image.new("RGBA", (100, 100)).save(path)
            with self.assertRaisesRegex(ValueError, "Не удалось вырезать"):
                cutout_person(path, Path(folder, "cache"))

    def test_almost_opaque_png_still_needs_segmentation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "photo.png"
            Image.new("RGBA", (200, 300), (100, 100, 100, 242)).save(source)
            extracted = Image.new("RGBA", (200, 300))
            ImageDraw.Draw(extracted).ellipse((40, 20, 160, 299), fill="red")
            fake = types.SimpleNamespace(new_session=Mock(return_value=object()), remove=Mock(return_value=extracted))
            with patch.dict(sys.modules, {"rembg": fake}), patch("person_cutout._session", None):
                cutout_person(source, root / "cache")
            fake.remove.assert_called_once()

    def test_project_keeps_character_fields_for_render(self):
        with tempfile.TemporaryDirectory() as folder:
            downloads = Path(folder, "downloads")
            downloads.mkdir()
            (downloads / "photo.png").touch()
            params = {"person_name": "Donald Trump", "person_role": "President"}
            chunk = {"id": 0, "type": "photo", "query": "Trump", "duration": 5, "start": 0,
                     "end": 5, "files": ["photo.png"], "template": "person_intro_right", "params": params}
            result = _prepare_build_chunks({"scene_dir": folder, "chunks": [chunk], "assets": {}})[0]
            self.assertEqual(result["params"], params)
            self.assertEqual(result["template"], "person_intro_right")

    def test_export_for_codex_contains_new_templates_and_instructions(self):
        name = "scene_intro_export_test"
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "luna_input.json").write_text(json.dumps({"text": "Test", "word_timestamps": []}))
            _sessions[name] = {"scene_dir": folder}
            try:
                with patch("app.library_catalog", return_value=[]):
                    response = app.test_client().get(f"/timeline_input/{name}")
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertTrue(set(PERSON_TEMPLATES).issubset(data["remotion_templates"]))
                self.assertIn("params.person_name", data["instructions"])
            finally:
                _sessions.pop(name, None)


if __name__ == "__main__":
    unittest.main()
