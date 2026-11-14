# PLAN FINAL — Lunar Landing Site Navigator
NASA Space Apps 2026 | Team Stelantis (Varun, Kavin, Guru Prashanth, Rehaan) | written 13 Nov 2026

This is the record of what was actually built, how it differs from `PLAN1.md`, and why.
`PLAN1.md` is kept as the original plan; where the two disagree, this file describes the code.

---

## 1. Goal (unchanged from PLAN1)

Pick a point near the lunar south pole, then answer three questions:

1. **Can we land here?** Slope and roughness under the landing circle.
2. **Will it have power?** Is the Sun above the terrain horizon, hour by hour?
3. **Can it talk to Earth?** Is Earth above the terrain horizon?

Then compare sites and find landing windows (hours when the Sun and Earth are both up).
Output: one Streamlit app, run with `python3 -m streamlit run main.py`.

---

## 2. Symbols used in this file

| Symbol | Meaning | Unit |
|---|---|---|
| R | Moon radius, 1 737 400 | m |
| D | DEM cell size (5 m site maps, 80 m polar map) | m |
| d | horizontal distance from the site | m |
| az | azimuth, clockwise from local north | deg |
| el | elevation of the Sun or Earth centre above the local horizontal plane | deg |
| h(az) | terrain horizon angle in direction az | deg |
| ρ | Earth's angular radius seen from the Moon = asin(R_E / d_EM) | deg |
| R_E | Earth radius, 6.371 × 10⁶ | m |
| d_EM | Earth–Moon distance, ≈ 3.844 × 10⁸ (varies 3.56–4.07 × 10⁸) | m |
| φ | latitude | deg |
| P_load | power drawn while dark | W |
| t_dark | longest continuous darkness | h |
| E | battery energy needed = P_load × t_dark | Wh |

---

## 3. What was built (final state)

| File | Does |
|---|---|
| `terrain.py` | `load_dem` (rasterio windowed reads; applies scale/offset so packed files load), `slope_map`, `roughness_map` (3 × 3 plane fit), `cells_in_circle` (touch rule), `plane_fit`, `is_safe` with 4 user tolerances |
| `horizon.py` | `horizon_mask` (vectorised, 150 km; quick = 80 m DEM, precise = 5 m near + 80 m far), `refine_horizon`, `horizon_at`, per-point `.npy` cache |
| `sky.py` | JPL Horizons query, interval cache in `cache/*.csv` (never refetches an hour), visibility test, `snapshot`, `window_stats`, `compare`, cache clear |
| `regional.py` | One Horizons table per region centre, moved exactly to any point in the region (see §4.2) |
| `precompute.py` | Fetches and caches the 4 region-centre tables (1 Nov 2026 – 31 Dec 2027, hourly) and checks `regional.py` against a live Horizons table |
| `pack_data.py` | Writes small int32-centimetre, deflate-compressed copies of the DEMs to `data/packed/` for GitHub |
| `validate_illum.py` | Compares our sunlit % and Earth-visible % with NASA's average illumination maps (PGDA product 69) |
| `apply_updates.py` | One-off patcher: scale/offset in `load_dem`, `main.py` fallback to `data/packed/`, pandas in `requirements.txt`, `.gitignore` |
| `test_regional.py` | Tests for `regional.py` |
| `main.py` | The app: region picker, overview + 5 m detail maps with click selection, safety verdict, sunlight/Earth section, charts, landing windows, compare table, cache panel |

Data: 4 site DEMs (Site23 Malapert, Haworth, Site06 Nobile Rim 1, Site11 de Gerlache), 4 NASA slope maps, `LDEM_80S_80MPP_ADJ.TIF`, and NASA's illumination maps for validation.

---

## 4. Where we moved away from PLAN1, and why

### 4.1 Landing safety: 2 limits became 4, plus a plane fit

