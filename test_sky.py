"""Checks sky.py without the internet: a made-up Sun/Earth and a made-up horizon."""
import numpy as np
import pandas as pd
import sky

calls = []


def fake_fetch(lat, lon, alt_km, t0, t1):
    """Stands in for Horizons: Sun circles once per 708 h at el = 1.5*sin, Earth fixed."""
    calls.append((t0, t1))
    t = pd.date_range(t0, t1, freq="h")
    h = (t - pd.Timestamp("2026-01-01")) / pd.Timedelta(hours=1)
    az = (360.0 * h / 708.0) % 360.0
    return pd.DataFrame({"time": t, "sun_az": az, "sun_el": 1.5 * np.sin(np.radians(az)),
                         "earth_az": 0.0, "earth_el": 4.0})


args = ("TEST REGION", 1.0, 2.0, -86.0, 0.0, 5.0)
sky.clear_cache("TEST REGION")
a, n = sky.horizons_query(*args, "2026-01-01", "2026-01-03 02:00", fetcher=fake_fetch)
print("days 0-50h   : rows", len(a), "requests", n, "(expect 51, 1)")
b, n = sky.horizons_query(*args, "2026-01-01", "2026-01-08 02:00", fetcher=fake_fetch)
print("days 0-170h  : rows", len(b), "requests", n, "fetched from", calls[-1][0], "(expect 171, 1, from 2026-01-03 03:00)")
c, n = sky.horizons_query(*args, "2026-01-02 06:00", "2026-01-02 16:00", fetcher=fake_fetch)
print("inside cache : rows", len(c), "requests", n, "(expect 11, 0)")
d, n = sky.horizons_query(*args, "2025-12-30", "2026-01-10", fetcher=fake_fetch)
print("both sides   : rows", len(d), "requests", n, "(expect 265, 2)")

# visibility: horizon is 0 deg everywhere except a 10 deg wall between az 350 and 10 (hides Earth)
full, _ = sky.horizons_query(*args, "2026-01-01", "2026-01-30 11:00", fetcher=fake_fetch)   # 708 h = one circle
az = np.arange(360.0); flat = (az, np.zeros(360)); wall = (az, np.where((az >= 350) | (az <= 10), 10.0, 0.0))
s = sky.window_stats(sky.add_visibility(full, flat), p_load_w=200)
print("flat horizon : sunlit %.1f%% (expect ~50), Earth %.0f%% (expect 100), longest dark %d h (expect ~354), battery %.0f Wh, windows %d"
      % (s["illum_pct"], s["earth_pct"], s["t_dark_h"], s["battery_wh"], len(s["windows"])))
s2 = sky.window_stats(sky.add_visibility(full, wall))
print("wall at north: Earth %.0f%% (expect 0), both %.0f%% (expect 0), windows %d" % (s2["earth_pct"], s2["both_pct"], len(s2["windows"])))
print(sky.compare({"flat": s, "wall": s2}).to_string(index=False))
snap = sky.snapshot(sky.add_visibility(full, flat), "2026-01-05 10:20")
print("snapshot     :", snap["time"], "sun_up", snap["sun_up"], "earth_up", snap["earth_up"])
print("cache        : %.3f MB, cleared %d file(s)" % (sky.cache_size_mb(), sky.clear_cache("TEST REGION")))
