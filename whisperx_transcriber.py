import json
import math
import os
import queue
import re
import subprocess
import tempfile
import threading
from collections import deque

from config import WHISPERX_PYTHON

LANGUAGES = {"cs", "de", "en", "es", "pl"}
DEFAULT_LANGUAGE = "pl"


def _aligned_words(result):
    words, pending = [], []
    for segment in result.get("segments", []):
        for item in segment.get("words", []):
            text = item.get("word", "").strip()
            if not text:
                continue
            start, end = item.get("start"), item.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                # WhisperX cannot align some numbers/symbols: keep their text with a timed neighbour.
                if words:
                    words[-1]["word"] += " " + text
                else:
                    pending.append(text)
                continue
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError("WhisperX вернул неверные таймкоды")
            words.append({"word": " ".join(pending + [text]), "start": round(start, 3), "end": round(end, 3)})
            pending.clear()
    return words


def transcribe_audio(audio_path: str, language=DEFAULT_LANGUAGE, progress_callback=None, cancel_event=None) -> list[dict]:
    if language not in LANGUAGES:
        raise ValueError("Выбери язык озвучки: cs, de, en, es или pl")
    audio_path = os.path.abspath(audio_path)
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Сессия отменена")
    if progress_callback:
        progress_callback(f"WhisperX large-v2 · {language.upper()} · CPU int8 · batch 4")
        progress_callback("Загружаю WhisperX и модели из локального кэша…")
    with tempfile.TemporaryDirectory(prefix="whisperx_", dir=os.path.dirname(audio_path)) as folder:
        command = [WHISPERX_PYTHON, "-u", "-m", "whisperx", audio_path,
                   "--model", "large-v2", "--language", language,
                   "--device", "cpu", "--compute_type", "int8", "--batch_size", "4",
                   "--output_format", "json", "--output_dir", folder,
                   "--verbose", "False", "--log-level", "info", "--print_progress", "True"]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RuntimeError("Не удалось запустить WhisperX. Проверь WHISPERX_PYTHON в .env") from exc
        messages, tail = queue.Queue(), deque(maxlen=12)
        stage, last_percent = "Загрузка моделей", -1

        def read_output():
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Сессия отменена")
                try:
                    line = messages.get(timeout=0.5)
                except queue.Empty:
                    continue
                if line is None:
                    break
                line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
                tail.append(line)
                if "Performing transcription" in line:
                    stage, last_percent = "Распознавание речи", -1
                    if progress_callback: progress_callback("WhisperX: распознаю речь…")
                elif "Performing alignment" in line:
                    stage, last_percent = "Выравнивание таймкодов", -1
                    if progress_callback: progress_callback(f"WhisperX: выравниваю таймкоды слов ({language.upper()})…")
                elif match := re.search(r"Progress:\s*([0-9.]+)%", line):
                    percent = min(100, int(float(match[1])))
                    if percent // 5 > last_percent // 5:
                        last_percent = percent
                        if progress_callback: progress_callback(f"WhisperX · {stage}: {percent}%")
            if process.wait() != 0:
                raise RuntimeError("Ошибка WhisperX:\n" + "\n".join(tail))
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            process.stdout.close()
        path = os.path.join(folder, os.path.splitext(os.path.basename(audio_path))[0] + ".json")
        with open(path, encoding="utf-8") as file:
            words = _aligned_words(json.load(file))
    if progress_callback:
        progress_callback(f"WhisperX: {len(words)} таймкодов готово")
    return words
