import os
import re
import math
import glob
import subprocess
import json
import sqlite3
import time
import threading
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit, unquote, parse_qsl, urlunsplit, quote
from PIL import Image
import requests
from config import (PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY, RESERP_API_KEY,
                    BRIGHTDATA_API_KEY, BRIGHTDATA_SERP_ZONE,
                    YOUTUBE_TRUSTED_CHANNELS, YOUTUBE_ALLOW_CREATIVE_COMMONS,
                    YOUTUBE_PUBLIC_SEARCH, YOUTUBE_COOKIE_FILE, OUTPUT_DIR)
from vision_ranker import analyze_youtube, is_available as vision_available
from media_matching import requested_work, requested_creator, requested_kind, VISUAL_FORMATS

TIMEOUT = 15
_SEARCH_LOCKS = {}
_SEARCH_LOCKS_GUARD = threading.Lock()
_SEARCH_NEXT_AT = {}
RESULTS_PER_SOURCE = 5
MIN_FILE_SIZE = 10 * 1024
MIN_IMAGE_WIDTH = 640
MIN_IMAGE_HEIGHT = 360
MIN_VIDEO_WIDTH = 1280
MIN_VIDEO_HEIGHT = 720
ARCHIVE_COLLECTIONS = ("prelinger", "universal_newsreels", "wwIIarchive", "FedFlix")
ARCHIVE_MIN_VIDEO_SIZE = (640, 360)  # Native SD footage is common; stock keeps its HD floor.
_WATERMARKED_STOCK_MARKERS = (
    "alamy", "shutterstock", "gettyimages", "istockphoto", "adobestock", "stock.adobe",
    "dreamstime", "depositphotos", "123rf", "bigstock", "pond5", "freepik",
)
_GENERIC_QUERY_WORDS = {
    "a", "an", "and", "close", "footage", "image", "in", "of", "on", "photo", "shot",
    "the", "underwater", "up", "video", "view", "wildlife",
}
_QUERY_MARKER_RE = re.compile(r"\b(?:visual variation|documentary frame|fallback frame|panel frame)\s+[a-z0-9]+\b", re.IGNORECASE)

_PERSON_RE = re.compile(r'\b(man|men|person|guy|guys|people)\b', re.IGNORECASE)


def is_rejected_stock_preview(url: str, source: str = "") -> bool:
    """Google Images previews from commercial stock sites are watermarked, not licensable assets."""
    haystack = f"{url} {source}".casefold()
    return any(marker in haystack for marker in _WATERMARKED_STOCK_MARKERS)


def is_relevant_search_result(query: str, *details: str) -> bool:
    query = re.sub(r'-\S+|"', ' ', query)
    keywords = [word for word in re.findall(r"[a-z0-9]+", query.casefold())
                if len(word) > 2 and word not in _GENERIC_QUERY_WORDS]
    text = _metadata_text(*details)
    # A single broad word turns "German Bundestag" into a dog tagged "German".
    matches = sum(_contains_phrase(text, word) for word in keywords)
    return not keywords or matches >= min(2, len(keywords))


def _metadata_text(*details):
    return re.sub(r'[^\w]+', ' ', unquote(' '.join(value for value in details if isinstance(value, str))).casefold()).strip()


def _contains_phrase(text, phrase):
    return f" {_metadata_text(phrase)} " in f" {text} "


ENTITY_TYPES = {"species", "person", "place", "organization", "object", "event", "culture", "generic"}
SEARCH_FIELDS = ("search_mode", "entity", "entity_type", "scientific_name", "entity_aliases", "negative_keywords",
                 "search_queries", "required_terms", "visual_fallbacks", "entity_scope", "query_budget", "source_policy",
                 "visual_intent", "context", "match_policy", "work_title", "required_format", "work_creator", "work_kind")
SOURCE_CLASSES = {"archive", "licensed_stock", "official", "editorial", "youtube", "ai_fallback"}
VISUAL_FALLBACK_ORDER = {"photo": 1, "environment": 2, "location": 2, "map": 3,
                         "document": 3, "illustration": 3, "broll": 4, "ai": 5}
DEFAULT_QUERY_BUDGET = 6  # hard ceiling for empty exact searches, never a spending target


def _entity_type(plan):
    return plan.get("entity_type", "species" if plan.get("scientific_name") else "generic")


def _entity_name(plan):
    return (plan.get("scientific_name") if _entity_type(plan) == "species" else None) or plan.get("entity")


def canonical_media_url(url):
    if not url: return ""
    parts = urlsplit(url)
    ignored = {"w", "h", "width", "height", "q", "quality", "fm", "auto", "ixid", "ixlib", "fbclid", "gclid"}
    params = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                    if key.casefold() not in ignored and not key.casefold().startswith("utm_"))
    return urlunsplit(("https" if parts.scheme in {"http", "https"} else parts.scheme,
                       parts.netloc.casefold(), parts.path, urlencode(params), ""))