| PLAN1 | Final | Why |
|---|---|---|
| Cell is safe if slope < θ_max and roughness < rough_max (2 limits) | 4 user tolerances: cell slope, cell roughness, footprint slope, footprint roughness | Whether a site is landable depends on the mission and how much it will engineer. The tool reports what each spot actually measures instead of calling one site good and the rest bad. |
| Plane fit computed | Plane fit over the whole circle can **reject** a spot on its own | Catches a broad hump where every cell looks fine alone. |
| Roughness window not fixed | 3 × 3 cells (15 m) | Tested 3/5/7/9. Wider windows measure broad curvature, not bumps under the lander, and turn most slope-safe ground red. |

**Finding:** at NASA's 8° landed-tilt limit with a 100 m circle (1 m lander + 100 m uncertainty), 0 of 10 000 test spots in the Malapert tile pass. At 20° / 1.5 m cell and 20° / 12 m footprint, 1 091 pass. The 5 m map's own slope error is 1.5–2.5°, which is large next to an 8° limit.

### 4.2 Sun and Earth positions: per-point Horizons calls became regional tables

| PLAN1 | Final | Why |
|---|---|---|
| Query JPL Horizons for each clicked point, cache per point | `regional.py`: one Horizons table per region centre, moved exactly to the clicked point. `main.py` uses it. | The app works offline and responds fast in the demo, with no network calls. |

How it works: the Sun (≈1.5 × 10¹¹ m away) and Earth (≈3.8 × 10⁸ m away) point the same way in space from every spot in a 20–30 km region. Only the local up/north/east frame changes. So the centre's az/el is turned into a direction vector and re-expressed in the clicked point's frame.

Check against live Horizons at the Malapert test point (x 5700 m, y 120 900 m; 6.2 km from the centre; 721 hours):

| Quantity | Max difference |
|---|---|
| Sun azimuth | 0.0000° |
| Sun elevation | 0.0000° |
| Earth azimuth | 0.0010° |
| Earth elevation | 0.0001° |
| Sun elevation **without** the frame correction | 0.2052° |
| Sun-visible / Earth-visible flags | agree 100 % of hours |

The Earth error is the expected parallax, θ ≈ s / d_EM, where s is the distance from the centre: 6.2 × 10³ m / 3.84 × 10⁸ m ≈ 1.6 × 10⁻⁵ rad ≈ 0.0009°. Haworth, the largest tile (5 960 cells × 5 m ≈ 29.8 km), puts no point more than ≈ 21 km from its centre, so θ stays under ≈ 0.003°.

**Limit:** the tables cover 1 Nov 2026 – 31 Dec 2027. For dates outside that, the app shows an error telling the user to widen `T0`/`T1` in `precompute.py` and re-run it. It does not fall back to live calls.

### 4.3 Earth visibility rule

| PLAN1 | Final | Why |
|---|---|---|
| Visible iff el > h(az), for both bodies | Sun: el > h(az). Earth: **el + ρ > h(az)**, with ρ fixed at 0.95° | NASA's Earth-visibility map counts Earth as visible if any part of its disc is unobscured. Our centre-only rule read low in all 4 regions. |

ρ = asin(6.371 × 10⁶ / 3.844 × 10⁸) ≈ 0.95°. The true value varies from 0.90° to 1.02° with the Earth–Moon distance. Using a fixed value moves the edge by up to 0.07°, which we accepted rather than change the Horizons query.

Effect on the validation (mean Earth-visible %, ours vs NASA):

| Region | Before | After | NASA | Median diff, after |
|---|---|---|---|---|
| Malapert | 46.1 | 49.0 | 48.6 | 0.0 |
| Haworth | 30.3 | 35.6 | 38.9 | 2.3 |
| Nobile Rim 1 | 19.0 | 21.7 | 22.3 | 0.4 |
| de Gerlache | 27.6 | 30.5 | 31.7 | 1.3 |

What remains is consistent with our ~14-month window versus NASA's 18.6-year average (Earth's position wobbles by several degrees with libration).

### 4.4 Data in the repo

