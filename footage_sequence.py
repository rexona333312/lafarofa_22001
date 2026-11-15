"""Check actual selected stills after retrieval; explicit editor choices stay fixed."""


def same_photo(left, right, assets):
    if not left or not right:
        return False
    if left == right:
        return True
    a, b = assets.get(left, {}), assets.get(right, {})
    for key in ('approved_digest', 'original_url', 'image_url'):
        if a.get(key) and a.get(key) == b.get(key):
            return True
    ah, bh = a.get('perceptual_hash'), b.get('perceptual_hash')
    try:
        return bool(ah and bh and len(ah) == len(bh) == 16 and (int(ah,16)^int(bh,16)).bit_count() <= 4)
    except (ValueError, TypeError):
        return False


def _ordinary(chunk):
    return (not chunk.get('template') and not chunk.get('music_insert')
            and chunk.get('media_origin', 'real') == 'real')


def balance_sequence(chunks, assets, overrides=None, preserved=()):
    recent, changed = [], {}
    for index, chunk in enumerate(chunks):
        cid = chunk.get('id',index)
        files = chunk.get('files', [])
        chosen = (overrides or {}).get(str(cid), (overrides or {}).get(cid, files[:1]))
        if not _ordinary(chunk) or chunk.get('type') != 'photo' or len(chosen) != 1:
            recent = []
            continue
        name = chosen[0]
        if (str(cid) not in (overrides or {}) and cid not in (overrides or {}) and cid not in preserved
                and not (chunk.get('shot_plan') or {}).get('motif')
                and any(same_photo(name, old, assets) for old in recent[-2:])):
            for candidate in files[1:]:
                asset = assets.get(candidate, {})
                if ((asset.get('editor_confirmed') or (asset.get('vision_verified') and asset.get('vision_relevant')))
                        and not asset.get('vision_needs_review')
                        and not any(same_photo(candidate, old, assets) for old in recent[-2:])):
                    name = candidate
                    chunk['files'] = [name, *[f for f in files if f != name]]
                    changed[cid] = chunk['files']
                    break
        recent.append(name)
    return changed


def sequence_issues(chunks, assets, overrides=None):
    recent, issues = [], []
    for index, chunk in enumerate(chunks):
        cid = chunk.get('id', index)
        names = (overrides or {}).get(str(cid), (overrides or {}).get(cid, chunk.get('files', [])[:1]))
        if not _ordinary(chunk) or len(names) != 1:
            recent = []
            continue
        name = names[0]
        if chunk.get('type') == 'photo' and not (chunk.get('shot_plan') or {}).get('motif'):
            if any(same_photo(name, old['file'], assets) for old in recent[-2:] if old['type']=='photo'):
                issues.append(dict(chunk_id=cid,start=chunk.get('start',0),end=chunk.get('end',0),
                    file=name,severity=1,reason='Повтор того же изображения рядом; подтверждённой другой версии в пуле нет'))
        scale = assets.get(name,{}).get('vision_visual_evidence',{}).get('shot_scale','unknown')
        if scale != 'unknown' and len(recent) >= 2:
            group = recent[-2:]
            if (chunk.get('scene_id') is not None and all(c['scene']==chunk['scene_id'] and c['scale']==scale for c in group)
                    and len({c['planned'] for c in group} | {(chunk.get('shot_plan') or {}).get('scale','unknown')}) > 1):
                issues.append(dict(chunk_id=cid,start=chunk.get('start',0),end=chunk.get('end',0),file=name,
                    severity=1,reason='Три фактических плана одной крупности: запланированная смена крупности не получилась'))
        recent.append(dict(file=name,type=chunk.get('type'),scale=scale,scene=chunk.get('scene_id'),
                           planned=(chunk.get('shot_plan') or {}).get('scale','unknown')))
    return issues
