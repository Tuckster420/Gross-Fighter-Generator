import os, re, sys, time, shutil, tempfile, collections
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame
from PIL import Image
import gui

app = gui.App()
tmp = tempfile.mkdtemp()
labels = []
orig_button, _frame = app.button, app.frame
def spy(rect, label, *a, **k):
    labels.append((pygame.Rect(rect), label)); return orig_button(rect, label, *a, **k)
app.button = spy
def frame():
    labels.clear(); _frame()
app.frame = frame

def tick(n=3):
    for _ in range(n):
        for e in pygame.event.get(): app.handle_event(e)
        app.poll_job(); app.frame()
def click(pos):
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)); tick(1)
def press(label):
    for rect, lbl in labels:
        if lbl.startswith(label):
            click(rect.center); return
    raise AssertionError("no button " + label + str([l for _, l in labels]))
def wait(limit=300):
    t = time.time()
    while app.busy() and time.time() - t < limit: tick(1); time.sleep(0.01)
    tick(2)
def type_into(pos, text):
    click(pos)
    for _ in range(300):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0, unicode="", scancode=0))
    tick(1)
    pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text=text)); tick(1)
COUNT, SEED, FOLDER = (90, 140), (430, 140), (200, 535)

def check_files(d, n, ext, *, group_ok=None):
    files = [f for f in os.listdir(d) if not f.startswith(".") and not f.endswith(".csv")]
    assert len(files) == n, (len(files), n)
    groups = collections.defaultdict(list)
    for f in files:
        m = re.fullmatch(rf"(white|black|asian|latino|mixed)_(male|female)_(\d+)\.{ext}", f)
        assert m, f
        groups[m[1] + "_" + m[2]].append(int(m[3]))
        with Image.open(os.path.join(d, f)) as im:
            im.load(); assert im.size == (150, 150) and im.format == ("PNG" if ext == "png" else "JPEG"), f
    for g, nums in groups.items():
        assert sorted(nums) == list(range(len(nums))), (g, sorted(nums))  # zero-based, gap-free
    return groups

# ---------- 100-image batch, defaults except count/seed/folder
d = os.path.join(tmp, "b100"); tick(2)
type_into(COUNT, "100"); type_into(SEED, "777"); type_into(FOLDER, d)
assert app.fmt == "jpg"
press("Generate"); wait()
print(app.status); assert app.status.startswith("Done: 100 JPG")
g = check_files(d, 100, "jpg"); print("100-batch groups:", {k: len(v) for k, v in sorted(g.items())})
assert not [f for f in os.listdir(d) if f.startswith(".gfg_batch")]  # log cleaned up on success

# ---------- selected settings used: black female cartoon PNG, 40
d2 = os.path.join(tmp, "bf"); 
press("Black"); press("Female"); press("Exaggerated"); press("PNG")
type_into(COUNT, "40"); type_into(FOLDER, d2)
press("Generate"); wait(); assert app.status.startswith("Done: 40 PNG"), app.status
g = check_files(d2, 40, "png"); assert list(g) == ["black_female"], g

# ---------- never overwrite: run again into same folder (new random seed) -> next numbers
snap = {f: open(os.path.join(d2, f), "rb").read() for f in os.listdir(d2) if not f.endswith(".csv")}
press("Generate"); wait(); assert app.status.startswith("Done")
g = check_files(d2, 80, "png"); assert list(g) == ["black_female"]
assert all(open(os.path.join(d2, f), "rb").read() == b for f, b in snap.items()), "overwrote!"
print("no-overwrite ok")
# pre-existing gap-free collision with explicit seed: file black_female_85 etc still fine

