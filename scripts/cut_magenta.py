"""Cut generated illustrations off their magenta backdrop into transparent PNGs.

Diffusion models give no alpha channel, so every cut-out prompt asks for a flat
magenta (#FF00FF) field. This tool turns that field into transparency.

    python3 -I cut_magenta.py single in.png out.png --canvas 960x640 [--fill 0.9] [--anchor bottom]
    python3 -I cut_magenta.py sheet  in.png outdir name1,name2,name3 --canvas 400x400 [--grid 2x2]
    python3 -I cut_magenta.py photo  in.jpg out.jpg --canvas 1200x900

How the matte works:
  * the backdrop is sampled from the four corners, never assumed (a JPEG "#FF00FF" arrives as
    something like (247, 12, 249));
  * magenta is the only colour with red and blue high and green low, so min(R, B) - G measures how
    much backdrop a pixel holds: near the backdrop's own value on the field, at or below zero on every
    painted surface (greens, whites, stone, oak, amber), in between on soft edges and shadows;
  * that share is taken OUT of the pixel (un-blended), so no pink fringe survives on edges, glass or
    contact shadows;
  * the object's box is found by counting solid pixels per row/column, so a stray JPEG column at
    the border cannot stretch it.
Needs only ffmpeg (decode, resize, pad) and the standard library.
"""

import os
import struct
import subprocess
import sys
import tempfile
import zlib

FLOOR = 18          # below this much magenta a pixel is untouched foreground (JPEG chroma haze)
ALPHA_MIN = 0.02    # below this alpha a pixel is dropped entirely


def decode(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", path],
                           capture_output=True, text=True, check=True).stdout.strip()
    width, height = (int(v) for v in probe.split(",")[:2])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return width, height, raw


def backdrop(raw, width, height):
    total, count = [0, 0, 0], 0
    for cx, cy in ((4, 4), (width - 14, 4), (4, height - 14), (width - 14, height - 14)):
        for y in range(cy, cy + 10):
            for x in range(cx, cx + 10):
                i = (y * width + x) * 3
                for c in range(3):
                    total[c] += raw[i + c]
                count += 1
    return tuple(t / count for t in total)


SNAP = 0.82        # a backdrop that drifts (gradient, noise) still counts as backdrop above this share
SHADOW_ALPHA = 0.4 # below this alpha a pixel is shadow or haze: give it a calm shadow tone, not noise
SHADOW_RGB = (14, 30, 22)


def matte(raw, width, height, back):
    """RGBA bytes with the backdrop share removed from every pixel.

    Generators rarely return one flat colour: the field drifts by 10-15 units across the frame and
    carries noise. Un-blending a pixel that is 97% backdrop divides that noise by 0.03, which turns a
    clean field into a faint coloured box. So the share is measured against SNAP of the sampled
    reach (anything that close to the backdrop is backdrop), and nearly transparent pixels — which
    are shadows — get one fixed dark tone instead of amplified noise.
    """
    reach = max(1.0, (min(back[0], back[2]) - back[1] - FLOOR) * SNAP)
    out = bytearray(width * height * 4)
    for p in range(width * height):
        i = p * 3
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        v = min(r, b) - g - FLOOR
        share = 0.0 if v <= 0 else min(1.0, v / reach)
        alpha = 1.0 - share
        o = p * 4
        if alpha <= ALPHA_MIN:
            continue
        if alpha < SHADOW_ALPHA:
            out[o:o + 3] = bytes(SHADOW_RGB)
        else:
            for k, (value, bk) in enumerate(((r, back[0]), (g, back[1]), (b, back[2]))):
                out[o + k] = max(0, min(255, int(round((value - share * bk) / alpha))))
        out[o + 3] = int(round(alpha * 255))
    return out


def ink_box(rgba, width, x0, y0, x1, y1, threshold=128, least=4):
    cols = [0] * (x1 - x0)
    rows = [0] * (y1 - y0)
    for y in range(y0, y1):
        base = y * width * 4
        for x in range(x0, x1):
            if rgba[base + x * 4 + 3] > threshold:
                cols[x - x0] += 1
                rows[y - y0] += 1
    xs = [i for i, n in enumerate(cols) if n >= least]
    ys = [i for i, n in enumerate(rows) if n >= least]
    if not xs or not ys:
        raise SystemExit("no object found in region %s" % ((x0, y0, x1, y1),))
    bx0, by0, bx1, by1 = x0 + xs[0], y0 + ys[0], x0 + xs[-1] + 1, y0 + ys[-1] + 1
    # The solid box misses thin curved edges (a disc's rim, soft shadows) and would cut them with a
    # straight line. Grow each side while the next line still holds faint ink, then keep a margin.
    def ink(line):
        return sum(1 for a in line if a > 12) >= 2
    def col(x):
        return [rgba[(y * width + x) * 4 + 3] for y in range(by0, by1)]
    def row(y):
        return [rgba[(y * width + x) * 4 + 3] for x in range(bx0, bx1)]
    while bx0 > x0 and ink(col(bx0 - 1)):
        bx0 -= 1
    while bx1 < x1 and ink(col(bx1)):
        bx1 += 1
    while by0 > y0 and ink(row(by0 - 1)):
        by0 -= 1
    while by1 < y1 and ink(row(by1)):
        by1 += 1
    pad = 6
    return max(x0, bx0 - pad), max(y0, by0 - pad), min(x1, bx1 + pad), min(y1, by1 + pad)


