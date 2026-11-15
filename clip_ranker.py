import os
import subprocess

from stock_downloader import _metadata_score, source_score
from vision_ranker import analyze_local, is_available
from media_matching import match_key, MATCH_VERSION
from footage_sequence import sequence_issues


VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def selection_review(chunks, assets, overrides=None):
    """Remaining problems of selected ordinary shots, not every rejected candidate."""
    issues=[]
    for index,chunk in enumerate(chunks):
        if chunk.get('template') or chunk.get('music_insert') or chunk.get('media_origin')=='ai_image':continue
        cid=chunk.get('id',index)
        selected=(overrides or {}).get(str(cid),(overrides or {}).get(cid))
        files=chunk.get('files',[])[:1] if selected is None else selected
        for name in files or [None]:
            asset=assets.get(name,{})
            reason=None;severity=1
            if not name:reason='Не найден материал';severity=2
            elif asset.get('vision_verified') and asset.get('vision_relevant') is False:
                reason=asset.get('vision_reason') or 'Выбранный материал не прошёл визуальную проверку';severity=2
            elif asset.get('vision_needs_review'):
                reason=asset.get('vision_continuity_error') or (asset.get('vision_continuity_reason')
                    if asset.get('vision_continuity_matches') is False else None) or asset.get('vision_reason') or 'Нужна проверка'
            elif (asset.get('vision_model') == 'apple-foundation-models' and not name.startswith('user_')
                  and not asset.get('editor_confirmed')
                  and not str(asset.get('vision_match_key', '')).startswith(MATCH_VERSION)):
                reason='Оценка прежней версии: запусти повторный поиск для новой проверки'
            elif (not asset.get('vision_verified') and not name.startswith('user_')
                  and not asset.get('editor_confirmed') and not asset.get('generated_graphic')):
                reason='Содержимое не проверено Vision'
            if reason:
                issues.append(dict(chunk_id=cid,start=chunk.get('start',0),end=chunk.get('end',0),
                                   file=name,severity=severity,reason=reason))
    flagged={item['chunk_id'] for item in issues}
    issues.extend(item for item in sequence_issues(chunks,assets,overrides) if item['chunk_id'] not in flagged)
    issues.sort(key=lambda item:(-item['severity'],item['start']))
    return dict(total=len(issues),items=issues[:10],remaining=max(0,len(issues)-10),
                scope='Selected ordinary footage only; no issues is not proof of semantic accuracy.')


def _order_by_scores(paths: list[str], scores: list[float]) -> list[str]:
    return [path for _, path in sorted(zip(scores, paths), reverse=True)]


def _metadata_rank(query, path, assets):
    asset = assets.get(os.path.basename(path), {})
    return _metadata_score(query, asset.get("search_text", "")) * 10 + source_score(
        asset.get("page_url", ""), asset.get("source", ""))


def _trim_to_moment(path, start, end):
    duration = max(0.0, end - start)
    if start < 0 or duration < 1/30 or os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
        return False
    temporary = path + ".vision.mp4"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(start), "-i", path, "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac", temporary,
        ], check=True, capture_output=True, timeout=300)
        probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                                '-of','default=noprint_wrappers=1:nokey=1',temporary],
                               capture_output=True,text=True,check=True,timeout=15)
        if abs(float(probe.stdout.strip())-duration) <= .1 and os.path.getsize(temporary) > 0:
            os.replace(temporary, path)
            return True
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
    return False


