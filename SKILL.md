---
name: ai-image-assets
description: Write prompts for image generators (ChatGPT / gpt-image, Gemini / Nano Banana, Midjourney) for app and website assets, and process what comes back. Use when the user asks for image, illustration, photo, icon or logo prompts ("şəkil promptu yaz", "loqo üçün prompt"), when they hand back generated images to clean ("arxa planı təmizlə", "fonu sil", "kəs", "şəffaf et", "remove background"), or to turn into vectors ("vektora çevir", "SVG et", "vectorize"). Covers the magenta-backdrop method for transparency, vector-ready prompts for potrace, and the two bundled scripts that cut and vectorize.
---

# Diffusion image prompts — transparent cut-outs and vectors

Three families of asset, three ways of prompting. Decide the family for every image first.

| Family | Use for | Background in the prompt | After generation |
|---|---|---|---|
| **Cut-out** | illustrations, objects, banners, empty states, anything that sits on a changing background | flat magenta `#FF00FF` | `scripts/cut_magenta.py` → transparent PNG |
| **Photo** | property/product photos, covers | a real scene, no backdrop | crop to the box (`cut_magenta.py photo`) |
| **Vector** | logos, marks, icons, app icons — anything that must become SVG | flat white (one colour) or flat magenta (several colours, or white inside the mark) | `scripts/vectorize.py` → SVG |

Write the prompt document in the user's language (prose), keep every prompt itself in English.

## 1. Why magenta (the transparency method)

Diffusion models give no alpha channel, so ask for a backdrop that is removed afterwards.
- **Not white**: white walls, paper, highlights and window light would be cut with it.
- **Magenta** is the one colour with red and blue high and green low. Nothing in a normal palette
  (greens, whites, stone, wood, amber, blues) has `min(R,B) − G` high, so the script can measure how much
  backdrop each pixel holds and remove exactly that much — soft edges, glass and shadows survive.
- Therefore **forbid pink, purple and violet** in every cut-out prompt; they would turn transparent.
- Generators rarely return pure `#FF00FF`: Gemini (Nano Banana) returned violet fields like `(212,87,243)` and
  `(205,123,218)` with a 10–15 unit drift and noise. That is fine — the script samples the corners and
  tolerates drift. Only a field that is not magenta at all (grey, gradient sky) fails.

## 2. Prompt anatomy (every prompt complete, copy-paste ready)

```
SUBJECT: <what, described by proportions, not just by name>
(or for a sheet) LAYOUT: one wide sheet containing EXACTLY N objects in one row, evenly spaced with wide
magenta gaps, all at the same scale. Each object is drawn exactly once. Do not repeat an object, do not add
an extra object, do not fill empty space. No object touches another object or the edge of the sheet.

STYLE: <identical, word for word, in every prompt of the family>
CAMERA: <angle, framing, "nothing cropped at the edges">
BACKGROUND: one flat, uniform magenta field (#FF00FF) behind everything, nothing else: no floor, no sky,
no gradient, no vignette, no shadow on the background. The magenta must not appear anywhere on the subject,
in its reflections or in its shadow. No pink, purple or violet materials anywhere.
DO NOT DRAW: text, letters, numbers, signs, logos, watermarks, people, faces, hands, UI, frames, borders.
FORMAT: landscape 3:2 | square 1:1 | portrait 2:3
```

Rules learned the hard way:
1. **The style block is identical in every prompt**; only SUBJECT/LAYOUT changes. That is what makes a set
   look like one family.
2. **2–3 objects per sheet work; 8 do not.** Models ignore counts and repeat to fill space. Use explicit
   «EXACTLY N», numbered items left to right, «do not repeat».
3. **Describe shape by proportion**: «wider than tall, width ≈1.4× height, six storeys, glass corner
   balconies» beats «a modern building».
4. **Name colours in hex** and say where each goes; keep one warm accent at most.
5. **First approved image becomes the style reference** for the rest (attach it in Gemini / ChatGPT, `--sref`
   in Midjourney).
6. Flying objects: say «no shadow» — a cast shadow under a plane or a pin looks wrong once cut out.
7. Give each image an **ID** (S1, F3, L2…) and keep a table: ID · what · where it is used · final canvas
   size · priority. Add acceptance criteria (readable at its real display size, no fringe on light and dark
   backgrounds, no text, exact object count).

Photo family: replace STYLE/BACKGROUND with a photography block (natural light, 24 mm, eye level, verticals
straight, true colours, tidy staging, no HDR) plus SETTING and «no people, no readable text, no watermarks».

## 3. Vector-ready prompts (when the user wants SVG)

When a logo, mark or icon must end up as a vector, write the prompt so the raster traces cleanly with
potrace. Add this block (verbatim) and keep the subject geometric:

