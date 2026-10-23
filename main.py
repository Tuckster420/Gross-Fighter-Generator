"""Gross Fighter Generator - stage 1: generate sample portraits and a preview sheet."""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from portrait_generator import SIZE, build_traits, derive_seed, draw_portrait, portrait_signature, save_portrait

QUALITY = 90


def make_preview(paths, preview_path, columns=6):
    pad, label_h = 10, 16
    rows = -(-len(paths) // columns)
    cell_w, cell_h = SIZE + pad, SIZE + label_h + pad
    sheet = Image.new("RGB", (pad + columns * cell_w, pad + rows * cell_h), (30, 30, 34))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, path in enumerate(paths):
        x, y = pad + (i % columns) * cell_w, pad + (i // columns) * cell_h
        with Image.open(path) as im:
            sheet.paste(im.convert("RGB"), (x, y))
        draw.text((x + 2, y + SIZE + 2), os.path.basename(path), fill=(230, 230, 230), font=font)
    sheet.save(preview_path, "JPEG", quality=QUALITY)


def verify(path):
    try:
        with Image.open(path) as im:
            im.load()
            return im.format == "JPEG" and im.size == (SIZE, SIZE)
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser(description="Gross Fighter Generator. Opens the GUI unless --cli is given.")
    ap.add_argument("--cli", action="store_true", help="run the command-line sample generator instead of the GUI")
    ap.add_argument("--seed", type=int, default=12345, help="master random seed (CLI)")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--gender", choices=["male", "female"], help="default: random per portrait")
    ap.add_argument("--out", default="output")
    ap.add_argument("--preview", default="preview.jpg")
    ap.add_argument("--overwrite", action="store_true", help="replace existing files")
    args = ap.parse_args()

    if not args.cli:
        from gui import run
        run()
        return 0

    os.makedirs(args.out, exist_ok=True)
    paths, signatures, skipped = [], set(), []
    for i in range(args.count):
        path = os.path.join(args.out, f"sample_{i}.jpg")
        traits = build_traits(derive_seed(args.seed, i), args.gender)
        signatures.add(portrait_signature(traits))
        paths.append(path)
        if os.path.exists(path) and not args.overwrite:
            skipped.append(path)
            continue
        save_portrait(draw_portrait(traits), path, QUALITY)

    if skipped:
        print(f"WARNING: {len(skipped)} existing file(s) were NOT overwritten "
              f"(use --overwrite to replace them), e.g. {skipped[0]}")

    bad = [p for p in paths if not verify(p)]
    if bad:
        print("ERROR: invalid images:", *bad, sep="\n  ")
        return 1
    print(f"Verified {len(paths)} JPEGs at {SIZE}x{SIZE}; "
          f"{len(signatures)} unique feature combinations.")

    if os.path.exists(args.preview) and not args.overwrite:
        print(f"WARNING: {args.preview} exists and was NOT overwritten (use --overwrite).")
    else:
        make_preview(paths, args.preview)
        print(f"Preview sheet written to {args.preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
