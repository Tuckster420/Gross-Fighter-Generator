import csv, os, sys, tempfile, shutil, threading, time, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SDL_VIDEODRIVER"] = "dummy"
from PIL import Image
import gui, metadata as md
from portrait_generator import derive_seed

tmp = tempfile.mkdtemp()
def rows(d): return md.read_rows(os.path.join(d, md.METADATA_FILE), md.PORTRAIT_FIELDS)
def brows(d): return md.read_rows(os.path.join(d, md.BATCHES_FILE), md.BATCH_FIELDS)
def imgs(d): return sorted(f for f in os.listdir(d) if f.endswith((".jpg", ".png")))

def run(d, count=10, seed=11, gender="female", category="asian", style="crude", fmt="jpg",
        resume=False, batch_id=None, cancel_at=None):
    cfg = dict(count=count, seed=seed, gender=gender, category=category, style=style, fmt=fmt,
               folder=d, batch_id=batch_id or md.new_batch_id(seed))
    job = gui.Job(count)
    if cancel_at:
        orig = gui._render
        def r(i, c):
            if i == cancel_at: job.cancel = True
            return orig(i, c)
        gui._render = r
    try: gui.generate_worker(job, cfg, gui._log_path(cfg), resume)
    finally:
        if cancel_at: gui._render = orig
    return job, cfg

def check_matches_disk(d):
    """every file <-> exactly one success row, dimensions/format agree, no duplicate (batch, id)"""
    rs = rows(d)
    keys = [(r["batch_id"], r["portrait_id"]) for r in rs]
    assert len(keys) == len(set(keys)), "duplicate records"
    ok = [r for r in rs if r["status"] == "success"]
    assert sorted(r["filename"] for r in ok) == imgs(d), "success rows != files on disk"
    for r in ok:
        with Image.open(os.path.join(d, r["filename"])) as im:
            assert (im.width, im.height) == (int(r["width"]), int(r["height"])) == (150, 150)
            assert im.format == ("PNG" if r["image_format"] == "png" else "JPEG")
    return rs

# ---- 1. creation: small 10-image batch
d = os.path.join(tmp, "a")
job, cfg1 = run(d)
rs = check_matches_disk(d)
assert job.ok == 10 and len(rs) == 10 and md.read_rows(os.path.join(d, md.METADATA_FILE), md.PORTRAIT_FIELDS)
r0 = rs[0]
print(r0)
assert list(r0) == md.PORTRAIT_FIELDS
assert r0["gender"] == "female" and r0["category"] == "asian" and r0["art_style"] == "crude"
assert r0["master_seed"] == "11" and r0["portrait_seed"] == str(derive_seed(11, 0)) and r0["status"] == "success"
assert r0["filename"] == "asian_female_0.jpg" and r0["portrait_id"] == "0"
b = brows(d); print(b)
assert [x["event"] for x in b] == ["started", "completed"] and b[1]["saved"] == "10"
assert b[0]["gender_setting"] == "female" and b[0]["count"] == "10" and b[0]["image_format"] == "jpg"
head = open(os.path.join(d, md.METADATA_FILE), encoding="utf-8").read().splitlines()[0]
assert head == ",".join(md.PORTRAIT_FIELDS)

# ---- 2. appending: second batch (random gender/category, PNG) keeps history
before = rows(d)
job, cfg2 = run(d, count=12, seed=22, gender=None, category=None, style="gross", fmt="png")
rs = check_matches_disk(d)
assert rs[:10] == before and len(rs) == 22
assert {r["batch_id"] for r in rs} == {cfg1["batch_id"], cfg2["batch_id"]}
assert all(r["gender"] in ("male", "female") and r["category"] in md.__dict__.get("X", ["white","black","asian","latino","mixed"]) for r in rs[10:])
for r in rs[10:]:  # filename agrees with recorded gender/category
    assert r["filename"].startswith(f"{r['category']}_{r['gender']}_"), r
assert len(brows(d)) == 4
# same-seed rerun gets a NEW batch id and next filenames, old rows untouched
job, cfg3 = run(d, count=10)
rs = check_matches_disk(d); assert len(rs) == 32 and rs[:22] == before + rs[10:22]
assert sorted(r["filename"] for r in rs if r["batch_id"] == cfg3["batch_id"])[0] == "asian_female_10.jpg"

# ---- 3. cancel + resume: no duplicates, skipped rows replaced, failures retried
d2 = os.path.join(tmp, "b")
job, cfg = run(d2, count=40, seed=5, cancel_at=15)
rs = rows(d2); c = collections.Counter(r["status"] for r in rs); print("after cancel:", c, brows(d2)[-1]["event"])
assert job.cancel and c["success"] == 16 and c["skipped"] == 24 and len(rs) == 40
assert brows(d2)[-1]["event"] == "cancelled" and brows(d2)[-1]["skipped"] == "24"
assert all(r["filename"] == "" and r["error"] == "batch cancelled" for r in rs if r["status"] == "skipped")
snap = {r["portrait_id"]: r for r in rs if r["status"] == "success"}
job, _ = run(d2, count=40, seed=5, resume=True, batch_id=cfg["batch_id"])
rs = check_matches_disk(d2)
assert len(rs) == 40 and all(r["status"] == "success" for r in rs), collections.Counter(r["status"] for r in rs)
assert all(snap[k] == r for r in rs for k in [r["portrait_id"]] if k in snap), "earlier rows changed"
assert [x["event"] for x in brows(d2)] == ["started", "cancelled", "resumed", "completed"]
# resume again when finished = nothing to do, still no duplicates
job, _ = run(d2, count=40, seed=5, resume=True, batch_id=cfg["batch_id"]); check_matches_disk(d2)