| PLAN1 | Final | Why |
|---|---|---|
| Repo holds code only; `setup_data.py` downloads and crops on first run | `data/packed/` holds int32-centimetre, deflate copies of every DEM, committed to GitHub; `data/raw/` is git-ignored; `main.py` falls back to `data/packed/` | The deployed app and the demo work without downloading anything. |

| File | Grid (cells) | Packed size | Max height change |
|---|---|---|---|
| Site23 (Malapert) | 4200 × 4200 | 21.5 MB | 0.51 cm |
| Haworth | 5960 × 5960 | 41.2 MB | 0.51 cm |
| Site06 (Nobile Rim 1) | 4000 × 4000 | 17.9 MB | 0.54 cm |
| Site11 (de Gerlache) | 3200 × 3200 | 12.0 MB | 0.50 cm |
| LDEM_80S_80MPP_ADJ | 5661 × 5388 | 58.3 MB | 0.54 cm |

All are under GitHub's 100 MB per-file limit; no-data cells are kept. The 0.5 cm rounding is far below the 5 m grid and the 0.3–0.5 m map error.

### 4.5 Horizon

| PLAN1 | Final | Why |
|---|---|---|
| One 80 m pass, variable step 20–500 m, coarse 1° then refine | Two modes: **Quick** (80 m DEM, screening) and **Precise** (5 m near + 80 m far); refine to 0.1° is a checkbox | Nearby terrain (under 2 km) sets the horizon in most directions, where the 80 m map can be up to 1.84° off. Fast screening first, detail only when needed. |
| Horizon formula h(az) = max over d of atan((z_terrain − z_site − h_mast − d²/(2R)) / d) | Same | Checked against exact 3D geometry: within 0.017°. |

### 4.6 App / UI changes

- Snapshot readout for Earth notes "(top edge of Earth's disc counts)", because Earth can show VISIBLE while its centre is up to 0.95° below the terrain line.
- Metric arrows removed (`delta_arrow="off"`; Streamlit 1.64).
- Outline of the selected area and landing circle is cyan on the elevation layer (yellow was hard to see on grey), yellow on the others.
- Run with `python3 -m streamlit run main.py` (the bare `streamlit` command is not on the PATH on this Mac).

### 4.7 Not built (as planned or by decision)

- Rover traverse paths (Dijkstra/A*): cut, as PLAN1 said.
- Whole-map "safe AND lit AND Earth-visible" heat map: stretch goal, not built.
- Custom-lander calculator and conservative mode: optional in PLAN1, not built.
- Streamlit Cloud deploy: not done; the demo uses slides instead (see §6).
- Sun as a 0.53° disc and an 18.6-year date range: suggested in review, listed as next steps.

---

## 5. Validation results

| Check | Result |
|---|---|
| Our slope vs NASA slope maps, 79 million cells over 4 regions | median difference 0.000–0.001°; same side of 8° for 99.97–100 % of cells |
| Horizon formula vs exact 3D geometry | within 0.017° |
| JPL Horizons link | Sun azimuth drifts −0.507 °/h (expected −0.508 °/h for one lunar day) |
| Regional transfer vs live Horizons | see §4.2 |
| Sunlit % vs NASA illumination maps, 144 points | correlation 0.984; median difference 0.8–1.6 percentage points per region |
| Earth-visible % vs NASA, after the disc rule | correlation 0.97–1.00 per region; see §4.3 |
| Shadow check | the 1 test point we find at 0 % sunlight is also 0 % in NASA's map |

Why the slope match is near-perfect: both come from the same LOLA heights. It shows our pipeline reproduces NASA's processing; real-world accuracy is limited by the map itself.

PLAN1 also listed a roughness comparison with NASA's `LDRM_*` maps and a PSR-list check. Neither result is recorded here.

---

## 6. Results

**A spot that passes all three tests** (Malapert, −85.9864°, 1.9215°; quick horizon; 13 Nov – 12 Dec 2026, 709 hourly steps; tolerances: cell 11.5° / 0.7 m, footprint 10.5° / 4.0 m):

