"""Pygame front end for the Gross Fighter Generator."""
import json
import os
import random
import re
import threading

import pygame
from PIL import Image

from metadata import (BATCH_FIELDS, BATCHES_FILE, METADATA_FILE, PORTRAIT_FIELDS, Recorder, batch_row,
                      new_batch_id, portrait_row, read_rows, reconcile)
from portrait_generator import (CATEGORIES, SIZE, STYLES, build_traits, derive_seed, draw_portrait,
                                save_portrait)

WIDTH, HEIGHT = 980, 690
MAX_COUNT = 10000
JPEG_QUALITY = 90
PREVIEW_COUNT = 12
DEFAULT_COUNT = 100
DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

GENDER_OPTS = [("Male", "male"), ("Female", "female"), ("Random", None)]
CATEGORY_OPTS = [(c.capitalize(), c) for c in CATEGORIES] + [("Random", None)]
STYLE_OPTS = [(label, key) for key, label in STYLES.items()]
FORMAT_OPTS = [("JPG", "jpg"), ("PNG", "png")]

BG = (28, 30, 38)
PANEL = (40, 43, 54)
FIELD = (22, 24, 30)
TEXT = (230, 232, 240)
DIM = (150, 155, 170)
ACCENT = (86, 140, 235)
BTN = (62, 66, 82)
BTN_HOVER = (80, 85, 105)
GOOD = (110, 200, 130)
BAD = (240, 100, 100)


class Job:
    """Shared state between the UI thread and a worker thread."""

    def __init__(self, total):
        self.total = total
        self.done = 0
        self.cancel = False
        self.finished = False
        self.error = None
        self.ok = 0  # portraits saved (including ones completed in an earlier run)
        self.failed = 0
        self.skipped = 0
        self.meta_warning = None
        self.last_error = None
        self.items = []  # preview images


def validate(count_text, folder_text, seed_text):
    """Return (settings, errors). errors maps field name -> message."""
    errors, settings = {}, {}
    count_text = count_text.strip()
    if not count_text.isdigit():
        errors["count"] = "Enter a whole number"
    elif not 1 <= int(count_text) <= MAX_COUNT:
        errors["count"] = f"Must be between 1 and {MAX_COUNT}"
    else:
        settings["count"] = int(count_text)

    seed_text = seed_text.strip()
    if not seed_text:
        settings["seed"] = None
    elif not seed_text.isdigit() or int(seed_text) >= 2 ** 63:
        errors["seed"] = "Seed must be a whole number"
    else:
        settings["seed"] = int(seed_text)

    folder = folder_text.strip().strip('"')
    if not folder:
        errors["folder"] = "Choose an output folder"
    else:
        folder = os.path.abspath(folder)
        if any(ch in os.path.splitdrive(folder)[1] for ch in '<>"|?*'):
            errors["folder"] = "Folder name has invalid characters"
        elif os.path.exists(folder) and not os.path.isdir(folder):
            errors["folder"] = "That path is a file, not a folder"
        else:
            probe = folder
            while not os.path.exists(probe) and os.path.dirname(probe) != probe:
                probe = os.path.dirname(probe)
            if not os.path.isdir(probe) or not os.access(probe, os.W_OK):
                errors["folder"] = "Folder is not writable"
            else:
                settings["folder"] = folder
    return settings, errors


MAX_FAIL_STREAK = 25  # abort the batch if this many images in a row fail (e.g. disk full)


def group_name(traits):
    return f"{traits['category']}_{traits['gender']}"


def output_pattern(fmt):
    return f"<category>_<gender>_N.{fmt}"


def _log_path(cfg):
    key = "_".join(str(cfg[k] if cfg[k] is not None else "random")
                   for k in ("count", "gender", "category", "style", "fmt"))
    return os.path.join(cfg["folder"], f".gfg_batch_{cfg['seed']}_{key}.jsonl")


def load_log(path):
    """Return (header, {index: filename}) for a batch log; completed entries whose file is gone are dropped."""
    header, done = None, {}
    folder = os.path.dirname(path)
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # torn last line after a crash
                if n == 0:
                    header = rec
                elif isinstance(rec, dict) and "i" in rec and os.path.isfile(os.path.join(folder, rec["f"])):
                    done[rec["i"]] = rec["f"]
    except OSError:
        return None, {}
    return header, done


