"""Compatibility adapter: existing still-photo presets use the Remotion camera."""
from pathlib import Path
from presets import PRESETS, IMAGE_EXTENSIONS, dimensions, asset_path


def uses_photo_camera(source, scene):
    if not source or Path(source).suffix.lower() not in IMAGE_EXTENSIONS or scene.get('template'):
        return False
    preset=PRESETS[scene.get('preset','PHOTO_SLOW_ZOOM' if scene['type']=='photo' else 'PHOTO_STATIC')]
    params=scene.get('params',{})
    a=float(params.get('zoom_start',preset['zoom_start']))
    b=float(params.get('zoom_end',preset['zoom_end']))
    return preset['id'] in {'PHOTO_SLOW_ZOOM','PHOTO_SLOW_ZOOM_OUT','PHOTO_PAN','BLUR_BG_CENTER'} or a != b


def photo_camera_props(source,scene,width,height):
    preset=PRESETS[scene.get('preset','PHOTO_SLOW_ZOOM' if scene['type']=='photo' else 'PHOTO_STATIC')]
    params=scene.get('params',{})
    iw,ih=dimensions(source)
    fit=params.get('fit','auto')
    layout=preset['layout']
    a=float(params.get('zoom_start',preset['zoom_start']))
    b=float(params.get('zoom_end',preset['zoom_end']))
    if layout=='full':
        if fit=='auto' and (iw<1920 or ih<1080):
            layout='blur'
            if b>a and 'zoom_end' not in params:
                b=.04  # Preserve the former small-photo inward movement, never reverse an outward move.
        elif fit=='contain' or (fit=='auto' and abs(iw/ih-width/height)>.06):
            layout='contain'
        else:
            layout='cover'
    paper=asset_path(params['paper'],{'paper'}) if layout=='paper' and params.get('paper') else None
    return {'cameraParams':{'layout':layout,'zoom_start':a,'zoom_end':b,
                            'direction':params.get('direction','right') if preset['id']=='PHOTO_PAN' else None,
                            'blur':float(params.get('blur',28))}},paper