def image_perceptual_hash(path):
    """64-bit dHash, no models; JPEG draft avoids decoding the full original."""
    try:
        with Image.open(path) as image:
            image.draft("L", (144, 128))
            pixels = list(image.convert("L").resize((9, 8), Image.Resampling.BILINEAR).tobytes())
        if max(pixels) - min(pixels) < 8: return None  # flat images produce misleading collisions
        value = sum((pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
        return f"{value:016x}"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def source_score(url, source=""):
    domain = urlsplit(url).hostname or ""
    if is_rejected_stock_preview(url, source): return -100
    if domain.endswith((".edu", ".gov", ".gov.uk")): return 3
    if any(domain == host or domain.endswith("." + host) for host in
           ("wikimedia.org", "wikipedia.org", "inaturalist.org", "biodiversitylibrary.org", "si.edu", "nhm.ac.uk")):
        return 3
    if source.casefold() in {"wikimedia commons", "pexels", "pixabay", "unsplash"}: return 2
    return 0  # preference, NOT a license or identity guarantee


class QueryBudgetExceeded(RuntimeError):
    pass


def _youtube_bot_block(error):
    message = str(error).casefold()
    return "sign in to confirm" in message and "not a bot" in message


def retrieval_context(limit=DEFAULT_QUERY_BUDGET, seen_urls=None, image_hashes=None, debug_callback=None, failed_urls=None):
    return {"limit": limit, "used": 0, "lock": threading.Lock(),
            "seen": {canonical_media_url(url) for url in (seen_urls or ())},
            "failed": failed_urls if failed_urls is not None else set(),
            "hashes": image_hashes if image_hashes is not None else set(), "debug": debug_callback}


def inherit_main_entity(plan, main_entity="", scientific_name="", main_entity_type=None):
    plan = dict(plan)
    explicit = bool(plan.get("entity") or plan.get("scientific_name"))
    plan.setdefault("entity_scope", "context" if explicit else "main")
    if plan.get("search_mode", "exact") == "exact" and not explicit and (main_entity or scientific_name):
        plan["entity"] = main_entity or scientific_name
        plan.setdefault("entity_type", main_entity_type or ("species" if scientific_name else "generic"))
        if plan["entity_type"] == "species" and scientific_name:
            plan["scientific_name"] = scientific_name
    plan.setdefault("entity_type", _entity_type(plan))
    if plan["entity_type"] != "species":
        plan.pop("scientific_name", None)
    return plan


def _fallback_plan(plan, fallback):
    alternative = {**{key: plan[key] for key in ("shot_plan", "scene_id", "_shot_context", "_previous_visual") if key in plan}, **fallback}
    if alternative["role"] in {"photo", "document", "illustration"} and not (alternative.get("entity") or alternative.get("scientific_name")):
        alternative.update({key: plan[key] for key in ("entity", "entity_type", "scientific_name", "entity_aliases") if key in plan})
        alternative.setdefault("negative_keywords", plan.get("negative_keywords", []))
    return _search_plan(alternative)


def _spend_query(context):
    if context is None: return
    with context["lock"]:
        if context["used"] >= context.get("phase_limit", context["limit"]): raise QueryBudgetExceeded("Лимит поисковых запросов этапа исчерпан")
        context["used"] += 1


def _report_results(plan, cb, source, query, received, files, *, cache_hit=False, started=None, reasons=None, error=None):
    context = (plan or {}).get("_retrieval")
    row = {"query": query, "source": source, "stage": (plan or {}).get("role", "exact"),
           "source_class": (plan or {}).get("_source_class"),
           "received": received, "accepted": len(files), "rejected": sum((reasons or {}).values()),
           "reasons": reasons or {}, "not_selected": max(0, received-len(files)-sum((reasons or {}).values())),
           "cache_hit": cache_hit, "elapsed_ms": round((time.perf_counter()-started)*1000, 2) if started else 0,
           "requests_used": context["used"] if context else 0, "max_requests": context["limit"] if context else None}
    if error: row["error"] = error
    if context and context.get("debug"): context["debug"](row)
    if cb: cb(f"[{row['stage']}] {source} · {query} · пришло {received}, отсеяно {row['rejected']}, принято {len(files)} · requests_used / max_requests: {row['requests_used']} / {row['max_requests']}" + (f" · {error}" if error else ""))


def _append_asset(files, path, asset, asset_callback, plan):
    context = (plan or {}).get("_retrieval")
    identity = canonical_media_url(asset.get("original_url") or asset.get("image_url"))
    if context:
        with context["lock"]:
            if identity and identity in context["seen"]:
                _discard_file(path)
                return False
    fingerprint = image_perceptual_hash(path) if os.path.splitext(path)[1].lower() in {".jpg", ".jpeg", ".png", ".webp"} else None
    if context:
        with context["lock"]:
            if identity and identity in context["seen"]:
                _discard_file(path)
                return False
            # ponytail: linear scan of <= a few thousand hashes; bucket them if projects reach 10k images.
            if fingerprint and any((int(fingerprint, 16) ^ int(old, 16)).bit_count() <= 4 for old in context["hashes"]):
                _discard_file(path)
                return False
            if identity: context["seen"].add(identity)
            if fingerprint: context["hashes"].add(fingerprint)
    if fingerprint: asset["perceptual_hash"] = fingerprint
    if (plan or {}).get("_source_class"):
        asset["source_class"] = plan["_source_class"]
    asset.update({"source_score": source_score(asset.get("page_url", ""), asset.get("source", "")),
                  "visual_role": (plan or {}).get("role", "exact" if (plan or {}).get("search_mode") == "exact" else "broll")})
    if (plan or {}).get("search_mode") == "exact":
        asset["entity"] = _entity_name(plan)
        asset["entity_type"] = _entity_type(plan)
    files.append(path)
    if asset_callback: asset_callback(os.path.basename(path), asset)
    return True


def _discard_file(path):
    try:
        if os.path.isfile(path): os.remove(path)
    except OSError:
        pass


def validate_search_plan(plan, fallback=False):
    if not isinstance(plan.get("query"), str) or not plan["query"].strip() or len(plan["query"]) > 500:
        raise ValueError("query: нужна непустая строка до 500 символов")
    if plan.get("search_mode", "exact") not in {"exact", "broll"}:
        raise ValueError("search_mode: exact или broll")
    for field in ("visual_intent", "context"):
        if field in plan and (not isinstance(plan[field], str) or len(plan[field]) > 4000):
            raise ValueError(f"{field}: строка до 4000 символов")
    if plan.get("match_policy", "illustrative") not in {"illustrative", "strict"}:
        raise ValueError("match_policy: illustrative или strict")
    if plan.get('required_format', 'general') not in VISUAL_FORMATS:
        raise ValueError('required_format: ' + '/'.join(VISUAL_FORMATS))
    if plan.get('work_kind', 'other') not in {'song', 'album', 'film', 'book', 'musical', 'theatre', 'document', 'other'}:
        raise ValueError('work_kind: song/album/film/book/musical/theatre/document/other')
    if plan.get("entity_scope", "main") not in {"main", "context"}:
        raise ValueError("entity_scope: main или context")
    if not isinstance(_entity_type(plan), str) or _entity_type(plan) not in ENTITY_TYPES:
        raise ValueError("entity_type: species/person/place/organization/object/event/culture/generic")
    if plan.get("scientific_name") and _entity_type(plan) != "species":
        raise ValueError("scientific_name допустим только для entity_type=species")
    if "query_budget" in plan and (type(plan["query_budget"]) is not int or not 1 <= plan["query_budget"] <= 6):
        raise ValueError("query_budget: целое число 1–6")
    policy = plan.get("source_policy", default_source_policy(plan))
    if (not isinstance(policy, list) or not 1 <= len(policy) <= len(SOURCE_CLASSES)
            or any(not isinstance(tier, str) or tier not in SOURCE_CLASSES for tier in policy)
            or len(set(policy)) != len(policy)):
        raise ValueError("source_policy: непустой список archive/licensed_stock/official/editorial/youtube/ai_fallback без повторов")
    plan.setdefault("source_policy", policy)
    if plan.get("search_mode") == "exact" and not (plan.get("entity") or plan.get("scientific_name")):
        raise ValueError("Для search_mode=exact нужна entity или scientific_name")
    for field in ("entity", "scientific_name", "work_title", "work_creator"):
        if field in plan and (not isinstance(plan[field], str) or not plan[field].strip() or len(plan[field]) > 200):
            raise ValueError(f"{field}: нужна непустая строка до 200 символов")
    for field in ("entity_aliases", "negative_keywords", "search_queries", "required_terms", "fallback_queries"):
        if field in plan and (not isinstance(plan[field], list) or len(plan[field]) > (3 if field == "search_queries" else 12)
                or any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in plan[field])):
            raise ValueError(f"Неверный формат {field}")
    if "search_queries" in plan and not plan["search_queries"]:
        raise ValueError("search_queries: нужны 1–3 запроса")
    fallbacks = plan.get("visual_fallbacks", [])
    if not isinstance(fallbacks, list) or len(fallbacks) > 3 or (fallback and fallbacks):
        raise ValueError("visual_fallbacks: максимум 3, без вложенных fallback")
    for alternative in fallbacks:
        if (not isinstance(alternative, dict) or alternative.get("role") not in VISUAL_FALLBACK_ORDER
                or alternative.get("type", "photo") not in {"photo", "video"}
                or not isinstance(alternative.get("query"), str) or not alternative["query"].strip()):
            raise ValueError("visual_fallbacks: нужны role, query и type")
        if alternative.get("role") in {"photo", "document", "illustration", "map"} and alternative.get("search_mode") == "broll":
            raise ValueError("Фото/документ/иллюстрация/карта должны иметь точную entity")
        resolved = _fallback_plan(plan, alternative)
        validate_search_plan(resolved, fallback=True)
        alternative.setdefault("source_policy", resolved["source_policy"])
        if alternative["role"] == "ai" and alternative["source_policy"] != ["ai_fallback"]:
            raise ValueError("AI fallback требует source_policy: [ai_fallback]")


def default_source_policy(plan):
    """Real documentary sources first; generic stock is the final option."""
    broll = plan.get("role") == "broll" or (not plan.get("role") and plan.get("search_mode") == "broll")
    if broll:
        return (["youtube", "archive", "licensed_stock"] if plan.get("type") == "video"
                else ["editorial", "archive", "licensed_stock"])
    return ["youtube"] if plan.get("type") == "video" else ["editorial"]


def _search_plan(chunk):
    plan = inherit_main_entity(chunk)
    plan.setdefault("search_mode", "exact")
    plan.setdefault("source_policy", default_source_policy(plan))
    preferred = "youtube" if plan.get("type") == "video" else "editorial"
    if preferred == "editorial" and preferred in plan["source_policy"]:
        plan["source_policy"] = [preferred] + [source for source in plan["source_policy"] if source != preferred]
    return plan


def _matches_plan(plan, *details):
    text = _metadata_text(*details)
    if any(_contains_phrase(text, word) for word in plan.get("negative_keywords", [])):
        return False
    work = requested_work(plan)
    if work and not _contains_phrase(text, work):
        return False
    creator = requested_creator(plan)
    if creator and not _contains_phrase(text, creator):
        return False
    if requested_kind(plan) in {'musical', 'theatre'} and not re.search(r'\bmusical\b|theat(?:er|re)|bühne|broadway|мюзикл', text):
        return False
    # A named person stays an exact search even when Luna labels the shot as b-roll.
    if plan.get("entity_type") == "person" and plan.get("entity"):
        names = [plan["entity"], *plan.get("entity_aliases", [])]
        if not any(name and (_contains_phrase(text, name)
                   or (len(_metadata_text(name).split()) == 2
                       and _contains_phrase(text, ' '.join(reversed(_metadata_text(name).split())))))
                   for name in names):
            return False
    if plan.get("search_mode") == "exact":
        names = [plan.get("entity", "")] + plan.get("entity_aliases", [])
        if _entity_type(plan) == "species":
            names.append(plan.get("scientific_name", ""))
            matches = any(name and _contains_phrase(text, name) for name in names)
        else:
            # ponytail: reordered name tokens can mix entities; aliases/required_terms and editor review disambiguate.
            terms = [[term for term in _metadata_text(name).split() if term not in {"a", "an", "and", "for", "in", "of", "on", "the", "to"}] for name in names]
            matches = any(words and all(_contains_phrase(text, word) for word in words) for words in terms)
        if not matches:
            return False
    elif not is_relevant_search_result(plan["query"], *details):
        return False
    if plan.get("role") == "illustration" and not any(_contains_phrase(text, word) for word in ("illustration", "drawing", "diagram", "schematic")):
        return False
    if plan.get("role") == "map" and not _contains_phrase(text, "map"):
        return False
    if plan.get("role") == "document" and not any(_contains_phrase(text, word) for word in ("document", "letter", "manuscript", "newspaper", "report", "scan")):
        return False
    return all(any(_contains_phrase(text, alias.strip()) for alias in term.split('|') if alias.strip())
               for term in plan.get("required_terms", []))


def _planned_queries(plan):
    queries = plan.get("search_queries") or [plan["query"]] + plan.get("fallback_queries", [])
    queries = list(dict.fromkeys(normalize_search_query(q) for q in queries))[:3]
    if plan["search_mode"] != "exact":
        return queries
    name = _entity_name(plan)
    if not name:
        return []
    aliases = plan.get('entity_aliases', [])
    variants = [(next((alias for alias in aliases if _contains_phrase(_metadata_text(
        re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)', '', query)), alias)), name), query) for query in queries]
    # A supplied full alias disambiguates a short name without inventing facts.
    if plan.get('entity_type') == 'person' and len(_metadata_text(name).split()) == 1:
        full_aliases = [alias for alias in aliases if len(_metadata_text(alias).split()) > 1]
        variants[1:1] = [(alias, queries[0]) for alias in full_aliases[:1]
                         if not any(selected == alias for selected, _ in variants)]
    result = []
    for selected_name, query in variants[:3]:
        query = re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)', '', query).strip()
        for alias in [name, plan.get("entity", "")] + plan.get("entity_aliases", []):
            if alias:
                query = re.sub(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', '', query, flags=re.IGNORECASE)
        query = f'"{selected_name}" {query.strip(" ,\"")}'
        if requested_work(plan) and not _contains_phrase(_metadata_text(query), requested_work(plan)):
            query += ' "' + requested_work(plan).replace('"', '') + '"'
        if requested_creator(plan) and not _contains_phrase(_metadata_text(query), requested_creator(plan)):
            query += ' "' + requested_creator(plan).replace('"', '') + '"'
        if requested_kind(plan) and not _contains_phrase(_metadata_text(query), requested_kind(plan)):
            query += ' ' + requested_kind(plan)
        query += ''.join(' "' + term.split('|')[0].replace('"', '') + '"'
                         for term in plan.get('required_terms', [])
                         if not any(_contains_phrase(_metadata_text(query), alias.strip())
                                    for alias in term.split('|') if alias.strip()))
        query += ''.join(' -"' + word.replace('"', '') + '"' for word in plan.get("negative_keywords", []))
        query += ' -site:shutterstock.com -site:alamy.com -site:gettyimages.com -site:istockphoto.com'
        result.append(normalize_search_query(query))
    return list(dict.fromkeys(result))


def _cached_json(provider, url, fetch, cb, context=None, cache_info=None):
    """Cache successful searches; serialize API calls and retry temporary failures."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with _SEARCH_LOCKS_GUARD:
        lock = _SEARCH_LOCKS.setdefault(provider, threading.Lock())
    with lock:
        with sqlite3.connect(os.path.join(OUTPUT_DIR, "search_cache.sqlite3"), timeout=15) as db:
            db.execute("CREATE TABLE IF NOT EXISTS searches (provider TEXT, url TEXT, created REAL, payload TEXT, PRIMARY KEY(provider,url))")
            row = db.execute("SELECT created,payload FROM searches WHERE provider=? AND url=?", (provider, url)).fetchone()
            if row and time.time() - row[0] < 86400:
                if cache_info is not None: cache_info["hit"] = True
                if cb: cb(f"{provider}: кэш запроса")
                return json.loads(row[1])
        wait = _SEARCH_NEXT_AT.get(provider, 0) - time.monotonic()
        if wait > 0: time.sleep(wait)
        for attempt in range(2):
            _spend_query(context)
            try:
                data = fetch()
                break
            except requests.RequestException as exc:
                response = exc.response
                status = response.status_code if response is not None else None
                temporary = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status in {429, 500, 502, 503, 504}
                if not temporary: raise
                try: delay = max(1., float(response.headers.get("Retry-After", "5"))) if status == 429 else 1.
                except (TypeError, ValueError): delay = 5.
                _SEARCH_NEXT_AT[provider] = time.monotonic() + min(delay, 30.)
                if attempt: raise
                if cb: cb(f"{provider}: временная ошибка, повтор через {min(delay, 30.):g} с")
                time.sleep(min(delay, 30.))
        _SEARCH_NEXT_AT[provider] = time.monotonic() + (.5 if provider.startswith("Wikimedia") else .15)
        with sqlite3.connect(os.path.join(OUTPUT_DIR, "search_cache.sqlite3"), timeout=15) as db:
            db.execute("INSERT OR REPLACE INTO searches VALUES (?,?,?,?)", (provider, url, time.time(), json.dumps(data)))
            db.execute("DELETE FROM searches WHERE created < ?", (time.time() - 86400,))
        return data


def normalize_search_query(query: str) -> str:
    """Remove generator bookkeeping before a query reaches a stock API."""
    cleaned = _QUERY_MARKER_RE.sub("", str(query or ""))
    return re.sub(r"\s+", " ", cleaned).strip(" ,")


def _apply_elderly_mode(query: str) -> str:
    if _PERSON_RE.search(query):
        return 'elderly ' + query
    return query


def _retrieval_stages(plan):
    yield {**plan, "role": plan.get("role", "exact" if plan["search_mode"] == "exact" else "broll")}
    name = _entity_name(plan)
    if name and plan["search_mode"] == "exact" and plan.get("role") not in VISUAL_FALLBACK_ORDER:
        yield {**plan, "role": "exact_no_action", "query": name, "search_queries": [name],
               "fallback_queries": []}
    for fallback in sorted(plan.get("visual_fallbacks", []), key=lambda item: VISUAL_FALLBACK_ORDER[item["role"]]):
        yield {**{key: plan[key] for key in ("text", "context", "duration", "match_policy") if key in plan},
               **_fallback_plan(plan, fallback), "type": fallback.get("type", "photo"), "_retrieval": plan["_retrieval"]}


def _query_key(query):
    # Stock APIs receive queries without Google's operators or quoting.
    return normalize_search_query(re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)|"', '', query)).casefold()


def _retry_rejected_stage(stage, queries, rejected_assets, context):
    """Retry only a real visual rejection, within the original shared request budget."""
    if not any(a.get('vision_verified') and a.get('vision_relevant') is False for a in rejected_assets):
        return None
    maximum = 1 if stage.get('_processing_mode') == 'fast' else 2
    if context.get('visual_retries', 0) >= maximum or context['used'] >= context.get('phase_limit', context['limit']):
        return None
    remaining = [q for q in queries if _query_key(q) not in stage.get('_used_query_keys', [])]
    skipped = set(stage.get('_skip_sources', []))
    if not remaining:
        alternatives={'licensed_stock':{'Pexels','Pixabay','Unsplash'},
                      'editorial':set(stage.get('_retry_sources',['ReSERP','Bright Data']))}
        sources=alternatives.get(stage.get('_source_class'),set())
        if not sources:return None
        skipped.update(stage.get('_returned_sources', []))
        if sources <= skipped:return None
        remaining = queries
    exclusions = set(stage.get('_vision_excluded_urls', []))
    exclusions.update(canonical_media_url(a.get('original_url') or a.get('image_url')) for a in rejected_assets)
    exclusions.discard('')
    context['visual_retries'] = context.get('visual_retries', 0)+1
    return {**stage, 'search_queries':remaining, 'fallback_queries':[],
            '_skip_sources':sorted(skipped), '_vision_excluded_urls':sorted(exclusions)}


def download_for_chunk(
    chunk: dict,
    chunk_index: int,
    scene_dir: str,
    per_source: int = RESULTS_PER_SOURCE,
    file_offset: int = 0,
    progress_callback=None,
    elderly_mode: bool = False,
    reserp_mode: bool = False,
    youtube_mode: bool = False,
    asset_callback=None,
    brightdata_mode: bool = False,
    excluded_urls=None,
    retrieval=None,
    youtube_health=None,
    candidate_ranker=None,
    pool_sources=False,
) -> list[str]:
    validate_search_plan(chunk)
    plan = _search_plan(chunk)
    context = retrieval if retrieval is not None else retrieval_context(plan.get("query_budget", DEFAULT_QUERY_BUDGET), excluded_urls)
    plan["_retrieval"] = context
    downloads_dir = os.path.join(scene_dir, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    target = min(per_source, 3)
    def attempt(fetch, source, stage, query, args):
        started = time.perf_counter()
        if source in stage.get('_skip_sources', []):return []
        stage.setdefault('_used_query_keys', []).append(_query_key(query))
        try:
            with context["lock"]:
                excluded = set(context["seen"]) | set(stage.get('_vision_excluded_urls', []))
                unavailable = context.get("provider_failures", {}).get(source, 0) >= 3
            if unavailable:
                _report_results(stage, progress_callback, source, query, 0, [],
                                error="Источник требует авторизации; проверь ключ API или cookies YouTube")
                return []
            result = fetch(query, *args, plan=stage, excluded_urls=excluded)
            if result:stage.setdefault('_returned_sources', []).append(source)
            with context["lock"]:
                if source != "YouTube" or context.get("provider_failures", {}).get(source, 0) < 3:
                    context.get("provider_failures", {}).pop(source, None)
            return result
        except Exception as exc:
            response = getattr(exc, "response", None)
            unauthorized = response is not None and response.status_code in {401, 403}
            if (source == "YouTube" and _youtube_bot_block(exc)) or unauthorized:
                with context["lock"]:
                    context.setdefault("provider_failures", {})[source] = 3
            error = str(exc).replace(PIXABAY_API_KEY, "[скрыто]") if PIXABAY_API_KEY else str(exc)
            _report_results(stage, progress_callback, source, query, 0, [], error=error, started=started)
            return []
    stages = list(_retrieval_stages(plan))
    primary_count = 2 if len(stages) > 1 and stages[1]["role"] == "exact_no_action" else 1
    groups = [stages[:primary_count]] + [[stage] for stage in stages[primary_count:]]
    # Finish a tier (including the same entity without action) before trying the next.
    routes = [(tier, {**stage, "_source_class": tier, "_primary": group_index == 0}) for group_index, group in enumerate(groups)
              for tier in group[0]["source_policy"] for stage in group]
    for route_index, (tier, stage) in enumerate(routes):
        stage = {**stage, '_returned_sources':[]}
        if tier=='editorial':
            stage['_retry_sources']=[s for enabled,s in [(reserp_mode,'ReSERP'),(brightdata_mode,'Bright Data')] if enabled]
        context["phase_limit"] = (max(1, context["limit"] - 2)
                                  if plan.get("visual_fallbacks") and stage["_primary"]
                                  else context["limit"])
        actual_type = stage["type"]
        if (tier == "ai_fallback" or (tier == "editorial" and actual_type == "video")
                or (tier == "official" and actual_type == "photo")):
            _report_results(stage, progress_callback, tier, stage["query"], 0, [],
                            error="Источник для этого типа пока не подключён; тип визуала не меняется")
            continue
        queries = _planned_queries(stage)
        if not queries: continue
        primary_exact = stage["search_mode"] == "exact" and stage["role"] == "exact"
        if primary_exact and len(queries) == 1:
            name = _entity_name(stage)
            plain = _planned_queries({**stage, "query": name, "search_queries": [name]})
            queries = list(dict.fromkeys(queries + plain))
        if progress_callback: progress_callback(f"Сцена {chunk_index+1}: {tier} · {stage['role']} · запросы {context['used']}/{context['limit']}")
        files = []
        candidate_assets = {}
        route_asset_callback = asset_callback
        if candidate_ranker:
            route_asset_callback = lambda name, asset: candidate_assets.update({name: asset})
        if tier == "archive" and actual_type == "video":
            files = attempt(_fetch_archive, "Internet Archive", stage, queries[0],
                            (chunk_index, downloads_dir, progress_callback, target, file_offset, route_asset_callback))
        elif tier == "official" and actual_type == "video" and not (YOUTUBE_TRUSTED_CHANNELS - {"all"}):
            _report_results(stage, progress_callback, "Official YouTube", queries[0], 0, [],
                            error="Для official добавь YOUTUBE_TRUSTED_CHANNELS; Creative Commons сюда не входит")
        elif tier in {"youtube", "official"} and actual_type == "video" and youtube_mode and (youtube_health or {}).get("failures", 0) < 3:
            for query in queries[:1 if stage.get('_processing_mode')=='fast' else 2]:
                youtube_files = attempt(_fetch_youtube, "YouTube", stage, query,
                    (chunk_index, downloads_dir, progress_callback, target-len(files), file_offset+len(files), chunk.get("duration", 5), route_asset_callback))
                files.extend(youtube_files)
                if youtube_files and youtube_health is not None:
                    youtube_health["failures"] = 0
                if len(files) >= target: break
        elif tier in {"youtube", "official"} and actual_type == "video":
            _report_results(stage, progress_callback, "YouTube", queries[0], 0, [],
                            error="YouTube выключен или приостановлен после 3 пустых попыток")
        elif tier == "editorial" and actual_type == "photo":
            for enabled, fetch, source in ((reserp_mode, _fetch_reserp, "ReSERP"), (brightdata_mode, _fetch_brightdata, "Bright Data")):
                if not enabled or len(files) >= target: continue
                # Adaptive: R1 -> R2 only if needed -> one BD, never R3/BD2/BD3.
                query_limit = 2 if fetch is _fetch_reserp and primary_exact else 1
                for query in queries[:query_limit]:
                    files.extend(attempt(fetch, source, stage, query,
                        (chunk_index, downloads_dir, progress_callback, target-len(files), file_offset+len(files), route_asset_callback)))
                    if len(files) >= target: break
        elif tier in {"licensed_stock", "archive"}:
            providers = ((_fetch_wikimedia, "Wikimedia"),) if tier == "archive" else (
                (_fetch_pexels, "Pexels"), (_fetch_pixabay, "Pixabay"), (_fetch_unsplash, "Unsplash"))
            for query in queries:
                if tier == "licensed_stock":
                    # Stock APIs do not understand Google's operators; filters still use the full plan.
                    query = re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)|"', '', query).strip()
                if elderly_mode: query = _apply_elderly_mode(query)
                for fetch, source in providers:
                    files.extend(attempt(fetch, source, stage, query,
                        (actual_type, chunk_index, downloads_dir, progress_callback, target, file_offset, route_asset_callback)))
                    if files: break
                if files: break
        if files and pool_sources and tier != "licensed_stock":
            peers = [source for source in stage["source_policy"] if source != tier and
                     source in ({"editorial", "archive"} if actual_type == "photo" else {"youtube", "archive", "official"})]
            if peers:
                # Bounded port of sourceCandidates: compare two real sources, stock stays last.
                # Share deduplication and request accounting; preserve the fallback's reserved budget.
                secondary = {**stage, "source_policy": [peers[0]], "visual_fallbacks": []}
                limit, phase_limit = context["limit"], context.get("phase_limit", context["limit"])
                context["limit"] = phase_limit
                try:
                    extra = download_for_chunk(secondary, chunk_index, scene_dir, per_source=target,
                        file_offset=file_offset+len(files), progress_callback=progress_callback,
                        elderly_mode=elderly_mode, reserp_mode=reserp_mode, youtube_mode=youtube_mode,
                        brightdata_mode=brightdata_mode, asset_callback=route_asset_callback,
                        retrieval=context, youtube_health=youtube_health, pool_sources=False)
                    files = list(dict.fromkeys(files+extra))
                    if progress_callback: progress_callback(f"Общий пул {tier} + {peers[0]}: {len(files)} кандидатов перед итоговым отбором")
                finally:
                    context["limit"], context["phase_limit"] = limit, phase_limit
        if files and candidate_ranker:
            try:
                accepted = candidate_ranker(stage, files, candidate_assets)
            except Exception as exc:
                if progress_callback: progress_callback(f"Vision ranker: {exc}; сохраняю текстовый результат")
                accepted = files
            rejected = set(files) - set(accepted)
            rejected_assets = [candidate_assets.get(os.path.basename(p), {}) for p in rejected]
            for path in rejected:
                asset = candidate_assets.get(os.path.basename(path), {})
                with context["lock"]:
                    context["seen"].discard(canonical_media_url(asset.get("original_url") or asset.get("image_url")))
                    fingerprint = asset.get("perceptual_hash")
                    if fingerprint: context["hashes"].discard(fingerprint)
                _discard_file(path)
                _discard_file(asset.get("contact_sheet", ""))
            files = accepted
            if not files:
                retry = _retry_rejected_stage(stage, queries, rejected_assets, context)
                if retry:
                    routes.insert(route_index+1, (tier,retry))
                    if progress_callback:
                        progress_callback(f"Vision: кандидаты не подошли; повторяю поиск того же визуала ({context['visual_retries']}) в пределах бюджета")
            if asset_callback:
                for path in files:
                    asset_callback(os.path.basename(path), candidate_assets.get(os.path.basename(path), {}))
        if files:
            chunk["type"], chunk["visual_role"] = actual_type, stage["role"]
            if progress_callback: progress_callback(f"STOP: {len(files)} кандидатов · requests_used / max_requests: {context['used']} / {context['limit']}")
            return files
    if progress_callback: progress_callback(f"Сцена {chunk_index+1}: безопасный материал не найден — заглушка; фото требует явного visual_fallbacks")
    return []


# ── YouTube: approved channels, Creative Commons, or user-enabled public search ─

def youtube_clip_request(url, start, duration):
    """Validate a manual YouTube clip and round its requested length up."""
    parts = urlsplit(str(url).strip())
    host = parts.hostname
    if parts.scheme not in {"https", "http"} or host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ValueError("Вставь ссылку на видео YouTube")
    path = parts.path.strip("/").split("/")
    video_id = (path[0] if host == "youtu.be" else
                dict(parse_qsl(parts.query)).get("v", "") if parts.path == "/watch" else
                path[1] if len(path) == 2 and path[0] in {"shorts", "embed", "live"} else "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Нужна ссылка на конкретное видео YouTube")
    value = str(start).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?::[0-5]?\d){0,2}(?:\.\d+)?", value):
        raise ValueError("Начало: секунды (83) или таймкод (1:23, 0:01:23)")
    seconds = 0.
    for part in value.split(":"):
        seconds = seconds * 60 + float(part)
    duration = float(duration)
    if not math.isfinite(seconds) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Неверное время или длительность клипа")
    return f"https://www.youtube.com/watch?v={video_id}", seconds, math.ceil(duration)

def download_youtube_clip(url, start, length, destination):
    """Download one manually chosen section; incomplete files stay temporary."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    options = {"quiet": True, "noprogress": True, "noplaylist": True,
               "socket_timeout": 15, "retries": 1, "extractor_retries": 1,
               "fragment_retries": 2}
    runtimes = {name: {"path": path} for name in ("deno", "node") if (path := shutil.which(name))}
    if runtimes: options["js_runtimes"] = runtimes
    if YOUTUBE_COOKIE_FILE: options["cookiefile"] = YOUTUBE_COOKIE_FILE
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        total = float(info.get("duration") or 0)
        if info.get("is_live") or not math.isfinite(total) or total <= 0:
            raise ValueError("Не удалось определить длительность видео; выбери завершённый ролик")
        end = start + length
        if end > total:
            raise ValueError(f"До конца видео не хватает {length} с. Укажи начало раньше (не позже {max(0, total-length):g} с).")
        with tempfile.TemporaryDirectory(dir=os.path.dirname(destination)) as folder:
            path = os.path.join(folder, "clip.mp4")
            with yt_dlp.YoutubeDL({**options,
                    "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
                    "merge_output_format": "mp4", "outtmpl": path,
                    "download_ranges": download_range_func([], [(start, end)]),
                    "force_keyframes_at_cuts": True}) as ydl:
                ydl.extract_info(url, download=True)
            actual = _probe_duration(path)
            if not actual or actual < length - .15:
                raise ValueError("Скачался неполный отрезок. Попробуй другое начало или видео.")
            os.replace(path, destination)
    except yt_dlp.utils.DownloadError as exc:
        raise ValueError(f"YouTube: не удалось скачать видео. {exc}") from exc
    return {"source": f"YouTube · {info.get('uploader') or 'channel'}", "page_url": url,
            "original_url": url, "source_start": start, "source_end": end,
            "rights_confirmed": False}

def _fetch_youtube(query, chunk_index, downloads_dir, cb, per_source, file_offset, duration, asset_callback, plan=None, excluded_urls=None):
    started = time.perf_counter()
    official = (plan or {}).get("_source_class") == "official"
    trusted = YOUTUBE_TRUSTED_CHANNELS - {"all"}
    allow_any = not official and (YOUTUBE_PUBLIC_SEARCH or "all" in YOUTUBE_TRUSTED_CHANNELS)
    allow_cc = not official and YOUTUBE_ALLOW_CREATIVE_COMMONS
    if not trusted and not allow_any and not allow_cc:
        return []
    import yt_dlp
    from yt_dlp.utils import download_range_func
    from types import SimpleNamespace

    keep_audio = (plan or {}).get("music_insert") is True
    fast = (plan or {}).get("_processing_mode") == "fast"
    def log(message):
        if _youtube_bot_block(message):
            context = (plan or {}).get("_retrieval")
            if context:
                with context["lock"]: context.setdefault("provider_failures", {})["YouTube"] = 3
            message = "YouTube требует входа; пробую другие источники. Настрой YOUTUBE_COOKIE_FILE."
        if cb: cb(f"YouTube: {message}")
    options = {"quiet": True, "noprogress": True, "noplaylist": True,
               "socket_timeout": 8 if fast else 15, "retries": 0 if fast else 1, "extractor_retries": 0 if fast else 1,
               "fragment_retries": 0 if fast else 2, "concurrent_fragment_downloads": 4,
               "logger": SimpleNamespace(debug=lambda message: None, warning=log, error=log)}
    runtimes = {name: {"path": path} for name in ("deno", "node") if (path := shutil.which(name))}
    if runtimes: options["js_runtimes"] = runtimes
    if YOUTUBE_COOKIE_FILE: options["cookiefile"] = YOUTUBE_COOKIE_FILE
    query = re.sub(r'-"[^"]*"|-\S+', '', query).strip()
    if plan and plan.get("scientific_name") and plan.get("entity"):
        query = query.replace(plan["scientific_name"], plan["entity"])
    search_query = f"{query} {' '.join(sorted(trusted)[:2])}" if official else query
    def search():
        with yt_dlp.YoutubeDL({**options, "extract_flat": True, "skip_download": True}) as ydl:
            return (ydl.extract_info(f"ytsearch{max(per_source * 4, 12)}:{search_query}", download=False) or {}).get("entries", [])
    entries = _cached_json("YouTube-search-v1", search_query, search, cb,
                           (plan or {}).get("_retrieval"))

    allowed_items = []
    entries = [item for item in entries if isinstance(item, dict)]
    entries.sort(key=lambda item: (-_metadata_score(query, item.get("title", "")), float(item.get("duration") or 86400)))
    for item in entries:
        if not isinstance(item, dict) or item.get("is_live") or item.get("live_status") == "is_live": continue
        video_url = item.get("webpage_url") or item.get("url")
        if (not video_url or canonical_media_url(video_url) in (excluded_urls or ())
                or not (_matches_plan(plan, item.get("title", ""), item.get("description", ""), video_url) if plan
                        else is_relevant_search_result(query, item.get("title", "")))):
            continue
        channel = (item.get("uploader") or item.get("channel") or "").casefold()
        allowed = allow_any or channel in trusted or str(item.get("channel_id", "")).casefold() in trusted
        # Public search needs no expensive license probe for every result.
        if not allowed and allow_cc:
            try:
                with yt_dlp.YoutubeDL({**options, "skip_download": True}) as ydl:
                    item = ydl.extract_info(video_url, download=False)
                allowed = "creative commons" in (item.get("license") or "").casefold()
            except Exception as exc:
                log(f"метаданные недоступны: {exc}")
                continue
        if not allowed: continue
        item["webpage_url"] = video_url
        allowed_items.append(item)
        if len(allowed_items) >= (2 if fast else 4): break

    clip_duration = min(max(float(duration), 1.0), 30.0)
    assessments = None
    if vision_available() and allowed_items:
        try:
            assessments = analyze_youtube({**(plan or {"query": query}), "_fast_vision": fast}, allowed_items, clip_duration, cb,
                preview_loader=lambda item, directory, index: _youtube_preview(
                    item, directory, index, options, plan or {"query": query}, clip_duration))
        except Exception as exc:
            log(f"Vision недоступен: {exc}; кандидаты требуют проверки")
    ranked = (sorted(((item, result) for item, result in zip(allowed_items, assessments) if result["relevant"]),
                     key=lambda pair: pair[1]["score"], reverse=True)
              if assessments is not None else [(item, None) for item in allowed_items])
    files = []
    for item, assessment in ranked:
        if (plan or {}).get("_retrieval", {}).get("provider_failures", {}).get("YouTube", 0) >= 3: break
        if len(files) >= per_source: break
        video_duration = float(item.get("duration") or (max(assessment["end"], assessment["start"] + clip_duration) if assessment else clip_duration))
        if not math.isfinite(video_duration) or video_duration <= 0: continue
        start = min(max(float(assessment["start"]), 0), max(video_duration - 1, 0)) if assessment else max((video_duration-clip_duration)/2, 0)
        end = min(start + clip_duration, video_duration)
        if assessment and float(assessment["end"]) > start:
            end = min(end, float(assessment["end"]))
        if end - start < .5: continue
        index = len(files) + file_offset
        source_prefix = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_youtube_{index:02d}_source")
        dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_youtube_{index:02d}.mp4")
        try:
            with yt_dlp.YoutubeDL({**options,
                # Only explicit music breaks keep the source audio.
                "format": "bv*[height<=1080]+ba/b[height<=1080]/best" if keep_audio else "bestvideo[height<=1080]/best[height<=1080]/bestvideo/best",
                "merge_output_format": "mp4",
                "download_ranges": download_range_func([], [(start, end)]),
                "force_keyframes_at_cuts": True,
                "outtmpl": source_prefix + ".%(ext)s",
            }) as ydl:
                ydl.extract_info(item["webpage_url"], download=True)
            sources = [path for path in glob.glob(source_prefix + ".*")
                       if os.path.splitext(path)[1].lower() in {".mp4", ".webm", ".mkv", ".mov"}]
            if not sources: continue
            subprocess.run(["ffmpeg", "-y", "-i", max(sources, key=os.path.getsize), "-t", str(end-start),
                            "-map", "0:v:0", *(["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if keep_audio else ["-an"]), "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", dest],
                           check=True, capture_output=True, timeout=180)
            if not _is_valid_file(dest):
                _discard_file(dest)
                continue
        except Exception as exc:
            log(f"не удалось скачать отрезок {item['webpage_url']}: {exc}")
            _discard_file(dest)
            continue
        finally:
            for path in glob.glob(source_prefix + ".*"): _discard_file(path)
        asset = {"source": f"YouTube · {item.get('uploader') or item.get('channel') or 'channel'}",
                 "page_url": item["webpage_url"], "original_url": item["webpage_url"],
                 "search_text": item.get("title", ""), "start": round(start, 2), "end": round(end, 2),
                 "source_start": round(start, 2), "source_end": round(end, 2),
                 "contact_sheet": _make_contact_sheet(dest), "rights_confirmed": False,
                 "license": item.get("license", ""), "vision_verified": bool(assessment)}
        if assessment:
            asset.update({"vision_model": assessment.get("model", "gemini"), "vision_score": assessment["score"],
                          "vision_relevant": True, "vision_reason": assessment["reason"]})
            for key in ("confidence", "primary_score", "primary_confidence", "fallback_reason",
                        "fallback_error", "needs_review", "coverage", "sample_windows", "visual_evidence", "selection_method", "selected_window", "window_assessments", "continuity_matches", "continuity_reason", "refinement_error", "continuity_error", "match_checks", "match_key", "observed_format", "source_check", "source_error", "observed_motion", "frame_difference", "audio_activity", "audio_error", "assessed_format"):
                if key in assessment: asset["vision_"+key] = assessment[key]
        _append_asset(files, dest, asset, asset_callback, plan)
    _report_results(plan, cb, "YouTube", query, len(entries), files, started=started,
                    reasons={"filtered_or_unavailable": max(0, len(entries)-len(allowed_items)),
                             "vision_rejected": len(allowed_items)-len(ranked) if assessments is not None else 0})
    return files


def _youtube_preview(item, directory, index, options, plan, clip_duration):
    """Bounded, actual video windows; transcript selects moments when available."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    prefix = os.path.join(directory, f"candidate{index}")
    try:
        with yt_dlp.YoutubeDL({**options, "skip_download": True}) as ydl:
            info = ydl.extract_info(item["webpage_url"], download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(f"Метаданные YouTube недоступны: {exc}") from exc
    duration = float(info.get("duration") or item.get("duration") or 0)
    if not math.isfinite(duration) or duration < 1:
        raise ValueError("Неизвестная длительность видео")
    item["duration"] = duration
    cues = []
    captions = info.get("subtitles") or info.get("automatic_captions") or {}
    languages = sorted(captions, key=lambda language: (language not in {"en", "de", "ru"}, language))
    for language in languages:
        subtitle = next((entry for entry in captions[language] if entry.get("ext") == "json3"), None)
        if not subtitle: continue
        try:
            response = requests.get(subtitle["url"], timeout=(5, 10)); response.raise_for_status()
            for event in response.json().get("events", []):
                text = " ".join(segment.get("utf8", "") for segment in event.get("segs", []))
                if text.strip(): cues.append((float(event.get("tStartMs", 0))/1000, text))
        except (requests.RequestException, ValueError, TypeError):
            pass
        break
    fast = plan.get("_processing_mode") == "fast"
    length = min(duration, max(6., clip_duration) if fast else max(12., clip_duration*2))
    windows = _preview_windows(cues, info.get("chapters") or [], plan, duration, length)
    if fast: windows = windows[:1]
    clips, mapping, cursor = [], [], 0.
    for number, start in enumerate(windows):
        end = min(duration, start+length)
        source = f"{prefix}_{number}"
        try:
            keep_audio = bool(plan.get('music_insert'))
            with yt_dlp.YoutubeDL({**options, "format": ("bestvideo[height<=480]+bestaudio/best[height<=480]/best" if keep_audio else "bestvideo[height<=480]/best[height<=480]/best"),
                                 "download_ranges": download_range_func([], [(start, end)]),
                                 "force_keyframes_at_cuts": True,
                                 "outtmpl": source + ".%(ext)s"}) as ydl:
                ydl.extract_info(item["webpage_url"], download=True)
            candidates = [p for p in glob.glob(source+".*") if p.endswith((".mp4", ".webm", ".mkv", ".mov"))]
            if not candidates: continue
            clip = f"{prefix}_normalized_{number}.mp4"
            subprocess.run(["ffmpeg", "-y", "-i", max(candidates, key=os.path.getsize), "-t", str(end-start),
                            *(['-map','0:v:0','-map','0:a:0?','-c:a','aac','-ar','48000','-ac','2'] if keep_audio else ['-an']),
                            "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=4",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-pix_fmt", "yuv420p", clip],
                           check=True, capture_output=True, timeout=90)
            actual = _probe_duration(clip)
            if not actual or actual < .5: continue
            clips.append(clip)
            mapping.append({"preview_start": cursor, "preview_end": cursor+actual, "source_start": start})
            cursor += actual
        except (yt_dlp.utils.DownloadError, OSError, subprocess.SubprocessError):
            continue
    if not clips:
        raise RuntimeError("YouTube не отдал фрагменты для визуальной проверки")
    manifest = prefix+".txt"
    with open(manifest, "w", encoding="utf-8") as file:
        file.write("".join(f"file '{path}'\n" for path in clips))
    preview = prefix+"_preview.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", manifest, "-c", "copy", preview],
                   check=True, capture_output=True, timeout=30)
    return preview, mapping


def _preview_windows(cues, chapters, plan, duration, length):
    from bisect import bisect_right
    query = " ".join(str(plan.get(key) or "") for key in ("query", "entity", "visual_intent"))
    cues = sorted(cues)
    times = [start for start, _ in cues]
    scored = [(_metadata_score(query, " ".join(text for _, text in cues[index:bisect_right(times, start+length)])),
               max(0., start-1)) for index, (start, _) in enumerate(cues)]
    scored.extend((_metadata_score(query, chapter.get("title", "")), float(chapter.get("start_time", 0)))
                  for chapter in chapters)
    starts = []
    for score, start in sorted(scored, reverse=True):
        start = min(max(0., start), max(0., duration-length))
        if score > 0 and all(abs(start-old) >= length for old in starts): starts.append(start)
        if len(starts) == 3: break
    # ponytail: without useful subtitles, inspect three distributed windows, not the whole film.
    for fraction in (.1, .45, .8):
        start = max(0., min(duration-length, duration*fraction))
        if len(starts) < 3 and all(abs(start-old) >= length for old in starts): starts.append(start)
    return sorted(starts or [0.])


def _make_contact_sheet(video_path: str) -> str | None:
    duration = _probe_duration(video_path)
    if not duration:
        return None
    sheet_path = os.path.splitext(video_path)[0] + "_contact.jpg"
    timestamps = [max(duration * point, 0.1) for point in (0.15, 0.5, 0.85)]
    frames = [sheet_path + f".{index}.jpg" for index in range(3)]
    try:
        for timestamp, frame in zip(timestamps, frames):
            subprocess.run(["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path, "-frames:v", "1", frame], check=True, capture_output=True, timeout=60)
        subprocess.run(["ffmpeg", "-y", "-i", frames[0], "-i", frames[1], "-i", frames[2], "-filter_complex", "hstack=inputs=3", sheet_path], check=True, capture_output=True, timeout=60)
        return sheet_path if os.path.exists(sheet_path) else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        for frame in frames:
            try: os.remove(frame)
            except OSError: pass


# ── Pexels ────────────────────────────────────────────────────────────────────

def _fetch_pexels(query, media_type, chunk_index, downloads_dir, cb, per_source=RESULTS_PER_SOURCE, file_offset=0, asset_callback=None, plan=None, excluded_urls=None):
    started = time.perf_counter()
    if not PEXELS_API_KEY:
        return []
    headers = {"Authorization": PEXELS_API_KEY}
    _spend_query((plan or {}).get("_retrieval"))

    if media_type == "video":
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&per_page={per_source}&orientation=landscape"
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("videos", [])
        if not items:
            _report_results(plan, cb, "Pexels", query, 0, [], started=started)
            if cb: cb(f"Pexels: ничего по '{query}'")
            return []
        if cb: cb(f"Pexels: {len(items)} видео, скачиваю...")
        files = []
        for i, item in enumerate(items):
            if not (_matches_plan(plan, item.get("url", "")) if plan else is_relevant_search_result(query, item.get("url", ""))):
                continue
            video_files = item.get("video_files", [])
            hd = sorted(video_files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
            hd = [f for f in hd if (f.get("width") or 0) >= MIN_VIDEO_WIDTH and (f.get("height") or 0) >= MIN_VIDEO_HEIGHT]
            if not hd:
                continue
            if canonical_media_url(hd[0]["link"]) in (excluded_urls or ()): continue
            dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_pexels_{i + file_offset:02d}.mp4")
            if _download_file(hd[0]["link"], dest):
                _append_asset(files, dest, {"source": "Pexels", "page_url": item.get("url", ""), "original_url": hd[0]["link"], "search_text": item.get("url", ""), "rights_confirmed": True}, asset_callback, plan)
        _report_results(plan, cb, "Pexels", query, len(items), files, started=started, reasons={"filtered_or_invalid": len(items)-len(files)})
        return files
    else:
        url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page={per_source}&orientation=landscape"
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("photos", [])
        if not items:
            _report_results(plan, cb, "Pexels", query, 0, [], started=started)
            if cb: cb(f"Pexels: ничего по '{query}'")
            return []
        if cb: cb(f"Pexels: {len(items)} фото, скачиваю...")
        files = []
        for i, item in enumerate(items):
            if not (_matches_plan(plan, item.get("alt", ""), item.get("url", "")) if plan else is_relevant_search_result(query, item.get("url", ""))):
                continue
            dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_pexels_{i + file_offset:02d}.jpg")
            original_url = item["src"]["original"] + "?w=1920&q=100"
            if canonical_media_url(original_url) in (excluded_urls or ()): continue
            if _download_file(original_url, dest, headers=headers):
                _append_asset(files, dest, {"source": "Pexels", "page_url": item.get("url", ""), "original_url": original_url, "search_text": item.get("alt", ""), "rights_confirmed": True}, asset_callback, plan)
        _report_results(plan, cb, "Pexels", query, len(items), files, started=started, reasons={"filtered_or_invalid": len(items)-len(files)})
        return files


# ── Pixabay ───────────────────────────────────────────────────────────────────

def _fetch_pixabay(query, media_type, chunk_index, downloads_dir, cb, per_source=RESULTS_PER_SOURCE, file_offset=0, asset_callback=None, plan=None, excluded_urls=None):
    started = time.perf_counter()
    if not PIXABAY_API_KEY:
        return []
    _spend_query((plan or {}).get("_retrieval"))

    if media_type == "video":
        url = (
            f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}"
            f"&q={requests.utils.quote(query)}&per_page={max(per_source, 3)}"
            f"&video_type=film&orientation=horizontal"
        )
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("hits", [])
        if not items:
            _report_results(plan, cb, "Pixabay", query, 0, [], started=started)
            if cb: cb(f"Pixabay: ничего по '{query}'")
            return []
        if cb: cb(f"Pixabay: {len(items)} видео, скачиваю...")
        files = []
        for i, item in enumerate(items):
            if len(files) >= per_source: break
            if not (_matches_plan(plan, item.get("tags", "")) if plan else is_relevant_search_result(query, item.get("tags", ""))):
                continue
            videos = item.get("videos", {})
            options = sorted(videos.values(), key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
            file_url = next((f.get("url") for f in options
                             if (f.get("width") or 0) >= MIN_VIDEO_WIDTH and (f.get("height") or 0) >= MIN_VIDEO_HEIGHT), None)
            if not file_url or canonical_media_url(file_url) in (excluded_urls or ()): continue
            dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_pixabay_{i + file_offset:02d}.mp4")
            if _download_file(file_url, dest):
                _append_asset(files, dest, {"source": "Pixabay", "page_url": item.get("pageURL", ""), "original_url": file_url, "search_text": item.get("tags", ""), "rights_confirmed": True}, asset_callback, plan)
        _report_results(plan, cb, "Pixabay", query, len(items), files, started=started, reasons={"filtered_or_invalid": len(items)-len(files)})
        return files
    else:
        url = (
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}"
            f"&q={requests.utils.quote(query)}&image_type=photo"
            f"&per_page={max(per_source, 3)}&orientation=horizontal&min_width=1920"
        )
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("hits", [])
        if not items:
            _report_results(plan, cb, "Pixabay", query, 0, [], started=started)
            if cb: cb(f"Pixabay: ничего по '{query}'")
            return []
        if cb: cb(f"Pixabay: {len(items)} фото, скачиваю...")
        files = []
        for i, item in enumerate(items):
            if len(files) >= per_source: break
            if not (_matches_plan(plan, item.get("tags", "")) if plan else is_relevant_search_result(query, item.get("tags", ""))):
                continue
            file_url = item.get("largeImageURL") or item.get("webformatURL")
            if not file_url or canonical_media_url(file_url) in (excluded_urls or ()): continue
            dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_pixabay_{i + file_offset:02d}.jpg")
            if _download_file(file_url, dest):
                _append_asset(files, dest, {"source": "Pixabay", "page_url": item.get("pageURL", ""), "original_url": file_url, "search_text": item.get("tags", ""), "rights_confirmed": True}, asset_callback, plan)
        _report_results(plan, cb, "Pixabay", query, len(items), files, started=started, reasons={"filtered_or_invalid": len(items)-len(files)})
        return files


# ── Unsplash ──────────────────────────────────────────────────────────────────

def _fetch_unsplash(query, media_type, chunk_index, downloads_dir, cb, per_source=RESULTS_PER_SOURCE, file_offset=0, asset_callback=None, plan=None, excluded_urls=None):
    started = time.perf_counter()
    if not UNSPLASH_ACCESS_KEY or media_type == "video":
        return []
    _spend_query((plan or {}).get("_retrieval"))
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    url = (
        f"https://api.unsplash.com/search/photos"
        f"?query={requests.utils.quote(query)}&per_page={per_source}&orientation=landscape"
    )
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    items = resp.json().get("results", [])
    if not items:
        _report_results(plan, cb, "Unsplash", query, 0, [], started=started)
        if cb: cb(f"Unsplash: ничего по '{query}'")
        return []
    if cb: cb(f"Unsplash: {len(items)} фото, скачиваю...")
    files = []
    for i, item in enumerate(items):
        details = (item.get("alt_description", ""), item.get("description", ""), item.get("links", {}).get("html", ""))
        if not (_matches_plan(plan, *details) if plan else is_relevant_search_result(query, *details)):
            continue
        dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_unsplash_{i + file_offset:02d}.jpg")
        original_url = item["urls"]["raw"] + "&w=1920&q=100&fm=jpg"
        if canonical_media_url(original_url) in (excluded_urls or ()): continue
        if _download_file(original_url, dest, headers=headers):
            _append_asset(files, dest, {"source": "Unsplash", "page_url": item.get("links", {}).get("html", ""), "original_url": original_url, "search_text": ' '.join(v for v in details if isinstance(v, str)), "rights_confirmed": True}, asset_callback, plan)
    _report_results(plan, cb, "Unsplash", query, len(items), files, started=started, reasons={"filtered_or_invalid": len(items)-len(files)})
    return files


# ── Reserp / Google Images ───────────────────────────────────────────────────

def _fetch_reserp(query, chunk_index, downloads_dir, cb, per_source, file_offset, asset_callback, plan=None, excluded_urls=None):
    started, cache_info = time.perf_counter(), {}
    if not RESERP_API_KEY:
        if cb: cb("Reserp: RESERP_API_KEY не задан — пропускаю")
        return []

    google_url = "https://www.google.com/search?" + urlencode({
        "q": query,
        "tbm": "isch",
    })
    def fetch():
        response = requests.post(
            "https://api.reserp.ai/v2/serp/structured",
            headers={"Authorization": f"Bearer {RESERP_API_KEY}"},
            json={"url": google_url}, timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("ok") is False:
            raise ValueError("ReSERP: некорректный ответ API")
        if data.get("page", {}).get("state") in {"consent_only", "unsupported"}:
            raise ValueError("ReSERP: поисковая выдача недоступна")
        if isinstance(data.get("results"), dict) and isinstance(data["results"].get("images"), list):
            images = data["results"]["images"]
        elif isinstance(data.get("blocks"), list):
            images = [item for block in data["blocks"] if isinstance(block, dict) and block.get("type") == "images"
                      for item in block.get("items", [])]
        else:
            raise ValueError("ReSERP: ожидался results.images")
        return [_image_record(item, "image_url", "url") for item in images if isinstance(item, dict)]
    items = _cached_json("ReSERP-v2", google_url, fetch, cb, (plan or {}).get("_retrieval"), cache_info)
    return _download_google_images(items, query, "reserp", chunk_index, downloads_dir, cb,
                                   per_source, file_offset, asset_callback, plan, excluded_urls, cache_info.get("hit", False), started)


# ── Bright Data / Google Images ───────────────────────────────────────────────

def _fetch_brightdata(query, chunk_index, downloads_dir, cb, per_source, file_offset, asset_callback, plan=None, excluded_urls=None):
    started, cache_info = time.perf_counter(), {}
    if not BRIGHTDATA_API_KEY:
        if cb: cb("Bright Data: BRIGHTDATA_API_KEY не задан — пропускаю")
        return []

    google_url = "https://www.google.com/search?" + urlencode({"q": query, "tbm": "isch", "brd_json": "json"})
    def fetch():
        response = requests.post(
            "https://api.brightdata.com/request",
            headers={"Authorization": f"Bearer {BRIGHTDATA_API_KEY}"},
            json={"zone": BRIGHTDATA_SERP_ZONE, "url": google_url, "format": "raw"}, timeout=60,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            content_type = response.headers.get("Content-Type", "неизвестный тип")
            raise RuntimeError(f"Bright Data: сервер вернул не-JSON ({response.status_code}, {content_type})")
        if not isinstance(data, dict) or not isinstance(data.get("images"), list):
            raise ValueError("Bright Data: ожидался JSON с массивом images")
        return [_image_record(item, "original_image", "link") for item in data["images"] if isinstance(item, dict)]
    items = _cached_json("BrightData-v2:" + BRIGHTDATA_SERP_ZONE, google_url, fetch, cb, (plan or {}).get("_retrieval"), cache_info)
    return _download_google_images(items, query, "brightdata", chunk_index, downloads_dir, cb,
                                   per_source, file_offset, asset_callback, plan, excluded_urls, cache_info.get("hit", False), started)


def _image_record(item, image_key, page_key):
    return {"image_url": item.get(image_key), "page_url": item.get(page_key) or "",
            "source": item.get("source") or item.get("domain") or "Google Images",
            "search_text": " ".join(str(item.get(key) or "") for key in ("title", "image_alt")).strip(),
            "width": item.get("original_width"), "height": item.get("original_height")}


def _download_google_images(items, query, provider, chunk_index, downloads_dir, cb, per_source,
                            file_offset, asset_callback, plan=None, excluded_urls=None, cache_hit=False, started=None):
    context = (plan or {}).get("_retrieval")
    failed = context.get("failed", set()) if context else set()
    seen = {canonical_media_url(url) for url in (excluded_urls or ())} | failed
    files = []
    candidates = []
    reasons = {"url_or_watermark": 0, "failed_url_cache": 0, "duplicate_url": 0, "entity_or_terms": 0, "resolution": 0, "download_invalid": 0, "near_duplicate": 0}
    for item in items:
        image_url = item.get("image_url")
        if (not isinstance(image_url, str) or not image_url.startswith(("https://", "http://"))
                or is_rejected_stock_preview(image_url, item["source"] + " " + item["page_url"])):
            reasons["url_or_watermark"] += 1
            continue
        identity = canonical_media_url(image_url)
        if identity in failed:
            reasons["failed_url_cache"] += 1
            continue
        if identity in seen:
            reasons["duplicate_url"] += 1
            continue
        details = (item["search_text"], item["page_url"], image_url)
        if not (_matches_plan(plan, *details) if plan else is_relevant_search_result(query, *details)):
            reasons["entity_or_terms"] += 1
            continue
        width, height = item.get("width"), item.get("height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            if max(width, height) < MIN_IMAGE_WIDTH or min(width, height) < MIN_IMAGE_HEIGHT:
                reasons["resolution"] += 1
                continue
        candidates.append(item)
    ordered = sorted(candidates, key=lambda i: _metadata_score(query, i["search_text"])*10 + source_score(i["page_url"], i["source"]), reverse=True)[:max(9, per_source*4)]
    def fetch_item(pair):
        index, item = pair
        ext = os.path.splitext(urlsplit(item["image_url"]).path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"): ext = ".jpg"
        dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_{provider}_{index + file_offset:02d}{ext}")
        headers = {"Referer": item["page_url"]} if item["page_url"] else None
        return item, dest, _download_file(item["image_url"], dest, headers=headers)
    # Bounded waves avoid serial HTTP stalls and don't fetch the whole search result.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for offset in range(0, len(ordered), 3):
            batch = list(enumerate(ordered[offset:offset+3], offset))
            for item, dest, ok in pool.map(fetch_item, batch):
                identity = canonical_media_url(item["image_url"])
                if not ok:
                    reasons["download_invalid"] += 1
                    failed.add(identity)
                elif len(files) >= per_source or identity in seen:
                    _discard_file(dest)
                elif _append_asset(files, dest, {
                        "source": item["source"], "page_url": item["page_url"], "search_text": item["search_text"],
                        "image_url": item["image_url"], "original_url": item["image_url"], "rights_confirmed": False,
                    }, asset_callback, plan):
                    seen.add(identity)
                else:
                    reasons["near_duplicate"] += 1
            if len(files) >= per_source: break
    _report_results(plan, cb, provider, query, len(items), files, cache_hit=cache_hit, started=started, reasons=reasons)
    return files


def _metadata_score(query, text):
    positive = re.sub(r'-"[^"]*"|-\S+', '', query)
    terms = {word for word in re.findall(r'\w+', positive.casefold()) if len(word) > 2 and word not in _GENERIC_QUERY_WORDS}
    return sum(_contains_phrase(_metadata_text(text), word) for word in terms)


# Internet Archive: bounded metadata search and public video files; rights stay manual.
def _fetch_archive(query, chunk_index, downloads_dir, cb, per_source, file_offset, asset_callback, plan=None, excluded_urls=None):
    started, cache_info = time.perf_counter(), {}
    context = (plan or {}).get("_retrieval")
    failed = context["failed"] if context else set()
    positive = re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)', '', query)
    terms = re.findall(r'"([^"]+)"|(\w+)', positive)
    expression = " AND ".join('"' + (phrase or word) + '"' for phrase, word in terms)
    if not expression:
        return []
    search_url = "https://archive.org/advancedsearch.php?" + urlencode({
        "q": f"mediatype:movies AND ({expression})",
        "fl[]": ["identifier", "title", "description", "subject"],
        "rows": 6, "page": 1, "output": "json",
    }, doseq=True)

    def read(url, kind):
        response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "VideoAssembler/1.0"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("error") or not isinstance(data.get(kind), dict):
            raise ValueError("Internet Archive: некорректный ответ API")
        if not isinstance(data["response"].get("docs") if kind == "response" else data.get("files"), list):
            raise ValueError("Internet Archive: ожидался список результатов/файлов")
        return data

    result = _cached_json("InternetArchive-search-v1", search_url, lambda: read(search_url, "response"),
                          cb, context, cache_info)
    items = [item for item in result["response"]["docs"] if isinstance(item, dict)][:6]
    files, reasons = [], {}
    def reject(reason):
        reasons[reason] = reasons.get(reason, 0) + 1
    for item in sorted(items, key=lambda i: _metadata_score(query, str(i.get("title", ""))), reverse=True):
        if len(files) >= per_source:
            break
        identifier = item.get("identifier")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", identifier):
            reject("invalid_identifier")
            continue
        page_url = f"https://archive.org/details/{identifier}"
        if canonical_media_url(page_url) in (excluded_urls or ()):
            reject("duplicate_url")
            continue
        metadata_url = f"https://archive.org/metadata/{identifier}"
        try:
            # Item/file metadata, like YouTube license checks, is not another search.
            data = _cached_json("InternetArchive-metadata-v1", metadata_url,
                                lambda: read(metadata_url, "metadata"), cb)
        except (requests.RequestException, ValueError) as exc:
            reject("metadata_unavailable")
            if cb: cb(f"Internet Archive · {identifier}: {exc}")
            continue
        metadata = data["metadata"]
        collections = metadata.get("collection", [])
        if isinstance(collections, str): collections = [collections]
        if (metadata.get("mediatype") != "movies" or
                any(str(metadata.get(key, "")).casefold() in {"true", "1"} for key in ("access-restricted-item", "is_dark"))):
            reject("restricted_or_not_video")
            continue
        search_text = " ".join(str(metadata.get(key) or "") for key in ("title", "description", "subject", "creator", "date"))
        if not (_matches_plan(plan, search_text) if plan else is_relevant_search_result(query, search_text)):
            reject("entity_or_terms")
            continue
        candidates = []
        for video in data["files"]:
            if not isinstance(video, dict) or str(video.get("private", "")).casefold() in {"true", "1"}:
                continue
            name = video.get("name")
            if (not isinstance(name, str) or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/"))
                    or any(ord(char) < 32 for char in name) or os.path.splitext(name)[1].lower() not in {".mp4", ".webm", ".mov", ".mkv"}):
                continue
            try:
                size = int(video.get("size", 0))
                width, height = int(video.get("width") or 0), int(video.get("height") or 0)
            except (ValueError, TypeError):
                continue
            if width and height and (width < ARCHIVE_MIN_VIDEO_SIZE[0] or height < ARCHIVE_MIN_VIDEO_SIZE[1]):
                continue
            if MIN_FILE_SIZE <= size <= MAX_FILE_BYTES:
                candidates.append((size, name))
        accepted = False
        # ponytail: at most two public derivatives per item; segment retrieval belongs to stage two.
        for _, name in sorted(candidates)[:2]:
            download_url = f"https://archive.org/download/{identifier}/{quote(name, safe='/')}"
            if canonical_media_url(download_url) in failed:
                continue
            dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_archive_{file_offset+len(files):02d}{os.path.splitext(name)[1].lower()}")
            if not _download_file(download_url, dest, min_video_size=ARCHIVE_MIN_VIDEO_SIZE):
                failed.add(canonical_media_url(download_url))
                continue
            duration = _probe_duration(dest)
            if not duration or not math.isfinite(duration) or duration <= 0:
                _discard_file(dest)
                failed.add(canonical_media_url(download_url))
                continue
            accepted = _append_asset(files, dest, {
                "source": "Internet Archive", "page_url": page_url, "original_url": page_url,
                "download_url": download_url, "metadata_url": metadata_url, "archive_identifier": identifier,
                "search_text": search_text, "license_url": metadata.get("licenseurl", ""),
                "rights": metadata.get("rights", ""), "usage": metadata.get("usage", ""),
                "creator": metadata.get("creator", ""), "date": metadata.get("date", ""),
                "collection": metadata.get("collection", []), "duration": duration,
                "rights_confirmed": False,
            }, asset_callback, plan)
            break
        if not accepted:
            reject("no_valid_video")
    _report_results(plan, cb, "Internet Archive", query, len(items), files,
                    cache_hit=cache_info.get("hit", False), started=started, reasons=reasons)
    return files


# ── Wikimedia Commons ─────────────────────────────────────────────────────────

def _fetch_wikimedia(query, media_type, chunk_index, downloads_dir, cb, per_source=RESULTS_PER_SOURCE, file_offset=0, asset_callback=None, plan=None, excluded_urls=None):
    started = time.perf_counter()
    if media_type == "video":
        return []

    api_url = "https://commons.wikimedia.org/w/api.php"
    wm_headers = {"User-Agent": "VideoAssembler/1.0 (local documentary editor; Python requests)"}
    # MediaWiki search does not understand Google's negative site operators.
    query = re.sub(r'(?<!\S)-(?:"[^"]*"|\S+)', '', query).strip()
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",
        "srlimit": "12",
        "format": "json",
    }
    def fetch():
        resp = requests.get(api_url, params=search_params, headers=wm_headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    results = _cached_json("Wikimedia-v2", api_url + "?" + urlencode(search_params), fetch, cb,
                           (plan or {}).get("_retrieval")).get("query", {}).get("search", [])

    photo_results = [
        r for r in results
        if any(r["title"].lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png"))
        and (_matches_plan(plan, r.get("title", "")) if plan else is_relevant_search_result(query, r.get("title", "")))
    ][:max(per_source * 2, 6)]

    if not photo_results:
        _report_results(plan, cb, "Wikimedia", query, len(results), [], started=started, reasons={"filtered": len(results)})
        if cb: cb(f"Wikimedia: ничего по '{query}'")
        return []

    if cb: cb(f"Wikimedia: найдено {len(photo_results)} фото, скачиваю...")

    titles = "|".join(r["title"] for r in photo_results)
    info_params = {
        "action": "query",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1920",
        "format": "json",
    }
    info_resp = requests.get(api_url, params=info_params, headers=wm_headers, timeout=TIMEOUT)
    info_resp.raise_for_status()
    pages = info_resp.json().get("query", {}).get("pages", {})

    files = []
    i = 0
    for page in pages.values():
        if i >= per_source:
            break
        imageinfo = page.get("imageinfo", [])
        if not imageinfo:
            continue
        file_url = imageinfo[0].get("thumburl") or imageinfo[0].get("url")
        if not file_url or canonical_media_url(file_url) in (excluded_urls or ()):
            continue
        title = page.get("title", "").lower()
        ext = "png" if title.endswith(".png") else "jpg"
        dest = os.path.join(downloads_dir, f"chunk{chunk_index:02d}_wikimedia_{i + file_offset:02d}.{ext}")
        if _download_file(file_url, dest):
            meta = imageinfo[0].get("extmetadata", {})
            _append_asset(files, dest, {"source": "Wikimedia Commons", "page_url": imageinfo[0].get("descriptionurl", ""),
                          "original_url": file_url, "search_text": page.get("title", ""), "rights_confirmed": False,
                          "license": meta.get("LicenseShortName", {}).get("value", ""),
                          "license_url": meta.get("LicenseUrl", {}).get("value", ""),
                          "creator": re.sub('<[^>]+>', '', meta.get("Artist", {}).get("value", ""))}, asset_callback, plan)
            i += 1

    _report_results(plan, cb, "Wikimedia", query, len(results), files, started=started, reasons={"filtered_or_invalid": len(results)-len(files)})
    return files


# ── Utility ───────────────────────────────────────────────────────────────────

def _is_valid_file(path: str) -> bool:
    try:
        if os.path.getsize(path) < MIN_FILE_SIZE:
            return False
        result = subprocess.run(
            ["ffprobe", "-v", "error", path],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _has_minimum_image_resolution(path: str) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True, timeout=10, check=True,
        )
        width, height = (int(value) for value in result.stdout.strip().split("x"))
        return max(width, height) >= MIN_IMAGE_WIDTH and min(width, height) >= MIN_IMAGE_HEIGHT
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _has_minimum_video_resolution(path: str, minimum=(MIN_VIDEO_WIDTH, MIN_VIDEO_HEIGHT)) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True, timeout=10, check=True,
        )
        width, height = (int(value) for value in result.stdout.strip().split("x"))
        return width >= minimum[0] and height >= minimum[1]
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _probe_duration(path: str) -> float | None:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except (OSError, ValueError):
        return None


MAX_FILE_BYTES = 150 * 1024 * 1024  # 150 MB
MAX_DOWNLOAD_SECONDS = 15


def _download_file(url: str, dest: str, headers: dict | None = None, *, min_video_size=(MIN_VIDEO_WIDTH, MIN_VIDEO_HEIGHT)) -> bool:
    extension = os.path.splitext(dest)[1].lower()
    is_image = extension in {".jpg", ".jpeg", ".png", ".webp"}
    is_video = extension in {".mp4", ".mov", ".webm", ".mkv"}
    expected_type = "image/" if is_image else "video/" if is_video else ""
    temporary = dest + ".part"
    converted = temporary + ".converted"
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; VideoAssembler/1.0)", **(headers or {})}
    limit = min(MAX_FILE_BYTES, 30 * 1024 * 1024) if is_image else MAX_FILE_BYTES
    for attempt in range(2):
        resp = None
        try:
            resp = requests.get(url, headers=request_headers, timeout=(8, 15), stream=True)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().casefold()
            if expected_type and content_type and not (content_type.startswith(expected_type) or content_type in {"application/octet-stream", "binary/octet-stream"}):
                return False
            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length > limit: return False
            written, deadline = 0, time.monotonic() + (30 if is_image else 120)
            with open(temporary, "wb") as output:
                for block in resp.iter_content(chunk_size=256 * 1024):
                    written += len(block)
                    if written > limit or time.monotonic() > deadline: return False
                    output.write(block)
            if content_length and not resp.headers.get("Content-Encoding") and written != content_length:
                raise requests.ConnectionError("Incomplete media body")
            if is_image:
                with Image.open(temporary) as image:
                    width, height = image.size
                    if max(width, height) < MIN_IMAGE_WIDTH or min(width, height) < MIN_IMAGE_HEIGHT: return False
                    actual_format = image.format
                    image.verify()
                target_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[extension]
                if actual_format != target_format or target_format == "PNG":
                    with Image.open(temporary) as image:
                        image.load()
                        clean = image if actual_format == target_format else image.convert("RGB" if target_format == "JPEG" else "RGBA")
                        clean.save(converted, format=target_format)
                    os.replace(converted, temporary)
            elif not _is_valid_file(temporary) or (is_video and not _has_minimum_video_resolution(temporary, min_video_size)):
                return False
            os.replace(temporary, dest)
            return True
        except (requests.Timeout, requests.ConnectionError):
            if attempt: return False
        except requests.HTTPError:
            if attempt or resp is None or resp.status_code not in {429, 500, 502, 503, 504}: return False
        except (OSError, ValueError, Image.DecompressionBombError):
            return False
        finally:
            if resp is not None: resp.close()
            _discard_file(temporary)
            _discard_file(converted)
        time.sleep(.5)
    return False