def find_resumable(cfg):
    """Look for an unfinished batch with the same settings. Returns (seed, log_path, done_count) or None."""
    try:
        names = os.listdir(cfg["folder"])
    except OSError:
        return None
    key = "_".join(str(cfg[k] if cfg[k] is not None else "random")
                   for k in ("count", "gender", "category", "style", "fmt"))
    seed = r"\d+" if cfg["seed"] is None else str(cfg["seed"])
    pat = re.compile(rf"^\.gfg_batch_({seed})_{re.escape(key)}\.jsonl$")
    best = None
    for name in names:
        if pat.match(name):
            path = os.path.join(cfg["folder"], name)
            header, done = load_log(path)
            if header and len(done) < cfg["count"]:
                if best is None or os.path.getmtime(path) > best[0]:
                    best = (os.path.getmtime(path), header["seed"], path, len(done),
                            header.get("batch_id") or f"legacy_{header['seed']}")
    return best[1:] if best else None


def _success_row(cfg, i, traits, name, size):
    return portrait_row(cfg, i, "success", filename=name, gender=traits["gender"], category=traits["category"],
                        portrait_seed=derive_seed(cfg["seed"], i), size=size)


def _repair_from_log(cfg, done, recorder):
    """Add records for images the resume log lists but metadata.csv lacks (crash between the two writes)."""
    known = {(r["batch_id"], r["portrait_id"]) for r in read_rows(recorder.path, PORTRAIT_FIELDS)
             if r["status"] == "success"}
    rows = []
    for i, name in sorted(done.items()):
        if (cfg["batch_id"], str(i)) in known:
            continue
        with Image.open(os.path.join(cfg["folder"], name)) as im:
            size = im.size
        traits = build_traits(derive_seed(cfg["seed"], i), cfg["gender"], cfg["category"], cfg["style"])
        rows.append(_success_row(cfg, i, traits, name, size))
    if rows:
        recorder.add(*rows)


