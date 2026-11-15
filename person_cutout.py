"""Local, cached foreground extraction for still-photo character introductions."""
import hashlib
import threading
from pathlib import Path

from PIL import Image, ImageOps

MODEL = "u2net_human_seg"
_session = None
_lock = threading.Lock()


def cutout_person(source, cache_dir, progress=None):
    source, cache = Path(source), Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.read_bytes() + MODEL.encode() + Path(__file__).read_bytes()).hexdigest()[:24]
    output = cache / f"person_cutout_{digest}.png"
    with _lock:
        if output.is_file():
            if progress:
                progress("Представление персонажа: использую сохранённую вырезку")
            return output
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGBA")
        # A supplied transparent PNG is already a cutout; never segment it again.
        if image.getchannel("A").getextrema()[0] > 8:
            if progress:
                progress("Представление персонажа: вырезаю человека локально (U²-Net, без API)…")
            try:
                from rembg import new_session, remove
            except ImportError as exc:
                raise RuntimeError("Для вырезания человека установи requirements-person-intro.txt в окружение приложения") from exc
            global _session
            if _session is None:
                _session = new_session(MODEL, providers=["CPUExecutionProvider"])
            image = remove(image, session=_session).convert("RGBA")
        alpha = image.getchannel("A").point(lambda value: 0 if value < 8 else value)
        image.putalpha(alpha)
        box = alpha.getbbox()
        if box is None or box[2] - box[0] < 20 or box[3] - box[1] < 20:
            raise ValueError("Не удалось вырезать человека: выбери чёткую фотографию одного человека или прозрачный PNG")
        if alpha.getextrema()[0] == 255:
            raise ValueError("Модель не отделила человека от фона: выбери другой портрет или прозрачный PNG")
        image = image.crop(box)
        staging = output.with_suffix(".building.png")
        image.save(staging)
        staging.replace(output)
        return output