# ---- 4. failures recorded, then fixed on resume
d3 = os.path.join(tmp, "c"); real = gui._render
gui._render = lambda i, c: (_ for _ in ()).throw(RuntimeError("bad\nthing, \"quoted\"")) if i in (2, 7) else real(i, c)
job, cfg = run(d3, count=10, seed=9)
gui._render = real
rs = rows(d3); fails = [r for r in rs if r["status"] == "failed"]
assert len(fails) == 2 and all("\n" not in r["error"] and r["filename"] == "" for r in fails), fails
assert brows(d3)[-1]["event"] == "incomplete" and brows(d3)[-1]["failed"] == "2"
job, _ = run(d3, count=10, seed=9, resume=True, batch_id=cfg["batch_id"])
rs = check_matches_disk(d3); assert len(rs) == 10 and all(r["status"] == "success" for r in rs)

# ---- 5. files on disk vs metadata: deleted image -> "missing" then regenerated on resume
d4 = os.path.join(tmp, "d"); job, cfg = run(d4, count=6, seed=3)
log = gui._log_path(cfg)
open(log, "w").write("")  # simulate: batch log gone; just test reconcile
victim = rows(d4)[2]["filename"]; os.remove(os.path.join(d4, victim))
md.reconcile(d4); st = {r["portrait_id"]: r for r in rows(d4)}
assert st["2"]["status"] == "missing" and sum(r["status"] == "success" for r in st.values()) == 5
os.remove(log)

# ---- 6. interrupted write: torn last line is ignored and repaired by the next append
path = os.path.join(d, md.METADATA_FILE)
good = rows(d)
with open(path, "ab") as f: f.write(b"batch_x,asian_female_99.jpg,99,fema")   # no newline: torn
assert rows(d) == good
job, cfg4 = run(d, count=3, seed=77); rs = check_matches_disk(d)
assert len(rs) == len(good) + 3 and all(r["batch_id"] != "batch_x" for r in rs)
# torn header only
p2 = os.path.join(tmp, "hdr.csv"); open(p2, "wb").write(b"batch_id,file")
md.append_rows(p2, md.PORTRAIT_FIELDS, [md.portrait_row(cfg4, 1, "skipped")]); assert len(md.read_rows(p2, md.PORTRAIT_FIELDS)) == 1
# crash between log write and csv write: repaired from log on resume
d5 = os.path.join(tmp, "e"); job, cfg = run(d5, count=8, seed=4, cancel_at=5)
full = rows(d5)
keep = [r for r in full if r["status"] == "success"][:-2]   # drop last two success rows + skipped rows
os.remove(os.path.join(d5, md.METADATA_FILE)); md.append_rows(os.path.join(d5, md.METADATA_FILE), md.PORTRAIT_FIELDS, keep)
job, _ = run(d5, count=8, seed=4, resume=True, batch_id=cfg["batch_id"])
rs = check_matches_disk(d5); assert len(rs) == 8 and all(r["status"] == "success" for r in rs)
print("repair-from-log ok")

# ---- 7. CSV locked (e.g. open in Excel): batch still finishes, warning reported, rows kept in queue
d6 = os.path.join(tmp, "f"); os.makedirs(d6)
real_append = md.append_rows
calls = {"n": 0}
def locked(path, fields, rows_):
    if path.endswith(md.METADATA_FILE) and calls["n"] < 6:
        calls["n"] += 1; raise PermissionError("locked")
    return real_append(path, fields, rows_)
md.append_rows = locked
job, cfg = run(d6, count=8, seed=6)
md.append_rows = real_append
assert job.ok == 8 and len(imgs(d6)) == 8
check_matches_disk(d6); print("locked csv: queued rows flushed later, warning =", job.meta_warning)
# foreign CSV is not clobbered
d7 = os.path.join(tmp, "g"); os.makedirs(d7); open(os.path.join(d7, md.METADATA_FILE), "w").write("a,b\n1,2\n")
job, _ = run(d7, count=3, seed=1)
assert job.ok == 3 and job.meta_warning and open(os.path.join(d7, md.METADATA_FILE)).read() == "a,b\n1,2\n"
print("foreign csv preserved:", job.meta_warning)

# ---- 8. opens in csv module cleanly
with open(os.path.join(d, md.METADATA_FILE), newline="", encoding="utf-8") as f:
    assert len(list(csv.DictReader(f))) == len(rows(d))
shutil.rmtree(tmp); print("ALL METADATA TESTS PASSED")
