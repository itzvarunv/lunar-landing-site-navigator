"""sky.py - PLAN1 stage 2/3: Sun and Earth positions (JPL Horizons) + visibility.

Cache: cache/{region}_x{x}_y{y}_sun_earth.csv with columns
    time (UTC), sun_az, sun_el, earth_az, earth_el      (degrees, 1 h steps)
az = azimuth, clockwise from local north. el = elevation above the local level plane.
The same time range is never fetched twice: only missing hours are requested.
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from horizon import CACHE, horizon_at

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
SUN, EARTH = "10", "399"          # Horizons body codes
COLS = ["sun_az", "sun_el", "earth_az", "earth_el"]
EARTH_RADIUS_DEG = 0.95           # Earth's angular radius seen from the Moon: asin(6.371e6 m / 3.844e8 m)


def _fetch_body(body, lat, lon, alt_km, t0, t1):
    """One Horizons request: az/el of `body` seen from a point on the Moon,
    hourly from t0 to t1 (datetimes, UTC). Returns DataFrame(time, az, el)."""
    params = {
        "format": "text", "COMMAND": f"'{body}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'", "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon % 360:.6f},{lat:.6f},{alt_km:.4f}'",
        "START_TIME": f"'{t0:%Y-%m-%d %H:%M}'", "STOP_TIME": f"'{t1:%Y-%m-%d %H:%M}'",
        "STEP_SIZE": "'1 h'", "QUANTITIES": "'4'", "APPARENT": "'AIRLESS'",
        "ANG_FORMAT": "'DEG'", "CSV_FORMAT": "'YES'",
    }
    r = requests.get(API, params=params, timeout=120)
    r.raise_for_status()
    text = r.text
    if "$$SOE" not in text:
        raise RuntimeError("Horizons returned no table. Its message:\n" + text[-1500:])
    rows = []
    for line in text.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        nums = []
        for p in parts[1:]:
            try:
                nums.append(float(p))
            except ValueError:
                pass
        when = datetime.strptime(parts[0], "%Y-%b-%d %H:%M")
        rows.append((when, nums[0], nums[1]))
    return pd.DataFrame(rows, columns=["time", "az", "el"])


def fetch(lat, lon, alt_km, t0, t1):
    """Sun + Earth az/el for one time range. DataFrame(time, sun_az, sun_el, earth_az, earth_el)."""
    s = _fetch_body(SUN, lat, lon, alt_km, t0, t1)
    e = _fetch_body(EARTH, lat, lon, alt_km, t0, t1)
    out = s.rename(columns={"az": "sun_az", "el": "sun_el"})
    out["earth_az"], out["earth_el"] = e["az"].values, e["el"].values
    return out


def csv_path(region, x, y):
    return os.path.join(CACHE, f"{region}_x{x:.0f}_y{y:.0f}_sun_earth.csv".replace(" ", "_"))


def load_cache(path):
    if os.path.exists(path):
        return pd.read_csv(path, parse_dates=["time"])
    return pd.DataFrame(columns=["time"] + COLS)


def missing_ranges(have, t0, t1):
    """Hours between t0 and t1 that are not in `have` (a set of times), grouped
    into continuous (start, end) ranges."""
    hours = pd.date_range(t0, t1, freq="h")
    gaps, start, prev = [], None, None
    for h in hours:
        if h not in have:
            if start is None:
                start = h
            prev = h
        elif start is not None:
            gaps.append((start, prev))
            start = None
    if start is not None:
        gaps.append((start, prev))
    return gaps


def cache_merge(old, new):
    """Join two tables, drop duplicate hours, sort by time."""
    if len(old) == 0:
        return new.sort_values("time").reset_index(drop=True)
    both = pd.concat([old, new], ignore_index=True)
    return both.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def horizons_query(region, x, y, lat, lon, alt_km, t0, t1, fetcher=fetch):
    """Hourly Sun/Earth az/el from t0 to t1 for a point. Uses the cache and only
    asks Horizons for the hours that are missing. Returns (table, n_requests)."""
    t0 = pd.Timestamp(t0).floor("h")
    t1 = pd.Timestamp(t1).ceil("h")
    path = csv_path(region, x, y)
    table = load_cache(path)
    gaps = missing_ranges(set(table["time"]), t0, t1)
    for g0, g1 in gaps:
        if g0 == g1:                       # Horizons needs stop > start
            g1 = g0 + timedelta(hours=1)
        table = cache_merge(table, fetcher(lat, lon, alt_km, g0.to_pydatetime(), g1.to_pydatetime()))
    if gaps:
        os.makedirs(CACHE, exist_ok=True)
        table.to_csv(path, index=False)
    sel = table[(table["time"] >= t0) & (table["time"] <= t1)].reset_index(drop=True)
    return sel, len(gaps)


def visibility(el, az, mask):
    """True where the body is above the terrain horizon: el > h(az)."""
    return np.asarray(el) > horizon_at(mask, az)


def add_visibility(table, mask):
    """Adds sun_up, earth_up and both_up columns to a Sun/Earth table.
    Earth counts as visible if any part of its disc clears the terrain (NASA PGDA
    product 69 rule): el + EARTH_RADIUS_DEG > h(az)."""
    out = table.copy()
    out["sun_up"] = visibility(out["sun_el"], out["sun_az"], mask)
    out["earth_up"] = visibility(out["earth_el"] + EARTH_RADIUS_DEG, out["earth_az"], mask)
    out["both_up"] = out["sun_up"] & out["earth_up"]
    return out


def snapshot(vis_table, t):
    """State at the hour nearest to time t."""
    i = (vis_table["time"] - pd.Timestamp(t)).abs().idxmin()
    return vis_table.loc[i].to_dict()


def longest_run(flags, step_h=1.0):
    """Longest unbroken stretch (hours) where flags is True."""
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best * step_h


def window_stats(vis_table, p_load_w=None):
    """Summary over the whole table.
    illum_pct    : % of time the Sun is visible
    earth_pct    : % of time Earth is visible
    both_pct     : % of time both are visible
    t_dark_h     : longest continuous darkness (h)
    t_no_earth_h : longest continuous stretch without Earth in view (h)
    battery_wh   : E = P_load * t_dark (Wh), if p_load_w (W) is given
    windows      : list of (start, end) times where Sun AND Earth are both up
    """
    v = vis_table
    out = {
        "hours": len(v),
        "illum_pct": 100.0 * v["sun_up"].mean(),
        "earth_pct": 100.0 * v["earth_up"].mean(),
        "both_pct": 100.0 * v["both_up"].mean(),
        "t_dark_h": longest_run(~v["sun_up"]),
        "t_no_earth_h": longest_run(~v["earth_up"]),
    }
    if p_load_w is not None:
        out["battery_wh"] = p_load_w * out["t_dark_h"]
    windows, start, prev = [], None, None
    for t, up in zip(v["time"], v["both_up"]):
        if up:
            start = t if start is None else start
            prev = t
        elif start is not None:
            windows.append((start, prev))
            start = None
    if start is not None:
        windows.append((start, prev))
    out["windows"] = windows
    return out


def compare(stats_by_site):
    """dict {site name: window_stats result} -> one comparison table."""
    rows = []
    for name, s in stats_by_site.items():
        rows.append({"Site": name, "Sunlit %": round(s["illum_pct"], 1),
                     "Earth visible %": round(s["earth_pct"], 1),
                     "Both %": round(s["both_pct"], 1),
                     "Longest dark (h)": s["t_dark_h"],
                     "Longest no-Earth (h)": s["t_no_earth_h"],
                     "Landing windows": len(s["windows"])})
    return pd.DataFrame(rows)


def cache_size_mb():
    if not os.path.isdir(CACHE):
        return 0.0
    return sum(os.path.getsize(os.path.join(CACHE, f)) for f in os.listdir(CACHE)) / 1e6


def clear_cache(region=None):
    """Delete cached files for one region, or everything if region is None.
    Returns the number of files removed."""
    if not os.path.isdir(CACHE):
        return 0
    prefix = None if region is None else region.replace(" ", "_") + "_"
    n = 0
    for f in os.listdir(CACHE):
        if prefix is None or f.startswith(prefix):
            os.remove(os.path.join(CACHE, f))
            n += 1
    return n
