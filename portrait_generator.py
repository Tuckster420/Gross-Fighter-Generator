"""Procedural ugly/goofy fighter portrait generator (Pillow only).

Public API:
    derive_seed(master_seed, portrait_id) -> int
    build_traits(seed, gender=None)       -> dict   (all random choices, no drawing)
    draw_portrait(traits)                 -> PIL.Image (150x150 RGB)
    generate_portrait(portrait_id, master_seed=0, gender=None) -> PIL.Image
    portrait_signature(traits)            -> tuple  (categorical feature combo)
    save_portrait(image, path, quality=90)

New appearance options are added by extending the option tables below and
handling them in the matching draw function.
"""
import colorsys
import hashlib
import math
import os
import random

from PIL import Image, ImageDraw, ImageEnhance

SIZE = 150
SCALE = 3  # supersampling factor, image is downscaled at the end
OUTLINE = (45, 28, 28)

# ---------------------------------------------------------------- option tables
SKIN_TONES = [(255, 224, 200), (240, 200, 165), (224, 172, 130), (198, 134, 90),
              (160, 100, 65), (120, 75, 50), (90, 55, 38)]
COMPLEXIONS = {"normal": ((0, 0, 0), 0), "ruddy": ((230, 110, 100), 0.22),
               "sallow": ((205, 190, 100), 0.2), "pale": ((255, 245, 240), 0.25),
               "tanned": ((170, 100, 50), 0.15)}
HAIR_COLORS = {"black": (25, 20, 20), "dark brown": (60, 38, 25), "brown": (105, 68, 38),
               "auburn": (125, 52, 30), "ginger": (200, 100, 40), "blonde": (208, 175, 92),
               "platinum": (232, 218, 165), "gray": (150, 150, 150), "white": (228, 228, 228),
               "blue": (60, 90, 200), "pink": (230, 100, 170)}
HAIR_WEIGHTS = {"black": 22, "dark brown": 22, "brown": 20, "auburn": 6, "ginger": 6,
                "blonde": 12, "platinum": 3, "blue": 1, "pink": 1}
EYE_COLORS = [(70, 110, 170), (80, 55, 30), (60, 120, 70), (110, 110, 110), (40, 30, 25),
              (130, 150, 170), (120, 95, 40)]
BG_STYLES = ["plain", "plain", "plain", "gradient", "vignette", "split"]
SHIRT_COLORS = [(190, 40, 40), (40, 70, 160), (40, 120, 60), (230, 230, 225), (30, 30, 35),
                (220, 170, 40), (130, 50, 140), (230, 120, 40), (90, 90, 95), (60, 150, 160)]
SHIRT_PATTERNS = ["none", "none", "none", "hstripes", "plaid", "band", "dots", "emblem", "zigzag"]
LIP_COLORS = [(190, 110, 100), (170, 85, 85), (200, 60, 90), (150, 50, 60), (175, 120, 110)]
SCARS = ["brow", "cheek", "chin", "lip", "forehead", "nose", "double", "long_cheek", "eye"]
GLASSES = ["round", "square", "shades", "tiny"]
AGE_BRACKETS = [(18, 25), (26, 35), (36, 45), (46, 55), (56, 78)]
AGE_WEIGHTS = [20, 28, 22, 17, 13]

# lower-face profile (x fraction of half-width, y fraction of half-height below center)
JAWS = {
    "round": [(0.98, .25), (0.90, .55), (0.70, .82), (0.36, .98)],
    "square": [(1.00, .35), (0.97, .75), (0.82, .97), (0.45, 1.0)],
    "pointy": [(0.95, .30), (0.78, .62), (0.50, .88), (0.16, 1.0)],
    "wide": [(1.06, .35), (1.03, .70), (0.88, .92), (0.50, 1.0)],
    "weak": [(0.95, .30), (0.80, .65), (0.52, .84), (0.30, .90)],
    "jutting": [(0.92, .30), (0.80, .60), (0.62, .72), (0.55, 1.05)],
    "narrow": [(0.86, .30), (0.72, .62), (0.50, .88), (0.28, 1.0)],
    "heavy": [(1.02, .40), (1.05, .75), (0.92, .95), (0.58, 1.0)],
    "jowly": [(0.98, .30), (1.00, .62), (0.93, .85), (0.62, .98)],
    "chiseled": [(0.98, .35), (0.90, .80), (0.70, .98), (0.38, 1.0)],
    "melon": [(1.00, .40), (0.98, .72), (0.80, .95), (0.42, 1.02)],
    "long": [(0.92, .30), (0.84, .70), (0.64, .95), (0.40, 1.04)],
    "bulldog": [(1.05, .30), (0.97, .66), (0.80, .78), (0.52, .86)],
    "chinless": [(0.90, .30), (0.72, .62), (0.50, .70), (0.30, .74)],
    "anvil": [(0.92, .30), (0.96, .75), (0.90, .98), (0.62, 1.0)],
}
FEMALE_JAWS = ["round", "pointy", "weak", "square", "narrow", "melon", "chiseled", "long", "chinless"]
# style: (bridge half-width, tip half-width, tip height, bend, zig, nostril size)
NOSES = {
    "button": (2.5, 4, 3, 0, 0, 1.2), "long": (3, 5, 4, 0, 0, 1.4),
    "bulbous": (3, 7.5, 6, 0, 0, 2.0), "hooked": (3, 5, 4, 3, 0, 1.4),
    "broad": (4, 8.5, 3.5, 0, 0, 2.2), "pointy": (2, 4, 2.5, 0, 0, 1.0),
    "broken": (3.5, 6, 4, 0, -3, 1.6), "upturned": (2.5, 5, 3, 0, 0, 2.3),
    "potato": (3.5, 9.5, 7, 0, 0, 2.2), "tiny": (1.5, 2.8, 2, 0, 0, 0.8),
    "pig": (2.5, 6, 2.5, 0, 0, 3.2), "flat": (4.5, 7.5, 2, 0, 0, 2.6),
    "roman": (2.5, 4.5, 4, 2, 0, 1.3), "crooked": (3, 5.5, 4, 2, 3.5, 1.5),
    "drooping": (3, 5.5, 8, 0, 0, 1.3), "thin": (1.5, 3.2, 3.5, 0, 0, 1.0),
    "knobby": (3, 6, 5.5, 0, 1.5, 1.8),
}
# style: (smile depth, open height, teeth, half-width factor)
MOUTHS = {
    "smile": (3.5, 3, True, 1.0), "grin": (4, 6, True, 1.25), "flat": (0, 0, False, 1.0),
    "frown": (-3, 0, False, 1.0), "open": (1, 8, False, 0.8), "buck": (1.5, 3, True, 0.8),
    "gap": (3, 3, True, 1.0), "smirk": (2, 2, True, 1.0), "pursed": (0, 0, False, 0.6),
    "tongue": (2, 7, False, 0.9), "snarl": (-1.5, 5, True, 1.0), "wide": (5, 8, True, 1.5),
    "tiny": (0.5, 3.5, False, 0.4), "pout": (-0.5, 0, False, 0.7), "lopsided": (2, 5, True, 1.0),
    "toothless": (3, 5, False, 1.0),
}
BROWS = ["thick", "thin", "unibrow", "angry", "sad", "arched", "bushy", "stubby", "high", "none"]
BROW_WEIGHTS = [14, 14, 6, 10, 8, 10, 10, 6, 6, 2]
EYE_SHAPES = ["round", "almond", "slit", "bug", "beady", "droopy", "upslant", "wide", "hooded"]
EYE_RATIO = {"round": 0.9, "almond": 0.55, "slit": 0.3, "bug": 1.1, "beady": 0.85, "droopy": 0.6,
             "upslant": 0.55, "wide": 0.7, "hooded": 0.42}
EYE_WMULT = {"beady": 0.62, "wide": 1.2, "bug": 1.05, "hooded": 1.05}
EYE_TILT = {"droopy": -2.2, "upslant": 2.4}  # px the outer corner sits above (+) / below (-) the inner one

GENDERS = ["male", "female"]
STYLES = {"gross": "Gross and Goofy", "crude": "Crude Game Art", "cartoon": "Exaggerated Cartoon"}
BASE_CATEGORIES = ["white", "black", "asian", "latino"]
CATEGORIES = ["white", "black", "asian", "latino", "mixed"]

# Per-category appearance pools. "mixed" draws each attribute from a random base category.
CATEGORY_DATA = {
    "white": {
        "skins": [(255, 224, 200), (245, 210, 180), (235, 195, 160), (255, 235, 220), (225, 180, 150),
                  (250, 205, 185)],
        "hair": {"brown": 24, "dark brown": 20, "blonde": 22, "black": 10, "ginger": 12, "auburn": 8,
                 "platinum": 4},
        "eye_shapes": ["round", "almond", "bug", "slit", "wide", "droopy", "hooded", "beady", "upslant"],
        "eye_colors": [(70, 110, 170), (60, 120, 70), (80, 55, 30), (110, 110, 110), (130, 150, 170),
                       (120, 95, 40)],
        "noses": ["long", "hooked", "pointy", "bulbous", "button", "upturned", "broken", "roman", "thin",
                  "drooping", "potato", "crooked", "knobby", "pig"],
    },
    "black": {
        "skins": [(160, 100, 65), (120, 75, 50), (90, 55, 38), (75, 45, 32), (185, 120, 80), (105, 65, 45)],
        "hair": {"black": 80, "dark brown": 20},
        "eye_shapes": ["round", "almond", "bug", "wide", "droopy", "beady", "hooded", "upslant"],
        "eye_colors": [(40, 30, 25), (80, 55, 30), (120, 95, 40)],
        "noses": ["broad", "bulbous", "button", "upturned", "broken", "flat", "pig", "tiny", "drooping",
                  "potato", "knobby"],
        "hair_styles": ["bald", "buzz", "short", "sidepart", "receding", "afro", "curly", "long",
                        "spiky", "mohawk", "bob", "pigtails", "bun", "pixie", "flattop", "dreads",
                        "cornrows", "topknot", "afropuffs", "braid", "wisps", "messy", "horseshoe",
                        "bowl", "wavy", "shaggy"],
    },
    "asian": {
        "skins": [(240, 205, 160), (230, 190, 145), (245, 215, 175), (225, 180, 135), (250, 222, 190)],
        "hair": {"black": 85, "dark brown": 15},
        "eye_shapes": ["almond", "slit", "almond", "upslant", "hooded", "beady", "droopy", "round"],
        "eye_colors": [(40, 30, 25), (60, 40, 25)],
        "noses": ["button", "pointy", "upturned", "broad", "tiny", "flat", "thin", "pig", "potato",
                  "crooked"],
        "hair_styles": ["bald", "buzz", "short", "sidepart", "combover", "receding", "spiky", "long",
                        "bob", "ponytail", "bun", "pixie", "pigtails", "mohawk", "flattop", "bowl",
                        "pompadour", "slicked", "topknot", "messy", "wisps", "braid", "sideswept",
                        "horseshoe", "mullet", "wavy", "shaggy"],
    },
    "latino": {
        "skins": [(224, 172, 130), (205, 150, 108), (215, 165, 120), (190, 135, 95), (232, 185, 145)],
        "hair": {"black": 55, "dark brown": 35, "brown": 10},
        "eye_shapes": ["round", "almond", "bug", "droopy", "wide", "hooded", "beady"],
        "eye_colors": [(80, 55, 30), (40, 30, 25), (60, 120, 70), (120, 95, 40)],
        "noses": ["long", "hooked", "broad", "button", "bulbous", "broken", "roman", "drooping", "crooked",
                  "potato", "flat", "knobby"],
    },
}
MUSTACHES = ["none", "chevron", "handlebar", "pencil", "toothbrush", "walrus"]
BEARDS = ["full", "goatee", "chinstrap", "soul patch", "long", "patchy", "neckbeard", "vandyke", "mutton"]
SHIRTS = ["crew", "vneck", "polo", "tank", "suit", "hoodie", "turtleneck", "gi", "robe", "shirtless",
          "jersey", "sweater"]
