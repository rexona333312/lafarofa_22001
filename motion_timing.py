"""Frame windows shared by the automatic renderer and its SFX tracks (30 fps)."""

def marker_window(frames):
    delay = min(9, max(1, frames // 5))
    sweep = min(33, max(1, frames - delay - 9))
    return delay, sweep


def timeline_scroll_frames(frames, params):
    return min(int(params.get("scroll_frames", 72)), max(1, frames - 45))
