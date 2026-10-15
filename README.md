# ai-image-assets

A [Claude Code](https://claude.com/claude-code) skill for turning AI image generators into a reliable asset
pipeline for apps and websites:

- **Transparent cut-outs** — prompt illustrations on a flat magenta backdrop, then remove it pixel-exactly
  (soft edges, glass and contact shadows survive, no pink fringe).
- **Vector logos and icons** — prompt marks so they trace cleanly, then convert raster → SVG with potrace.
- **Consistent sets** — one verbatim style block per family, explicit object counts, proportions instead
  of names, IDs and acceptance criteria for every image.

Works with ChatGPT (gpt-image), Gemini (Nano Banana), Midjourney or any other generator.

## Why magenta instead of a transparent background

Diffusion models do not output an alpha channel. A white backdrop cannot be removed without eating white
walls, paper and highlights. Magenta is the one colour with red and blue high and green low, so
`min(R, B) − G` measures how much backdrop each pixel contains — the script removes exactly that share and
"un-blends" the rest. Prompts therefore forbid pink, purple and violet in the subject.

Generators rarely return pure `#FF00FF` (violet fields like `(212, 87, 243)` are common, with drift and
noise). The script samples the backdrop from the corners and tolerates both.

## Install

```bash
git clone https://github.com/ulvi-vali/ai-image-assets ~/.claude/skills/ai-image-assets
brew install ffmpeg potrace librsvg      # macOS; use your package manager elsewhere
```

The scripts use only the Python standard library plus `ffmpeg`, `potrace` and (optionally)
`rsvg-convert`. Claude Code picks the skill up automatically; ask it for image prompts, to clean a
background, or to vectorize a logo.

## Scripts

### `scripts/cut_magenta.py` — remove the backdrop

```bash
python3 -I scripts/cut_magenta.py single in.png out.png --canvas 960x640 --fill 0.96 --anchor bottom
python3 -I scripts/cut_magenta.py sheet  sheet.png outdir a,b,c --canvas 400x400
python3 -I scripts/cut_magenta.py sheet  sheet.png outdir a,b,c,d --grid 2x2 --canvas 512x512
python3 -I scripts/cut_magenta.py single plane.png plane.png --canvas 384x384 --drop-shadow
python3 -I scripts/cut_magenta.py photo  in.jpg out.jpg --canvas 1200x900
```

1. Samples the backdrop from the four corners (never assumes `#FF00FF`).
2. Per pixel, measures the magenta share and removes it (un-blends), so edges stay clean.
3. Treats anything within 82% of the backdrop as backdrop (gradient drift, JPEG noise) and gives nearly
   transparent pixels one calm shadow tone instead of amplified noise.
4. Finds the object by counting solid pixels, then grows the box until faint edges end (+6 px), so curved
   rims are never cut by a straight line.
5. Scales into a fixed canvas and pads with transparency. `sheet` splits a row (or a grid) of objects.

### `scripts/vectorize.py` — raster to SVG

```bash
python3 -I scripts/vectorize.py mono   logo.png logo.svg                          # fill="currentColor"
python3 -I scripts/vectorize.py colors logo.png logo.svg "#004532,#5FE3A9,#F59E0B"  # one layer per colour
```

Isolate the shape (real alpha, magenta matte, or darker than a threshold on white) → crop with a 12 px
margin → upscale 2× with Lanczos while still grey → threshold to 1-bit → `potrace -s --flat -t 8 -a 1.1 -O 0.4`
→ strip metadata → `currentColor` for one-colour marks, one `<g>` per colour otherwise. Off-palette pixels
(shadows, haze) are dropped. A `.preview.png` is rendered for a visual check.

Tracing copies the generated shapes faithfully, small irregularities included. Shaded or 3D renders trace
badly — regenerate with the vector-ready prompt from `SKILL.md` instead.

## Prompt templates

See [`SKILL.md`](SKILL.md): the cut-out prompt anatomy (SUBJECT / LAYOUT / STYLE / CAMERA / BACKGROUND /
DO NOT DRAW / FORMAT), the photo block, and the vector-ready block.

## Azərbaycanca qısa

Bu skill süni intellekt şəkil generatorları üçün prompt yazır və gələn şəkilləri emal edir:
- **Şəffaf fon:** illüstrasiya magenta fonda çəkilir, `cut_magenta.py` fonu pikselin payına görə çıxarır.
- **Vektor:** loqo və ikonlar potrace üçün uyğun promptla çəkilir, `vectorize.py` SVG-yə çevirir.
- Claude Code-a «arxa planı təmizlə», «vektora çevir» və ya «şəkil promptu yaz» deməyiniz kifayətdir.

## License

MIT — see [LICENSE](LICENSE).