# ---------- cancel + resume (JPG, mixed random gender, 300), slowed so cancel lands mid-run
press("JPG"); press("Random"); 
# category row has its own Random; set gender random explicitly
for rect, lbl in labels: pass
app.gender, app.category, app.style = None, None, "gross"
d3 = os.path.join(tmp, "resume")
type_into(COUNT, "300"); type_into(SEED, "2024"); type_into(FOLDER, d3)
press("Generate")
t = time.time()
while app.job and app.job.done < 60 and time.time() - t < 60: tick(1); time.sleep(0.01)
press("Cancel"); wait()
part = len([f for f in os.listdir(d3) if not f.startswith(".") and not f.endswith(".csv")])
print("cancelled:", app.status); assert app.status.startswith("Cancelled") and 60 <= part < 300
assert any(f.startswith(".gfg_batch") for f in os.listdir(d3))
files_before = {f: open(os.path.join(d3, f), "rb").read() for f in os.listdir(d3) if not f.startswith(".") and not f.endswith(".csv")}
press("Generate"); tick(2)
assert app.mode == "confirm"
# Cancel in dialog leaves things alone
press("Cancel"); assert app.mode == "menu" and not app.busy()
press("Generate"); tick(2); press("Resume"); wait()
print("resumed:", app.status); assert app.status.startswith("Done: 300")
g = check_files(d3, 300, "jpg")
for f, b in files_before.items(): assert open(os.path.join(d3, f), "rb").read() == b  # untouched
# resumed batch == uninterrupted batch with the same seed
d4 = os.path.join(tmp, "ref"); type_into(FOLDER, d4); press("Generate"); wait()
ref = {f: open(os.path.join(d4, f), "rb").read() for f in os.listdir(d4) if not f.startswith(".") and not f.endswith(".csv")}
res = {f: open(os.path.join(d3, f), "rb").read() for f in os.listdir(d3) if not f.startswith(".") and not f.endswith(".csv")}
assert ref == res, "resumed output differs from uninterrupted run"
print("resume identical to uninterrupted run")

# ---------- individual failures
d5 = os.path.join(tmp, "fail")
real = gui._render
def flaky(i, cfg):
    if i % 10 == 3: raise RuntimeError("boom")
    return real(i, cfg)
gui._render = flaky
type_into(COUNT, "50"); type_into(SEED, "5"); type_into(FOLDER, d5)
press("Generate"); wait(); print(app.status)
assert app.status.startswith("Finished with errors: 45 of 50 saved, 5 failed")
check_files(d5, 45, "jpg")
pass
gui._render = real
press("Generate"); tick(2); press("Resume"); wait()   # retries only failed ones
assert app.status.startswith("Done: 50"), app.status
check_files(d5, 50, "jpg"); print("failed ones retried on resume")

# ---------- abort on consecutive failures
gui._render = lambda i, cfg: (_ for _ in ()).throw(OSError("disk full"))
d6 = os.path.join(tmp, "dead"); type_into(COUNT, "100"); type_into(FOLDER, d6)
press("Generate"); wait(); print(app.status); assert app.status.startswith("Stopped") and app.job is None
gui._render = real

# ---------- invalid output paths
open(os.path.join(tmp, "afile"), "w").close()
for bad in (os.path.join(tmp, "afile", "sub"), "Z:\\no\\such\\drive\\x"):
    type_into(FOLDER, bad); press("Generate"); tick(2)
    assert not app.busy(), bad; print("bad path:", app.status)
    assert app.status.startswith(("Fix", "Cannot")), app.status

# ---------- 1500 batch
d7 = os.path.join(tmp, "b1500"); type_into(COUNT, "1500"); type_into(SEED, "99"); type_into(FOLDER, d7)
press("Generate"); t0 = time.time()
mid = False
while app.busy():
    tick(1); time.sleep(0.02)
    if not mid and app.job and app.job.done > 300:
        mid = True
tick(2); print("1500 in %.0fs:" % (time.time() - t0), app.status)
assert app.status.startswith("Done: 1500"); g = check_files(d7, 1500, "jpg"); print({k: len(v) for k, v in sorted(g.items())})

shutil.rmtree(tmp); print("ALL BULK TESTS PASSED")
