# Paper Card

Reusable Remotion scene (1920×1080, 30 fps). A photo or video enters from off-screen and turns in 3D over a background. The video assembler selects it through `chunk.template` (see `../README.md`).

```bash
npm install
npm run render -- /path/to/background.jpg /path/to/photo.jpeg /path/to/output.mp4 top-right
```

The fourth argument is `top-right`, `top-left`, `bottom-right`, `bottom-left`, `top`, `bottom`, `left`, or `right`. Omit it for `top-right`. Optional fifth and sixth arguments set frame count and scale. Run `npm run studio` to preview the composition.