MALE_HAIR = ["bald", "buzz", "short", "sidepart", "combover", "receding", "horseshoe",
             "mohawk", "afro", "long", "mullet", "spiky", "curly", "flattop", "bowl", "pompadour",
             "slicked", "dreads", "cornrows", "topknot", "messy", "wisps", "shaggy"]
FEMALE_HAIR = ["long", "bob", "ponytail", "bun", "pigtails", "pixie", "curly", "buzz",
               "afro", "short", "braid", "sideswept", "wavy", "shaggy", "afropuffs", "topknot", "wisps",
               "messy", "slicked", "bowl"]
BALDING = ["bald", "receding", "horseshoe", "combover", "wisps", "buzz"]
CAP_THICKNESS = {"buzz": 1.5, "short": 4, "sidepart": 5, "combover": 4, "receding": 4,
                 "mohawk": 0, "afro": 6, "long": 5, "mullet": 4, "spiky": 3, "curly": 7,
                 "bob": 5, "ponytail": 4, "bun": 4, "pigtails": 4, "pixie": 3,
                 "horseshoe": 0, "bald": 0, "flattop": 4, "bowl": 5, "pompadour": 4, "slicked": 3,
                 "dreads": 4, "cornrows": 2, "topknot": 3, "messy": 4, "wisps": 0, "shaggy": 5,
                 "braid": 4, "sideswept": 4, "wavy": 5, "afropuffs": 4}


# ---------------------------------------------------------------- small helpers
def derive_seed(master_seed, portrait_id):
    digest = hashlib.sha256(f"{master_seed}:{portrait_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _scaled(pts):
    return [(x * SCALE, y * SCALE) for x, y in pts]


def _poly(d, pts, fill, outline=OUTLINE, w=0.8):
    d.polygon(_scaled(pts), fill=fill, outline=outline,
              width=max(1, round(w * SCALE)) if outline else 1)


def _ell(d, cx, cy, rx, ry, fill, outline=OUTLINE, w=0.8):
    d.ellipse([(cx - rx) * SCALE, (cy - ry) * SCALE, (cx + rx) * SCALE, (cy + ry) * SCALE],
              fill=fill, outline=outline, width=max(1, round(w * SCALE)))


def _line(d, pts, fill=OUTLINE, w=1.0):
    d.line(_scaled(pts), fill=fill, width=max(1, round(w * SCALE)), joint="curve")


def _inside_face(t, x, y, margin=0.9):
    return ((x - t["cx"]) / t["hw"]) ** 2 + ((y - t["cy"]) / t["hh"]) ** 2 < margin


def _eye_pos(t, side):
    ex = t["cx"] + side * t["eye_gap"]
    ey = t["cy"] + t["hh"] * t["eye_y"] + (t["eye_dy"] if side == 1 else 0)
    k = t["eye_scale"] if side == 1 else 1.0
    return ex, ey, t["eye_w"] * k, t["eye_h"] * k


def _nose_geom(t):
    ey = t["cy"] + t["hh"] * t["eye_y"]
    return t["cx"] + t["nose_dx"], ey + t["hh"] * t["nose_len"]


def _nose_dims(t):
    bw, tw, th, bend, zig, nost = NOSES[t["nose"]]
    k, w = t["nose_scale"], t["nose_w"]
    return bw * k * w, tw * k * w, th * k, bend + t["nose_lean"], zig * k, nost * k


def _chin_y(t):
    return _head_points(t)[3]


def _mouth_xy(t):
    """Mouth sits a set distance under the nose but always stays clear of the chin."""
    _, ny = _nose_geom(t)
    my = ny + _nose_dims(t)[2] + t["mouth_gap"]
    my = min(my, _chin_y(t) - 7 - MOUTHS[t["mouth"]][1] * 0.6)
    return t["cx"] + t["mouth_dx"], my


def _set_eye_shape(t, shape):
    t["eye_shape"] = shape
    t["eye_w"] = t["eye_w0"] * EYE_WMULT.get(shape, 1.0)
    t["eye_h"] = t["eye_w"] * EYE_RATIO[shape]
    t["eye_tilt"] = EYE_TILT.get(shape, 0.0) + t["eye_extra"]


def _hsv(h, s, v):
    return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v))))


def _lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


