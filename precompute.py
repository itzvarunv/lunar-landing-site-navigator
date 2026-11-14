"""precompute.py - PLAN1 step 5: fetch and cache Sun/Earth tables for the 4 regions.

Run once on your Mac (needs internet to JPL):  python3 precompute.py

1. One Horizons table per region, at the region centre, hourly over T0..T1
   (2 requests per region). Saved in cache/CENTRE_<region>_..._sun_earth.csv.
2. Accuracy check: moves the Malapert centre table to the point you tested
   live earlier (x 5700, y 120900) with regional.transfer() and compares it,
   hour by hour, with the live Horizons table for that exact point.
"""
import os

import numpy as np
import rasterio

import horizon as hz
import regional as rg
import sky
import terrain as t

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
REGIONS = {
    "Malapert Massif (Site23)": "Site23_final_adj_5mpp_surf.tif",
    "Haworth": "Haworth_final_adj_5mpp_surf.tif",
    "Nobile Rim 1 (Site06)": "Site06_final_adj_5mpp_surf.tif",
    "de Gerlache Rim (Site11)": "Site11_final_adj_5mpp_surf.tif",
}
T0, T1 = "2026-11-01 00:00", "2027-12-31 23:00"     # ~14 months, hourly


def region_centre(path):
    """Centre of the DEM (map metres), its lat/lon (deg) and surface height (m)."""
    with rasterio.open(path) as s:
        b = s.bounds
    cx, cy = (b.left + b.right) / 2, (b.bottom + b.top) / 2
    dem = t.load_dem(path, crop=(cx - 50, cy - 50, cx + 50, cy + 50))
    z = float(hz.sample(dem, np.array([cx]), np.array([cy]))[0])
    lat, lon = t.xy_to_latlon(cx, cy)
    return cx, cy, float(lat), float(lon), z


def centre_table(name):
    """Cached (or freshly fetched) Sun/Earth table at a region's centre."""
    cx, cy, lat, lon, z = region_centre(os.path.join(RAW, REGIONS[name]))
    table, n = sky.horizons_query("CENTRE " + name, cx, cy, lat, lon, z / 1000.0, T0, T1)
    return table, n, (cx, cy, lat, lon, z)


def main():
    print(f"Fetching {T0} to {T1}, hourly, at each region centre")
    centres = {}
    for name in REGIONS:
        table, n, c = centre_table(name)
        centres[name] = (table, c)
        print(f"  {name:26s} centre lat {c[2]:.4f}, lon {c[3]:8.4f}, h {c[4]:7.1f} m | "
              f"{len(table)} rows, {n} new request batch(es)")

    # accuracy check against the live table for the tested Malapert point
    name, x, y = "Malapert Massif (Site23)", 5700.0, 120900.0
    live_path = sky.csv_path(name, x, y)
    if not os.path.exists(live_path):
        print("No live table for the Malapert test point - skipping the accuracy check.")
        return
    live = sky.load_cache(live_path)
    table, c = centres[name]
    lat_p, lon_p = t.xy_to_latlon(x, y)
    moved = rg.transfer(table, c[2], c[3], float(lat_p), float(lon_p))
    both = live.merge(moved, on="time", suffixes=("_live", "_moved"))
    print(f"\nAccuracy check: Malapert centre table moved {np.hypot(x - c[0], y - c[1]) / 1000:.1f} km "
          f"to the test point vs live Horizons there ({len(both)} common hours)")
    for col in sky.COLS:
        d = both[f"{col}_moved"] - both[f"{col}_live"]
        if col.endswith("_az"):
            d = (d + 180) % 360 - 180
        print(f"  {col:9s} max |difference| {np.abs(d).max():.4f} deg")
    unmoved = live.merge(table, on="time", suffixes=("_live", "_centre"))
    print(f"  (without moving: sun_el max |difference| "
          f"{np.abs(unmoved['sun_el_centre'] - unmoved['sun_el_live']).max():.4f} deg)")
    mask = hz.horizon_mask(hz.load_wide_dem(os.path.join(RAW, "LDEM_80S_80MPP_ADJ.TIF"), x, y), x, y, 0.0)
    a = sky.add_visibility(live[live["time"].isin(both["time"])].reset_index(drop=True), mask)
    b = sky.add_visibility(moved[moved["time"].isin(both["time"])].reset_index(drop=True), mask)
    print(f"  Sun-visible flag agrees {100 * (a['sun_up'] == b['sun_up']).mean():.2f}% of hours, "
          f"Earth-visible flag {100 * (a['earth_up'] == b['earth_up']).mean():.2f}%")


if __name__ == "__main__":
    main()
