"""Remove retired effects while preserving the media and timing of saved projects."""

REMOVED_TEXT = frozenset({'accent1', 'accent2', 'accent3', 'plain1', 'plain2'})
_MAP_PARAMS = frozenset({'annotations', 'camera_zoom', 'title', 'camera_frames',
    'camera_scale_start', 'camera_scale_end', 'rotation_start', 'rotation_end',
    'pan_x', 'pan_y', 'fade_frames'})


def active_text_cues(cues):
    if not isinstance(cues, list):
        return cues
    return [cue for cue in cues if not isinstance(cue, dict) or
            (not (isinstance(cue.get('template'), str) and cue['template'] in REMOVED_TEXT) and
             not (cue.get('kind') == 'plain' and not cue.get('template')))]


def without_retired_templates(project):
    result = dict(project)
    chunks = project.get('chunks')
    if isinstance(chunks, list):
        result['chunks'] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                name, params = chunk.get('template'), chunk.get('params', {})
                legacy_map = name == 'map_annotations' and isinstance(params, dict) and 'geo' not in params
                if name in ('map_trace_camera', 'map_annotations_image') or legacy_map:
                    chunk = dict(chunk)
                    if isinstance(params, dict) and 'geo' in params:
                        chunk['template'] = 'map_geographic'
                    else:
                        chunk.pop('template', None)
                        if isinstance(params, dict):
                            chunk['params'] = {k: v for k, v in params.items() if k not in _MAP_PARAMS}
            result['chunks'].append(chunk)
    if 'text_cues' in project:
        result['text_cues'] = active_text_cues(project['text_cues'])
    return result
