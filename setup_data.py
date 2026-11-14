"""setup_data.py - downloads the raw NASA LOLA DEMs (PLAN1, step 0).

Run once:  python3 setup_data.py
Files go to data/raw/. Safe to re-run: finished files are skipped.
Source: NASA GSFC Planetary Geodesy Data Archive (PGDA), products 78 and 90.
URLs pinned on 13 Nov 2026.
"""
import os
import sys
import urllib.request

BASE_5M = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp"
BASE_20M = "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp"

# name -> url
FILES = {
    # 5 m site DEMs (landing safety)
    "Site23_final_adj_5mpp_surf.tif": f"{BASE_5M}/Site23/Site23_final_adj_5mpp_surf.tif",
    "Haworth_final_adj_5mpp_surf.tif": f"{BASE_5M}/Haworth/Haworth_final_adj_5mpp_surf.tif",
    "Site06_final_adj_5mpp_surf.tif": f"{BASE_5M}/Site06/Site06_final_adj_5mpp_surf.tif",
    "Site11_final_adj_5mpp_surf.tif": f"{BASE_5M}/Site11/Site11_final_adj_5mpp_surf.tif",
    # NASA's own 5 m slope maps (validation of our slope_map)
    "Site23_final_adj_5mpp_slp.tif": f"{BASE_5M}/Site23/Site23_final_adj_5mpp_slp.tif",
    "Haworth_final_adj_5mpp_slp.tif": f"{BASE_5M}/Haworth/Haworth_final_adj_5mpp_slp.tif",
    "Site06_final_adj_5mpp_slp.tif": f"{BASE_5M}/Site06/Site06_final_adj_5mpp_slp.tif",
    "Site11_final_adj_5mpp_slp.tif": f"{BASE_5M}/Site11/Site11_final_adj_5mpp_slp.tif",
    # 80 m wide-area DEM (horizon)
    "LDEM_80S_80MPP_ADJ.TIF": f"{BASE_20M}/LDEM_80S_80MPP_ADJ.TIF",
}

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
SIZE_LIMIT_MB = 500  # PLAN1: skip anything bigger than this


def remote_size_mb(url):
    """Ask the server how big the file is, without downloading it."""
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return int(resp.headers.get("Content-Length", 0)) / 1e6


def download(url, path):
    """Download url to path, printing progress."""
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write(f"\r    {done / 1e6:7.0f} / {total / 1e6:.0f} MB")
                sys.stdout.flush()
    os.replace(tmp, path)
    print()


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    print("Checking file sizes on NASA PGDA...")
    sizes = {}
    for name, url in FILES.items():
        try:
            sizes[name] = remote_size_mb(url)
            print(f"  {name:38s} {sizes[name]:8.0f} MB")
        except Exception as e:
            sizes[name] = None
            print(f"  {name:38s} ERROR: {e}")

    for name, url in FILES.items():
        path = os.path.join(RAW_DIR, name)
        size = sizes[name]
        if size is None:
            print(f"SKIP {name}: could not reach it")
            continue
        if os.path.exists(path) and abs(os.path.getsize(path) / 1e6 - size) < 0.01:
            print(f"OK   {name}: already downloaded")
            continue
        if size > SIZE_LIMIT_MB:
            print(f"SKIP {name}: {size:.0f} MB is over the {SIZE_LIMIT_MB} MB limit")
            continue
        print(f"GET  {name}")
        download(url, path)
    print("Done. Files are in data/raw/")


if __name__ == "__main__":
    main()
