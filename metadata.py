"""CSV metadata for generated portraits: portrait records (metadata.csv) and batch settings (batches.csv).

Rows are appended one write at a time. A torn last line (crash mid-write) is ignored on read and
truncated before the next append. reconcile() collapses duplicates (latest record per batch +
portrait ID wins) and marks records whose image file is gone, rewriting atomically.
"""
import csv
import io
import os
import secrets
import time

METADATA_FILE = "metadata.csv"
BATCHES_FILE = "batches.csv"

PORTRAIT_FIELDS = ["batch_id", "filename", "portrait_id", "gender", "category", "art_style", "master_seed",
                   "portrait_seed", "image_format", "width", "height", "status", "error", "timestamp"]
BATCH_FIELDS = ["batch_id", "timestamp", "event", "count", "gender_setting", "category_setting", "art_style",
                "image_format", "master_seed", "width", "height", "saved", "failed", "skipped"]
STATUSES = ("success", "failed", "skipped", "missing")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_batch_id(seed):
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{seed}_{secrets.token_hex(2)}"


def read_rows(path, fields):
    """Complete, well-formed rows only. Missing file -> []. Foreign header -> ValueError."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    if text and not text.endswith("\n"):
        text = text[:text.rfind("\n") + 1]  # drop the torn last line
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != fields:
        raise ValueError(f"{os.path.basename(path)} has unexpected columns")
    return [r for r in reader if None not in r and None not in r.values()]


def append_rows(path, fields, rows):
    """Append rows in one write, creating the file/header as needed and repairing a torn tail."""
    mode, need_header = "ab", True
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as f:
            first = f.readline()
        if first.endswith(b"\n"):
            if first.decode("utf-8-sig").strip() != ",".join(fields):
                raise ValueError(f"{os.path.basename(path)} has unexpected columns")
            need_header = False
            with open(path, "rb+") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.seek(0)
                    data = f.read()
                    f.truncate(data.rfind(b"\n") + 1)
        else:
            mode = "wb"  # file only held a torn header
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fields, lineterminator="\n")
    if need_header:
        writer.writeheader()
    writer.writerows(rows)
    with open(path, mode) as f:
        f.write(buf.getvalue().encode("utf-8"))
        f.flush()


def _rewrite(path, fields, rows):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def reconcile(folder):
    """Keep the latest record per (batch, portrait) and flag successes whose file is gone."""
    path = os.path.join(folder, METADATA_FILE)
    rows = read_rows(path, PORTRAIT_FIELDS)
    latest = {}
    for r in rows:
        latest[(r["batch_id"], r["portrait_id"])] = r
    out = []
    for r in latest.values():
        if r["status"] == "success" and not os.path.isfile(os.path.join(folder, r["filename"])):
            r = dict(r, status="missing", error="file not found on disk")
        out.append(r)
    if out != rows:
        _rewrite(path, PORTRAIT_FIELDS, out)


def portrait_row(cfg, index, status, *, filename="", gender="", category="", portrait_seed="", size=("", ""),
                 error=""):
    return {"batch_id": cfg["batch_id"], "filename": filename, "portrait_id": index, "gender": gender,
            "category": category, "art_style": cfg["style"], "master_seed": cfg["seed"],
            "portrait_seed": portrait_seed, "image_format": cfg["fmt"], "width": size[0], "height": size[1],
            "status": status, "error": " ".join(str(error).split())[:200], "timestamp": now()}


def batch_row(cfg, event, saved=0, failed=0, skipped=0):
    from portrait_generator import SIZE
    return {"batch_id": cfg["batch_id"], "timestamp": now(), "event": event, "count": cfg["count"],
            "gender_setting": cfg["gender"] or "random", "category_setting": cfg["category"] or "random",
            "art_style": cfg["style"], "image_format": cfg["fmt"], "master_seed": cfg["seed"],
            "width": SIZE, "height": SIZE, "saved": saved, "failed": failed, "skipped": skipped}


class Recorder:
    """Appends records, keeping them queued (and reporting a warning) if the CSV can't be written,
    e.g. while it is open in Excel."""

    def __init__(self, folder, filename, fields):
        self.path = os.path.join(folder, filename)
        self.fields = fields
        self.pending = []
        self.warning = None

    def add(self, *rows):
        self.pending.extend(rows)
        try:
            append_rows(self.path, self.fields, self.pending)
            self.pending.clear()
            self.warning = None
        except (OSError, ValueError) as exc:
            self.warning = f"{os.path.basename(self.path)} not updated ({exc})"
