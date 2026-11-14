"""apply_updates.py - small edits to existing files (run once):  python3 apply_updates.py

1. terrain.load_dem applies a file's scale/offset (needed for the packed DEMs
   in data/packed/, which store centimetres; raw NASA files are unaffected).
2. main.py uses data/packed/ when data/raw/ has no DEMs (GitHub / Streamlit Cloud).
3. requirements.txt gets pandas; a .gitignore keeps data/raw/ out of git.
Safe to run twice: each edit is skipped if already done.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def edit(fname, old, new, tag):
    path = os.path.join(HERE, fname)
    s = open(path).read()
    if new in s:
        print(f"[skip] {tag}: already done")
        return
    if old not in s:
        print(f"[FAIL] {tag}: expected text not found in {fname} - tell Claude")
        return
    open(path, "w").write(s.replace(old, new, 1))
    print(f"[done] {tag}")


edit("terrain.py",
     '''        if src.nodata is not None:
            z[z == src.nodata] = np.nan
''',
     '''        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        if src.scales[0] != 1.0 or src.offsets[0] != 0.0:   # packed files store centimetres
            z = z * np.float32(src.scales[0]) + np.float32(src.offsets[0])
''', "terrain.load_dem applies scale/offset")

edit("main.py",
     '''RAW = os.path.join(HERE, "data", "raw")
''',
     '''RAW = os.path.join(HERE, "data", "raw")
if not os.path.isdir(RAW) or not any(f.lower().endswith(".tif") for f in os.listdir(RAW)):
    RAW = os.path.join(HERE, "data", "packed")       # small copies committed to GitHub
''', "main.py falls back to data/packed/")

req = os.path.join(HERE, "requirements.txt")
lines = open(req).read().split()
if "pandas" not in lines:
    open(req, "a").write("pandas\n")
    print("[done] pandas added to requirements.txt")
else:
    print("[skip] pandas already in requirements.txt")

gi = os.path.join(HERE, ".gitignore")
if not os.path.exists(gi):
    open(gi, "w").write("data/raw/\n__pycache__/\n*.part\n.DS_Store\ncache/TEST_REGION*\n")
    print("[done] .gitignore written")
else:
    print("[skip] .gitignore already exists")
