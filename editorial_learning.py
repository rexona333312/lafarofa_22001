"""Reuse explicit editor choices, with the original request and provenance intact."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

from media_matching import requested_format, requested_work, requested_creator, requested_kind, MATCH_VERSION

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}


def _normal(value):
    return ' '.join(re.findall(r'[^\W_]+', str(value or '').casefold()))


def request_profile(plan):
    if (plan.get('type') != 'photo' or not plan.get('entity') or plan.get('panels')
            or plan.get('music_insert') or plan.get('media_origin', 'real') != 'real'
            or requested_format(plan) not in {'person_portrait', 'record_cover', 'document'}):
        return None
    if (plan.get('entity_type') == 'person' and len(_normal(plan['entity']).split()) < 2
            and not any(len(_normal(v).split()) > 1 for v in plan.get('entity_aliases', []))
            and not plan.get('context')):
        return None
    # Reuse a request, never infer that two events are equivalent from a shared name.
    data = dict(entity_type=plan.get('entity_type'))
    data.update(work_creator=_normal(requested_creator(plan)), work_kind=requested_kind(plan) or 'other')
    data.update({key: _normal(plan.get(key)) for key in ('query', 'entity', 'context', 'visual_intent')})
    data.update(format=requested_format(plan), work=_normal(requested_work(plan)),
                required=sorted(_normal(x) for x in plan.get('required_terms', [])),
                forbidden=sorted(_normal(x) for x in plan.get('negative_keywords', [])),
                years=sorted(set(re.findall(r'\b(?:1\d{3}|20\d{2})\b', plan.get('text', '')))),
                scale=(plan.get('shot_plan') or {}).get('scale', 'unknown'))
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _local_file(root, scene, name):
    if not re.fullmatch(r'[\w.-]+', name) or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
        return None
    base = Path(root).resolve()
    path = (base / scene / 'downloads' / name).resolve()
    if not path.is_relative_to(base / scene / 'downloads') or not path.is_file():
        return None
    return path


def load_approved(root):
    from stock_downloader import image_perceptual_hash
    entries, seen = [], set()
    for project in sorted(Path(root).glob('*/project.json')):
        try:
            data = json.loads(project.read_text())
            for chunk in data.get('chunks', []):
                profile = request_profile(chunk)
                if not profile:
                    continue
                selected = data.get('file_overrides', {}).get(str(chunk.get('id')), [])
                if len(selected) != 1:
                    continue
                name = selected[0]
                asset = data.get('assets', {}).get(name, {})
                if asset.get('approved_reuse') or not (name.startswith('user_') or asset.get('editor_confirmed')):
                    continue
                if (requested_format(chunk) != 'person_portrait' and not (
                        asset.get('vision_verified') and asset.get('vision_relevant')
                        and str(asset.get('vision_match_key','')).startswith(MATCH_VERSION))):
                    continue
                path = _local_file(root, project.parent.name, name)
                if not path:
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                proof = (profile, digest, chunk.get('match_policy','illustrative'),
                         tuple(sorted(_normal(v) for v in chunk.get('entity_aliases', []))))
                if proof in seen:
                    continue
                seen.add(proof)
                asset = dict(asset)
                asset.setdefault('perceptual_hash', image_perceptual_hash(str(path)))
                if not asset['perceptual_hash']:
                    continue
                entries.append(dict(profile=profile, path=str(path), digest=digest,
                    scene=project.parent.name, chunk_id=chunk['id'], filename=name,
                    aliases=chunk.get('entity_aliases', []), match_policy=chunk.get('match_policy','illustrative'), asset=asset))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return entries


def reuse_approved(plan, entries, scene_dir, chunk_id, used):
    profile = request_profile(plan)
    for entry in entries if profile else []:
        if entry['profile'] != profile or entry['digest'] in used:
            continue
        if plan.get('match_policy') == 'strict' and entry['match_policy'] != 'strict':
            continue
        left = {_normal(v) for v in plan.get('entity_aliases', [])}
        right = {_normal(v) for v in entry['aliases']}
        if left and right and not left.intersection(right):
            continue
        source = Path(entry['path'])
        name = f'approved_{chunk_id}_{entry["digest"][:20]}{source.suffix.lower()}'
        target = Path(scene_dir) / 'downloads' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
        except OSError:
            continue
        used.add(entry['digest'])
        asset = {key: value for key, value in entry['asset'].items()
                 if key in {'source', 'page_url', 'original_url', 'image_url', 'search_text',
                            'rights_confirmed', 'license', 'perceptual_hash'}}
        asset.update(editor_confirmed=True, approved_reuse=True, approval_profile=profile,
            approved_digest=entry['digest'],
            approved_from=dict(scene=entry['scene'], chunk_id=entry['chunk_id'], file=entry['filename']),
            source=asset.get('source') or 'Подтверждённый редактором материал', media_origin='real')
        return str(target), asset
    return None


def record_choice(session, chunk, names):
    previous = session.get('file_overrides', {}).get(str(chunk['id']), chunk.get('files', [])[:1])
    if list(previous) != list(names):
        session.setdefault('editorial_corrections', []).append(dict(
            time=time.time(), chunk_id=chunk['id'], previous=list(previous), selected=list(names),
            request={key:copy.deepcopy(chunk[key]) for key in ('query','entity','entity_type','entity_aliases',
                'type','visual_intent','context','match_policy','required_terms','required_format','work_title',
                'work_creator','work_kind','shot_plan') if key in chunk},
            previous_sources={name:{key:asset[key] for key in ('source','search_text','page_url','original_url',
                'source_start','source_end') if key in asset} for name in previous
                for asset in [session.get('assets',{}).get(name,{})]},
            profile=request_profile(chunk), classification='editor_choice_reason_unspecified'))
    for name in names:
        session.setdefault('assets', {}).setdefault(name, {})['editor_confirmed'] = True


def propagate_choice(session, source, names):
    """Up to two compatible unresolved shots; never overwrite explicit choices."""
    profile = request_profile(source)
    if not profile or len(names) != 1:
        return []
    name = names[0]
    if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
        return []
    asset = session.get('assets',{}).get(name,{})
    if requested_format(source) != 'person_portrait' and not (
            asset.get('vision_verified') and asset.get('vision_relevant')
            and str(asset.get('vision_match_key','')).startswith(MATCH_VERSION)):
        return []
    changed = []
    for chunk in session.get('chunks', []):
        cid = chunk['id']
        if (cid == source['id'] or str(cid) in session.get('file_overrides', {})
                or abs(cid-source['id']) < 2 or request_profile(chunk) != profile):
            continue
        if chunk.get('match_policy') == 'strict' and source.get('match_policy') != 'strict':
            continue
        if any(abs(cid - updated['id']) < 2 for updated in changed):
            continue
        left = {_normal(v) for v in source.get('entity_aliases', [])}
        right = {_normal(v) for v in chunk.get('entity_aliases', [])}
        if left and right and not left.intersection(right):
            continue
        current = next(iter(chunk.get('files', [])), None)
        asset = session.get('assets', {}).get(current, {})
        if (asset.get('editor_confirmed') or (asset.get('vision_verified') and asset.get('vision_relevant')
                and asset.get('vision_match_key') and not asset.get('vision_needs_review'))):
            continue
        chunk['files'] = [name, *[f for f in chunk.get('files', []) if f != name]]
        chunk['approved_reuse_from'] = source['id']
        changed.append(copy.deepcopy(chunk))
        if len(changed) == 2:
            break
    return changed