def generate_worker(job, cfg, log_path, resume):
    log = None
    complete = False
    recorder = batches = None
    event = "aborted"
    try:
        os.makedirs(cfg["folder"], exist_ok=True)
        recorder = Recorder(cfg["folder"], METADATA_FILE, PORTRAIT_FIELDS)
        batches = Recorder(cfg["folder"], BATCHES_FILE, BATCH_FIELDS)
        done = load_log(log_path)[1] if resume else {}
        log = open(log_path, "a" if resume else "w", encoding="utf-8")
        if not resume or log.tell() == 0:
            log.write(json.dumps({"seed": cfg["seed"], "count": cfg["count"], "batch_id": cfg["batch_id"]}) + "\n")
            log.flush()
        try:
            reconcile(cfg["folder"])
            _repair_from_log(cfg, done, recorder)
            if resume:  # the CSV is also a record of completed work (covers a lost or finished log)
                for r in read_rows(recorder.path, PORTRAIT_FIELDS):
                    if (r["batch_id"] == cfg["batch_id"] and r["status"] == "success"
                            and int(r["portrait_id"]) < cfg["count"]):
                        done.setdefault(int(r["portrait_id"]), r["filename"])
        except (OSError, ValueError) as exc:
            recorder.warning = f"metadata.csv not updated ({exc})"
        batches.add(batch_row(cfg, "resumed" if resume else "started", saved=len(done)))
        handled = set(done)  # portrait IDs with a final outcome so far
        next_free = {}  # per filename group: where to start looking for an unused number
        streak = 0
        for i in range(cfg["count"]):
            if job.cancel:
                break
            if i in done:
                job.ok += 1
                job.done += 1
                continue
            handled.add(i)
            try:
                img, traits = _render(i, cfg)
                group = group_name(traits)
                n = next_free.get(group, 0)
                while True:  # never overwrite: take the next unused number
                    name = f"{group}_{n}.{cfg['fmt']}"
                    path = os.path.join(cfg["folder"], name)
                    try:
                        save_portrait(img, path, JPEG_QUALITY, exclusive=True)
                        break
                    except FileExistsError:
                        n += 1
                next_free[group] = n + 1
                try:
                    with Image.open(path) as im:
                        im.load()
                        expected = "PNG" if cfg["fmt"] == "png" else "JPEG"
                        if im.size != (SIZE, SIZE) or im.format != expected:
                            raise ValueError("saved image failed verification")
                except Exception:
                    os.remove(path)
                    raise
                try:
                    log.write(json.dumps({"i": i, "f": name}) + "\n")
                    log.flush()
                except OSError:
                    pass  # worst case on resume: this portrait is regenerated under a new name
                recorder.add(_success_row(cfg, i, traits, name, (SIZE, SIZE)))
                job.ok += 1
                streak = 0
            except Exception as exc:
                job.failed += 1
                job.last_error = f"#{i}: {type(exc).__name__}: {exc}"
                recorder.add(portrait_row(cfg, i, "failed", gender=cfg["gender"] or "",
                                          category=cfg["category"] or "",
                                          portrait_seed=derive_seed(cfg["seed"], i),
                                          error=f"{type(exc).__name__}: {exc}"))
                streak += 1
                if streak >= MAX_FAIL_STREAK:
                    job.error = f"Stopped after {streak} consecutive failures. Last: {job.last_error}"
                    break
            job.done += 1
        complete = not job.cancel and not job.error and job.ok == cfg["count"]
        skipped = [i for i in range(cfg["count"]) if i not in handled]
        if skipped:
            job.skipped = len(skipped)
            recorder.add(*[portrait_row(cfg, i, "skipped", gender=cfg["gender"] or "",
                                        category=cfg["category"] or "",
                                        portrait_seed=derive_seed(cfg["seed"], i),
                                        error="batch cancelled" if job.cancel else "batch stopped")
                           for i in skipped])
        event = ("completed" if complete else "cancelled" if job.cancel else "aborted" if job.error
                 else "incomplete")
    except Exception as exc:  # shown in the UI instead of crashing
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        if log:
            log.close()
            if complete:
                try:
                    os.remove(log_path)
                except OSError:
                    pass
        if batches:
            batches.add(batch_row(cfg, event, job.ok, job.failed, job.skipped))
            try:
                reconcile(cfg["folder"])
            except (OSError, ValueError) as exc:
                recorder.warning = f"metadata.csv not tidied ({exc})"
            job.meta_warning = recorder.warning or batches.warning
        job.finished = True


def preview_worker(job, cfg, start):
    try:
        for i in range(start, start + job.total):
            job.items.append(_make(i, cfg))
            job.done += 1
    except Exception as exc:
        job.error = f"{type(exc).__name__}: {exc}"
    job.finished = True


def _render(index, cfg):
    traits = build_traits(derive_seed(cfg["seed"], index), cfg["gender"], cfg["category"], cfg["style"])
    return draw_portrait(traits), traits


def _make(index, cfg):
    img, traits = _render(index, cfg)
    return img, f"#{index} {traits['gender'][0].upper()} {traits['category']}"


