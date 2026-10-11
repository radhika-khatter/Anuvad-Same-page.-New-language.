"""
Scanned English PDF -> Hindi PDF that LOOKS LIKE THE ORIGINAL

How it works:
  1. Each page is rendered to an image and OCR'd with positions (Tesseract).
  2. Text blocks (paragraphs/headings) are translated to Hindi.
  3. The original page image is kept as the background, each English text block
     is painted over with the page's background colour, and the Hindi text is
     written in the same place (shrunk to fit if Hindi is longer).
  Pictures, logos, lines, tables' borders etc. stay exactly as in the scan.


Usage:
    python pdf_translate_layout.py input.pdf --engine nllb --start 1 --end 2   # test
    python pdf_translate_layout.py input.pdf --engine nllb                      # full

Windows paths :
    --tesseract "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    --poppler   "C:\\poppler\\Library\\bin"

Progress (OCR + translations) is saved to <name>_layout_progress.json
"""
import argparse
import html
import io
import json
import re
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF
    import fitz

import pytesseract
from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import ImageStat
from pytesseract import Output

from pdf_translate_hi import make_engine, preprocess

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\mangal.ttf",
    r"C:\Windows\Fonts\Nirmala.ttf",
    r"C:\Windows\Fonts\NirmalaUI.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
]


def find_font(user_font):
    if user_font:
        if not Path(user_font).exists():
            sys.exit(f"Font not found: {user_font}")
        return user_font
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    # search the Windows fonts folder for any known Hindi-capable font
    fonts_dir = Path(r"C:\Windows\Fonts")
    if fonts_dir.exists():
        for pat in ("mangal*", "nirmala*", "utsaah*", "kokila*", "aparaj*", "*devanagari*"):
            for f in sorted(fonts_dir.glob(pat)):
                if f.suffix.lower() in (".ttf", ".otf", ".ttc") and "b" != f.stem.lower()[-1:]:
                    return str(f)
    sys.exit("No Hindi font found. Pass one with --font \"C:\\path\\to\\font.ttf\"")


# ---------- OCR with positions ----------
def extract_blocks(img, lang="eng", min_conf=40):
    d = pytesseract.image_to_data(
        preprocess(img), lang=lang, config="--psm 3", output_type=Output.DICT
    )
    groups = {}
    for i, txt in enumerate(d["text"]):
        if not txt.strip():
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < min_conf:
            continue
        groups.setdefault((d["block_num"][i], d["par_num"][i]), []).append(i)

    blocks = []
    for idxs in groups.values():
        lines = {}
        for i in idxs:
            lines.setdefault(d["line_num"][i], []).append(i)
        texts, heights = [], []
        x0 = y0 = 10 ** 9
        x1 = y1 = 0
        for ln in sorted(lines):
            ws = sorted(lines[ln], key=lambda i: d["left"][i])
            texts.append(" ".join(d["text"][i].strip() for i in ws))
            top = min(d["top"][i] for i in ws)
            bot = max(d["top"][i] + d["height"][i] for i in ws)
            heights.append(bot - top)
            x0 = min(x0, min(d["left"][i] for i in ws))
            x1 = max(x1, max(d["left"][i] + d["width"][i] for i in ws))
            y0, y1 = min(y0, top), max(y1, bot)
        text = ""
        for t in texts:  # join lines, undo end-of-line hyphenation
            if text.endswith("-") and t[:1].islower():
                text = text[:-1] + t
            else:
                text = f"{text} {t}".strip()
        if len(re.findall(r"[A-Za-z]", text)) < 2:
            continue  # page numbers, stray marks: leave untouched in the scan
        blocks.append(
            {"bbox": [x0, y0, x1, y1], "en": text, "line_h": statistics.median(heights)}
        )
    blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return blocks


# ---------- Rendering ----------
def background_color(img, box):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, img.width), min(y1, img.height)
    if x1 <= x0 or y1 <= y0:
        return (1, 1, 1)
    med = ImageStat.Stat(img.crop((x0, y0, x1, y1)).convert("RGB")).median
    return tuple(c / 255 for c in med[:3])


def room_below(block, blocks, page_h):
    """How far (px) the text box may grow downward without hitting another block."""
    x0, y0, x1, y1 = block["bbox"]
    limit = page_h
    for o in blocks:
        if o is block:
            continue
        ox0, oy0, ox1, _ = o["bbox"]
        if oy0 >= y1 - 2 and ox0 < x1 and ox1 > x0:
            limit = min(limit, oy0 - 2)
    return max(0, limit - y1)


