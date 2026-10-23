"""Drives the real menu through every option combination and checks files + metadata.

Also checks that main.py starts the GUI and keeps running. Run: python tests\\test_matrix.py
"""
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
from PIL import Image

import gui
import metadata as md

# ---- the menu launches and stays up
proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")], cwd=tempfile.gettempdir(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
time.sleep(4)
assert proc.poll() is None, "main.py exited early: " + proc.stderr.read().decode(errors="replace")[-500:]
proc.kill()
proc.wait()
print("main menu launches ok")

assert gui.DEFAULT_OUTPUT == os.path.join(ROOT, "output")
app = gui.App()
assert (app.count_text, app.fmt, app.gender, app.category) == ("100", "jpg", None, None)
assert app.folder_text == gui.DEFAULT_OUTPUT

labels = []
orig_button, orig_frame = app.button, app.frame


def spy(rect, label, *a, **k):
    labels.append((pygame.Rect(rect), label))
    return orig_button(rect, label, *a, **k)


def frame():
    labels.clear()
    orig_frame()


app.button, app.frame = spy, frame


def tick(n=3):
    for _ in range(n):
        for e in pygame.event.get():
            app.handle_event(e)
        app.poll_job()
        app.frame()


def press(label, nth=0):
    hits = [r for r, l in labels if l.startswith(label)]
    assert len(hits) > nth, f"no button {label!r}"
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=hits[nth].center))
    tick(1)


def wait(limit=120):
    t0 = time.time()
    while app.busy() and time.time() - t0 < limit:
        tick(1)
        time.sleep(0.005)
    tick(2)
    assert not app.busy(), "job did not finish"


GENDERS = [("Male", "male"), ("Female", "female"), ("Random", None)]
CATS = [("White", "white"), ("Black", "black"), ("Asian", "asian"), ("Latino", "latino"),
        ("Mixed", "mixed"), ("Random", None)]
STYLES = [("Gross and Goofy", "gross"), ("Crude Game Art", "crude"), ("Exaggerated Cartoon", "cartoon")]
FORMATS = [("JPG", "jpg"), ("PNG", "png")]
N = 4

tmp = tempfile.mkdtemp()
tick(2)
combos = list(itertools.product(GENDERS, CATS, STYLES, FORMATS))
for i, ((gl, g), (cl, c), (sl, s), (fl, f)) in enumerate(combos):
    press(gl, 0)                       # first "Random" button is the gender row
    press(cl, 1 if cl == "Random" else 0)  # second "Random" button is the category row
    press(sl)
    press(fl)
    assert (app.gender, app.category, app.style, app.fmt) == (g, c, s, f), (app.gender, app.category, app.style, app.fmt)
    d = os.path.join(tmp, f"c{i}")
    app.count_text, app.folder_text, app.seed_text = str(N), d, str(1000 + i)
    press("Generate")
    wait()
    assert app.status.startswith(f"Done: {N} {f.upper()}"), (i, app.status)

    files = sorted(x for x in os.listdir(d) if x.endswith(("." + f)))
    assert len(files) == N and len(set(files)) == N
    assert sorted(x for x in os.listdir(d) if not x.startswith(".")) == sorted(files + [md.METADATA_FILE, md.BATCHES_FILE])
    for name in files:
        m = re.fullmatch(rf"({c or '[a-z]+'})_({g or 'male|female'})_(\d+)\.{f}", name)
        assert m, (name, c, g)
        with Image.open(os.path.join(d, name)) as im:
            im.load()
            assert im.size == (150, 150) and im.format == ("PNG" if f == "png" else "JPEG"), name
    rows = md.read_rows(os.path.join(d, md.METADATA_FILE), md.PORTRAIT_FIELDS)
    assert sorted(r["filename"] for r in rows if r["status"] == "success") == files
    for r in rows:
        assert (r["art_style"], r["image_format"], r["width"], r["height"]) == (s, f, "150", "150"), r
        assert r["gender"] == (g or r["gender"]) and r["category"] == (c or r["category"])
    shutil.rmtree(d)
print(f"option matrix ok: {len(combos)} combinations x {N} portraits")
shutil.rmtree(tmp, ignore_errors=True)
print("ALL MATRIX TESTS PASSED")
