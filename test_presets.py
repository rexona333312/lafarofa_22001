import json
import shutil
import subprocess
import tempfile
import threading
import io
import sys
import math
import array
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
import presets
import ffmpeg_builder as builder
import app as app_module


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class PresetTests(unittest.TestCase):
    def test_light_leaks_render_at_full_opacity(self):
        for asset in ("transitions/Light Leaks 1.mov",):
            with self.subTest(asset=asset):
                layer = {"kind": "overlay", "asset": asset, "blend": "screen", "opacity": .1,
                         "_start": 0, "_end": 1, "_seek": 0}
                _, graph, _ = presets.graph_for_scene([], {"type": "photo", "preset": "PHOTO_STATIC"},
                                                      1, 320, 180, 30, [layer])
                self.assertIn("all_opacity=1.0", graph)

    def test_builtin_transitions_preserve_frames_mix_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = []
            for index, color in enumerate(((190, 40, 40), (40, 60, 190))):
                image = Image.new("RGB", (320, 180), color)
                ImageDraw.Draw(image).rectangle((40, 25, 90, 90), fill="white")
                path = root / f"source{index}.png"
                image.save(path); files.append(str(path))
            bounds = [0, 1.017, 2.017, 3.017, 4.017, 5.017, 6.017]
            scenes = [{"type": "photo", "query": "test", "preset": "PHOTO_STATIC", "start": start,
                       "end": end, "_files": [files[index % 2]]}
                      for index, (start, end) in enumerate(zip(bounds, bounds[1:]))]
            # Small JSON rounding must not move a boundary across the frame midpoint.
            scenes[2]["start"] -= .0005
            transitions = [{"kind": kind, "start": bounds[index+1]-.3, "end": bounds[index+1]+.3}
                           for index, kind in enumerate(kind for kind in presets.BUILTIN_TRANSITIONS if kind not in presets.REMOTION_TRANSITIONS)]
            voice = root / "voice.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=48000:duration=6.017", str(voice)], check=True)
            with patch.object(builder, "W", 320), patch.object(builder, "H", 180):
                output, _ = builder.build_video(scenes, str(root), "native", audio_path=str(voice),
                                               audio_duration=6.017, transitions=transitions)
                details = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                    "stream=codec_type,nb_frames,duration,start_time", "-of", "json", output],
                    check=True, capture_output=True, text=True).stdout)
                video = next(stream for stream in details["streams"] if stream["codec_type"] == "video")
                self.assertEqual(int(video["nb_frames"]), 181)
                self.assertAlmostEqual(float(video["duration"]), 181/30, delta=.001)
                self.assertAlmostEqual(float(video["start_time"]), 0, delta=.001)
                audio = next(stream for stream in details["streams"] if stream["codec_type"] == "audio")
                self.assertAlmostEqual(float(audio["duration"]), 6.017, delta=.04)
                def pixel(second):
                    data = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(second), "-i", output,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True).stdout
                    return Image.frombytes("RGB", (320, 180), data).getpixel((160, 90))
                middle = pixel(31/30)
                self.assertTrue(65 < middle[0] < 165 and 65 < middle[2] < 165, middle)
                for second, expected in ((.2, (190,40,40)), (5.8, (40,60,190))):
                    self.assertLess(max(abs(a-b) for a,b in zip(pixel(second), expected)), 8)
                with patch.object(builder, "_render_transition_window", side_effect=AssertionError("transition cache missed")), \
                     patch.object(builder, "_render_preset", side_effect=AssertionError("scene cache missed")):
                    builder.build_video(scenes, str(root), "native", audio_duration=6.017, transitions=transitions)
                scenes[0]["preset"] = "PHOTO_SLOW_ZOOM"
                with patch.object(builder, "_render_transition_window", wraps=builder._render_transition_window) as render:
                    builder.build_video(scenes, str(root), "native", audio_duration=6.017, transitions=transitions)
                    self.assertEqual(render.call_count, 1)
            for bad in ({"kind":"spin","direction":"left"}, {"kind":"whip_pan","strength":float("nan")},
                        {"kind":"slide","direction":"x;movie=bad"}, {"kind":"spin","degrees":180}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    presets.validate_tracks({"transitions":[{**transitions[0], **bad}]}, 6.017, scenes)
            for invalid in ([transitions[0], {**transitions[0], "kind":"fade"}],
                            [{**transitions[0], "start":.5,"end":.9}],
                            [{**transitions[0], "start":0,"end":2.034}]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    presets.validate_tracks({"transitions":invalid}, 6.017, scenes)

    def test_all_presets_render_and_keep_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = []
            for index, size in enumerate(((240, 420), (360, 360), (480, 360))):
                image = Image.new("RGB", size, ("#346eaa", "#ca7145", "#439867")[index])
                ImageDraw.Draw(image).ellipse((size[0]//4, size[1]//4, size[0]*3//4, size[1]*3//4), fill="white")
                path = root / f"source{index}.png"
                image.save(path)
                sources.append(str(path))
            for preset in presets.PRESETS:
                with self.subTest(preset=preset):
                    scene = {"type": "photo", "query": "test", "preset": preset}
                    files = sources[:1]
                    if preset == "PHOTO_STATIC":
                        scene["credits"] = {Path(files[0]).name: "Источник: O'Reilly; %{pts}"}
                    if len(files) > 1:
                        scene["panels"] = [{"type": "photo", "query": str(n)} for n in range(len(files))]
                    presets.validate_scene(scene)
                    output = root / f"{preset}.mp4"
                    builder._render_preset(files, str(output), 1, scene, 320, 180)
                    self.assertEqual(presets.dimensions(output), (320, 180))
                    self.assertAlmostEqual(builder._probe_duration(str(output)), 1, delta=.04)

    def test_25fps_video_is_normalized_before_zoompan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output = root / "25fps.mp4", root / "zoom.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=s=320x180:r=25:d=2", "-c:v", "libx264", str(source)], check=True)
            scene = {"type": "video", "preset": "PHOTO_SLOW_ZOOM",
                     "params": {"fit": "cover", "zoom_start": 0, "zoom_end": .06}}
            _, graph, _ = presets.graph_for_scene([str(source)], scene, 2, 320, 180, 30)
            self.assertIn("fps=fps=30:round=near:start_time=0,settb=1/30", graph)
            builder._render_preset([str(source)], str(output), 2, scene, 320, 180)
            stream = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,nb_frames", "-of", "json", str(output)],
                check=True, capture_output=True, text=True).stdout)["streams"][0]
            self.assertEqual((stream["avg_frame_rate"], int(stream["nb_frames"])), ("30/1", 60))

    def test_photo_pan_remotion_keeps_continuous_subpixel_motion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output = root / "marker.png", root / "pan.mp4"
            image = Image.new("RGB", (1920, 1080), "black")
            ImageDraw.Draw(image).rectangle((940, 0, 979, 1079), fill="white")
            image.save(source)
            scene = {"type": "photo", "preset": "PHOTO_PAN",
                     "params": {"fit": "cover", "direction": "right"}}
            with patch.object(builder,'render_remotion',wraps=builder.render_remotion) as render:
                builder._render_preset([str(source)], str(output), 6, scene, 320, 180)
                self.assertEqual(render.call_args.args[0],'PhotoCamera')
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "rawvideo",
                                  "-pix_fmt", "gray", "pipe:1"], check=True, capture_output=True).stdout
            width, height, frame_size = 320, 180, 320 * 180
            positions = []
            for offset in range(0, len(raw), frame_size):
                frame = raw[offset:offset + frame_size]
                columns = [sum(frame[y * width + x] for y in range(height)) for x in range(width)]
                total = sum(columns)
                positions.append(sum(x * value for x, value in enumerate(columns)) / total)
            steps = [b - a for a, b in zip(positions, positions[1:])][30:-30]
            self.assertLess(positions[-1] - positions[0], -20)
            self.assertLessEqual(max(steps), .06)
            self.assertLess(max(map(abs, steps)), .5)
            self.assertLess(sum(abs(step) < .01 for step in steps), len(steps) / 3)

    def test_asset_layers_audio_timing_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets = root / "assets"
            for name in ("transitions", "textures", "music", "ambience", "sfx", "paper", "luts"):
                (assets / name).mkdir(parents=True)
            photo = root / "photo.png"
            Image.new("RGB", (400, 300), "#da8637").save(photo)
            Image.new("RGB", (320, 180), "#888888").save(assets / "textures/grain.png")
            Image.new("RGBA", (320, 180), (255, 0, 0, 80)).save(assets / "transitions/wipe.png")
            Image.new("RGB", (320, 180), "#e0d1bb").save(assets / "paper/paper.png")
            (assets / "luts/identity.cube").write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n")
            for path in (root / "voice.wav", assets / "music/calm.wav", assets / "ambience/ocean.wav", assets / "sfx/hit.wav"):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                                str(path)], check=True, capture_output=True)
            scenes = [{"type": "photo", "query": "test", "preset": "BLUR_BG_CENTER", "_chunk_id": 0,
                       "start": 0, "end": 1, "duration": 1, "_files": [str(photo)],
                       "layers": [{"asset": "textures/grain.png", "blend": "softlight", "opacity": .15}]},
                      {"type": "photo", "query": "test", "preset": "ARCHIVE_PAPER", "params": {"paper": "paper/paper.png"},
                       "_chunk_id": 1, "start": 1, "end": 2, "duration": 1, "_files": [str(photo)]}]
            transitions = [{"kind": "overlay", "asset": "transitions/wipe.png", "blend": "alpha", "start": .8, "end": 1.2}]
            tracks = [{"asset": f"{category}/{name}.wav", "start": 0, "end": 2, "fade": .1}
                      for category, name in (("music","calm"), ("ambience","ocean"), ("sfx","hit"))]
            with patch.object(presets, "ASSETS_ROOT", assets), patch.object(builder, "ASSETS_ROOT", assets), \
                    patch.object(builder, "W", 320), patch.object(builder, "H", 180):
                presets.validate_tracks({"transitions": transitions, "audio_tracks": tracks}, 2)
                output, used = builder.build_video(scenes, str(root), "test", audio_path=str(root/"voice.wav"),
                                                   audio_duration=2, transitions=transitions, audio_tracks=tracks)
                details = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=start_time,duration,nb_frames", "-of", "json", output], capture_output=True, text=True).stdout
                details += str([(p.name, builder._probe_duration(str(p))) for p in (root/".render_cache").glob("*.mp4")])
                for p in (root/".render_cache").glob("*.mp4"):
                    details += subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=start_time,duration,nb_frames", "-of", "json", str(p)], capture_output=True, text=True).stdout
                self.assertAlmostEqual(builder._probe_duration(output), 2, delta=.04, msg=details)
                self.assertEqual(used, {0: ["photo.png"], 1: ["photo.png"]})
                with patch.object(builder, "_render_preset", side_effect=AssertionError("cache not reused")):
                    builder.build_video(scenes, str(root), "test", transitions=transitions)
                scenes[1]["params"]["zoom_end"] = .08
                with patch.object(builder, "_render_preset", wraps=builder._render_preset) as render:
                    builder.build_video(scenes, str(root), "test", transitions=transitions)
                    # One invalidated source scene; its camera clip has a separate finishing pass.
                    self.assertEqual(sum(call.args[3]['type']=='photo' for call in render.call_args_list),1)
                # Missing sources stop the final render before a placeholder can be published.
                scenes[0]["_files"] = []
                with self.assertRaisesRegex(ValueError, "Добавь фото или видео для кадров: 1"):
                    builder.build_video(scenes, str(root), "test", transitions=transitions)
                self.assertFalse((root / "test.mp4.building.mp4").exists())

    def test_validation_rejects_injection_and_unknown_assets(self):
        for params in ({"fit": "stretch"}, {"zoom_end": float("nan")}, {"direction": "x;movie=bad"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                presets.validate_scene({"type": "photo", "preset": "PHOTO_STATIC", "params": params})
        for identifier in ("../config.py", "luts/../../config.py", "/etc/passwd", "music/no.wav", "textures/file';bad.mp4"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                presets.asset_path(identifier)

    def test_black_screen_overlay_preserves_color_and_video_alpha_works(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); assets=root/"assets"; (assets/"transitions").mkdir(parents=True)
            source=root/"photo.png"; Image.new("RGB",(320,180),(80,130,180)).save(source)
            black=assets/"transitions/black.png"; Image.new("RGB",(320,180),"black").save(black)
            alpha=assets/"transitions/alpha.mov"
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=red@0.3:s=320x180:r=30:d=1,format=rgba",
                            "-c:v","qtrle",str(alpha)],check=True,capture_output=True)
            with patch.object(presets,"ASSETS_ROOT",assets):
                def render(layer,name):
                    output=root/(name+".mp4")
                    builder._render_preset([str(source)],str(output),1,
                        {"type":"photo","preset":"PHOTO_STATIC","layers":[layer]},320,180)
                    result=subprocess.run(["ffmpeg","-v","error","-ss","0.5","-i",str(output),
                        "-frames:v","1","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],check=True,capture_output=True)
                    return Image.frombytes("RGB",(320,180),result.stdout).getpixel((160,90))
                color=render({"asset":"transitions/black.png","blend":"screen"},"screen")
                self.assertLess(max(abs(a-b) for a,b in zip(color,(80,130,180))),6)
                color=render({"asset":"transitions/alpha.mov","blend":"alpha","opacity":.5},"alpha")
                self.assertGreater(color[0],80)
                self.assertLess(color[2],180)

    def test_screen_transition_crossfades_and_hides_dirty_edge_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); assets=root/"assets"; (assets/"transitions").mkdir(parents=True)
            left=root/"left.png"; right=root/"right.png"; transition=assets/"transitions/dirty.mov"
            Image.new("RGB",(320,180),(190,40,40)).save(left)
            Image.new("RGB",(320,180),(40,60,190)).save(right)
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=white:s=320x180:r=30:d=1",
                            "-c:v","libx264",str(transition)],check=True,capture_output=True)
            scenes=[{"type":"photo","query":"left","preset":"PHOTO_STATIC","start":0,"end":1,"_files":[str(left)]},
                    {"type":"photo","query":"right","preset":"PHOTO_STATIC","start":1,"end":2,"_files":[str(right)]}]
            cue={"kind":"overlay","asset":"transitions/dirty.mov","blend":"screen","opacity":.2,
                 "start":.5,"end":1.5}
            with patch.object(presets,"ASSETS_ROOT",assets), patch.object(builder,"ASSETS_ROOT",assets), \
                    patch.object(builder,"W",320), patch.object(builder,"H",180), \
                    patch.object(presets,"MOTION_SUPERSAMPLE",1):
                output,_=builder.build_video(scenes,str(root),"screen",audio_duration=2,transitions=[cue])
            report=json.loads((root/"render_report.json").read_text())
            self.assertEqual(report["builtin_transitions"],["crossfade"])
            def pixel(second):
                raw=subprocess.run(["ffmpeg","-v","error","-ss",str(second),"-i",output,"-frames:v","1",
                                    "-f","rawvideo","-pix_fmt","rgb24","pipe:1"],check=True,capture_output=True).stdout
                return Image.frombytes("RGB",(320,180),raw).getpixel((160,90))
            self.assertLess(max(abs(a-b) for a,b in zip(pixel(.5),(190,40,40))),10)
            middle=pixel(1.0)
            self.assertGreater(middle[0],90); self.assertGreater(middle[2],90)
            self.assertLess(max(abs(a-b) for a,b in zip(pixel(1.467),(40,60,190))),12)

    def test_music_is_ducked_when_voice_is_present(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); assets=root/"assets"; (assets/"music").mkdir(parents=True)
            voice=root/"voice.wav"; music=assets/"music/calm.wav"; video=root/"video.mp4"
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=2",
                "-af","volume='if(lt(t,1),1,0)':eval=frame",str(voice)],check=True,capture_output=True)
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=1000:sample_rate=48000:duration=2",
                str(music)],check=True,capture_output=True)
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=black:s=320x180:r=30:d=2",
                "-c:v","libx264",str(video)],check=True,capture_output=True)
            with patch.object(presets,"ASSETS_ROOT",assets):
                builder._mux_audio(str(video),str(voice),[{"asset":"music/calm.wav","start":0,"end":2,"fade":0}],2)
            result=subprocess.run(["ffmpeg","-v","error","-i",str(video),"-map","0:a","-ac","1","-ar","48000",
                "-f","f32le","pipe:1"],check=True,capture_output=True)
            samples=array.array("f"); samples.frombytes(result.stdout)
            if sys.byteorder != "little": samples.byteswap()
            def music_component(start):
                segment=samples[int(start*48000):int((start+.1)*48000)]
                real=sum(value*math.cos(2*math.pi*1000*n/48000) for n,value in enumerate(segment))
                imag=sum(value*math.sin(2*math.pi*1000*n/48000) for n,value in enumerate(segment))
                return math.hypot(real,imag)/len(segment)
            self.assertLess(music_component(.5),music_component(1.7)*.7)

    def test_removed_features_are_rejected(self):
        removed = ("SPLIT_SCREEN", "PHOTO_COLLAGE", "FILM_LOOK", "ARCHIVE_FILM", "CINEMATIC_GRADE", "UNDERWATER_GRADE")
        self.assertNotIn("slide-left", presets.REMOTION_TEMPLATES)
        self.assertNotIn("rotate-in", presets.REMOTION_TEMPLATES)
        for name in removed:
            self.assertNotIn(name, presets.PRESETS)
            with self.assertRaises(ValueError):
                presets.validate_scene({"type": "photo", "preset": name})
        for extra in ({"panels": []}, {"effects": [{"preset": "FILM_LOOK"}]}):
            with self.assertRaises(ValueError):
                presets.validate_scene({"type": "photo", "preset": "PHOTO_STATIC", **extra})
        for kind in ("spin", "whip_pan", "zoom_blur", "slide"):
            self.assertNotIn(kind, presets.BUILTIN_TRANSITIONS)
            with self.assertRaises(ValueError):
                presets.validate_tracks({"transitions": [{"kind": kind, "start": .7, "end": 1.3}]}, 2)
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder); (assets / "transitions").mkdir()
            Image.new("RGB", (10, 10)).save(assets / "transitions/glitch_test.png")
            with patch.object(presets, "ASSETS_ROOT", assets):
                self.assertEqual(presets.library_catalog(), [])
                with self.assertRaises(ValueError):
                    presets.asset_path("transitions/glitch_test.png")
            with self.assertRaises(ValueError):
                builder.build_video([{"type": "photo", "preset": "SPLIT_SCREEN", "start": 0, "end": 2}], folder, "test")


