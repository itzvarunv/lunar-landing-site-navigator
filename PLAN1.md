# PLAN 1 — Lunar Landing Site Navigator
NASA Space Apps 2026 | target: finish 13 Nov

## Goal
Pick a point near the lunar south pole -> check it is **safe to land** -> check
**sunlight (power)** and **Earth visibility (comms)** at a chosen time and over a
date range -> compare sites and find landing windows.

Output = one Streamlit app, launched with `streamlit run main.py`.

---

## Data

| Use | Source | File |
|---|---|---|
| Landing safety (5 m) | PGDA product 78 | `Site23/Haworth/Site06/Site11_final_adj_5mpp_surf.tif` |
| Horizon (80 m, wide area) | PGDA product 90 | `LDEM_80S_80MPP_ADJ.TIF` |
| Validation: slope | PGDA product 90 | `LDSM_80S_*_ADJ.TIF` (degrees) |
| Validation: roughness | PGDA product 90 | `LDRM_80S_*_ADJ_ROUGH_*M.TIF` (metres) |
| Validation: illumination | PGDA product 69 | avg illumination GeoTIFF |
| Validation: PSRs | PGDA product 90 | `LPSR_80S_20MPP_ADJ_1km2.CSV` |
| Sun + Earth az/el | JPL Horizons API | queried, then cached |

Format: GeoTIFF, south polar stereographic X/Y in metres, MOON_ME frame,
ephemeris DE421, projection radius R = 1 737 400 m. Read with `rasterio`
(windowed reads only — never load a whole file).

**Repo holds code only.** `setup_data.py` downloads from pinned PGDA URLs on
first run, crops to the 4 sites, saves small files. Try rasterio windowed read
over HTTP first; if the files are not tiled, fall back to full download.

### Sites (4 presets, Artemis III regions with a 5 m DEM)
| Region | DEM |
|---|---|
| Malapert Massif | Site23 |
| Haworth | Haworth |
| Nobile Rim 1 | Site06 |
| de Gerlache Rim | Site11 |

User picks a region, then clicks freely inside it.
Check each file size before download; skip anything over ~500 MB.

---

## Maths

Symbols: R = Moon radius 1 737 400 m; D = DEM cell size (m); z = surface height
(m); phi = latitude; lambda = longitude; el = elevation angle above local
horizontal; az = azimuth (0 deg = north); d = horizontal distance (m).

### Click -> coordinates
Pixel (i, j) -> metres: x = x0 + j*D, y = y0 - i*D (x0, y0 from the GeoTIFF).
Then south polar stereographic -> lat/lon:
- rho = sqrt(x^2 + y^2)
- phi = -(90 deg - 2*atan(rho / (2R)))
- lambda = atan2(x, y)

### Stage 1 — landing safety
Slope per cell, from the gradient:
- dz/dx = (z[i, j+1] - z[i, j-1]) / (2D)
- dz/dy = (z[i-1, j] - z[i+1, j]) / (2D)
- slope = atan( sqrt((dz/dx)^2 + (dz/dy)^2) )

Footprint check, radius r = r_lander + r_uncertainty:
- Y = every cell the circle **touches** (conservative: touch, not centre-inside)
- B = cells with slope < theta_max AND roughness < rough_max
- **Accept iff Y is a subset of B** (i.e. Y \ B = empty)
- NaN / no-data cells -> red. Circle crossing the map edge -> reject.
- Warn if r < D (footprint smaller than map resolution).

Footprint plane fit (least squares), z = a*x + b*y + c, solving A^T A p = A^T z
for p = [a, b, c]:
- footprint slope = atan( sqrt(a^2 + b^2) )
- roughness = max |z - (a*x + b*y + c)|  (biggest bump/dip vs the plane, m)

### Stage 2 — horizon, sunlight, comms
Horizon angle per azimuth (march outward, take the max):
- h(az) = max over d of atan( (z_terrain(d) - z_site - h_mast - d^2/(2R)) / d )
- d^2/(2R) = curvature drop of the Moon over distance d
- Range ~150 km on the 80 m DEM. Variable step: 20 m near the site growing to
  ~500 m far out (~500 samples/direction). Vectorise across all 360 azimuths.
- Coarse pass at 1 deg, then **refine to 0.1 deg only at azimuths the Sun or
  Earth actually passes through**. Refine triggered by a button, not hover
  (Streamlit cannot read Plotly zoom events cleanly).

Sun / Earth az + el per time step: **JPL Horizons API** (observer = site lat/lon
on the Moon). Reference vectors if ever needed without Horizons:
- up = r_site / |r_site|
- east = [-sin(lambda), cos(lambda), 0]
- north = [-sin(phi)cos(lambda), -sin(phi)sin(lambda), cos(phi)]
- el = asin(s . up), az = atan2(s . east, s . north), s = unit vector to the body

**Visible iff el > h(az).**

Per site over a window:
- illumination % = sunlit steps / total steps
- longest darkness t_dark (h) -> battery E = P_load * t_dark
  (P_load = power draw while dark, W; E in Wh)
