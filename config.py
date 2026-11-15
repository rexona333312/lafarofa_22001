import os
import sys
from pathlib import PureWindowsPath
from dotenv import load_dotenv

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
RESERP_API_KEY = os.getenv("RESERP_API_KEY", "")
BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "")
BRIGHTDATA_SERP_ZONE = os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1").strip() or "serp_api1"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
VISION_MIN_SCORE = float(os.getenv("VISION_MIN_SCORE", "0.6"))
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "apple").strip().lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
VISION_PRIMARY_MODEL = os.getenv("VISION_PRIMARY_MODEL", "qwen/qwen3.7-flash").strip()
VISION_FALLBACK_MODEL = os.getenv("VISION_FALLBACK_MODEL", "qwen/qwen3.8-flash").strip()
VISION_CONFIDENCE_THRESHOLD = float(os.getenv("VISION_CONFIDENCE_THRESHOLD", "0.70"))
VISION_CLOSE_SCORE_MARGIN = float(os.getenv("VISION_CLOSE_SCORE_MARGIN", "0.08"))
YOUTUBE_TRUSTED_CHANNELS = {name.strip().casefold() for name in os.getenv("YOUTUBE_TRUSTED_CHANNELS", "").split(",") if name.strip()}
YOUTUBE_ALLOW_CREATIVE_COMMONS = os.getenv("YOUTUBE_ALLOW_CREATIVE_COMMONS", "0") == "1"
# Public candidates are collected for the owner's manual rights review.
YOUTUBE_PUBLIC_SEARCH = os.getenv("YOUTUBE_PUBLIC_SEARCH", "1") == "1"
YOUTUBE_COOKIE_FILE = os.path.expanduser(os.getenv("YOUTUBE_COOKIE_FILE", "").strip())
_output_dir = os.getenv("OUTPUT_DIR", "").strip()
if not _output_dir or (os.name != "nt" and PureWindowsPath(_output_dir).is_absolute()):
    _output_dir = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_DIR = os.path.abspath(os.path.expanduser(_output_dir))

_whisperx_python = os.path.expanduser("~/whisperx-env/Scripts/python.exe" if os.name == "nt" else "~/whisperx-env/bin/python")
WHISPERX_PYTHON = os.path.expanduser(os.getenv("WHISPERX_PYTHON", "").strip() or
                                  (_whisperx_python if os.path.isfile(_whisperx_python) else sys.executable))