def render_pdf(pdf, pages, dpi, poppler, font_path, out_path):
    tmp = Path(tempfile.mkdtemp())
    font_name = "hindi" + Path(font_path).suffix
    shutil.copy(font_path, tmp / font_name)
    archive = fitz.Archive(str(tmp))
    k = 72.0 / dpi  # px -> pt
    out = fitz.open()
    tight = []

    for n in sorted(pages, key=int):
        pg = pages[n]
        img = convert_from_path(
            str(pdf), dpi=dpi, first_page=int(n), last_page=int(n), poppler_path=poppler
        )[0].convert("RGB")
        page = out.new_page(width=img.width * k, height=img.height * k)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        page.insert_image(page.rect, stream=buf.getvalue())

        blocks = [b for b in pg["blocks"] if b.get("hi")]
        # 1) paint over the English text
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            pad = max(2, b["line_h"] * 0.15)
            box = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            col = background_color(img, box)
            page.draw_rect(fitz.Rect(*[v * k for v in box]), color=None, fill=col, width=0)
        # 2) write Hindi on top
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            pad = max(2, b["line_h"] * 0.15)
            grow = min(room_below(b, blocks, img.height), (y1 - y0) * 0.5)
            rect = fitz.Rect(
                (x0 - pad) * k, (y0 - pad) * k, (x1 + pad) * k, (y1 + grow + pad) * k
            )
            fs = min(max(b["line_h"] * k * 0.95, 6), 40)
            css = (
                f"@font-face {{font-family: hi; src: url({font_name});}} "
                f"p {{font-family: hi; font-size: {fs:.1f}pt; line-height: 1.3; "
                f"color: #111; margin: 0;}}"
            )
            body = f"<p>{html.escape(b['hi'])}</p>"
            _, scale = page.insert_htmlbox(rect, body, css=css, archive=archive, scale_low=0)
            if scale < 0.55:
                tight.append((n, b["en"][:40], round(scale, 2)))
        print(f"  drawn page {n}")

    out.save(str(out_path), deflate=True, garbage=3)
    shutil.rmtree(tmp, ignore_errors=True)
    if tight:
        print(f"\nNote: {len(tight)} blocks needed very small text to fit (Hindi is longer):")
        for n, t, s in tight[:8]:
            print(f"   page {n}: '{t}...' scale {s}")


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Scanned English PDF -> Hindi PDF with the same layout")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output")
    ap.add_argument("--engine", choices=["google", "nllb", "argos"], default="nllb")
    ap.add_argument("--dpi", type=int, default=200, help="render/OCR resolution (default 200)")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--font", help="Path to a Devanagari .ttf (default: Mangal on Windows)")
    ap.add_argument("--tesseract", help="Path to tesseract.exe (Windows)")
    ap.add_argument("--poppler", help="Path to poppler 'bin' folder (Windows)")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        sys.exit(f"File not found: {pdf}")
    out_path = Path(args.output) if args.output else pdf.with_name(pdf.stem + "_hindi_layout.pdf")
    progress_path = pdf.with_name(pdf.stem + "_layout_progress.json")
    if args.tesseract:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract

    font_path = find_font(args.font)
    total = pdfinfo_from_path(str(pdf), poppler_path=args.poppler)["Pages"]
    end = min(args.end or total, total)
    print(f"PDF has {total} pages. Processing {args.start}-{end}. Font: {font_path}")

    progress = {}
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("_dpi") not in (None, args.dpi):
            sys.exit(f"Progress file was made at --dpi {progress['_dpi']}; use that, or delete {progress_path.name}")
    progress["_dpi"] = args.dpi
    pages = progress.setdefault("pages", {})

    engine = None
    for n in range(args.start, end + 1):
        if str(n) in pages:
            continue
        if engine is None:
            engine = make_engine(args.engine)
        print(f"Page {n}/{end}: OCR...")
        img = convert_from_path(
            str(pdf), dpi=args.dpi, first_page=n, last_page=n, poppler_path=args.poppler
        )[0]
        blocks = extract_blocks(img, args.lang)
        print(f"Page {n}/{end}: translating {len(blocks)} text blocks...")
        try:
            for b in blocks:
                b["hi"] = engine.translate(b["en"])
        except RuntimeError as e:
            print(f"\nStopped on page {n}: {e}\nFinished pages are saved. Re-run to resume.")
            break
        pages[str(n)] = {"blocks": blocks}
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=1), encoding="utf-8")

    todo = {k: v for k, v in pages.items() if args.start <= int(k) <= end}
    if not todo:
        sys.exit("No pages were translated, nothing to draw.")
    print("Drawing Hindi PDF...")
    render_pdf(pdf, todo, args.dpi, args.poppler, font_path, out_path)
    print(f"\nDone ({len(todo)} pages).\n  Hindi PDF: {out_path}")


if __name__ == "__main__":
    main()