```
STYLE: flat vector logo mark, geometric construction on a strict grid, solid flat shapes or uniform thick
strokes, perfectly smooth curves, rounded stroke ends, no gradients, no shadows, no highlights, no
textures, no 3D, no outlines around shapes, no anti-aliasing halos between colours. At most <N> colours,
each a single flat tone: <#hex1>, <#hex2>, <#hex3>. Shapes are closed and separated by clear gaps; no
hairlines thinner than 3% of the mark's width. The mark stays readable printed 24 pixels wide.
BACKGROUND (one colour mark): one perfectly flat pure white field (#FFFFFF), no texture, no paper grain,
no shadow.
BACKGROUND (several colours, or white inside the mark): one flat, uniform magenta field (#FF00FF); no
pink, purple or violet in the mark.
DO NOT DRAW: letters or words unless asked, mock-ups, business cards, devices, frames, drop shadows.
FORMAT: square 1:1, the mark centred, filling about 70% of the frame.
```

Why each rule: potrace traces 1-bit shapes. Gradients and shading become blotches; textures become noise;
thin hairlines break at threshold; colours that are close in tone merge into one layer; a soft shadow turns
into a solid blob. Text in generated images is unreliable — set wordmarks in a real font and vectorize only
the mark, unless the user insists.

## 4. «Arxa planı təmizlə» — cutting the backdrop

Always run the bundled script; do not hand-edit pixels. Copy downloaded images into a scratch folder first
and run Python with `-I`.

```bash
S=~/.claude/skills/ai-image-assets/scripts
python3 -I $S/cut_magenta.py single in.png out.png --canvas 960x640 --fill 0.96 --anchor bottom
python3 -I $S/cut_magenta.py sheet  sheet.png outdir a,b,c --canvas 400x400        # one row of objects
python3 -I $S/cut_magenta.py sheet  sheet.png outdir a,b,c,d --grid 2x2 --canvas 512x512
python3 -I $S/cut_magenta.py single plane.png plane.png --canvas 384x384 --drop-shadow   # no cast shadow
python3 -I $S/cut_magenta.py photo  in.jpg out.jpg --canvas 1200x900                  # crop/scale a photo
```

What it does: samples the backdrop from the corners → removes the magenta share from every pixel
(`min(R,B) − G`, un-blended, so no pink fringe) → treats anything within 82% of the backdrop as backdrop
(drift and noise) → gives nearly transparent pixels one calm shadow tone instead of amplified noise → finds
the object box by counting solid pixels, then **grows it until faint edges end** (+6 px) so curved rims are
never cut by a straight line → scales into the target canvas and pads with transparency. Needs only ffmpeg.

Check every result before placing it:
- composite it on the real light and dark backgrounds of the product and look at the edges;
- verify no alpha touches the canvas border (otherwise something was cut);
- a faint rectangular «haze» around the object means the field drifted more than usual — re-run, or raise
  `SNAP` in the script slightly.
Keep the canvas near the object's native resolution (no big upscales). If WebP is needed and ffmpeg has no
libwebp, ship PNG.

## 5. «Vektora çevir» — raster to SVG

```bash
python3 -I $S/vectorize.py mono   logo.png logo.svg                       # one colour → fill="currentColor"
python3 -I $S/vectorize.py colors logo.png logo.svg "#004532,#5FE3A9,#F59E0B"   # one traced layer per colour
```

The method (proven on calligraphic wordmarks and monograms): isolate the shape (alpha, magenta
matte, or darker-than-threshold on a white field) → crop with a 12 px margin → **upscale 2× with Lanczos
while still grey** (a little blur first) so the tracer sees smooth curves → threshold to 1-bit `.pbm` →
`potrace -s --flat -t 8 -a 1.1 -O 0.4` (`-t` drops specks under 8 px, `-a` corner sensitivity favouring
smooth calligraphic curves, `-O` curve optimisation, lower = more faithful) → strip metadata → mono marks get
`fill="currentColor"` so CSS colours them; colour marks get one `<g>` per palette colour. Pixels far from
every palette colour (shadows, haze) are left out. A `.preview.png` is rendered with `rsvg-convert` —
compare it with the source by eye.

Tell the user what tracing is: a faithful copy of the generated shapes, including their small
irregularities. For large print a designer should still clean the curves. Shaded or 3D sources trace badly;
if the user wants a vector, regenerate with the vector-ready prompt (section 3) instead of tracing a render.

## 6. Requirements

`ffmpeg`/`ffprobe` (decode, resize), `potrace` (vectors), optional `rsvg-convert` (preview). On macOS:
`brew install ffmpeg potrace librsvg`. The scripts use only the Python standard library.
