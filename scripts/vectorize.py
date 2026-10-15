"""Turn a generated logo / icon raster into a clean SVG with potrace.

The method: isolate the shape, upscale 2x so the tracer
sees smooth curves, threshold to 1-bit, trace with potrace, strip the metadata, colour with
currentColor (mono) or with the palette colours (one traced layer per colour).

    python3 -I vectorize.py mono   in.png out.svg
    python3 -I vectorize.py colors in.png out.svg "#004532,#5FE3A9,#F59E0B"

Options: --threshold 140 (mono on a white field), --turd 8, --alphamax 1.1, --opttolerance 0.4,
--scale 2 (upscale before tracing), --pad 12.

Background is detected, never assumed:
  * PNG with real transparency  -> the alpha channel is the shape;
  * magenta corners (#FF00FF-ish) -> the magenta matte from cut_magenta.py gives the alpha;
  * anything else (white / light field) -> pixels darker than --threshold are the shape (mono) or
    pixels far from the field colour are the shape (colors).
Needs: ffmpeg (decode, resize), potrace (trace), optional rsvg-convert (preview render).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cut_magenta import backdrop, matte  # noqa: E402


def option(args, name, default, cast=str):
    if name in args:
        i = args.index(name)
        value = args[i + 1]
        del args[i:i + 2]
        return cast(value)
    return default


def decode_rgba(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,pix_fmt", "-of", "csv=p=0", path],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h, fmt = int(probe[0]), int(probe[1]), probe[2] if len(probe) > 2 else ""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                         capture_output=True, check=True).stdout
    return w, h, raw, ("a" in fmt or fmt.startswith("pal"))


def to_alpha_and_rgb(path, threshold):
    """Per pixel: (r, g, b, coverage 0..255), whatever the background was."""
    w, h, rgba, has_alpha = decode_rgba(path)
    alphas = rgba[3::4]
    # Real transparency only when a meaningful share of the frame is see-through; generators often
    # save opaque images as RGBA with a handful of stray alpha values.
    if has_alpha and sum(1 for a in alphas[::7] if a < 128) > len(alphas[::7]) * 0.02:
        return w, h, bytearray(rgba), "alpha"
    rgb = bytes(b for i, b in enumerate(rgba) if i % 4 != 3)
    back = backdrop(rgb, w, h)
    if min(back[0], back[2]) - back[1] > 60:
        return w, h, matte(rgb, w, h, back), "magenta"
    out = bytearray(len(rgba))
    for p in range(w * h):
        r, g, b = rgb[p * 3:p * 3 + 3]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        # Soft coverage (not 0/255): the 2x upscale needs grey edges to produce smooth curves;
        # the threshold is applied after the upscale, exactly at `threshold`.
        cov = max(0, min(255, int(128 + (threshold - lum) * 2.5)))
        out[p * 4:p * 4 + 4] = bytes((r, g, b, cov))
    return w, h, out, "light field"


def hex_rgb(text):
    text = text.strip().lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def masks(w, h, px, palette):
    """One 0/255 coverage plane per colour (mono: one plane)."""
    if not palette:
        return [("currentColor", bytes(px[3::4]))]
    planes = [bytearray(w * h) for _ in palette]
    for p in range(w * h):
        r, g, b, a = px[p * 4:p * 4 + 4]
        if a < 128:
            continue
        dists = [sum((c - q) ** 2 for c, q in zip((r, g, b), palette[k])) for k in range(len(palette))]
        best = min(range(len(palette)), key=dists.__getitem__)
        if dists[best] > 110 ** 2:   # shadow, haze or an off-palette speck: not part of the vector
            continue
        planes[best][p] = 255
    return [("#%02X%02X%02X" % palette[k], bytes(planes[k])) for k in range(len(palette))]


def bbox(planes, w, h, pad):
    xs, ys = [], []
    for _, plane in planes:
        for p in range(0, w * h):
            if plane[p] > 127:
                xs.append(p % w)
                ys.append(p // w)
    if not xs:
        raise SystemExit("no shape found")
    return max(0, min(xs) - pad), max(0, min(ys) - pad), min(w, max(xs) + pad + 1), min(h, max(ys) + pad + 1)


def trace(plane, w, box, scale, turd, alphamax, opt, tmp, name):
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    crop = bytearray()
    for y in range(y0, y1):
        # potrace traces black: invert so the shape is dark on white
        crop += bytes(255 - v for v in plane[y * w + x0:y * w + x1])
    pgm = os.path.join(tmp, name + ".pgm")
    with open(pgm, "wb") as fh:
        fh.write(b"P5\n%d %d\n255\n" % (cw, ch))
        fh.write(crop)
    big = os.path.join(tmp, name + "-x.pgm")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", pgm, "-vf",
                    "gblur=sigma=0.7,scale=%d:%d:flags=lanczos" % (cw * scale, ch * scale), big], check=True)
    pbm = os.path.join(tmp, name + ".pbm")
    with open(big, "rb") as fh:
        data = fh.read()
    head = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", data)
    bw, bh = int(head.group(1)), int(head.group(2))
    pix = data[head.end():]
    rows = []
    for y in range(bh):
        row = bytearray((bw + 7) // 8)
        for x in range(bw):
            if pix[y * bw + x] < 128:
                row[x // 8] |= 0x80 >> (x % 8)
        rows.append(bytes(row))
    with open(pbm, "wb") as fh:
        fh.write(b"P4\n%d %d\n" % (bw, bh) + b"".join(rows))
    svg = os.path.join(tmp, name + ".svg")
    subprocess.run(["potrace", "-s", "--flat", "-t", str(turd), "-a", str(alphamax), "-O", str(opt),
                    "-o", svg, pbm], check=True)
    text = open(svg).read()
    g = re.search(r"<g transform=\"([^\"]+)\"[^>]*>(.*?)</g>", text, re.S)
    vb = re.search(r'viewBox="([^"]+)"', text).group(1)
    return vb, g.group(1), g.group(2).strip()


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    threshold = option(args, "--threshold", 140, int)
    turd = option(args, "--turd", 8, int)
    alphamax = option(args, "--alphamax", 1.1, float)
    opt = option(args, "--opttolerance", 0.4, float)
    scale = option(args, "--scale", 2, int)
    pad = option(args, "--pad", 12, int)
    mode, src, dst = args[0], args[1], args[2]
    palette = [hex_rgb(c) for c in args[3].split(",")] if mode == "colors" else []

    w, h, px, how = to_alpha_and_rgb(src, threshold)
    print("source %dx%d, background: %s" % (w, h, how))
    planes = masks(w, h, px, palette)
    box = bbox(planes, w, h, pad)
    layers, viewbox = [], None
    with tempfile.TemporaryDirectory() as tmp:
        for i, (fill, plane) in enumerate(planes):
            if not any(v > 127 for v in plane):
                continue
            viewbox, transform, paths = trace(plane, w, box, scale, turd, alphamax, opt, tmp, "l%d" % i)
            layers.append('<g transform="%s" fill="%s" stroke="none">\n%s\n</g>' % (transform, fill, paths))
    label = os.path.splitext(os.path.basename(dst))[0]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" role="img" aria-label="%s">\n%s\n</svg>\n'
           % (viewbox, label, "\n".join(layers)))
    with open(dst, "w") as fh:
        fh.write(svg)
    print("wrote %s  %d layer(s), %d bytes" % (dst, len(layers), len(svg.encode())))
    preview = os.path.splitext(dst)[0] + ".preview.png"
    try:
        subprocess.run(["rsvg-convert", "-w", "512", "-b", "white", "-o", preview, dst], check=True)
        print("preview %s (compare it with the source by eye)" % preview)
    except (OSError, subprocess.CalledProcessError):
        pass


if __name__ == "__main__":
    main()
