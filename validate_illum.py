"""validate_illum.py - PLAN1 step 5: our sunlight / Earth-visibility % vs NASA's maps.

Run after precompute.py:  python3 validate_illum.py

NASA maps: PGDA product 69, average solar illumination and average Earth
visibility, 85-90 deg S, 60 m/px (Mazarico et al. 2011, updated 2016).
Ours: quick horizon (80 m DEM), observer at the surface (mast 0 m), over the
~14 months in the precomputed tables. NASA's numbers are long-term averages,
so expect close agreement in ranking (correlation), not identical values.

Also the shadow check: points we find at 0 % sunlight should be ~0 % in NASA's map.
"""
import os

import numpy as np
import rasterio

import horizon as hz
import precompute as pc
import regional as rg
import setup_data as sd
import sky
import terrain as t

MAPS = {
    "sun": "AVGVISIB_85S_060M_201608.TIF",
    "earth": "AVGVISIB_85S_060M_201608_EARTH.TIF",
}
URL = "https://pgda.gsfc.nasa.gov/data/MoonIllumination/"
GRID = 6                      # 6 x 6 test points per region
RAW = pc.RAW
WIDE = os.path.join(RAW, "LDEM_80S_80MPP_ADJ.TIF")


def ensure_maps():
    for f in MAPS.values():
        path = os.path.join(RAW, f)
        if os.path.exists(path):
            continue
        mb = sd.remote_size_mb(URL + f)
        print(f"Downloading {f} ({mb:.0f} MB)")
        if mb > sd.SIZE_LIMIT_MB:
            raise SystemExit(f"{f} is over the {sd.SIZE_LIMIT_MB} MB limit - stopping.")
        sd.download(URL + f, path)


def nasa_percent(path, xs, ys, bounds):
    """NASA map values at points, converted to percent if the map stores fractions."""
    m = t.load_dem(path, crop=bounds)
    v = hz.sample(m, xs, ys)
    with rasterio.open(path) as s:
        raw_max = float(np.nanmax(s.read(1, out_shape=(1, 400, 400)) * s.scales[0] + s.offsets[0]))
    return (v * 100.0 if raw_max <= 1.0 + 1e-6 else v), raw_max


def main():
    ensure_maps()
    rows = []
    for name, f in pc.REGIONS.items():
        table, n, c = pc.centre_table(name)
        with rasterio.open(os.path.join(RAW, f)) as s:
            b = s.bounds
        fx = np.linspace(0.1, 0.9, GRID)
        xs = np.repeat(b.left + fx * (b.right - b.left), GRID)
        ys = np.tile(b.bottom + fx * (b.top - b.bottom), GRID)
        wide = hz.load_wide_dem(WIDE, c[0], c[1], d_max=hz.D_MAX + 16000)
        ours_sun, ours_earth = [], []
        for x, y in zip(xs, ys):
            lat, lon = t.xy_to_latlon(x, y)
            mask = hz.horizon_mask(wide, x, y, 0.0)
            vis = sky.add_visibility(rg.transfer(table, c[2], c[3], float(lat), float(lon)), mask)
            s = sky.window_stats(vis)
            ours_sun.append(s["illum_pct"]); ours_earth.append(s["earth_pct"])
        box = (b.left - 200, b.bottom - 200, b.right + 200, b.top + 200)
        nasa_sun, mx_s = nasa_percent(os.path.join(RAW, MAPS["sun"]), xs, ys, box)
        nasa_earth, mx_e = nasa_percent(os.path.join(RAW, MAPS["earth"]), xs, ys, box)
        rows.append((name, np.array(ours_sun), nasa_sun, np.array(ours_earth), nasa_earth))
        print(f"{name}: NASA raw value range up to {mx_s:.3g} (sun), {mx_e:.3g} (Earth)")

    print(f"\n{'Region':26s} {'quantity':6s} {'points':>6s} {'ours mean':>10s} {'NASA mean':>10s} "
          f"{'median |diff|':>14s} {'corr':>6s}")
    all_s, all_n = [], []
    for name, os_, ns, oe, ne in rows:
        for q, o, nmap in (("sun", os_, ns), ("earth", oe, ne)):
            ok = np.isfinite(nmap)
            corr = np.corrcoef(o[ok], nmap[ok])[0, 1] if ok.sum() > 2 and o[ok].std() > 0 else float("nan")
            print(f"{name:26s} {q:6s} {ok.sum():6d} {o[ok].mean():10.1f} {nmap[ok].mean():10.1f} "
                  f"{np.median(np.abs(o[ok] - nmap[ok])):14.1f} {corr:6.3f}")
        all_s.append(os_); all_n.append(ns)
    o, nmap = np.concatenate(all_s), np.concatenate(all_n)
    ok = np.isfinite(nmap)
    print(f"\nAll regions, sun: correlation {np.corrcoef(o[ok], nmap[ok])[0, 1]:.3f} over {ok.sum()} points")
    dark = ok & (o == 0)
    print(f"Shadow check: {dark.sum()} points we find at 0 % sunlight; "
          + (f"NASA's value there: max {nmap[dark].max():.1f} %, mean {nmap[dark].mean():.1f} %" if dark.any()
             else "none among the test points"))


if __name__ == "__main__":
    main()
