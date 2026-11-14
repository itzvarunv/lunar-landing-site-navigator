"""validate.py - PLAN1 step 5: our slope map vs NASA's own 5 m slope maps.

Put this file in the NASA Project folder, then run:  python3 validate.py
"""
import numpy as np
import rasterio

import terrain as t

SITES = {"Malapert Massif (Site23)": "Site23", "Haworth": "Haworth",
         "Nobile Rim 1 (Site06)": "Site06", "de Gerlache Rim (Site11)": "Site11"}

print(f"{'Region':26s} {'cells':>10s} {'mean diff':>10s} {'median |diff|':>14s} "
      f"{'95th pct |diff|':>16s} {'corr':>7s} {'same side of 8 deg':>19s}")
for name, tag in SITES.items():
    dem = t.load_dem(f"data/raw/{tag}_final_adj_5mpp_surf.tif")
    ours = t.slope_map(dem)
    with rasterio.open(f"data/raw/{tag}_final_adj_5mpp_slp.tif") as src:
        nasa = src.read(1).astype("float32")
        if src.nodata is not None:
            nasa[nasa == src.nodata] = np.nan
    if nasa.shape != ours.shape:
        print(f"{name:26s} grids differ: ours {ours.shape}, NASA {nasa.shape}")
        continue
    ok = np.isfinite(ours) & np.isfinite(nasa)
    d = ours[ok] - nasa[ok]
    agree = ((ours[ok] < 8) == (nasa[ok] < 8)).mean() * 100
    print(f"{name:26s} {ok.sum():10d} {d.mean():10.3f} {np.median(np.abs(d)):14.3f} "
          f"{np.percentile(np.abs(d), 95):16.3f} {np.corrcoef(ours[ok], nasa[ok])[0, 1]:7.4f} "
          f"{agree:18.2f}%")