# ---------------------------------------------------------------- randomization
def build_traits(seed, gender=None, category=None, style="gross"):
    """Make every random choice for one individual. Pure data, no drawing.

    gender: "male"/"female"/None (random). category: white/black/asian/latino/mixed/None (random).
    style: key of STYLES.
    """
    r = random.Random(seed)
    art_style = style
    t = {"seed": seed}
    t["gender"] = gender or r.choice(["male", "female"])
    male = t["gender"] == "male"
    weights = [w[0 if male else 1] for w in ARCHETYPES.values()]
    t["archetype"] = random.Random(seed ^ 0xA5C3A5C3).choices(list(ARCHETYPES), weights)[0]
    lo, hi = r.choices(AGE_BRACKETS, AGE_WEIGHTS)[0]
    lo, hi = {"babyface": (18, 24), "oldtimer": (56, 78)}.get(t["archetype"], (lo, hi))
    t["age"] = r.randint(lo, hi)
    old = t["age"] >= 55

    base = r.choice(SKIN_TONES)
    base = tuple(max(0, min(255, v + r.randint(-8, 8))) for v in base)
    t["complexion"] = r.choice(list(COMPLEXIONS))
    tint, amount = COMPLEXIONS[t["complexion"]]
    t["skin"] = _mix(base, tint, amount) if amount else base

    t["cx"] = 75 + r.uniform(-2.5, 2.5)
    t["cy"] = 63 + r.uniform(-4, 4)
    t["hw"] = r.uniform(23, 39) - (2 if not male else 0)
    t["hh"] = r.uniform(27, 40)
    t["head_n"] = r.choice([2.0, 2.0, 2.4, 3.0, 1.6])  # skull outline: >2 squarer, <2 pointier
    t["taper"] = r.choice([0, 0, 0, 0.12, 0.2, -0.12, -0.18])  # + narrow forehead, - wide forehead
    t["jaw"] = r.choice(list(JAWS) if male else FEMALE_JAWS)
    t["fat"] = 0.0
    t["jaw_jitter"] = [(r.uniform(-2.2, 2.2), r.uniform(-2.2, 2.2)) for _ in range(8)]
    t["neck_ratio"] = r.uniform(0.4, 0.95) * (1 if male else 0.85)
    t["cleft"] = r.random() < 0.15
    t["tilt"] = max(-8.0, min(8.0, r.gauss(0, 3.2)))

    t["ear_w"] = r.uniform(2.5, 8.5)
    t["ear_h"] = r.uniform(5, 15)
    t["ear_out"] = r.uniform(-1.5, 6)
    t["ear_drop"] = r.uniform(0.02, 0.22)
    t["ear_asym"] = r.uniform(0.8, 1.25)
    t["ear_pointy"] = r.random() < 0.1
    t["cauliflower"] = male and r.random() < 0.2

    t["eye_shape"] = r.choice(EYE_SHAPES)
    t["eye_w0"] = r.uniform(4.2, 8.8)
    t["eye_extra"] = r.uniform(-0.9, 0.9)
    t["eye_gap"] = t["hw"] * r.uniform(0.26, 0.54)
    t["eye_y"] = r.uniform(-0.24, 0.08)
    t["eye_scale"] = r.uniform(0.75, 1.3)
    t["eye_dy"] = r.uniform(-3, 3)
    t["eye_color"] = r.choice(EYE_COLORS)
    t["gaze"] = r.choice([0, 0, 0, 1, -1, 2]) * r.uniform(0.6, 1.2)  # 2 = cross-eyed
    t["gaze_y"] = r.uniform(-0.8, 0.8)
    t["droop"] = r.choice([0, 0, 0, 0, 0.3, 0.5, 0.7])
    t["bags"] = old or r.random() < 0.25
    t["brow"] = r.choices(BROWS if male else ["thin", "arched", "angry", "sad", "thick", "high", "stubby"],
                          BROW_WEIGHTS if male else [20, 20, 8, 8, 10, 8, 6])[0]
    t["brow_w"] = r.uniform(1.0, 3.2) if male else r.uniform(0.8, 1.6)
    t["brow_gap"] = r.uniform(1.5, 6.5)
    t["brow_tilt"] = r.uniform(-3, 3)
    t["eyeshadow"] = (not male) and r.random() < 0.4

    t["nose"] = r.choice(list(NOSES) if male else [n for n in NOSES if n != "broken"])
    t["nose_len"] = r.uniform(0.26, 0.48)
    t["nose_dx"] = r.uniform(-2, 2)
    t["nose_scale"] = r.uniform(0.75, 1.4)
    t["nose_w"] = r.uniform(0.85, 1.2)
    t["nose_lean"] = r.uniform(-1.2, 1.2)

    t["mouth"] = r.choice(list(MOUTHS))
    t["mouth_dx"] = r.uniform(-2.5, 2.5)
    t["mouth_gap"] = r.uniform(5, 13)
    t["mouth_w"] = t["hw"] * r.uniform(0.26, 0.46)
    t["mouth_tilt"] = r.uniform(-3.5, 3.5)
    t["lip"] = r.uniform(0.8, 4)
    t["lip_color"] = r.choice(LIP_COLORS) if not male and r.random() < .7 else \
        _mix(t["skin"], (190, 90, 90), r.uniform(.25, .55))
    t["tooth_color"] = r.choice([(246, 246, 235), (230, 220, 160), (215, 195, 120), (190, 170, 110)])
    t["missing"] = [i for i in range(6) if r.random() < (0.35 if t["mouth"] == "gap" else 0.04)]
    t["tooth_jitter"] = [r.uniform(-1, 1) for _ in range(6)]

    # hair
    t["gray"] = max(0.0, min(1.0, (t["age"] - 33) / 40 * r.uniform(0.3, 1.6)))
    names = list(HAIR_WEIGHTS)
    t["hair_color_name"] = r.choices(names, [HAIR_WEIGHTS[n] for n in names])[0]
    t["hair_color"] = tuple(max(0, min(255, v + r.randint(-10, 10)))
                            for v in HAIR_COLORS[t["hair_color_name"]])
    style = r.choice(MALE_HAIR if male else FEMALE_HAIR)
    if male and t["age"] > 42 and r.random() < min(0.6, (t["age"] - 40) / 40):
        style = r.choice(BALDING)
    elif old and style in ("long", "afro", "spiky", "mohawk", "curly", "pigtails", "afropuffs") \
            and r.random() < .6:
        style = r.choice(["wisps", "short", "bun"] if not male else BALDING)
    t["hair"] = style
    _refresh_hairline(t, r)
    t["sideburn"] = r.choice([0, 0, 4, 8, 12, 16]) if male else 0
    t["brow_color"] = _mix(t["hair_color"], OUTLINE, 0.3)

    t["beard"] = r.choice(BEARDS) if male and r.random() < 0.55 else "none"
    t["mustache"] = r.choice(MUSTACHES[1:]) if male and r.random() < 0.38 else "none"
    t["stubble"] = male and t["beard"] == "none" and r.random() < 0.35
    t["facial_color"] = t["hair_color"]

    # details
    t["wrinkles"] = max(0, (t["age"] - 22) // 11)
    t["freckles"] = r.choice([0, 0, 0, 12, 25, 40, 60])
    t["pimples"] = r.choice([0, 0, 1, 2, 4, 7, 11]) if t["age"] < 40 else r.choice([0, 0, 1])
    t["mole"] = r.random() < 0.25
    t["scar"] = r.choice(["none"] * 3 + SCARS) if male else r.choice(["none"] * 7 + SCARS)
    t["scar2"] = "none" if t["scar"] == "none" or r.random() < .7 else r.choice(SCARS)
    t["black_eye"] = r.choice([0, 0, 0, 0, 0, -1, 1]) if male else 0
    t["blush"] = r.random() < 0.5
    t["red_nose"] = r.random() < 0.3
    t["spots"] = (t["age"] - 40) // 3 if t["age"] > 45 and r.random() < 0.6 else 0
    t["wart"] = r.random() < 0.06
    t["birthmark"] = r.random() < 0.07
    t["blotch"] = r.random() < 0.15
    t["glasses"] = r.choice(GLASSES) if r.random() < 0.16 else "none"
    t["eyepatch"] = 0 if t["glasses"] != "none" or r.random() > 0.035 else r.choice([-1, 1])
    t["earring"] = r.random() < (0.12 if male else 0.3)
    t["bandage"] = r.random() < 0.04
    t["headband"] = r.random() < 0.04

    # clothes
    t["shirt"] = r.choice([s for s in SHIRTS if male or s != "shirtless"])
    t["shirt_color"] = tuple(max(0, min(255, v + r.randint(-22, 22))) for v in r.choice(SHIRT_COLORS))
    t["shirt_pattern"] = r.choice(SHIRT_PATTERNS)
    t["shoulder_w"] = r.uniform(52, 82) * (1 if male else 0.88)
    t["shoulder_slope"] = (r.uniform(-2, 10), r.uniform(-2, 10))
    t["neck_base"] = r.uniform(108, 114)
    t["bg_seed"] = r.getrandbits(32)
    t["detail_seed"] = r.getrandbits(32)

    # category/style use their own stream so they never disturb the base random choices
    rr = random.Random(seed ^ 0x5EED5EED)
    category = (category or "random").lower()
    t["category"] = rr.choice(BASE_CATEGORIES + ["mixed"]) if category == "random" else category
    t["style"] = (art_style or "gross").lower()
    _apply_category(t, rr)
    _apply_archetype(t, rr)
    _apply_style(t, rr)
    _finish(t, rr)
    return t


# name: (male weight, female weight)
ARCHETYPES = {"average": (30, 30), "bruiser": (16, 5), "goof": (14, 16), "grump": (10, 10),
              "weasel": (10, 10), "babyface": (8, 12), "heavy": (10, 8), "oldtimer": (8, 6)}


def _apply_archetype(t, rr):
    """Nudge several features together so the face reads as one person, not random parts."""
    a, male = t["archetype"], t["gender"] == "male"
    if a == "bruiser":
        t["hw"] += 3
        t["jaw"] = rr.choice(["heavy", "square", "anvil", "bulldog", "chiseled"])
        t["neck_ratio"] = max(t["neck_ratio"], 0.8)
        t["brow"] = rr.choice(["thick", "angry", "bushy", "unibrow"])
        t["brow_gap"] = min(t["brow_gap"], 3)
        t["eye_shape"] = rr.choice(["beady", "hooded", "slit", "almond"])
        if male:
            t["nose"] = rr.choice(["broken", "broken", "flat", "potato"])
            t["cauliflower"] = rr.random() < 0.7
            if t["scar"] == "none" and rr.random() < 0.6:
                t["scar"] = rr.choice(SCARS)
    elif a == "goof":
        t["eye_shape"] = rr.choice(["bug", "wide", "round", "droopy"])
        t["mouth"] = rr.choice(["buck", "grin", "wide", "tongue", "gap", "lopsided", "open"])
        t["ear_out"] += 2.5
        t["ear_w"] = max(t["ear_w"], 5)
        t["nose"] = rr.choice(["bulbous", "potato", "pig", "knobby", "long"])
        t["gaze"] = rr.choice([0, 2, -1, 1]) * 1.0
    elif a == "grump":
        t["brow"] = rr.choice(["angry", "thick", "bushy"])
        t["mouth"] = rr.choice(["frown", "snarl", "flat", "pursed", "pout"])
        t["bags"] = True
        t["eye_shape"] = rr.choice(["hooded", "beady", "slit", "droopy"])
    elif a == "weasel":
        t["hw"] = min(t["hw"], 29)
        t["jaw"] = rr.choice(["narrow", "chinless", "pointy", "weak"])
        t["nose"] = rr.choice(["long", "pointy", "thin", "hooked"])
        t["eye_shape"] = rr.choice(["beady", "slit", "upslant"])
        t["eye_gap"] = t["hw"] * rr.uniform(0.26, 0.34)
        t["mouth"] = rr.choice(["buck", "smirk", "gap", "pursed", "tiny"])
        t["neck_ratio"] = min(t["neck_ratio"], 0.55)
    elif a == "babyface":
        t["hh"] *= 0.93
        t["jaw"] = rr.choice(["round", "melon", "weak"])
        t["nose"] = rr.choice(["button", "tiny", "upturned"])
        t["eye_w0"] = max(t["eye_w0"], 6.5)
        t["eye_shape"] = rr.choice(["round", "wide", "bug"])
        t["wrinkles"], t["bags"], t["beard"], t["stubble"] = 0, False, "none", False
        t["blush"] = True
    elif a == "heavy":
        t["fat"] = rr.uniform(0.12, 0.22)
        t["hw"] = min(41, t["hw"] * (1 + t["fat"]))
        t["jaw"] = rr.choice(["jowly", "melon", "round", "bulldog", "heavy"])
        t["neck_ratio"] = max(t["neck_ratio"], 0.85)
        t["nose"] = rr.choice(["bulbous", "potato", "flat", "pig", "broad"])
        t["eye_shape"] = rr.choice(["beady", "hooded", "droopy", "slit"])
        t["red_nose"] = rr.random() < 0.5
        t["complexion"] = rr.choice(["ruddy", "ruddy", "normal", "sallow"])
    elif a == "oldtimer":
        t["bags"] = True
        t["wrinkles"] += 2
        t["ear_h"] *= 1.2
        t["ear_w"] *= 1.1
        t["nose_scale"] *= 1.15
        t["brow"] = rr.choice(["bushy", "thick", "thin"])
        t["mouth"] = rr.choice(["toothless", "flat", "smile", "frown"])
    if t["nose"] == "broken" and not male:
        t["nose"] = "button"


def _fit_features(t):
    """Keep features inside the face and stop eyes, nose and mouth colliding."""
    hw = t["hw"]
    # eye half-width (with the larger eye scale) must clear the centre line and the face edge
    t["eye_gap"] = max(t["eye_gap"], hw * 0.24)
    t["eye_w0"] = min(t["eye_w0"], (t["eye_gap"] - 1.5) / (1.3 * max(1, EYE_WMULT.get(t["eye_shape"], 1))))
    while t["eye_gap"] + t["eye_w0"] * 1.3 * EYE_WMULT.get(t["eye_shape"], 1) > hw * 0.92 and t["eye_gap"] > 5:
        t["eye_gap"] -= 0.5
    _set_eye_shape(t, t["eye_shape"])
    bw, tw = NOSES[t["nose"]][:2]
    t["nose_scale"] = min(t["nose_scale"], hw * 0.4 / (tw * t["nose_w"]))
    t["mouth_w"] = min(t["mouth_w"], hw * 0.55 / max(0.4, MOUTHS[t["mouth"]][3]))
    t["mouth_w"] = max(t["mouth_w"], 5)


def _apply_bg(t):
    r = random.Random(t["bg_seed"])
    t["bg_style"] = r.choice(BG_STYLES)
    hue, sat = r.random(), r.uniform(0.1, 0.55)
    val = r.uniform(0.5, 0.95)
    bg = _hsv(hue, sat, val)
    ref = [_lum(t["hair_color"]), _lum(t["skin"])]
    for _ in range(8):  # keep the background distinguishable from both hair and skin
        if min(abs(_lum(bg) - x) for x in ref) >= 38:
            break
        val = val - 0.12 if val > 0.5 else val + 0.12
        val = max(0.18, min(1.0, val))
        bg = _hsv(hue, sat, val)
    t["bg"] = bg
    t["bg2"] = _hsv(hue + r.uniform(-0.1, 0.1), sat * r.uniform(0.8, 1.2), max(0.15, min(1, val + r.uniform(-.25, .2))))


def _finish(t, rr):
    """Final consistency pass after category, archetype and style have adjusted the traits."""
    g = t["gray"]
    if g > 0.05:
        t["hair_color"] = _mix(t["hair_color"], (205, 205, 205), min(1.0, g) * 0.9)
    t["facial_color"] = t["hair_color"]
    t["brow_color"] = _mix(t["hair_color"], OUTLINE, 0.3 + 0.2 * (1 - g))
    t["neck_w"] = t["hw"] * t["neck_ratio"]
    _fit_features(t)
    _apply_bg(t)


def _apply_category(t, rr):
    cat = t["category"]
    mixed = cat == "mixed"

    def src():
        return CATEGORY_DATA[rr.choice(BASE_CATEGORIES) if mixed else cat]

    s1, s2 = src(), src()
    base = _mix(rr.choice(s1["skins"]), rr.choice(s2["skins"]), rr.random() if mixed else 0)
    base = tuple(max(0, min(255, v + rr.randint(-10, 10))) for v in base)
    tint, amount = COMPLEXIONS[t["complexion"]]
    t["skin"] = _mix(base, tint, amount) if amount else base

    pool = src()["hair"]
    name = rr.choices(list(pool), list(pool.values()))[0]
    if rr.random() < 0.04:  # the odd dyed head
        name = rr.choice(["blue", "pink", "platinum"])
    t["hair_color_name"] = name
    t["hair_color"] = tuple(max(0, min(255, v + rr.randint(-12, 12))) for v in HAIR_COLORS[name])

    t["eye_shape"] = rr.choice(src()["eye_shapes"])
    t["eye_color"] = rr.choice(src()["eye_colors"])

    noses = [n for n in src()["noses"] if t["gender"] == "male" or n != "broken"]
    t["nose"] = rr.choice(noses)

    styles = src().get("hair_styles")
    if styles and t["hair"] not in styles:
        pool = [s for s in styles if s in (MALE_HAIR if t["gender"] == "male" else FEMALE_HAIR)]
        if t["hair"] in BALDING and t["gender"] == "male":
            pool = [s for s in pool if s in BALDING] or pool
        t["hair"] = rr.choice(pool)
        _refresh_hairline(t, rr)
    if cat == "asian" or (mixed and t["eye_shape"] == "slit"):
        t["beard"] = t["beard"] if rr.random() < 0.5 else "none"


def _refresh_hairline(t, rr):
    style = t["hair"]
    if style == "receding":
        t["hairline"], t["hairline_kind"] = (0.42, 0.62, 0.5), "receding"
    else:
        fc = rr.choice([0.45, 0.6, 0.65, 0.75, 0.85])
        t["hairline"], t["hairline_kind"] = (rr.uniform(0.15, 0.3), fc * 0.92, fc), "normal"
    t["peak"] = rr.choice([0, 0, 0, 0.18, 0.3])  # widow's peak depth
    t["hl_skew"] = rr.uniform(-0.12, 0.12)
    t["fringe"] = style in ("long", "bob", "ponytail", "pigtails", "pixie", "short", "wavy",
                            "shaggy", "braid") and rr.random() < 0.35


def _apply_style(t, rr):
    style = t["style"]
    if style == "gross":
        t["pimples"] += rr.randint(0, 3)
        t["wrinkles"] += 1
        t["eye_dy"] *= 1.5
        t["nose_scale"] *= 1.1
        t["blotch"] = t["blotch"] or rr.random() < 0.3
        t["bags"] = t["bags"] or rr.random() < 0.4
        if MOUTHS[t["mouth"]][2] and rr.random() < 0.3:
            t["missing"] = sorted(set(t["missing"]) | {rr.randrange(6)})
    elif style == "cartoon":
        t["hw"] = min(41, t["hw"] * 1.12)
        t["hh"] *= 1.05
        t["eye_w0"] *= 1.3
        t["nose_scale"] *= 1.35
        t["mouth_w"] *= 1.2
        t["ear_w"] *= 1.3
        t["ear_h"] *= 1.3
        t["brow_w"] *= 1.3
        t["wrinkles"] = 0
        t["pimples"] = 0
        t["bags"] = False
        t["droop"] = 0
        t["freckles"] = min(t["freckles"], 12)
        t["gaze"] = 0
    elif style == "crude":
        t["wrinkles"] = min(t["wrinkles"], 1)
        t["pimples"] = 0
        t["freckles"] = 0
        t["mole"] = False
        t["cauliflower"] = False
    else:
        raise ValueError(f"unknown style: {style!r}")


def portrait_signature(t):
    """Categorical feature combination, used to check for repeated faces."""
    keys = ("gender", "archetype", "jaw", "eye_shape", "brow", "nose", "mouth", "hair", "hair_color_name",
            "beard", "mustache", "scar", "glasses", "shirt", "shirt_pattern", "complexion")
    return tuple(t[k] for k in keys) + (round(t["hw"]), round(t["hh"]), t["shirt_color"], t["bg"])


# ---------------------------------------------------------------- drawing: structure
def _head_points(t):
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    n, tp = t["head_n"], t["taper"]
    pts = []
    for a in range(180, -1, -10):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        k = 2.0 / n
        x = math.copysign(abs(c) ** k, c) * hw * (1 - tp * s)
        pts.append((cx + x, cy - hh * 0.95 * (abs(s) ** k)))
    prof = JAWS[t["jaw"]]
    right, left = [], []
    for i, (fx, fy) in enumerate(prof):
        jr, jl = t["jaw_jitter"][i], t["jaw_jitter"][i + 4]
        right.append((cx + hw * fx + jr[0], cy + hh * fy + jr[1]))
        left.append((cx - hw * fx + jl[0], cy + hh * fy + jl[1]))
    chin_y = cy + hh * max(p[1] for p in prof)
    return pts + right + [(cx, chin_y)] + left[::-1], right, left, chin_y
    right, left = [], []
    for i, (fx, fy) in enumerate(prof):
        jr, jl = t["jaw_jitter"][i], t["jaw_jitter"][i + 4]
        right.append((cx + hw * fx + jr[0], cy + hh * fy + jr[1]))
        left.append((cx - hw * fx + jl[0], cy + hh * fy + jl[1]))
    chin_y = cy + hh * max(p[1] for p in prof)
    return pts + right + [(cx, chin_y)] + left[::-1], right, left, chin_y


def _draw_hair_back(d, t):
    cx, cy, hw, hh, col, style = t["cx"], t["cy"], t["hw"], t["hh"], t["hair_color"], t["hair"]
    th = CAP_THICKNESS[style]
    dark = _shade(col, 0.85)
    if style == "afro":
        _ell(d, cx, cy - hh * 0.3, hw + 15, hh * 0.85 + 6, col)
    elif style in ("long", "wavy", "shaggy"):
        bottom = {"long": 134, "wavy": 128, "shaggy": 120}[style]
        pts = [(cx - hw - th, cy - hh * 0.3), (cx - hw - th - 6, bottom - 4), (cx - hw * 0.4, bottom)]
        if style != "long":
            pts += [(cx - hw * 0.1, bottom - 5), (cx + hw * 0.2, bottom + 1)]
        pts += [(cx + hw * 0.4, bottom), (cx + hw + th + 6, bottom - 4), (cx + hw + th, cy - hh * 0.3)]
        _poly(d, pts, dark)
    elif style == "dreads":
        for k in range(-5, 6):
            x0 = cx + k * hw * 0.2
            _line(d, [(x0, cy - hh * 0.5), (x0 * 1.04 - cx * 0.04 + k * 0.6, 108 + abs(k) * 1.5)], dark, 2.6)
    elif style == "braid":
        _poly(d, [(cx - hw - th, cy - hh * 0.3), (cx - hw - th - 2, cy + hh * 0.6),
                  (cx + hw + th + 2, cy + hh * 0.6), (cx + hw + th, cy - hh * 0.3)], dark)
        for k in range(6):
            _ell(d, cx + hw * 0.5, cy + hh * 0.5 + k * 6, 3.4, 3.6, dark, w=0.6)
    elif style == "afropuffs":
        for s in (-1, 1):
            _ell(d, cx + s * hw * 0.72, cy - hh * 0.95 - 3, 9, 8.5, dark)
    elif style == "bob":
        _poly(d, [(cx - hw - th, cy - hh * 0.3), (cx - hw - th - 3, cy + hh * 0.8),
                  (cx + hw + th + 3, cy + hh * 0.8), (cx + hw + th, cy - hh * 0.3)], dark)
    elif style == "mullet":
        _poly(d, [(cx - hw * 0.8, cy), (cx - hw - 4, 118), (cx, 124), (cx + hw + 4, 118),
                  (cx + hw * 0.8, cy)], dark)
    elif style == "ponytail":
        _poly(d, [(cx + hw * 0.7, cy - hh * 0.6), (cx + hw + 16, cy), (cx + hw + 20, cy + hh * 1.1),
                  (cx + hw + 8, cy + hh * 0.6), (cx + hw * 0.9, cy)], dark)
    elif style == "pigtails":
        for s in (-1, 1):
            _ell(d, cx + s * (hw + 9), cy + hh * 0.35, 7, 15, dark)
    elif style == "horseshoe":
        pass


def _shirt_pattern(d, t, kind, shirt):
    r = random.Random(t["detail_seed"] + 3)
    cx = t["cx"]
    alt = _shade(shirt, 0.65) if _lum(shirt) > 90 else _shade(shirt, 1.6)
    if kind == "hstripes":
        for y in range(112, 154, 8):
            _line(d, [(0, y), (150, y)], alt, 2.4)
    elif kind == "plaid":
        for y in range(112, 154, 10):
            _line(d, [(0, y), (150, y)], alt, 1.6)
        for x in range(int(cx) % 11, 150, 11):
            _line(d, [(x, 100), (x, 154)], alt, 1.6)
    elif kind == "band":
        _line(d, [(0, 138), (150, 138)], (235, 235, 230), 5)
        _line(d, [(0, 138), (150, 138)], alt, 1.2)
    elif kind == "dots":
        for _ in range(26):
            _ell(d, r.uniform(0, 150), r.uniform(112, 152), 1.7, 1.7, alt, outline=None)
    elif kind == "emblem":
        ex = cx + r.choice([-1, 1]) * r.uniform(8, 22)
        _ell(d, ex, 138, 7, 7, (235, 215, 90), w=0.6)
        _poly(d, [(ex, 133), (ex + 2, 137.5), (ex + 6, 138), (ex + 2.5, 140.5), (ex, 144),
                  (ex - 2.5, 140.5), (ex - 6, 138), (ex - 2, 137.5)], alt, outline=None)
    elif kind == "zigzag":
        pts = [(x, 134 + (5 if (x // 8) % 2 else -5)) for x in range(0, 156, 8)]
        _line(d, pts, alt, 2.0)


def _draw_body(img, d, t):
    cx, cy, hh, nw = t["cx"], t["cy"], t["hh"], t["neck_w"]
    sw, (sl, sr) = t["shoulder_w"], t["shoulder_slope"]
    nb = t["neck_base"]
    skin, shirt, style = t["skin"], t["shirt_color"], t["shirt"]
    neck = _shade(skin, 0.88)
    if style == "hoodie":
        sw *= 1.08
    body = [(cx - sw, 152), (cx - sw, 128 + sl), (cx - sw * 0.7, 117 + sl * 0.4),
            (cx - nw * 1.4, nb - 1), (cx + nw * 1.4, nb - 1), (cx + sw * 0.7, 117 + sr * 0.4),
            (cx + sw, 128 + sr), (cx + sw, 152)]
    # neck first, so collars and shirt edges cover its base
    _poly(d, [(cx - nw, cy + hh * 0.6), (cx + nw, cy + hh * 0.6),
              (cx + nw * 1.15, nb + 4), (cx - nw * 1.15, nb + 4)], neck, outline=None)
    _line(d, [(cx - nw, cy + hh * 0.6), (cx - nw * 1.15, nb + 4)])
    _line(d, [(cx + nw, cy + hh * 0.6), (cx + nw * 1.15, nb + 4)])
    if style == "shirtless":
        _poly(d, body, skin)
        _line(d, [(cx, nb + 6), (cx, 150)], _shade(skin, 0.7), 0.8)
        for s in (-1, 1):
            _line(d, [(cx + s * 3, 134), (cx + s * 14, 137), (cx + s * 24, 132)], _shade(skin, 0.7), 0.9)
            _ell(d, cx + s * 17, 139, 1.2, 1.2, _shade(skin, 0.65), outline=None)
        _poly(d, [(cx - nw * 1.6, nb - 1), (cx - sw * 0.5, 120), (cx - nw * 0.9, nb + 5)], skin,
              outline=None)
        return
    base = _shade(shirt, 0.5) if style == "suit" else shirt
    if style == "tank":
        _poly(d, body, neck)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(_scaled([(cx - nw * 2.4, 152), (cx - nw * 2.4, 122), (cx - nw * 1.7, 112),
                                              (cx - nw * 1.3, 112), (cx - nw * 1.0, 126), (cx, 134),
                                              (cx + nw * 1.0, 126), (cx + nw * 1.3, 112), (cx + nw * 1.7, 112),
                                              (cx + nw * 2.4, 122), (cx + nw * 2.4, 152)]), fill=255)
    else:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(_scaled(body), fill=255)
    pat = Image.new("RGB", img.size, base)
    if t["shirt_pattern"] != "none" and style not in ("suit", "gi"):
        _shirt_pattern(ImageDraw.Draw(pat), t, t["shirt_pattern"], base)
    img.paste(pat, mask=mask)
    if style != "tank":
        _line(d, body[1:-1], OUTLINE, 1.0)
    if style == "jersey":
        _line(d, [(cx - sw * 0.98, 131 + sl), (cx - sw * 0.7, 119 + sl * 0.4)], (240, 240, 240), 2.2)
        _line(d, [(cx + sw * 0.98, 131 + sr), (cx + sw * 0.7, 119 + sr * 0.4)], (240, 240, 240), 2.2)
        _ell(d, cx, 140, 5, 5, (240, 240, 240), outline=None)
    if t["fat"] > 0.1:
        _ell(d, cx, cy + hh * 0.97, t["hw"] * 0.7, 6, _shade(skin, 0.78), outline=None)

    if style == "crew":
        _ell(d, cx, nb + 1, nw * 1.2, 8, neck)
        _line(d, [(cx - nw * 1.25, nb + 3), (cx, nb + 11), (cx + nw * 1.25, nb + 3)], _shade(shirt, 0.7), 2)
    elif style == "vneck":
        _poly(d, [(cx - nw * 1.2, nb), (cx + nw * 1.2, nb), (cx, nb + 21)], neck)
    elif style == "polo":
        _poly(d, [(cx - nw * 1.1, nb), (cx + nw * 1.1, nb), (cx, nb + 13)], neck)
        _poly(d, [(cx - nw * 1.3, nb - 1), (cx - 1, nb + 15), (cx - nw * 0.3, nb + 17), (cx - nw * 1.7, nb + 3)],
              _shade(shirt, 1.15))
        _poly(d, [(cx + nw * 1.3, nb - 1), (cx + 1, nb + 15), (cx + nw * 0.3, nb + 17), (cx + nw * 1.7, nb + 3)],
              _shade(shirt, 1.15))
    elif style == "suit":
        _poly(d, [(cx - nw * 1.2, nb), (cx + nw * 1.2, nb), (cx, nb + 33)], (235, 235, 230))
        _poly(d, [(cx - 3, nb + 8), (cx + 3, nb + 8), (cx + 4.5, nb + 31), (cx, 150), (cx - 4.5, nb + 31)],
              _mix(shirt, (150, 30, 30), 0.5))
        _line(d, [(cx - nw * 1.2, nb), (cx - 9, nb + 33)], _shade(shirt, 0.3), 1.2)
        _line(d, [(cx + nw * 1.2, nb), (cx + 9, nb + 33)], _shade(shirt, 0.3), 1.2)
    elif style == "hoodie":
        for s in (-1, 1):
            _poly(d, [(cx + s * nw * 1.5, nb - 4), (cx + s * nw * 2.5, nb + 6), (cx + s * nw * 1.7, nb + 16),
                      (cx + s * nw * 0.9, nb + 4)], _shade(shirt, 0.82))
        _ell(d, cx, nb + 2, nw * 1.1, 6, neck)
        for s in (-1, 1):
            _line(d, [(cx + s * 3, nb + 6), (cx + s * 3.5, nb + 22)], (235, 235, 230), 0.9)
    elif style == "turtleneck":
        _poly(d, [(cx - nw * 1.2, nb - 10), (cx + nw * 1.2, nb - 10), (cx + nw * 1.3, nb + 4),
                  (cx - nw * 1.3, nb + 4)], _shade(shirt, 1.1))
        for k in range(3):
            _line(d, [(cx - nw * 1.2, nb - 7 + k * 4), (cx + nw * 1.2, nb - 7 + k * 4)], _shade(shirt, 0.7), 0.7)
    elif style == "gi":
        _poly(d, [(cx - nw * 1.2, nb), (cx + nw * 1.2, nb), (cx + 2, 152), (cx - 2, 152)], neck)
        _poly(d, [(cx - nw * 1.3, nb - 1), (cx + 6, 152), (cx + 12, 152), (cx - nw * 0.4, nb - 1)],
              _shade(shirt, 1.15))
        _poly(d, [(cx + nw * 1.3, nb - 1), (cx - 6, 152), (cx - 12, 152), (cx + nw * 0.4, nb - 1)],
              _shade(shirt, 0.9))
        _line(d, [(cx - sw * 0.9, 146), (cx + sw * 0.9, 146)], (30, 30, 35), 3)
    elif style == "robe":
        _poly(d, [(cx - nw * 1.3, nb - 1), (cx, nb + 20), (cx + nw * 1.3, nb - 1), (cx + nw * 0.5, nb - 1),
                  (cx, nb + 8), (cx - nw * 0.5, nb - 1)], _shade(shirt, 1.25))
        _poly(d, [(cx - nw * 1.1, nb), (cx + nw * 1.1, nb), (cx, nb + 18)], neck)
        _line(d, [(cx - nw * 1.3, nb - 1), (cx + 3, 152)], _shade(shirt, 1.25), 2.5)
        _line(d, [(cx + nw * 1.3, nb - 1), (cx - 3, 152)], _shade(shirt, 1.25), 2.5)
    elif style == "sweater":
        _ell(d, cx, nb, nw * 1.35, 6, _shade(shirt, 1.12))
        for x in range(8, 150, 8):
            _line(d, [(x, 122 + abs(x - cx) * 0.08), (x, 152)], _shade(shirt, 0.82), 0.6)
    elif style == "tank":
        _line(d, [(cx - nw * 1.7, 112), (cx - nw * 1.0, 126), (cx, 134), (cx + nw * 1.0, 126),
                  (cx + nw * 1.7, 112)], OUTLINE, 1.0)


def _draw_ears(d, t):
    cx, hw, hh = t["cx"], t["hw"], t["hh"]
    y = t["cy"] + hh * (t["eye_y"] + 0.12 + t["ear_drop"])
    skin = _shade(t["skin"], 0.95)
    for s in (-1, 1):
        x = cx + s * (hw + t["ear_out"])
        k = t["ear_asym"] if s == 1 else 1.0
        ew, eh = t["ear_w"] * k, t["ear_h"] * k
        _ell(d, x, y, ew, eh, skin)
        if t["ear_pointy"]:
            _poly(d, [(x - s * ew * 0.5, y - eh * 0.4), (x + s * ew * 1.8, y - eh * 1.5),
                      (x + s * ew * 0.6, y + eh * 0.1)], skin)
        _line(d, [(x - s * 0.5, y - eh * 0.5), (x + s * ew * 0.2, y),
                  (x - s * 0.5, y + eh * 0.4)], _shade(skin, 0.7), 0.8)
        if t["earring"] and s == (1 if t["seed"] % 2 else -1):
            _ell(d, x, y + eh * 0.95, 1.8, 2.6, None, outline=(225, 190, 60), w=0.9)
        if t["cauliflower"] and s == 1:
            for dx, dy in ((0.5, -0.5), (0.8, 0.0), (0.4, 0.5)):
                _ell(d, x + dx * ew, y + dy * eh, 2.6, 2.6,
                     _mix(skin, (200, 90, 90), 0.4))


def _draw_head(d, t):
    pts, _, _, _ = _head_points(t)
    _poly(d, pts, t["skin"], w=1.1)
    if t["cleft"]:
        _, _, _, chin_y = _head_points(t)
        _line(d, [(t["cx"], chin_y - 5), (t["cx"], chin_y - 2)], _shade(t["skin"], 0.7), 0.8)


# ---------------------------------------------------------------- drawing: face
def _draw_cheeks(d, t):
    r = random.Random(t["detail_seed"])
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    if t["blush"]:
        pink = _mix(t["skin"], (225, 90, 90), 0.35)
        for s in (-1, 1):
            _ell(d, cx + s * hw * 0.55, cy + hh * 0.32, hw * 0.2, hh * 0.13, pink, outline=None)
    if t["black_eye"]:
        ex, ey, w, h = _eye_pos(t, t["black_eye"])
        _ell(d, ex, ey, w + 4, h + 4, _mix(t["skin"], (95, 50, 110), 0.65), outline=None)
    if t["bags"]:
        for s in (-1, 1):
            ex, ey, w, h = _eye_pos(t, s)
            _line(d, [(ex - w, ey + h + 1.5), (ex, ey + h + 3.5), (ex + w, ey + h + 1.5)],
                  _shade(t["skin"], 0.72), 0.9)
    if t["eyeshadow"]:
        for s in (-1, 1):
            ex, ey, w, h = _eye_pos(t, s)
            _ell(d, ex, ey - h * 0.6, w + 1.5, h + 2, (130, 100, 170), outline=None)


def _draw_eyes(d, t):
    skin = t["skin"]
    tilt = t["eye_tilt"]
    droop = max(t["droop"], 0.4 if t["eye_shape"] == "hooded" else 0)
    for s in (-1, 1):
        ex, ey, w, h = _eye_pos(t, s)

        def Y(dx):  # outer corner rises (+tilt) or falls (-tilt) relative to the inner corner
            return -tilt * 0.5 * (s * dx / w)

        outline = [(ex + w * math.cos(a * math.pi / 12), ey + h * math.sin(a * math.pi / 12) +
                    Y(w * math.cos(a * math.pi / 12))) for a in range(24)]
        _poly(d, outline, (245, 245, 240))
        rx = min(w * 0.55, h * 1.15)
        ry = h * 0.95
        gx = t["gaze"] * (-s if abs(t["gaze"]) > 1.2 else 1)
        gx = max(-(w - rx), min(w - rx, gx))
        px, py = ex + gx, ey + t["gaze_y"] * min(1, h / 3) + Y(gx)
        _ell(d, px, py, rx, ry, t["eye_color"], outline=None)
        _ell(d, px, py, rx * 0.45, ry * 0.5, (15, 10, 10), outline=None)
        if droop:
            cut = ey - h + 2 * h * droop
            _poly(d, [(ex - w - 0.5, ey - h - 1 + Y(-w)), (ex + w + 0.5, ey - h - 1 + Y(w)),
                      (ex + w + 0.5, cut + 0.3 + Y(w)), (ex, cut + 1.2), (ex - w - 0.5, cut + 0.3 + Y(-w))],
                  _shade(skin, 0.93), outline=None)
            _line(d, [(ex - w, cut + 0.3 + Y(-w)), (ex, cut + 1.2), (ex + w, cut + 0.3 + Y(w))], OUTLINE, 0.9)
        else:
            _line(d, [(ex - w, ey - h * 0.35 + Y(-w)), (ex, ey - h - 0.8), (ex + w, ey - h * 0.35 + Y(w))],
                  OUTLINE, 0.9)
        if t["gender"] == "female":
            for k in range(3):
                _line(d, [(ex + s * (w - 1 + k * 0.1), ey - h * 0.6 - k * 0.3 + Y(s * w)),
                          (ex + s * (w + 2.5), ey - h - 1.5 - k * 1.8 + Y(s * w))], OUTLINE, 0.7)
        if t["eyepatch"] == s:
            _line(d, [(ex - s * w * 2.6, ey - h * 3.3), (ex + s * w * 2.4, ey + h * 2.8)], (30, 30, 30), 0.9)
            _ell(d, ex, ey, w + 2.2, h + 2.4, (25, 25, 28), w=0.7)
            _line(d, [(ex - w * 0.4, ey - h * 0.4), (ex + w * 0.5, ey + h * 0.2)], (70, 70, 75), 0.7)


def _draw_brows(d, t):
    if t["brow"] == "none":
        return
    col = t["brow_color"]
    tilt = {"angry": 3.2, "sad": -3.2}.get(t["brow"], t["brow_tilt"] * 0.4)
    width = {"thick": t["brow_w"], "thin": 0.9, "unibrow": t["brow_w"], "bushy": 3.8,
             "arched": 1.4, "stubby": 2.4}.get(t["brow"], t["brow_w"])
    arch = 2.5 if t["brow"] == "arched" else 0.6
    inner = []
    for s in (-1, 1):
        ex, ey, w, h = _eye_pos(t, s)
        y = ey - h - t["brow_gap"] - (1.5 if t["brow"] == "arched" else 0) - (4 if t["brow"] == "high" else 0)
        xi, xo = ex - s * w * 0.9, ex + s * w * (0.7 if t["brow"] == "stubby" else 1.3)
        pts = [(xi, y + tilt), ((xi + xo) / 2, y - arch), (xo, y - tilt * 0.3 + 0.5)]
        _line(d, pts, col, width)
        inner.append((xi, y + tilt))
    if t["brow"] == "unibrow":
        _line(d, inner, col, width)


def _draw_nose(d, t):
    nx, ny = _nose_geom(t)
    bw, tw, th, bend, zig, nost = _nose_dims(t)
    ey = t["cy"] + t["hh"] * t["eye_y"]
    top = ey + 1
    tint = _mix(t["skin"], (215, 90, 90), 0.4 if t["red_nose"] else 0.1)
    tx = nx + bend
    mid_y = (top + ny) / 2
    pts = [(nx - bw, top), (nx + bw, top), (nx + bw * 1.2 + zig, mid_y), (tx + tw, ny),
           (tx + tw * 0.5, ny + th), (tx - tw * 0.5, ny + th), (tx - tw, ny),
           (nx - bw * 1.2 + zig, mid_y)]
    _poly(d, pts, tint, outline=None)
    shade = _shade(t["skin"], 0.7)
    _line(d, [(nx - bw * 1.2 + zig, mid_y), (nx - bw, top + 1)], shade, 0.7)
    _line(d, [(nx + bw * 1.2 + zig, mid_y), (nx + bw, top + 1)], shade, 0.7)
    _line(d, [(tx - tw, ny), (tx - tw * 0.5, ny + th), (tx + tw * 0.5, ny + th), (tx + tw, ny)], OUTLINE, 1.0)
    for s in (-1, 1):
        _ell(d, tx + s * tw * 0.42, ny + th * 0.55, nost, nost * 0.7, (60, 30, 30), outline=None)


def _draw_mouth(d, t):
    sd, openh, teeth, wf = MOUTHS[t["mouth"]]
    mx, my = _mouth_xy(t)
    mw = t["mouth_w"] * wf
    tilt = t["mouth_tilt"] * (1.3 if t["mouth"] == "smirk" else 1)
    us = [i / 10 for i in range(-10, 11)]
    top = [(mx + u * mw, my + sd * (1 - u * u) + tilt * u * 0.8) for u in us]
    bot = [(x, y + openh * (1 - u * u) ** 0.7) for (x, y), u in zip(top, us)]
    lip = t["lip"]
    lc = t["lip_color"]
    _poly(d, [(x, y + lip * (1 - u * u) ** 0.5 + 0.5) for (x, y), u in zip(bot, us)] +
          bot[::-1], lc, outline=None)
    _poly(d, top + [(x, y - lip * 0.6 * (1 - u * u) ** 0.5) for (x, y), u in zip(top[::-1], us[::-1])],
          _shade(lc, 0.9), outline=None)
    if openh > 0.5:
        _poly(d, top + bot[::-1], (70, 20, 28), outline=None)
        if t["mouth"] in ("open", "toothless"):
            _ell(d, mx, my + sd + openh * 0.75, mw * 0.4, 2.2, (200, 90, 100), outline=None)
        if t["mouth"] == "tongue":
            ty = my + sd + openh
            _poly(d, [(mx - mw * 0.35, my + sd + 1), (mx + mw * 0.35, my + sd + 1),
                      (mx + mw * 0.32, ty + 4), (mx, ty + 7), (mx - mw * 0.32, ty + 4)], (214, 98, 112))
            _line(d, [(mx, my + sd + 3), (mx, ty + 5)], (160, 60, 80), 0.7)
        if teeth:
            tc = t["tooth_color"]
            n = 6
            tw = (mw * 1.5) / n
            for i in range(n):
                if i in t["missing"]:
                    continue
                u = -0.75 + i * 1.5 / (n - 1)
                x = mx + u * mw + t["tooth_jitter"][i] * 0.8
                yt = my + sd * (1 - u * u) + tilt * u * 0.8 + t["tooth_jitter"][(i + 3) % 6] * 0.5
                if t["mouth"] == "lopsided":
                    yt += u * 1.5
                ho = openh * (1 - u * u) ** 0.7
                if t["mouth"] == "buck" and i in (2, 3):
                    _poly(d, [(x - tw * 0.55, yt), (x + tw * 0.55, yt), (x + tw * 0.55, yt + ho + 4),
                              (x - tw * 0.55, yt + ho + 4)], tc, w=0.6)
                else:
                    _poly(d, [(x - tw / 2, yt), (x + tw / 2, yt), (x + tw / 2, yt + min(ho, 3.2)),
                              (x - tw / 2, yt + min(ho, 3.2))], tc, w=0.4)
                    if ho > 4.5 and i not in t["missing"]:
                        _poly(d, [(x - tw / 2, yt + ho - 2.6), (x + tw / 2, yt + ho - 2.6),
                                  (x + tw / 2, yt + ho), (x - tw / 2, yt + ho)], tc, w=0.4)
    _line(d, top, OUTLINE, 1.0)
    if openh > 0.5:
        _line(d, bot, OUTLINE, 0.9)
    else:
        _line(d, [(x, y + 1.2) for x, y in top], _shade(lc, 0.6), 0.9)


def _draw_facial_hair(d, t):
    """Beard, stubble and sideburns; runs before eyes/mouth so features stay visible."""
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    col = t["facial_color"]
    _, right, left, chin_y = _head_points(t)
    _, my = _mouth_xy(t)
    if t["sideburn"]:
        n = t["sideburn"]
        ey = cy + hh * (t["eye_y"] + 0.05)
        for s in (-1, 1):
            x0 = cx + s * hw
            _poly(d, [(x0, ey - 6), (x0 - s * 4, ey - 6), (x0 - s * 3, ey + n), (x0, ey + n + 2)],
                  col, outline=None)
    if t["stubble"]:
        r = random.Random(t["detail_seed"] + 1)
        sc = _mix(col, t["skin"], 0.45)
        for _ in range(260):
            x = cx + r.uniform(-hw, hw)
            y = r.uniform(cy + hh * 0.1, cy + hh)
            if _inside_face(t, x, y, 0.82) or (y > cy + hh * 0.55 and _inside_face(t, x, y, 0.95)):
                _ell(d, x, y, 0.45, 0.45, sc, outline=None)
    style = t["beard"]
    if style == "none":
        return
    prof_r, prof_l = [(x + 1, y + 1) for x, y in right], [(x - 1, y + 1) for x, y in left]
    chin = (cx, chin_y + 2)
    if style == "full":
        pts = [(cx - hw * 0.98, cy + hh * 0.05)] + prof_l + [chin] + prof_r[::-1] + \
              [(cx + hw * 0.98, cy + hh * 0.05), (cx + hw * 0.7, my - 3), (cx + hw * 0.3, my - 5),
               (cx, my - 4), (cx - hw * 0.3, my - 5), (cx - hw * 0.7, my - 3)]
        _poly(d, pts, col, w=0.6)
    elif style == "goatee":
        _poly(d, [(cx - hw * 0.4, my - 3), (cx + hw * 0.4, my - 3), (cx + hw * 0.3, chin_y - 2),
                  chin, (cx - hw * 0.3, chin_y - 2)], col, w=0.6)
    elif style == "chinstrap":
        pts = [(cx - hw * 0.98, cy + hh * 0.1)] + prof_l + [chin] + prof_r[::-1] + \
              [(cx + hw * 0.98, cy + hh * 0.1), (cx + hw * 0.88, cy + hh * 0.1)] + \
              [(x * 0.9 + cx * 0.1, y - 4) for x, y in prof_r] + [(cx, chin_y - 4)] + \
              [(x * 0.9 + cx * 0.1, y - 4) for x, y in prof_l[::-1]] + [(cx - hw * 0.88, cy + hh * 0.1)]
        _poly(d, pts, col, w=0.5)
    elif style == "soul patch":
        _poly(d, [(cx - 3, my + 4), (cx + 3, my + 4), (cx + 2, my + 9), (cx - 2, my + 9)], col, w=0.5)
    elif style == "long":
        pts = [(cx - hw * 0.98, cy + hh * 0.05)] + prof_l + [(cx - 3, chin_y + 14), (cx, chin_y + 19),
                                                           (cx + 3, chin_y + 14)] + prof_r[::-1] + \
              [(cx + hw * 0.98, cy + hh * 0.05), (cx + hw * 0.7, my - 3), (cx, my - 4), (cx - hw * 0.7, my - 3)]
        _poly(d, pts, col, w=0.6)
    elif style == "patchy":
        rp = random.Random(t["detail_seed"] + 5)
        for _ in range(26):
            x = cx + rp.uniform(-hw * 0.85, hw * 0.85)
            y = rp.uniform(cy + hh * 0.3, chin_y)
            if _inside_face(t, x, y, 1.0) and y > cy + hh * 0.3:
                _ell(d, x, y, rp.uniform(1.4, 2.8), rp.uniform(1.2, 2.2), col, outline=None)
    elif style == "neckbeard":
        _poly(d, [(cx - hw * 0.7, chin_y - 3), (cx + hw * 0.7, chin_y - 3), (cx + hw * 0.6, chin_y + 11),
                  (cx, chin_y + 14), (cx - hw * 0.6, chin_y + 11)], col, w=0.5)
    elif style == "vandyke":
        _poly(d, [(cx - hw * 0.3, my - 3), (cx + hw * 0.3, my - 3), (cx + hw * 0.22, chin_y - 3),
                  (cx + 2, chin_y + 11), (cx - 2, chin_y + 11), (cx - hw * 0.22, chin_y - 3)], col, w=0.6)
    elif style == "mutton":
        for s in (-1, 1):
            _poly(d, [(cx + s * hw * 0.99, cy - hh * 0.05), (cx + s * hw * 0.55, my - 4),
                      (cx + s * hw * 0.5, my + 3), (cx + s * hw * 0.85, cy + hh * 0.62),
                      (cx + s * hw * 0.99, cy + hh * 0.35)], col, w=0.6)


def _draw_mustache(d, t):
    style = t["mustache"]
    if style == "none":
        return
    nx, ny = _nose_geom(t)
    mx, my = _mouth_xy(t)
    col = t["facial_color"]
    y0 = min(ny + _nose_dims(t)[2] + 1, my - 3)
    w = t["mouth_w"] * 1.1
    if style == "chevron":
        pts = [(mx - w, y0 + 3), (mx - w * 0.4, y0), (mx, y0 + 1), (mx + w * 0.4, y0),
               (mx + w, y0 + 3), (mx + w * 0.5, y0 + 5), (mx, y0 + 4), (mx - w * 0.5, y0 + 5)]
    elif style == "handlebar":
        pts = [(mx - w * 1.2, y0 - 2), (mx - w * 0.9, y0 + 3), (mx - w * 0.3, y0 + 1), (mx, y0 + 2),
               (mx + w * 0.3, y0 + 1), (mx + w * 0.9, y0 + 3), (mx + w * 1.2, y0 - 2),
               (mx + w * 0.8, y0 + 5), (mx, y0 + 5), (mx - w * 0.8, y0 + 5)]
    elif style == "pencil":
        pts = [(mx - w, y0 + 2), (mx + w, y0 + 2), (mx + w, y0 + 3.2), (mx - w, y0 + 3.2)]
    elif style == "toothbrush":
        pts = [(mx - w * 0.35, y0), (mx + w * 0.35, y0), (mx + w * 0.35, y0 + 5), (mx - w * 0.35, y0 + 5)]
    else:  # walrus
        pts = [(mx - w * 1.1, y0 + 8), (mx - w * 0.8, y0), (mx, y0 + 1), (mx + w * 0.8, y0),
               (mx + w * 1.1, y0 + 8), (mx + w * 0.5, y0 + 6), (mx, y0 + 7), (mx - w * 0.5, y0 + 6)]
    _poly(d, pts, col, w=0.5)


def _draw_details(d, t):
    r = random.Random(t["detail_seed"])
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    skin = t["skin"]
    wr = _shade(skin, 0.72)
    nx, ny = _nose_geom(t)
    mx, my = _mouth_xy(t)
    if t["blotch"]:
        for _ in range(2):
            x, y = cx + r.uniform(-hw * .6, hw * .6), cy + r.uniform(-hh * .2, hh * .6)
            _ell(d, x, y, r.uniform(4, 8), r.uniform(3, 6), _mix(skin, (210, 90, 90), 0.3), outline=None)
    if t["birthmark"]:
        s = r.choice([-1, 1])
        bx, by = cx + s * hw * 0.55, cy - hh * 0.35
        _poly(d, [(bx - 5, by), (bx - 2, by - 4), (bx + 3, by - 3), (bx + 5, by + 2), (bx, by + 5)],
              _mix(skin, (130, 60, 70), 0.55), outline=None)
    for i in range(min(t["wrinkles"], 5)):
        y = cy - hh * (0.66 - i * 0.07)
        x0 = r.uniform(0.25, 0.55) * hw
        _line(d, [(cx - x0, y), (cx - x0 * 0.3, y - 1 + r.uniform(-.8, .8)),
                  (cx + x0 * 0.3, y + r.uniform(-.8, .8)), (cx + x0, y - 0.5)], wr, 0.7)
    if t["wrinkles"] >= 2:
        for s in (-1, 1):
            ex, ey, w, h = _eye_pos(t, s)
            for k in (-2, 0, 2):
                _line(d, [(ex + s * (w + 1.5), ey + k * 0.8), (ex + s * (w + 5), ey + k * 2.2)], wr, 0.6)
    if t["wrinkles"] >= 3:
        for s in (-1, 1):
            _line(d, [(cx + s * hw * 0.3, my + 6), (cx + s * hw * 0.42, my + 9)], wr, 0.7)
    if t["wrinkles"] >= 1 and t["mouth"] not in ("open",):
        for s in (-1, 1):
            _line(d, [(nx + s * 5, ny + 2), (mx + s * (t["mouth_w"] + 2.5), my - 1)], wr, 0.7)
    if t["spots"]:
        sp = _mix(skin, (130, 85, 50), 0.5)
        for _ in range(t["spots"]):
            x, y = cx + r.uniform(-hw * .8, hw * .8), cy + r.uniform(-hh * .85, hh * .3)
            if _inside_face(t, x, y, 0.75):
                _ell(d, x, y, r.uniform(1, 2), r.uniform(0.8, 1.6), sp, outline=None)
    if t["freckles"]:
        fc = _mix(skin, (140, 70, 30), 0.55)
        for _ in range(t["freckles"]):
            x = cx + r.uniform(-hw * 0.7, hw * 0.7)
            y = ny + r.uniform(-8, 5)
            if abs(x - nx) > 3 or r.random() < 0.4:
                _ell(d, x, y, 0.7, 0.7, fc, outline=None)
    for _ in range(t["pimples"]):
        x, y = cx + r.uniform(-hw * .75, hw * .75), cy + r.uniform(-hh * .6, hh * .75)
        if _inside_face(t, x, y, 0.7) and abs(x - nx) > 4:
            _ell(d, x, y, 1.6, 1.6, (205, 90, 90), outline=None)
            _ell(d, x, y, 0.6, 0.6, (250, 235, 220), outline=None)
    if t["mole"]:
        s = r.choice([-1, 1])
        _ell(d, cx + s * hw * r.uniform(.3, .6), my + r.uniform(-4, 2), 1.5, 1.5, (50, 30, 25), outline=None)
    if t["wart"]:
        wx, wy = nx + r.choice([-1, 1]) * (_nose_dims(t)[1] + 3), ny - 1
        _ell(d, wx, wy, 2.2, 2.2, _mix(skin, (170, 110, 90), 0.5))
        _ell(d, wx - 0.5, wy - 0.5, 0.7, 0.7, _shade(skin, 1.1), outline=None)
    for scar in (t["scar"], t["scar2"]):
        if scar == "none":
            continue
        s = r.choice([-1, 1])
        ex, ey, w, h = _eye_pos(t, s)
        a, b = {"brow": ((ex - s * 2, ey - h - 9), (ex + s * 4, ey - h + 3)),
                "cheek": ((cx + s * hw * .3, ny + 1), (cx + s * hw * .75, ny + 11)),
                "chin": ((cx - 5, cy + hh * .82), (cx + 7, cy + hh * .74)),
                "lip": ((mx + s * (t["mouth_w"] - 3), my - 7), (mx + s * (t["mouth_w"] + 1), my + 6)),
                "forehead": ((cx + s * hw * .1, cy - hh * .75), (cx + s * hw * .5, cy - hh * .5)),
                "nose": ((nx - 4, ey + 1), (nx + 5, ny + 2)),
                "double": ((cx + s * hw * .35, ny - 2), (cx + s * hw * .75, ny + 9)),
                "long_cheek": ((cx + s * hw * .85, ey - 3), (cx + s * hw * .3, my + 3)),
                "eye": ((ex + s * 1, ey - h - 7), (ex - s * 2, ey + h + 8))}[scar]
        sc = _mix(skin, (230, 140, 140), 0.7)
        _line(d, [a, b], _shade(skin, 0.6), 2.2)
        _line(d, [a, b], sc, 1.2)
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        for k in range(1, 4):
            px, py = a[0] + dx * k / 4, a[1] + dy * k / 4
            _line(d, [(px - dy / ln * 2.2, py + dx / ln * 2.2), (px + dy / ln * 2.2, py - dx / ln * 2.2)],
                  _shade(skin, 0.6), 0.6)
    if t["bandage"]:
        bx, by = cx + r.choice([-1, 1]) * hw * 0.45, cy + hh * 0.2
        _poly(d, [(bx - 6, by - 2.5), (bx + 4, by - 5), (bx + 6, by + 2), (bx - 4, by + 4.5)], (235, 215, 180))
        _line(d, [(bx - 1, by - 3.5), (bx + 1.5, by + 3.5)], (205, 180, 145), 0.8)
    if t["glasses"] != "none":
        _draw_glasses(d, t)


def _draw_glasses(d, t):
    kind = t["glasses"]
    fr = (30, 30, 35) if kind in ("shades", "square") else (120, 85, 40)
    ex = [_eye_pos(t, s) for s in (-1, 1)]
    for s, (x, y, w, h) in zip((-1, 1), ex):
        rw, rh = {"round": (w + 3.5, h + 3.5), "square": (w + 3, h + 3), "shades": (w + 3.5, h + 3),
                  "tiny": (w + 1.5, h + 1.5)}[kind]
        rh = max(rh, 4.5)
        if kind == "shades":
            _poly(d, [(x - rw, y - rh), (x + rw, y - rh), (x + rw * 0.9, y + rh), (x - rw * 0.9, y + rh)],
                  (25, 25, 30), w=0.9)
            _line(d, [(x - rw * 0.5, y - rh * 0.6), (x - rw * 0.1, y - rh * 0.6)], (110, 110, 120), 0.8)
        elif kind == "square":
            _poly(d, [(x - rw, y - rh), (x + rw, y - rh), (x + rw, y + rh), (x - rw, y + rh)], None, outline=fr, w=1.1)
        else:
            _ell(d, x, y, rw, rh, None, outline=fr, w=1.1)
        _line(d, [(x + s * rw, y - rh * 0.2), (x + s * (rw + 6), y - rh * 0.4)], fr, 0.9)
    _line(d, [(ex[0][0] + ex[0][2] + 3.5, ex[0][1] - 1), (ex[1][0] - ex[1][2] - 3.5, ex[1][1] - 1)], fr, 1.0)


# ---------------------------------------------------------------- drawing: hair front
def _top_arc(t, extra, step=10):
    n, tp = t["head_n"], t["taper"]
    k = 2.0 / n
    pts = []
    for a in range(175, 4, -step):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        pts.append((t["cx"] + math.copysign(abs(c) ** k, c) * (t["hw"] + extra) * (1 - tp * s),
                    t["cy"] - (t["hh"] * 0.95 + extra) * (abs(s) ** k)))
    return pts


def _hairline(t):
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    if t["fringe"]:
        right = [(cx + hw * 0.97, cy - hh * 0.12)]
        for i in range(7):
            y = 0.38 if i % 2 == 0 else 0.47
            right.append((cx + hw * 0.92 * (1 - 2 * i / 6), cy - hh * y))
        return right + [(cx - hw * 0.97, cy - hh * 0.12)]
    ft, fm, fc = t["hairline"]
    sk = t["hl_skew"]
    c_y = cy - hh * fc + hh * t["peak"] * 0.35
    right = [(cx + hw * 0.97, cy - hh * 0.12), (cx + hw * 0.88, cy - hh * ft),
             (cx + hw * 0.5, cy - hh * fm * (1 + sk)), (cx, c_y)]
    left = [(cx - hw * 0.5, cy - hh * fm * (1 - sk)), (cx - hw * 0.88, cy - hh * ft),
            (cx - hw * 0.97, cy - hh * 0.12)]
    return right + left


def _draw_hair_front(d, t):
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    style, col = t["hair"], t["hair_color"]
    th = CAP_THICKNESS[style]
    r = random.Random(t["detail_seed"] + 7)
    ey = cy + hh * t["eye_y"]
    top = cy - hh * 0.95

    def arc(extra, step=10):
        return _top_arc(t, extra, step)

    def cap(thick, fill=col):
        _poly(d, arc(thick) + _hairline(t), fill, w=0.8)

    if style == "bald":
        if r.random() < 0.6:
            for s in (-1, 1):
                _poly(d, [(cx + s * hw * 0.99, ey - 8), (cx + s * (hw + 3), ey - 4),
                          (cx + s * (hw + 3), ey + 6), (cx + s * hw * 0.98, ey + 8)], col, outline=None)
        _accessory_band(d, t)
        return
    if style == "wisps":
        for k in range(5):
            x0 = cx + (k - 2) * hw * 0.3
            _line(d, [(x0, top + 3), (x0 + r.uniform(-6, 6), top - 6 + r.uniform(-3, 3)),
                      (x0 + r.uniform(-10, 10), top + 2 + r.uniform(0, 4))], col, 0.9)
        for s in (-1, 1):
            _poly(d, [(cx + s * hw * 0.99, ey - 8), (cx + s * (hw + 2), ey - 3),
                      (cx + s * (hw + 2), ey + 6), (cx + s * hw * 0.98, ey + 8)], col, outline=None)
        _accessory_band(d, t)
        return
    if style == "horseshoe":
        for s in (-1, 1):
            _poly(d, [(cx + s * hw * 0.97, cy - hh * 0.35), (cx + s * (hw + 5), cy - hh * 0.05),
                      (cx + s * (hw + 3), cy + hh * 0.3), (cx + s * hw * 0.88, cy + hh * 0.15),
                      (cx + s * hw * 0.95, cy - hh * 0.1)], col, w=0.8)
        _poly(d, [(cx - hw * 0.92, cy - hh * 0.2), (cx + hw * 0.92, cy - hh * 0.2),
                  (cx + hw * 0.6, cy - hh * 0.1), (cx - hw * 0.6, cy - hh * 0.1)], col, outline=None)
        _line(d, [(cx - hw * 0.5, cy - hh * 0.62), (cx - hw * 0.2, cy - hh * 0.8), (cx + hw * 0.2, cy - hh * 0.78)],
              _shade(col, 0.8), 1.2)
        _accessory_band(d, t)
        return
    if style == "mohawk":
        base = cy - hh * 0.85
        _poly(d, [(cx - 6, base + 2), (cx - 5, top - 9), (cx - 2, top - 15), (cx + 1, top - 8),
                  (cx + 4, top - 14), (cx + 6, top - 6), (cx + 6, base + 2)], col, w=0.8)
        _accessory_band(d, t)
        return
    if style == "afro":
        cap(th)
        _accessory_band(d, t)
        return
    cap(th, _mix(col, t["skin"], 0.35) if style == "buzz" else col)
    if style == "sidepart":
        _line(d, [(cx - hw * 0.55, cy - hh * 0.62), (cx - hw * 0.3, cy - hh * 0.92)], _shade(col, 0.6), 1.0)
    elif style == "combover":
        for k in range(5):
            y = cy - hh * (0.62 + k * 0.07)
            _line(d, [(cx - hw * 0.9, y + 2), (cx + hw * 0.4, y - 2)], _shade(col, 1.25), 0.7)
    elif style == "spiky":
        for a in range(165, 15, -15):
            x0 = cx + (hw + 2) * math.cos(math.radians(a))
            y0 = cy - (hh * 0.95 + 2) * math.sin(math.radians(a))
            ang = math.radians(a + r.uniform(-8, 8))
            tip = (x0 + 9 * math.cos(ang), y0 - 10 * math.sin(ang))
            _poly(d, [(x0 - 3, y0 + 2), tip, (x0 + 3, y0 + 2)], col, w=0.8)
    elif style == "messy":
        for a in range(165, 15, -20):
            x0 = cx + (hw + 2) * math.cos(math.radians(a))
            y0 = cy - (hh * 0.95 + 2) * math.sin(math.radians(a))
            ang = math.radians(a + r.uniform(-50, 50))
            L = r.uniform(5, 12)
            _line(d, [(x0, y0 + 1), (x0 + L * math.cos(ang), y0 - L * math.sin(ang))], col, 2.2)
    elif style == "curly":
        for a in range(170, 9, -14):
            x0 = cx + (hw + 5) * math.cos(math.radians(a))
            y0 = cy - (hh * 0.95 + 5) * math.sin(math.radians(a))
            _ell(d, x0, y0, 4.5, 4.5, col, w=0.8)
    elif style == "afropuffs":
        for s in (-1, 1):
            _ell(d, cx + s * hw * 0.72, top - 3, 9, 8.5, col, w=0.8)
    elif style == "bun":
        _ell(d, cx, top - 5, 9, 8, col, w=0.8)
    elif style == "topknot":
        _ell(d, cx, top - 6, 6, 6.5, col, w=0.8)
        _line(d, [(cx - 6, top - 5), (cx + 6, top - 5)], _shade(col, 0.6), 0.9)
    elif style == "flattop":
        _poly(d, [(cx - hw * 0.88, cy - hh * 0.62), (cx - hw * 0.84, top - 5), (cx + hw * 0.84, top - 5),
                  (cx + hw * 0.88, cy - hh * 0.62)], col, w=0.8)
    elif style == "pompadour":
        _poly(d, [(cx - hw * 0.85, cy - hh * 0.6), (cx - hw * 0.8, top - 5), (cx - hw * 0.3, top - 12),
                  (cx + hw * 0.5, top - 10), (cx + hw * 0.9, cy - hh * 0.6)], col, w=0.8)
        for k in range(4):
            _line(d, [(cx - hw * 0.6 + k * hw * 0.35, cy - hh * 0.65), (cx - hw * 0.5 + k * hw * 0.3, top - 6)],
                  _shade(col, 1.25), 0.7)
    elif style == "slicked":
        for k in range(5):
            _line(d, [(cx - hw * 0.8, cy - hh * (0.55 + k * 0.1)), (cx + hw * 0.1, cy - hh * (0.7 + k * 0.09)),
                      (cx + hw * 0.7, cy - hh * (0.45 + k * 0.08))], _shade(col, 1.3), 0.6)
    elif style == "bowl":
        _poly(d, [(cx - hw * 1.02, cy - hh * 0.15), (cx - hw * 0.9, cy - hh * 0.42), (cx + hw * 0.9, cy - hh * 0.42),
                  (cx + hw * 1.02, cy - hh * 0.15), (cx + hw * 1.0, cy - hh * 0.5), (cx + hw * 0.5, top - 3),
                  (cx - hw * 0.5, top - 3), (cx - hw * 1.0, cy - hh * 0.5)], col, w=0.8)
    elif style == "cornrows":
        for k in range(-3, 4):
            _line(d, [(cx + k * hw * 0.2, cy - hh * 0.55 + abs(k) * 2),
                      (cx + k * hw * 0.27, top + 2)], _shade(col, 1.6), 0.7)
    elif style == "dreads":
        for k in range(-4, 5):
            _line(d, [(cx + k * hw * 0.2, cy - hh * 0.6 + abs(k) * 1.2),
                      (cx + k * hw * 0.28, top + 1)], _shade(col, 1.4), 0.9)
    elif style == "sideswept":
        _poly(d, [(cx - hw * 0.95, cy - hh * 0.3), (cx - hw * 0.2, cy - hh * 0.62), (cx + hw * 0.7, cy - hh * 0.5),
                  (cx + hw * 0.95, cy - hh * 0.2), (cx + hw * 0.8, cy - hh * 0.7), (cx - hw * 0.5, cy - hh * 0.75)],
              col, w=0.8)
    elif style in ("long", "bob", "pigtails", "wavy", "shaggy", "braid"):
        bottom = {"long": 128, "bob": cy + hh * 0.7, "pigtails": cy + hh * 0.3, "wavy": 122, "shaggy": 118,
                  "braid": cy + hh * 0.5}[style]
        if style != "pigtails":
            for s in (-1, 1):
                _poly(d, [(cx + s * hw * 0.98, cy - hh * 0.3), (cx + s * (hw + th + 2), cy + hh * 0.1),
                          (cx + s * (hw + th), bottom), (cx + s * hw * 0.8, bottom - 6),
                          (cx + s * hw * 0.8, cy)], col, w=0.8)
        else:
            for s in (-1, 1):
                _ell(d, cx + s * (hw + 4), cy + hh * 0.05, 2.5, 3, (200, 50, 80), w=0.6)
        if style == "braid":
            for k in range(5):
                _ell(d, cx + hw * 0.5, cy + hh * 0.5 + k * 6 - 20, 3.4, 3.6, col, w=0.6)
    elif style == "ponytail":
        _ell(d, cx + hw * 0.8, cy - hh * 0.55, 2.5, 3, (200, 50, 80), w=0.6)
    elif style == "pixie":
        _poly(d, [(cx - hw * 0.9, cy - hh * 0.5), (cx - hw * 0.1, cy - hh * 0.45),
                  (cx + hw * 0.8, cy - hh * 0.6), (cx + hw * 0.6, cy - hh * 0.35)], col, outline=None)
    _accessory_band(d, t)


def _accessory_band(d, t):
    if not t["headband"]:
        return
    cx, cy, hw, hh = t["cx"], t["cy"], t["hw"], t["hh"]
    y = cy - hh * 0.5
    c = _mix(t["shirt_color"], (255, 255, 255), 0.2)
    _poly(d, [(cx - hw * 0.97, y + 1), (cx - hw * 0.5, y - 3), (cx + hw * 0.5, y - 3), (cx + hw * 0.97, y + 1),
              (cx + hw * 0.97, y + 5), (cx + hw * 0.5, y + 1), (cx - hw * 0.5, y + 1), (cx - hw * 0.97, y + 5)], c, w=0.7)


# ---------------------------------------------------------------- public API
def _background(t):
    size = SIZE * SCALE
    c1, c2, style = t["bg"], t["bg2"], t["bg_style"]
    img = Image.new("RGB", (size, size), c1)
    if style == "gradient":
        m = Image.linear_gradient("L").resize((size, size))
        img = Image.composite(Image.new("RGB", (size, size), c2), img, m)
    elif style == "vignette":
        m = Image.radial_gradient("L").resize((size, size))
        img = Image.composite(Image.new("RGB", (size, size), _shade(c1, 0.6)), img, m)
    elif style == "split":
        ImageDraw.Draw(img).polygon([(size * 0.55, 0), (size, 0), (size, size), (size * 0.3, size)], fill=c2)
    return img


def _layer(t):
    return Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), t["bg"] + (0,))


def _rot(layer, t):
    return layer.rotate(t["tilt"], resample=Image.BICUBIC,
                        center=(t["cx"] * SCALE, 112 * SCALE), fillcolor=t["bg"] + (0,))


def draw_portrait(t):
    img = _background(t).convert("RGBA")
    back = _layer(t)
    _draw_hair_back(ImageDraw.Draw(back), t)
    img.alpha_composite(_rot(back, t))
    img = img.convert("RGB")
    _draw_body(img, ImageDraw.Draw(img), t)
    face = _layer(t)
    d = ImageDraw.Draw(face)
    _draw_ears(d, t)
    _draw_head(d, t)
    _draw_cheeks(d, t)
    _draw_facial_hair(d, t)
    _draw_eyes(d, t)
    _draw_brows(d, t)
    _draw_nose(d, t)
    _draw_mouth(d, t)
    _draw_mustache(d, t)
    _draw_details(d, t)
    _draw_hair_front(d, t)
    img = img.convert("RGBA")
    img.alpha_composite(_rot(face, t))
    img = img.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    style = t.get("style")
    if style == "crude":  # chunky low-res, limited-palette look
        img = img.resize((SIZE // 2, SIZE // 2), Image.BOX).quantize(colors=24).convert("RGB")
        img = img.resize((SIZE, SIZE), Image.NEAREST)
    elif style == "cartoon":
        img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.4)).enhance(1.1)
    return img


def generate_portrait(portrait_id, master_seed=0, gender=None, category=None, style="gross"):
    """Return a 150x150 RGB portrait; identical inputs always give identical output."""
    return draw_portrait(build_traits(derive_seed(master_seed, portrait_id), gender, category, style))


def save_portrait(image, path, quality=90, exclusive=False):
    """Save as PNG or JPEG depending on the file extension.

    exclusive=True never overwrites: raises FileExistsError if the file exists, and removes
    the partial file if writing fails.
    """
    png = os.path.splitext(path)[1].lower() == ".png"
    f = open(path, "xb" if exclusive else "wb")  # FileExistsError propagates untouched
    try:
        with f:
            if png:
                image.save(f, "PNG")
            else:
                image.save(f, "JPEG", quality=quality)
    except Exception:
        if exclusive:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