| Quantity | Value |
|---|---|
| Worst cell slope / roughness | 11.0° / 0.61 m |
| Footprint slope / roughness | 2.7° / 3.95 m |
| Sunlit | 57.8 % |
| Earth visible | 62.9 % |
| Sun and Earth together | 48.5 % |
| Longest darkness | 179 h |
| Battery for longest dark (P_load = 200 W) | 35.8 kWh |
| Landing window | 18 Nov 00:00 – 2 Dec 07:00 |

For comparison, a rougher spot nearby (−86.005°, 1.500°) is not landing-safe, with 48.1 % sunlit, 41.6 % Earth visible and 268 h longest darkness.

**Mast effect** (Malapert test point, precise horizon, 13 Nov – 13 Dec 2026): sunlit 54.5 % at 0 m, 84.5 % at 5 m, 100 % at 10 m.

---

## 7. Challenges along the way

| Challenge | What we did |
|---|---|
| No spot passed at NASA's 8° limit with a 100 m circle | Made all 4 tolerances user-set and framed the result as a finding: it is why site choice matters |
| A 100 m plane fit picks up the massif's broad curvature, so footprint roughness runs high even where every cell passes | The passing spot needed a 4.0 m footprint-roughness limit; reported openly |
| Our Earth visibility read low against NASA's maps in all 4 regions | Found NASA's "any part of the disc" rule (PGDA product 69) and adopted it (§4.3) |
| Per-point Horizons calls need the network during the demo | Regional tables with an exact frame transfer (§4.2) |
| The DEMs are too large for GitHub as-is | int32-centimetre packed copies, all under 100 MB (§4.4) |
| The AI workspace could not reach NASA PGDA or JPL Horizons | Download and Horizons scripts were written there and run on the Mac |
| The link between the AI session and the project folder kept failing | Worked from attached files and replaced files by hand |
| zsh does not treat `#` as a comment when pasting, which broke a backup command | Commands are given without inline comments |
| The demo video was 48.5 s (limit 30 s), silent, low-resolution, and ended on a rejected spot | Submitted the 7-slide deck as the demo instead |
| Slide review (by Varun's dad): deck explained the method but never gave an answer | Added a user-experience slide and a result slide with the passing spot, battery sizing and a comparison table |

---

## 8. Stated limitations

1. Hazards smaller than a 5 m cell (boulders, small craters) are invisible.
2. The Sun is treated as a point, not a 0.53° disc (Earth is treated as a disc).
3. Earth above the horizon is necessary but not sufficient for comms: Deep Space Network station availability is not modelled.
4. Map error: height 0.3–0.5 m, slope 1.5–2.5° (Barker et al. 2021).
5. 14 months of Sun/Earth data versus NASA's 18.6-year averages; this may understate worst-case darkness.

---

## 9. Open items before submitting

- [ ] Push to a **public** GitHub repo: code, `data/packed/`, the four `cache/CENTRE_*.csv` tables (check `.gitignore` does not exclude them), README with run steps.
- [ ] Decide on the sidebar **Clear all** button: it deletes the `CENTRE_*` tables, after which the app needs the network to rebuild them.
- [ ] Update the README validation section with the §4.3 and §5 results.
- [ ] Slide 1: replace the image-credit placeholder.
- [ ] Export the deck to PDF and host it on a public link.
- [ ] Fill in the submission form, including the required **Use of AI** statement (built with Claude).

---

## 10. Sources

- PGDA product 78: high-resolution LOLA topography for south pole sites
- PGDA product 90: Barker et al. 2023, a new view of the lunar south pole
- PGDA product 69: lunar polar illumination (Mazarico et al. 2011)
- JPL Horizons
- Barker et al. 2021, Planetary & Space Science 203, 105119
- NASA, Artemis overview for Space Apps 2025 (Artemis III landing requirements)
- NASA Office of Inspector General, HLS audit, March 2026 (8° landed-tilt limit)
