"""pack_data.py - small copies of the DEMs for GitHub / Streamlit Cloud (<100 MB each).

Run once on your Mac:  python3 pack_data.py
Reads data/raw/, writes data/packed/ with the SAME file names.

How: heights are stored as whole centimetres (int32) with lossless deflate
compression. Rounding to 1 cm is far below the DEMs' own ~0.3-0.5 m height error.
The 80 m wide-area DEM is cropped to what the horizon rays of the 4 regions can
reach (region bounds + 153 km on every side).
"""
import os

import numpy as np
import rasterio
from rasterio.windows import from_bounds

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
OUT = os.path.join(HERE, "data", "packed")
SITES = ["Site23_final_adj_5mpp_surf.tif", "Haworth_final_adj_5mpp_surf.tif",
         "Site06_final_adj_5mpp_surf.tif", "Site11_final_adj_5mpp_surf.tif"]
WIDE = "LDEM_80S_80MPP_ADJ.TIF"
REACH = 153000.0            # horizon range 150 km + 2 % (matches horizon.load_wide_dem)
NODATA = np.iinfo("int32").min
GITHUB_LIMIT_MB = 100.0


def pack(src_name, bounds=None):
    src_path, dst_path = os.path.join(RAW, src_name), os.path.join(OUT, src_name)
    with rasterio.open(src_path) as s:
        if bounds is None:
            window, transform = None, s.transform
        else:
            b = s.bounds
            bounds = (max(bounds[0], b.left), max(bounds[1], b.bottom),
                      min(bounds[2], b.right), min(bounds[3], b.top))
            window = from_bounds(*bounds, transform=s.transform).round_offsets().round_lengths()
            transform = s.window_transform(window)
        z = s.read(1, window=window).astype("float64")
        if s.nodata is not None and not np.isnan(s.nodata):
            z[z == s.nodata] = np.nan
        bad = ~np.isfinite(z)
        q = np.round(z * 100.0)
        q[bad] = NODATA
        q = q.astype("int32")
        profile = dict(driver="GTiff", dtype="int32", count=1, width=q.shape[1], height=q.shape[0],
                       crs=s.crs, transform=transform, nodata=NODATA, compress="deflate",
                       predictor=2, zlevel=9, tiled=True, blockxsize=512, blockysize=512)
    os.makedirs(OUT, exist_ok=True)
    with rasterio.open(dst_path, "w", **profile) as d:
        d.write(q, 1)
        d.scales = (0.01,)          # stored value x 0.01 = metres
        d.offsets = (0.0,)
    # check: read back exactly the way terrain.load_dem does
    with rasterio.open(dst_path) as d:
        back = d.read(1).astype("float32")
        back[back == d.nodata] = np.nan
        back = back * np.float32(d.scales[0]) + np.float32(d.offsets[0])
    ok = np.isfinite(z)
    err = float(np.nanmax(np.abs(back[ok] - z[ok]))) if ok.any() else 0.0
    same_nan = bool((np.isnan(back) == bad).all())
    mb = os.path.getsize(dst_path) / 1e6
    flag = "OK" if mb < GITHUB_LIMIT_MB else "TOO BIG FOR GITHUB"
    print(f"{src_name:34s} {q.shape[1]:6d} x {q.shape[0]:<6d} {mb:7.1f} MB  "
          f"max height change {err * 100:.2f} cm  no-data kept: {same_nan}  {flag}")


def main():
    print(f"{'file':34s} {'size (cells)':>15s} {'packed':>10s}")
    region_bounds = []
    for f in SITES:
        with rasterio.open(os.path.join(RAW, f)) as s:
            region_bounds.append(s.bounds)
        pack(f)
    crop = (min(b.left for b in region_bounds) - REACH, min(b.bottom for b in region_bounds) - REACH,
            max(b.right for b in region_bounds) + REACH, max(b.top for b in region_bounds) + REACH)
    pack(WIDE, crop)
    print("Done. Commit data/packed/ to GitHub; keep data/raw/ out of git (.gitignore).")


if __name__ == "__main__":
    main()
