"""fetch_sky.py - first live test of the JPL Horizons link (PLAN1 step 3).

Run:  python3 fetch_sky.py
Fetches hourly Sun + Earth azimuth/elevation for the Malapert test point for
30 days, saves it to cache/, and prints a summary to paste back.
"""
import numpy as np

import horizon as hz
import sky
import terrain as t

REGION = "Malapert Massif (Site23)"
X, Y = 5700.0, 120900.0                      # the point clicked in the UI test (map metres)
T0, T1 = "2026-11-13 00:00", "2026-12-13 00:00"

dem5 = t.load_dem("data/raw/Site23_final_adj_5mpp_surf.tif")
z_site = float(hz.sample(dem5, np.array([X]), np.array([Y]))[0])
lat, lon = t.xy_to_latlon(X, Y)
print(f"Point: lat {lat:.4f} deg, lon {lon:.4f} deg, height {z_site:.1f} m")

try:
    table, n = sky.horizons_query(REGION, X, Y, lat, lon, z_site / 1000.0, T0, T1)
except Exception as e:
    print("FAILED:", e)
    raise SystemExit(1)

print(f"Rows: {len(table)}   Horizons requests made: {n}")
print(table.head(4).to_string(index=False))
print(table.iloc[::120].to_string(index=False))
for c in sky.COLS:
    print(f"{c:9s} min {table[c].min():8.3f}  max {table[c].max():8.3f}")
print("Saved to", sky.csv_path(REGION, X, Y))