def make_preview(destination):
    """Offline technical preview, not downloaded documentary footage."""
    order = list(presets.PRESETS)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        sources, renders = [], []
        for n, size in enumerate(((600,1000),(800,800),(1000,750))):
            image = Image.new("RGB",size,("#427bab","#bf8052","#549473")[n])
            draw = ImageDraw.Draw(image)
            for x in range(0,size[0],80):
                draw.line((x,0,x,size[1]),fill="#cbd5d9",width=4)
            cx,cy=size[0]//2,size[1]//2
            draw.ellipse((cx-140,cy-140,cx+140,cy+140),fill="white")
            path=Path(folder,f"source{n}.png"); image.save(path); sources.append(str(path))
        for name in order:
            print(name,flush=True)
            scene={"type":"photo","query":"technical preview","preset":name}
            files=sources[:1]
            path=Path(folder,name+".mp4")
            builder._render_preset(files,str(path),2,scene,1920,1080,progress=print)
            renders.append(str(path))
        builder._concat_with_xfade(renders,str(destination))
    print(destination.resolve(),flush=True)


def make_transition_preview(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        sources = []
        for index, color in enumerate(("#3b79a0", "#b9794b", "#548663")):
            image = Image.new("RGB", (1920,1080), color)
            draw = ImageDraw.Draw(image)
            for x in range(80,1920,160):
                draw.line((x,0,x,1080), fill="#cfdbdf", width=8)
            draw.ellipse((740,320,1180,760), fill="white")
            path = Path(folder, f"source{index}.png"); image.save(path); sources.append(str(path))
        scenes = [{"type":"photo", "query":"technical preview", "preset":"PHOTO_STATIC",
                   "start": index*2, "end": (index+1)*2, "_files":[sources[index%3]]} for index in range(8)]
        transitions = [{"kind":kind, "start":(index+1)*2-.4, "end":(index+1)*2+.4, "strength":.8}
                       for index,kind in enumerate(presets.BUILTIN_TRANSITIONS)]
        for cut, filename in ((14,"Light Leaks 1.mov"),):
            if (presets.ASSETS_ROOT / "transitions" / filename).is_file():
                transitions.append({"kind":"overlay", "asset":"transitions/"+filename,
                                    "blend":"screen", "start":cut-.5, "end":cut+.5})
        # Exercise an actual downloaded overlay above the scene handoff.
        if (presets.ASSETS_ROOT / "overlays/Reflections1_pr.mov").is_file():
            transitions.append({"kind":"overlay", "asset":"overlays/Reflections1_pr.mov", "blend":"alpha",
                                "opacity":.12, "start":3.6, "end":4.4})
        output, _ = builder.build_video(scenes, folder, "transitions", transitions=transitions, progress_callback=print)
        shutil.copy2(output, destination)
    print(destination.resolve(), flush=True)


if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--preview":
        make_preview(sys.argv[2])
    elif len(sys.argv)==3 and sys.argv[1]=="--transitions-preview":
        make_transition_preview(sys.argv[2])
    else:
        unittest.main()