def pick_folder(initial):
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=initial if os.path.isdir(initial) else None,
                                         title="Select output folder", mustexist=False)
        root.destroy()
        return chosen or None
    except Exception:
        return None


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Gross Fighter Generator")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        name = "segoeui,arial,helvetica"
        self.f_title = pygame.font.SysFont(name, 32, bold=True)
        self.f_label = pygame.font.SysFont(name, 18, bold=True)
        self.f_body = pygame.font.SysFont(name, 17)
        self.f_small = pygame.font.SysFont(name, 14)
        try:
            pygame.scrap.init()
        except Exception:
            pass

        self.count_text = str(DEFAULT_COUNT)
        self.seed_text = ""
        self.folder_text = DEFAULT_OUTPUT
        self.gender = None
        self.category = None
        self.style = "gross"
        self.fmt = "jpg"

        self.focus = None
        self.hits = []
        self.status = "Ready."
        self.status_color = DIM
        self.job = None
        self.job_kind = None
        self.job_cfg = None
        self.mode = "menu"  # menu | preview | confirm
        self.confirm = None
        self.job_thread = None
        self.preview_cfg = None
        self.preview_start = 0
        self.preview_surfaces = []
        self.running = True

    # ------------------------------------------------------------ helpers
    def busy(self):
        return self.job is not None and not self.job.finished

    def set_status(self, msg, color=DIM):
        self.status, self.status_color = msg, color

    def current_settings(self):
        settings, errors = validate(self.count_text, self.folder_text, self.seed_text)
        settings.update(gender=self.gender, category=self.category, style=self.style, fmt=self.fmt)
        return settings, errors

    def text(self, s, font, color, pos, center=False, right=False):
        surf = font.render(s, True, color)
        rect = surf.get_rect()
        if center:
            rect.center = pos
        elif right:
            rect.topright = pos
        else:
            rect.topleft = pos
        self.screen.blit(surf, rect)
        return rect

    def fit(self, s, font, width):
        if font.size(s)[0] <= width:
            return s
        while s and font.size("..." + s)[0] > width:
            s = s[1:]
        return "..." + s

    def button(self, rect, label, callback, enabled=True, selected=False, accent=False):
        rect = pygame.Rect(rect)
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        if not enabled:
            color = (46, 48, 58)
        elif selected or accent:
            color = ACCENT if not hover else (110, 160, 245)
        else:
            color = BTN_HOVER if hover else BTN
        pygame.draw.rect(self.screen, color, rect, border_radius=6)
        self.text(label, self.f_body, TEXT if enabled else (100, 104, 116), rect.center, center=True)
        if enabled:
            self.hits.append((rect, callback))

    def field(self, rect, value, name, error=None, placeholder=""):
        rect = pygame.Rect(rect)
        border = BAD if error else (ACCENT if self.focus == name else (70, 74, 90))
        pygame.draw.rect(self.screen, FIELD, rect, border_radius=5)
        pygame.draw.rect(self.screen, border, rect, 2, border_radius=5)
        shown = value if value or self.focus == name else placeholder
        color = TEXT if value else DIM
        caret = "|" if self.focus == name and (pygame.time.get_ticks() // 500) % 2 == 0 else ""
        self.text(self.fit(shown, self.f_body, rect.width - 20) + caret, self.f_body, color,
                  (rect.x + 10, rect.y + (rect.height - 22) // 2))
        self.hits.append((rect, lambda: setattr(self, "focus", name)))

    def options(self, y, opts, attr, x=30, width=560):
        n = len(opts)
        gap = 8
        w = (width - gap * (n - 1)) // n
        for i, (label, value) in enumerate(opts):
            self.button((x + i * (w + gap), y, w, 38), label,
                        lambda v=value: setattr(self, attr, v),
                        enabled=not self.busy(), selected=getattr(self, attr) == value)

    # ------------------------------------------------------------ actions
    def step_count(self, delta):
        value = int(self.count_text) if self.count_text.strip().isdigit() else DEFAULT_COUNT
        self.count_text = str(max(1, min(MAX_COUNT, value + delta)))

    def browse(self):
        chosen = pick_folder(self.folder_text)
        if chosen:
            self.folder_text = os.path.abspath(chosen)

    def start_generate(self):
        cfg, errors = self.current_settings()
        if errors:
            self.set_status("Fix the highlighted settings first.", BAD)
            return
        try:
            os.makedirs(cfg["folder"], exist_ok=True)
            probe = os.path.join(cfg["folder"], ".gfg_write_test")
            with open(probe, "w"):
                pass
            os.remove(probe)
        except OSError as exc:
            self.set_status(f"Cannot use output folder: {exc.strerror or exc}", BAD)
            return
        found = find_resumable(cfg)
        if found:
            seed, log_path, n_done, batch_id = found
            resumed = dict(cfg, seed=seed, batch_id=batch_id)
            fresh = dict(cfg, seed=cfg["seed"] if cfg["seed"] is not None else random.getrandbits(32))
            self.confirm = (
                "Unfinished batch found",
                [f"{n_done} of {cfg['count']} portraits from this batch (seed {seed}) are already saved.",
                 "Resume continues where it stopped. A new batch never overwrites files."],
                [(f"Resume ({cfg['count'] - n_done} left)", lambda: self.launch_generate(resumed, True)),
                 ("Start new batch", lambda: self.launch_generate(fresh, False)),
                 ("Cancel", None)])
            self.mode = "confirm"
        else:
            if cfg["seed"] is None:
                cfg["seed"] = random.getrandbits(32)
            self.launch_generate(cfg, False)

    def launch_generate(self, cfg, resume):
        self.mode = "menu"
        if not resume:
            cfg = dict(cfg, batch_id=new_batch_id(cfg["seed"]))
        self.job = Job(cfg["count"])
        self.job_kind, self.job_cfg = "generate", cfg
        self.job_thread = threading.Thread(target=generate_worker,
                                           args=(self.job, cfg, _log_path(cfg), resume), daemon=True)
        self.job_thread.start()
        self.set_status("Generating...", TEXT)

    def cancel_job(self):
        if self.busy():
            self.job.cancel = True
            self.set_status("Cancelling...", DIM)

    def start_preview(self):
        cfg, errors = self.current_settings()
        if errors:
            self.set_status("Fix the highlighted settings first.", BAD)
            return
        if cfg["seed"] is None:
            cfg["seed"] = random.getrandbits(32)
        self.preview_cfg = cfg
        self.preview_start = 0
        self.load_preview()

    def load_preview(self):
        cfg = self.preview_cfg
        n = min(PREVIEW_COUNT, cfg["count"] - self.preview_start)
        if n <= 0:
            self.preview_start = 0
            n = min(PREVIEW_COUNT, cfg["count"])
        self.job = Job(n)
        self.job_kind = "preview"
        threading.Thread(target=preview_worker, args=(self.job, cfg, self.preview_start), daemon=True).start()
        self.set_status("Building preview...", TEXT)

    def poll_job(self):
        job = self.job
        if not job or not job.finished:
            return
        self.job = None
        if self.job_kind == "generate":
            cfg = self.job_cfg
            summary = f"{job.ok} of {job.total} saved, {job.failed} failed"
            if job.skipped:
                summary += f", {job.skipped} skipped"
            warn = f"  WARNING: {job.meta_warning}" if job.meta_warning else ""
            if job.error:
                self.set_status(f"Stopped: {job.error}  ({summary}){warn}", BAD)
            elif job.cancel:
                self.set_status(f"Cancelled: {summary}. Click Generate to resume (seed {cfg['seed']}).{warn}", BAD)
            elif job.failed or job.ok < job.total:
                self.set_status(f"Finished with errors: {summary}. Click Generate to retry. "
                                f"Last error {job.last_error}{warn}", BAD)
            else:
                self.set_status(f"Done: {job.ok} {cfg['fmt'].upper()} portraits ({SIZE}x{SIZE}) saved in "
                                f"{cfg['folder']}  (seed {cfg['seed']}).{warn}", BAD if warn else GOOD)
            return
        if job.error:
            self.set_status("Error: " + job.error, BAD)
            return
        self.preview_surfaces = [(pygame.image.frombytes(img.tobytes(), img.size, "RGB"), label)
                                 for img, label in job.items]
        self.mode = "preview"
        self.set_status("Preview only - nothing was saved.", DIM)

    # ------------------------------------------------------------ events
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.mode == "menu":
                self.focus = None
            for rect, cb in reversed(self.hits):
                if rect.collidepoint(e.pos):
                    cb()
                    break
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                if self.mode in ("preview", "confirm"):
                    self.mode = "menu"
            elif self.mode == "menu" and self.focus:
                self.edit_field(e)
        elif e.type == pygame.TEXTINPUT and self.mode == "menu" and self.focus and not self.busy():
            self.type_text(e.text)

    def type_text(self, s):
        if self.focus == "folder":
            self.folder_text = (self.folder_text + s)[:260]
        elif self.focus in ("count", "seed"):
            digits = "".join(ch for ch in s if ch.isdigit())
            attr = self.focus + "_text"
            setattr(self, attr, (getattr(self, attr) + digits)[:19 if self.focus == "seed" else 6])

    def edit_field(self, e):
        if self.busy():
            return
        attr = self.focus + "_text"
        if e.key == pygame.K_BACKSPACE:
            setattr(self, attr, getattr(self, attr)[:-1])
        elif e.key == pygame.K_TAB:
            order = ["count", "seed", "folder"]
            self.focus = order[(order.index(self.focus) + 1) % 3]
        elif e.key == pygame.K_RETURN:
            self.focus = None
        elif e.key == pygame.K_v and e.mod & pygame.KMOD_CTRL:
            try:
                raw = pygame.scrap.get(pygame.SCRAP_TEXT)
                if raw:
                    self.type_text(raw.decode("utf-8", "ignore").strip("\x00\r\n"))
            except Exception:
                pass

    # ------------------------------------------------------------ drawing
    def draw_menu(self):
        idle = not self.busy()
        cfg, errors = self.current_settings()
        self.text("Gross Fighter Generator", self.f_title, TEXT, (30, 18))
        self.text("Procedural 150 x 150 fighter portraits", self.f_body, DIM, (32, 56))

        y = 92
        self.text("Number of portraits", self.f_label, TEXT, (30, y))
        self.field((30, y + 26, 130, 38), self.count_text, "count", errors.get("count"))
        self.button((168, y + 26, 38, 38), "-", lambda: self.step_count(-10), idle)
        self.button((212, y + 26, 38, 38), "+", lambda: self.step_count(10), idle)
        self.text("Seed (optional)", self.f_label, TEXT, (330, y))
        self.field((330, y + 26, 200, 38), self.seed_text, "seed", errors.get("seed"), "random")
        for key, x in (("count", 30), ("seed", 330)):
            if key in errors:
                self.text(errors[key], self.f_small, BAD, (x, y + 66))

        y += 100
        self.text("Gender", self.f_label, TEXT, (30, y))
        self.options(y + 26, GENDER_OPTS, "gender")
        y += 76
        self.text("Appearance category", self.f_label, TEXT, (30, y))
        self.options(y + 26, CATEGORY_OPTS, "category")
        y += 76
        self.text("Art style", self.f_label, TEXT, (30, y))
        self.options(y + 26, STYLE_OPTS, "style")
        y += 76
        self.text("Image format", self.f_label, TEXT, (30, y))
        self.options(y + 26, FORMAT_OPTS, "fmt", width=200)
        y += 76
        self.text("Output folder", self.f_label, TEXT, (30, y))
        self.field((30, y + 26, 450, 38), self.folder_text, "folder", errors.get("folder"))
        self.button((490, y + 26, 100, 38), "Browse...", self.browse, idle)
        if "folder" in errors:
            self.text(errors["folder"], self.f_small, BAD, (30, y + 66))

        self.draw_summary(cfg, errors)

        by = 598
        if self.busy() and self.job_kind == "generate":
            self.button((30, by, 170, 46), "Cancel", self.cancel_job, accent=True)
        else:
            self.button((30, by, 170, 46), "Generate", self.start_generate, idle, accent=True)
        self.button((214, by, 170, 46), "Preview", self.start_preview, idle)
        self.button((398, by, 170, 46), "Exit", lambda: setattr(self, "running", False), idle)

        self.draw_status()

    def draw_summary(self, cfg, errors):
        panel = pygame.Rect(640, 92, 310, 484)
        pygame.draw.rect(self.screen, PANEL, panel, border_radius=8)
        self.text("Selected options", self.f_label, TEXT, (panel.x + 18, panel.y + 14))
        label = lambda opts, v: next(l for l, val in opts if val == v)
        rows = [
            ("Portraits", str(cfg["count"]) if "count" in cfg else "invalid"),
            ("Gender", label(GENDER_OPTS, self.gender)),
            ("Category", label(CATEGORY_OPTS, self.category)),
            ("Art style", label(STYLE_OPTS, self.style)),
            ("Format", self.fmt.upper()),
            ("Seed", str(cfg["seed"]) if cfg.get("seed") is not None else "random"),
            ("Size", f"{SIZE} x {SIZE} px"),
        ]
        y = panel.y + 52
        for k, v in rows:
            self.text(k, self.f_small, DIM, (panel.x + 18, y))
            bad = v == "invalid"
            self.text(v, self.f_body, BAD if bad else TEXT, (panel.x + 18, y + 16))
            y += 46
        self.text("Output folder", self.f_small, DIM, (panel.x + 18, y))
        folder = cfg.get("folder") or "invalid"
        self.text(self.fit(folder, self.f_body, panel.width - 36), self.f_body,
                  BAD if "folder" in errors else TEXT, (panel.x + 18, y + 16))
        if "count" in cfg and "folder" in cfg:
            self.text(output_pattern(self.fmt), self.f_small, DIM, (panel.x + 18, y + 44))

    def draw_status(self):
        if self.busy():
            job = self.job
            frac = job.done / max(1, job.total)
            self.text(f"{frac * 100:.0f}%   |   {job.ok} saved   |   {job.failed} failed   |   "
                      f"{job.done} / {job.total} processed", self.f_body, TEXT, (30, 648))
            bar = pygame.Rect(30, 674, 920, 12)
            pygame.draw.rect(self.screen, FIELD, bar, border_radius=6)
            if job.done:
                pygame.draw.rect(self.screen, BAD if job.failed else ACCENT,
                                 (bar.x, bar.y, max(8, int(bar.width * frac)), bar.height), border_radius=6)
        else:
            self.text(self.fit(self.status, self.f_body, 920), self.f_body, self.status_color, (30, 652))

    def draw_preview(self):
        cfg = self.preview_cfg
        self.text("Preview (not saved)", self.f_title, TEXT, (30, 18))
        desc = (f"Gender: {dict((v, l) for l, v in GENDER_OPTS)[cfg['gender']]}   "
                f"Category: {dict((v, l) for l, v in CATEGORY_OPTS)[cfg['category']]}   "
                f"Style: {STYLES[cfg['style']]}   Seed: {cfg['seed']}")
        self.text(desc, self.f_body, DIM, (32, 58))
        gap, cols = 14, 4
        x0 = (WIDTH - (cols * SIZE + (cols - 1) * gap)) // 2
        for i, (surf, label) in enumerate(self.preview_surfaces):
            x = x0 + (i % cols) * (SIZE + gap)
            y = 92 + (i // cols) * (SIZE + 28)
            self.screen.blit(surf, (x, y))
            self.text(label, self.f_small, DIM, (x, y + SIZE + 3))
        more = cfg["count"] > PREVIEW_COUNT
        self.button((x0, 618, 170, 46), "Close", lambda: setattr(self, "mode", "menu"), accent=True)
        self.button((x0 + 184, 618, 170, 46), "Next set", self.next_preview, more and not self.busy())

    def next_preview(self):
        self.preview_start += PREVIEW_COUNT
        self.load_preview()

    def draw_confirm(self):
        title, lines, buttons = self.confirm
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        self.screen.blit(veil, (0, 0))
        box = pygame.Rect(0, 0, 640, 200)
        box.center = (WIDTH // 2, HEIGHT // 2)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=10)
        self.text(title, self.f_label, TEXT, (box.x + 24, box.y + 20))
        for k, line in enumerate(lines):
            self.text(self.fit(line, self.f_body, box.width - 48), self.f_body, DIM, (box.x + 24, box.y + 54 + k * 24))
        bw = (box.width - 48 - 12 * (len(buttons) - 1)) // len(buttons)
        for k, (label, cb) in enumerate(buttons):
            self.button((box.x + 24 + k * (bw + 12), box.y + 130, bw, 44), label,
                        cb or (lambda: setattr(self, "mode", "menu")), accent=k == 0)

    def frame(self):
        self.screen.fill(BG)
        self.hits = []
        if self.mode == "preview":
            self.draw_preview()
            self.draw_status() if self.busy() else None
        else:
            self.draw_menu()
            if self.mode == "confirm":
                self.hits = []
                self.draw_confirm()
        pygame.display.flip()

    def run(self):
        while self.running:
            for e in pygame.event.get():
                try:
                    self.handle_event(e)
                except Exception as exc:
                    self.set_status(f"Error: {exc}", BAD)
            self.poll_job()
            self.frame()
            self.clock.tick(30)
        if self.busy():
            self.job.cancel = True
            if self.job_thread:
                self.job_thread.join(5)
        pygame.quit()


def run():
    App().run()
