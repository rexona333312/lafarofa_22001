# Remotion pack from the Switzerland reference

Source analysis: `reference_analysis/swiss_1019_20261019/index.html`, 294 clips / 1,238 samples. The implementation reuses semantic patterns and visual language; it does not assume exact original fonts, easing curves, sound effects or verified historical facts.

## What changed

- `evidence_board`: 2–5 adjacent photo chunks share `params.carousel_group`. Each chunk has its own media query and `caption` (up to 60 characters). Cards accumulate and remain visible across cuts; carousel groups and existing internal-cut validation provide continuity.
- `stat_callout`: one exact `value` string and `label`; `layout:card` for a photo or `layout:overlay` for photo/video. `start_frame` and `arrival_frames` are local 30 fps timings; an overlay's ordinary lead-in is excluded from graphic coverage.
- `data_comparison`: 2–5 items with label, numeric value, formatted display and local start_frame. Bar lengths share one scale; all numeric values must use the same unit. The rendered labels preserve the requested values rather than inventing a count-up.
- `document_focus`: source-image `focus_rect:[x,y,width,height]`, normalized to 0–1. The whole document appears, the camera zooms to that region, then a light highlight or red circle appears. `zoom_start_frame` and `highlight_start_frame` enforce this order. No OCR or invented document quotations.
- `portrait_profile`: a framed photograph beside `name` and `description`; no cutout needed.
- `map_geographic`: NASA satellite imagery, modern Natural Earth boundaries, animated country/region highlights, routes and markers, plus flat/terrain camera modes. Both old map names also use this new renderer when `params.geo` is supplied. Previously authored `[x,y]` maps remain compatible. New planning exports prefer the geographic renderer.

Schema examples are exported as `documentary_template_contracts` and stored in `editorial_planning.py`. A complete assembled example is `examples/timeline_swiss_pack.json`. The gallery is `output/scene_swiss_pack/index.html`.

## Planning and coverage

The app continues its existing workflow: export timestamped input to Codex, receive a semantic timeline, validate it and assemble media. This update adds reference-based planning rules and structured contracts to that export; it does not add an autonomous language model inside the app.

The interface exposes a duration target, initially 70%, and measured coverage of the imported timeline. `motion_graphics_target` can be 0–100 and persists in the project. It is guidance for the next planning export, not an automatic operation that inserts random graphics into an existing edit. The 69.9% reference measurement includes photo cards and overlays; ordinary pan/zoom, avatar footage, vignette and transitions are excluded. Overlapping graphics/text are counted as a union of actual timeline intervals. Repeated-template warnings are advisory, not destructive rewrites.

Frame timings are local to each chunk, derived from real transcript onsets. Continuing text can span adjacent chunks using the existing text-cue track. Numeric values, labels, units and document focus positions still need correct source inputs; code cannot verify their factual truth.

Map scenes with real coordinates and data-comparison charts create a local picker thumbnail and skip stock search. Their final map is rendered from geodata during assembly. Required tiles are cached locally; the first use of a new camera area needs internet. NASA's global imagery is approximately 500 m, so very close satellite views are softer than high-resolution Google Earth imagery. Detailed photogrammetric buildings and historical border reconstruction are not included.

## Use

Restart the app to load the Python changes, choose the graphics target, then download a fresh input JSON. Existing already-downloaded JSON files keep their old instructions. Review the returned timeline and assemble normally. The preview project `scene_swiss_pack` can also be opened in the app.

Install reproducible JavaScript dependencies with `npm ci` in `assets/remotion/paper_card`; MapLibre is pinned to 6.15.0. `npm audit` after the dependency update reported zero vulnerabilities. Template assets and sound effects use the existing library. Backups of edited original files are in `backups/before_swiss_pack_20261020`.