def column_groups(rgba, width, height, count):
    """Split a one-row sheet into `count` objects at the widest empty column runs."""
    occupied = []
    for x in range(width):
        n = 0
        for y in range(0, height, 2):
            if rgba[(y * width + x) * 4 + 3] > 128:
                n += 1
                if n >= 3:
                    break
        occupied.append(n >= 3)
    gaps, start = [], None
    for x, occ in enumerate(occupied + [True]):
        if not occ and start is None:
            start = x
        elif occ and start is not None:
            if start > 0 and x < width:
                gaps.append((x - start, start, x))
            start = None
    cuts = sorted(sorted(gaps, reverse=True)[:count - 1], key=lambda g: g[1])
    edges = [0] + [(a + b) // 2 for _, a, b in cuts] + [width]
    return [(edges[i], 0, edges[i + 1], height) for i in range(count)]


def write_png(path, rgba, width, height):
    rows = b"".join(b"\x00" + bytes(rgba[y * width * 4:(y + 1) * width * 4]) for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(rows, 9)))
        fh.write(chunk(b"IEND", b""))


def crop(rgba, width, box):
    x0, y0, x1, y1 = box
    out = bytearray()
    for y in range(y0, y1):
        out += rgba[(y * width + x0) * 4:(y * width + x1) * 4]
    return out, x1 - x0, y1 - y0


def place(piece_png, out_path, cw, ch, fill, anchor):
    """Scale the cropped piece to fit fill*canvas, then pad it onto a transparent canvas."""
    bw, bh = int(cw * fill), int(ch * fill)
    y = {"bottom": "oh-ih-%d" % max(2, ch // 40), "top": str(max(2, ch // 40)), "center": "(oh-ih)/2"}[anchor]
    vf = ("scale=w=%d:h=%d:force_original_aspect_ratio=decrease:flags=lanczos,"
          "pad=%d:%d:(ow-iw)/2:%s:color=black@0,format=rgba" % (bw, bh, cw, ch, y))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", piece_png, "-vf", vf, out_path], check=True)


def parse_size(text):
    w, h = text.lower().split("x")
    return int(w), int(h)


def option(args, name, default):
    if name in args:
        i = args.index(name)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        raise SystemExit(__doc__)
    canvas = parse_size(option(args, "--canvas", "800x800"))
    fill = float(option(args, "--fill", "0.9"))
    anchor = option(args, "--anchor", "center")
    grid = option(args, "--grid", "")
    drop_shadow = "--drop-shadow" in args
    if drop_shadow:
        args.remove("--drop-shadow")
    mode = args[0]

    if mode == "photo":
        src, dst = args[1], args[2]
        cw, ch = canvas
        vf = "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d" % (cw, ch, cw, ch)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf, "-q:v", "3", dst], check=True)
        print("photo %s -> %s %dx%d" % (src, dst, cw, ch))
        return

    src = args[1]
    width, height, raw = decode(src)
    back = backdrop(raw, width, height)
    print("source %dx%d, backdrop sampled as (%d, %d, %d)" % ((width, height) + tuple(round(c) for c in back)))
    if min(back[0], back[2]) - back[1] < 60:
        raise SystemExit("corners are not magenta — was the image generated on #FF00FF?")
    rgba = matte(raw, width, height, back)
    if drop_shadow:
        # A flying object should not carry the generator's cast shadow: drop pixels that are both
        # partly transparent and dark once the backdrop is taken out (shadow), keep everything else.
        for p in range(width * height):
            o = p * 4
            a = rgba[o + 3]
            if 0 < a < 215 and rgba[o] + rgba[o + 1] + rgba[o + 2] < 200:
                rgba[o + 3] = 0

    if mode == "single":
        regions, names, outdir = [(0, 0, width, height)], [os.path.basename(args[2])], os.path.dirname(args[2]) or "."
    elif mode == "sheet":
        outdir, names = args[2], args[3].split(",")
        if grid:
            rws, cls = (int(v) for v in grid.lower().split("x"))
            regions = [(c * width // cls, r * height // rws, (c + 1) * width // cls, (r + 1) * height // rws)
                       for r in range(rws) for c in range(cls)]
        else:
            regions = column_groups(rgba, width, height, len(names))
        names = [n if n.endswith(".png") else n + ".png" for n in names]
    else:
        raise SystemExit(__doc__)

    os.makedirs(outdir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, region in zip(names, regions):
            box = ink_box(rgba, width, *region)
            piece, pw, ph = crop(rgba, width, box)
            tmp_png = os.path.join(tmp, name)
            write_png(tmp_png, piece, pw, ph)
            out = os.path.join(outdir, name)
            place(tmp_png, out, canvas[0], canvas[1], fill, anchor)
            print("wrote %s  object %dx%d at %s -> canvas %dx%d" % (out, pw, ph, box[:2], canvas[0], canvas[1]))


if __name__ == "__main__":
    main()
