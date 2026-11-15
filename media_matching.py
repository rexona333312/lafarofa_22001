"""Shared factual requirements for retrieval and Apple's visual verdict."""
import hashlib
import json
import re

VISUAL_FORMATS = ('person_portrait', 'interview', 'performance', 'record_cover', 'document', 'map', 'general')
MATCH_VERSION = 'apple-match-v3:'


def requested_format(plan):
    if plan.get('required_format'):
        return plan['required_format']
    if plan.get('music_insert'):
        return 'performance'
    text = plan.get('query', '').casefold()
    if re.search(r'\b(single|album|record|cd|schallplatte)\b.*\b(cover|sleeve)\b', text):
        return 'record_cover'
    if (plan.get('entity_type') in {'object', 'culture'} and re.search(r'\bcover\b', text)
            and re.search(r'album|single|record|обложк|альбом', plan.get('visual_intent', ''), re.I)):
        return 'record_cover'
    if re.search(r'\b(portrait|porträt|портрет)\b', text):
        return 'person_portrait'
    if re.search(r'\binterview\b', text):
        return 'interview'
    if plan.get('entity_type') in {'object', 'culture'} and re.search(r'\b(programm|program|plakat|poster|theater|theatre)\b', text):
        return 'document'
    return {'document': 'document', 'map': 'map'}.get(plan.get('role'), 'general')


def requested_work(plan):
    if plan.get('work_title'):
        return plan['work_title']
    # Older imported music plans put the exact title in guillemets instead.
    if plan.get('music_insert'):
        titles = re.findall(r'«([^»]+)»|“([^”]+)”|"([^"\n]+)"', plan.get('visual_intent', ''))
        if len(titles) == 1:
            return next(t for t in titles[0] if t).strip()
    if requested_format(plan) == 'record_cover' and plan.get('entity_type') in {'object', 'culture'}:
        return plan.get('entity', '')
    return ''


def requested_creator(plan):
    if plan.get('work_creator'):
        return plan['work_creator']
    if requested_format(plan) == 'record_cover' and plan.get('entity_type') in {'object', 'culture'}:
        title = requested_work(plan)
        if title:
            match = re.search(re.escape(title), plan.get('query', ''), re.I)
            prefix = plan['query'][:match.start()].strip(' ,"') if match else ''
            if prefix and len(prefix.split()) <= 5 and not re.search(r'\d|cover|album|original|single|vinyl', prefix, re.I):
                return prefix
    return ''


def requested_kind(plan):
    if plan.get('work_kind'):
        return plan['work_kind']
    if (plan.get('entity_type') in {'object', 'culture'}
            and re.search(r'\bmusical\b(?!\s+instrument)', plan.get('query', ''), re.I)):
        return 'musical'
    if plan.get('entity_type') in {'object', 'culture'} and re.search(r'\b(theater|theatre)\b', plan.get('query',''), re.I):
        return 'theatre'
    return ''


def source_identity_conflict(plan, source_subject):
    """Reject explicit namesakes, not missing captions or alternate spellings."""
    if plan.get('entity_type') != 'person' or not source_subject:
        return False
    def words(value):
        return re.findall(r'[^\W_]+', value.casefold())
    subject = words(source_subject)
    names = [words(name) for name in [plan.get('entity', ''), *plan.get('entity_aliases', [])]]
    if any(subject == name or (len(subject) == len(name) and sorted(subject) == sorted(name)) for name in names):
        return False
    if any(len(name) >= 2 and len(subject) >= 2 and name[0] == subject[0] and name[-1] == subject[-1]
           for name in names):
        return False
    # A longer explicit name sharing only part of a supplied name is not that identity.
    return len(subject) > 1 and any(set(name) & set(subject) for name in names if name)


def match_key(plan):
    fields = ('query', 'text', 'visual_intent', 'context', 'editor_note_ru', 'entity',
              'entity_type', 'entity_aliases', 'search_mode', 'match_policy', 'required_terms',
              'negative_keywords', 'work_title', 'work_creator', 'work_kind', 'required_format',
              'music_insert', 'shot_plan', 'duration')
    data = {key: plan[key] for key in fields if key in plan}
    data['person_role'] = (plan.get('params') or {}).get('person_role')
    return MATCH_VERSION + hashlib.sha256(json.dumps(data, sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()[:20]


def apply_apple_checks(item, choice, plan, evidence=None):
    """An aggregate score cannot overrule a conflicting individual check."""
    checks = {key: choice.get(key, 'unknown')
              for key in ('subject_match', 'visual_match', 'context_match')}
    allowed = {'supported', 'conflict', 'unknown', 'not_required'}
    if any(value not in allowed for value in checks.values()):
        raise ValueError('Apple вернул неверный формат проверки соответствия')
    conflicts = [key for key, value in checks.items() if value == 'conflict']
    required = ['visual_match']
    if plan.get('entity') and (plan.get('search_mode', 'exact') == 'exact'
                               or plan.get('entity_type') == 'person'):
        required.append('subject_match')
    explicit_context = bool(requested_work(plan) or plan.get('required_terms'))
    if explicit_context or plan.get('match_policy') == 'strict':
        required.append('context_match')
    uncertain = [key for key in required if checks[key] == 'unknown'
                 or (checks[key] == 'not_required' and (key != 'context_match' or explicit_context))]
    if evidence and evidence.get('usable') is False:
        conflicts.append('usable')
    expected_format = requested_format(plan)
    observed_format = (evidence or {}).get('format') or choice.get('observed_format')
    moving_closeup = (plan.get('type') == 'video' and expected_format in {'interview','performance'}
        and observed_format in {'person_portrait','other'} and (evidence or {}).get('motion_type') == 'real_action'
        and choice.get('observed_format') == expected_format)
    if expected_format != 'general' and observed_format != expected_format and not moving_closeup:
        (uncertain if observed_format is None else conflicts).append('format')
    if conflicts or uncertain:
        item['relevant'] = False
        if uncertain and not conflicts:
            item['needs_review'] = True
        label = 'Несоответствие' if conflicts else 'Недостаточно подтверждений'
        item['reason'] = f'{label}: {", ".join(conflicts or uncertain)}. ' + item['reason']
    item.update(match_checks=checks, match_key=match_key(plan), observed_format=observed_format,
                assessed_format=choice.get('observed_format'))
    return item