- Earth-visible % = Earth-visible steps / total steps
- landing window = dates where Sun AND Earth are both up

Final candidate set = **B AND L AND E** (safe, illumination % >= threshold,
Earth-visible % >= threshold). Always show the actual percentages, not just
pass/fail.

---

## Defaults (user-editable)
| Parameter | Default | Basis |
|---|---|---|
| theta_max (slope) | 8 deg | NASA requires Starship HLS land at <= 8 deg from vertical; CASSA assessment assumes <= 10 deg |
| rough_max | 0.5 m | lander ground clearance — adjust to spec |
| r_lander | 1 m | user sets per mission |
| r_uncertainty | 100 m | NASA Artemis site = ~100 m radius |
| h_mast | 0 m | slider 0-10 m |
| window | 29.5 d (one lunar day), 1 h steps | — |

Optional "Custom lander" preset: tan(theta_tip) = r_foot / h_cm, then
theta_max = theta_tip / SF.
- r_foot = centre-to-leg-pad distance (m); h_cm = centre-of-mass height (m);
  SF = safety factor (1.5-2)

Optional "conservative mode": judge each cell against theta_max - 2 deg, since
the 5 m DEMs have median RMS slope error ~1.5-2.5 deg.

---

## Caching
- `cache/{site}_sun_earth.csv` — time, sun_az, sun_el, earth_az, earth_el.
  **Never fetch the same time range twice**: on a new request, fetch only the
  missing interval and merge. (Saves network calls, not maths — an ephemeris
  lookup at day 170 costs the same as at day 0.)
- `cache/{site}_mast{h}.npy` — horizon mask (360 values).
- Sidebar: "Cache: X MB" + **Clear site** / **Clear all** buttons.
- Precompute all 4 sites before submission so the demo works offline.

---

## Build order (~10 h)
| # | Task | Time | Checkpoint |
|---|---|---|---|
| 0 | Download DEMs, crop, confirm they load | 1.0 h | heights print correctly |
| 1 | Slope, roughness, safety map, click -> circle -> Y subset B | 2.0 h | **working safety tool** |
| 2 | Horizon mask (coarse + refine) + mast slider, cached | 1.5 h | horizon plot per site |
| 3 | Horizons query + interval cache, snapshot + window stats | 2.0 h | **core challenge done** |
| 4 | UI: region picker, comparison table, time slider, cache panel | 1.5 h | full app |
| 5 | Precompute, push small files, deploy to Streamlit Cloud | 1.0 h | public link |
| 6 | Demo video + project page | 1.0 h | **submitted** |

**Cut in this order if behind:** cloud deploy (local + video instead) -> refine
button -> custom-lander calculator -> comparison polish.
**Never cut steps 1-3.**

Dropped by decision: rover traversability path (Dijkstra/A* over cells with
slope < theta_rover); whole-map B AND L AND E heat map = stretch goal only.

---

## Function order
```
load_dem(crop)
slope_map(dem)
roughness_map(dem)
safe_set(slope, roughness, theta_max, rough_max)   -> B
cells_in_circle(x0, y0, r)                         -> Y
plane_fit(cells)                                   -> a, b, c
is_safe(Y, B)                                      -> bool + reason
horizon_mask(site, h_mast)                         -> h(az), 360 values
refine_horizon(site, az_range)
horizons_query(site, t0, t1) + cache_merge
visibility(el, az, mask)                           -> bool
snapshot(site, t)                                  -> sun/earth up?
window_stats(site, t0, t1)                         -> illum %, t_dark, earth %
compare(sites)                                     -> table
clear_cache(site | all)
```

---

## Stack
Python, Streamlit + Plotly, numpy, rasterio, requests.
`main.py` imports helpers; one command runs everything.
Deployment: Streamlit Community Cloud, committing only precomputed small files
(cropped DEMs ~16 MB/site, horizon masks, Horizons CSVs) — all under GitHub's
100 MB limit.

---

## Stated limitations (put on a slide)
1. Hazards smaller than the DEM cell (boulders, small craters < 5-10 m) are
   invisible. Real missions use high-resolution camera imagery for these.
2. Sun treated as a point, not a 0.53 deg disc — no partial-shadow moments.
3. Comms assumes an Earth ground station is always available. Only lunar-side
   visibility is computed, so Earth-visible % is a slight upper bound. At the
   pole the lunar side dominates, so site ranking is barely affected.
4. DEM height/slope uncertainty: median RMS Z error ~0.30-0.50 m, slope error
   ~1.5-2.5 deg.

## Validation (step 5)
- own slope map vs NASA `LDSM_*`
- own roughness vs NASA `LDRM_*`
- own illumination % vs PGDA product 69 illumination maps
- any site at 0 % illumination should fall inside the PSR list

## Sources to cite
- PGDA product 78 — high-resolution LOLA topography for south pole sites
- PGDA product 90 — Barker et al. 2023, a new view of the lunar south pole
- PGDA product 69 — lunar polar illumination
- JPL Horizons
- Barker et al. 2021, Planetary & Space Science 203, 105119