def rank_files(query: str, paths: list[str], assets: dict, progress_callback=None,
               plan: dict | None = None, reject_below_threshold=False) -> list[str]:
    """Metadata shortlist first, then visual verification of at most four candidates."""
    if not paths:
        return []
    reserve = []
    fast = bool(plan and plan.get("_processing_mode") == "fast")
    if plan:
        pool = sorted(dict.fromkeys(paths), key=lambda path: _metadata_rank(query, path, assets), reverse=True)
        limit = 2 if fast else 4
        paths, reserve = pool[:limit], pool[limit:limit+2]
    if plan and is_available():
        pending = [path for path in paths if not assets.get(os.path.basename(path), {}).get("vision_verified")
                   or (assets.get(os.path.basename(path), {}).get('vision_model') == 'apple-foundation-models'
                       and assets[os.path.basename(path)].get('vision_match_key') != match_key(plan))]
        try:
            visual_plan = {**plan, "_fast_vision": fast, "_candidate_metadata": [{
                "source": assets.get(os.path.basename(path), {}).get("source", ""),
                "title": assets.get(os.path.basename(path), {}).get("search_text", ""),
                "page_url": assets.get(os.path.basename(path), {}).get("page_url", ""),
                "user_supplied": os.path.basename(path).startswith("user_") or assets.get(os.path.basename(path),{}).get('editor_confirmed',False),
            } for path in pending]}
            results = analyze_local(visual_plan, pending, float(plan.get("duration", 5)), progress_callback)
            for path, result in zip(pending, results or []):
                asset = assets.setdefault(os.path.basename(path), {})
                if (result.get("needs_review") and not result.get("score")
                        and not result.get("confidence")):
                    asset.update({"vision_verified": False,
                                  "vision_relevant": False, "vision_score": 0.0,
                                  "vision_model": result.get("model", "apple-foundation-models"),
                                  "vision_reason": result["reason"], "vision_needs_review": True})
                    continue
                asset.update({
                    "vision_verified": True,
                    "vision_model": result.get("model", "gemini"),
                    "vision_score": result["score"],
                    "vision_relevant": result["relevant"],
                    "vision_reason": result["reason"],
                    "vision_needs_review": bool(result.get('needs_review')),
                })
                for key in ("confidence", "primary_score", "primary_confidence", "fallback_reason", "fallback_error", "needs_review", "visual_evidence", "selection_method", "sample_windows", "selected_window", "coverage", "window_assessments", "continuity_matches", "continuity_reason", "refinement_error", "continuity_error", "match_checks", "match_key", "observed_format", "source_check", "source_error", "observed_motion", "frame_difference", "audio_activity", "audio_error", "assessed_format"):
                    if key in result: asset["vision_"+key] = result[key]
                if result["relevant"] and os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
                    if _trim_to_moment(path, result["start"], result["end"]):
                        offset = float(asset.get("source_start", 0))
                        asset["source_start"], asset["source_end"] = offset+result["start"], offset+result["end"]
                    else:
                        asset["vision_needs_review"] = True
                        asset["vision_reason"] += " · Не удалось применить выбранные таймкоды"
                        if result.get("selection_method") == "sampled_action_windows":
                            asset["vision_relevant"] = False
        except Exception as exc:
            if progress_callback:
                progress_callback(f"Vision недоступен: {exc}; оставляю текстовый порядок")

    ranked = (sorted(paths, key=lambda path: (
                        2 if assets.get(os.path.basename(path), {}).get("vision_relevant") else
                        1 if not assets.get(os.path.basename(path), {}).get("vision_verified") else 0,
                        {True:1, False:-1}.get(assets.get(os.path.basename(path), {}).get("vision_continuity_matches"),0),
                        assets.get(os.path.basename(path), {}).get("vision_score", -1),
                        _metadata_rank(query, path, assets)), reverse=True)
              if any(assets.get(os.path.basename(path), {}).get("vision_verified") for path in paths)
              else sorted(paths, key=lambda path: _metadata_rank(query, path, assets), reverse=True))
    if reject_below_threshold:
        verified = [path for path in ranked if assets.get(os.path.basename(path), {}).get("vision_verified")]
        if verified:
            rejected = [path for path in verified if not assets[os.path.basename(path)].get("vision_relevant")]
            ranked = [path for path in ranked if path not in rejected]
            if progress_callback and rejected:
                progress_callback(f"Vision: отклонено нерелевантных кандидатов — {len(rejected)}")
            if not ranked and reserve and plan and not plan.get('_reserve_batch'):
                if progress_callback:progress_callback('Vision: проверяю запасных кандидатов из уже скачанного пула')
                return rank_files(query,reserve,assets,progress_callback,
                                  plan={**plan,'_reserve_batch':True},reject_below_threshold=True)
    return ranked
