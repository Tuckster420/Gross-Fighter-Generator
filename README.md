# Gross Fighter Generator

Generates ugly, goofy, crude fictional 150 × 150 fighter portraits for boxing and MMA games.
Everything is drawn procedurally with Pillow (no external images, no online services).
The Pygame menu lets you pick how many portraits to make and what they look like.

## Install (Windows)

1. Install Python 3.9 or newer from <https://www.python.org/downloads/> (tick **Add python.exe to PATH**).
2. Double-click **`run.bat`**. On first run it installs the two dependencies
   (`Pillow`, `pygame`) and then opens the menu.

Manual install, from a Command Prompt in this folder:

```
python -m pip install -r requirements.txt
python main.py
```

## Using the menu

| Setting | Options |
|---|---|
| Number of portraits | 1 or more (default 100). Type it, or use the +/- buttons (steps of 10). |
| Gender | Male, Female, Random |
| Appearance category | White, Black, Asian, Latino, Mixed, Random |
| Art style | Gross and Goofy, Crude Game Art, Exaggerated Cartoon |
| Image format | JPG (default, quality 90) or PNG |
| Seed | Master random seed. The same settings and seed always give the same portraits. |
| Output folder | Type a path or press **Browse**. |

Buttons:

- **Generate** – creates the batch. A progress bar shows the percentage, saved count and failure count.
  The window stays responsive, and **Cancel** stops the batch safely after the current image.
- **Preview** – shows sample portraits with the current settings without saving anything.
- **Exit** – closes the program.

Settings with a problem (for example a bad count or an unusable folder) are highlighted and
Generate refuses to start until they are fixed.

Batches of any size work; 1,500 portraits take roughly a minute.

## Where files are saved

Default folder: **`output\`** inside the project folder (or whatever you choose in the menu).

- **Portraits**: `<category>_<gender>_<n>.<jpg|png>`, numbered from 0 within each name,
  e.g. `white_male_0.jpg`, `white_male_1.jpg`, `black_female_0.png`.
  Every image is exactly 150 × 150 pixels.
- **`metadata.csv`**: one row per portrait attempt with filename, portrait ID, gender, category, art style,
  random seeds, image format, width, height and status (`success`, `failed`, `skipped`, or `missing`
  if a file was later deleted). New batches are appended; history is never removed.
- **`batches.csv`**: one row when each batch starts and one when it ends, recording the
  settings used (count, gender/category/style settings, format, seed) and the final counts.
- **`.gfg_batch_*.jsonl`** (hidden): a progress log used for resuming. It is deleted when a batch finishes.

## Existing files are never overwritten

Files are created in exclusive mode. If `white_male_0.jpg` already exists, new portraits continue
with the next free number. Running Generate twice into the same folder adds more images.

## Cancelling and resuming

- Press **Cancel** during a run. Already-saved portraits stay in place.
- Press **Generate** again with the **same settings and seed** (including the same folder) and
  choose **Resume**: only the missing portraits are created, and the result is identical to an
  uninterrupted run. Choose **Start new batch** to ignore the old progress instead.
- The same applies after a crash or a closed window.
- If images fail (for example the disk is full), the failures are counted and recorded and the batch
  continues. After 25 failures in a row it stops with an error message. Resuming retries only the failed ones.

If `metadata.csv` is open in Excel (locked), rows are held in memory and written as soon as the file is free.

## Command-line sample generator

```
python main.py --cli                 # 30 samples (sample_0..29.jpg) in output\, plus preview.jpg
python main.py --cli --count 12 --gender female --seed 7 --out my_samples --overwrite
```

## Tests

Headless tests (no window appears) are in `tests\`. Double-click **`run_tests.bat`** or run:

```
python tests\test_matrix.py   # menu launch + every gender/category/style/format combination
python tests\test_bulk.py     # 100-image batch, 1,500-image batch, cancel/resume, errors, no-overwrite
python tests\test_meta.py     # CSV metadata consistency, appending, resume, torn writes
```

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point (GUI, or `--cli`) |
| `gui.py` | Pygame menu and the bulk-generation worker |
| `portrait_generator.py` | Procedural portrait drawing and randomization |
| `metadata.py` | CSV metadata handling |
| `run.bat` / `run_tests.bat` | Windows launchers |
| `diversity_test/` | 100-portrait sample collection and contact sheet |
