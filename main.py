"""main.py - Lunar Landing Site Navigator (PLAN1).

Run:  streamlit run main.py
Stage 1 (landing safety) UI. Stages 2-3 (sunlight, Earth visibility) plug in below.
"""
import os

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import horizon as hz
import precompute as pc
import regional as rg
import sky
import terrain as t

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
if not os.path.isdir(RAW) or not any(f.lower().endswith(".tif") for f in os.listdir(RAW)):
    RAW = os.path.join(HERE, "data", "packed")       # small copies committed to GitHub
WIDE = os.path.join(RAW, "LDEM_80S_80MPP_ADJ.TIF")     # 80 m wide-area DEM (horizon)

# Artemis III regions that have a 5 m LOLA DEM (PGDA product 78)
SITES = {
    "Malapert Massif (Site23)": "Site23_final_adj_5mpp_surf.tif",
    "Haworth": "Haworth_final_adj_5mpp_surf.tif",
    "Nobile Rim 1 (Site06)": "Site06_final_adj_5mpp_surf.tif",
    "de Gerlache Rim (Site11)": "Site11_final_adj_5mpp_surf.tif",
}
OVERVIEW_STEP = 10      # overview map shows 1 pixel per 10 x 10 cells
DETAIL_HALF = 150       # detail view = 301 x 301 cells around the picked area
ROUGH_K = 3             # roughness window, cells (decided: 3 x 3)

st.set_page_config(page_title="Lunar Landing Site Navigator", layout="wide")


@st.cache_resource(show_spinner="Loading terrain and computing slope + roughness...")
def load_site(filename):
    dem = t.load_dem(os.path.join(RAW, filename))
    return dem, t.slope_map(dem), t.roughness_map(dem, ROUGH_K)


@st.cache_data(show_spinner=False)
def region_table(site):
    """Precomputed hourly Sun/Earth table at the region centre (cache/CENTRE_*.csv,
    written by precompute.py) and the centre's latitude, longitude (deg)."""
    cx, cy, lat_c, lon_c, z_c = pc.region_centre(os.path.join(RAW, SITES[site]))
    table, _ = sky.horizons_query("CENTRE " + site, cx, cy, lat_c, lon_c, z_c / 1000.0, pc.T0, pc.T1)
    return table, lat_c, lon_c


def block_mean(a, step):
    """Average a 2D array over step x step blocks (for the overview map)."""
    n_i, n_j = (a.shape[0] // step) * step, (a.shape[1] // step) * step
    return a[:n_i, :n_j].reshape(n_i // step, step, n_j // step, step).mean(axis=(1, 3))


def click_grid(xs, ys, every):
    """Invisible points laid over a heatmap so that a click returns x, y."""
    gx, gy = np.meshgrid(xs[::every], ys[::every])
    return go.Scattergl(
        x=gx.ravel(), y=gy.ravel(), mode="markers", hoverinfo="none",
        marker=dict(size=8, opacity=0),
        selected=dict(marker=dict(opacity=0)), unselected=dict(marker=dict(opacity=0)),
        showlegend=False)


def picked_point(event):
    """x, y (km) of the clicked point, or None."""
    try:
        p = event["selection"]["points"]
        return (p[0]["x"], p[0]["y"]) if p else None
    except (KeyError, TypeError, IndexError):
        return None


def circle_xy(x, y, r, n=90):
    a = np.linspace(0, 2 * np.pi, n)
    return x + r * np.cos(a), y + r * np.sin(a)


LAYERS = {
    "Safety (blue = within tolerance)": None,
    "Slope (deg)": "Turbo",
    "Roughness (m)": "Turbo",
    "Elevation (m)": "Greys_r",
}
SAFE_COLORS = [[0, "#d62728"], [1, "#1f77b4"]]

# ---------------- sidebar ----------------
st.sidebar.title("Lunar Landing Site Navigator")
available = [n for n, f in SITES.items() if os.path.exists(os.path.join(RAW, f))]
if not available:
    st.error("No DEM files found in data/raw/. Run:  python3 setup_data.py")
    st.stop()
site = st.sidebar.selectbox("Region", available)
missing = [n for n in SITES if n not in available]
if missing:
    st.sidebar.caption("Not downloaded yet: " + ", ".join(missing))

st.sidebar.subheader("Cell tolerances")
theta_max = st.sidebar.slider("Max cell slope (deg)", 1.0, 30.0, 8.0, 0.5)
rough_max = st.sidebar.slider("Max cell roughness (m)", 0.1, 3.0, 0.5, 0.1)
st.sidebar.subheader("Footprint tolerances")
fp_theta_max = st.sidebar.slider("Max footprint slope (deg)", 1.0, 30.0, 8.0, 0.5)
fp_rough_max = st.sidebar.slider("Max footprint roughness (m)", 0.1, 20.0, 0.5, 0.1)
st.sidebar.subheader("Landing footprint")
r_lander = st.sidebar.number_input("Lander radius (m)", 0.5, 100.0, 1.0, 0.5)
r_unc = st.sidebar.number_input("Landing uncertainty (m)", 0.0, 1000.0, 100.0, 10.0)
r = r_lander + r_unc
layer = st.sidebar.radio("Map layer", list(LAYERS))
OUTLINE = "cyan" if layer == "Elevation (m)" else "yellow"   # yellow is hard to see on grey

st.sidebar.subheader("Sunlight and Earth visibility")
h_mast = st.sidebar.slider("Mast height (m)", 0.0, 10.0, 0.0, 0.5)
precise = st.sidebar.radio("Horizon mode", ["Quick (80 m DEM, screening)",
                                            "Precise (5 m near + 80 m far)"]).startswith("Precise")
refine = st.sidebar.checkbox("Refine horizon to 0.1 deg where the Sun and Earth pass")
start_day = st.sidebar.date_input("Start date (UTC)", date.today())
n_days = st.sidebar.number_input("Window length (days)", 1.0, 400.0, 29.5, 0.5)
min_sun = st.sidebar.slider("Min sunlit time (%)", 0, 100, 50, 5)
min_earth = st.sidebar.slider("Min Earth-visible time (%)", 0, 100, 50, 5)
p_load = st.sidebar.number_input("Power draw while dark (W)", 0.0, 100000.0, 200.0, 50.0)

st.sidebar.subheader("Cache")
st.sidebar.caption(f"{sky.cache_size_mb():.2f} MB stored")
cc = st.sidebar.columns(2)
if cc[0].button("Clear region"):
    st.sidebar.caption(f"Removed {sky.clear_cache(site)} file(s)")
if cc[1].button("Clear all"):
    st.sidebar.caption(f"Removed {sky.clear_cache()} file(s)")

dem, slope, rough = load_site(SITES[site])
z, D = dem["z"], dem["D"]
n_i, n_j = z.shape
B = t.safe_set(slope, rough, theta_max, rough_max)


def layer_data(rows, cols, step):
    """Values of the chosen layer for a block of cells, averaged over step."""
    src = {"Safety (blue = within tolerance)": B.astype("float32"), "Slope (deg)": slope,
           "Roughness (m)": rough, "Elevation (m)": z}[layer]
    a = src[rows, cols]
    return block_mean(a, step) if step > 1 else a


def heat(vals, xs, ys):
    if LAYERS[layer] is None:
        return go.Heatmap(z=vals, x=xs, y=ys, zmin=0, zmax=1, colorscale=SAFE_COLORS,
                          colorbar=dict(title="safe fraction"), hoverinfo="skip")
    return go.Heatmap(z=vals, x=xs, y=ys, colorscale=LAYERS[layer],
                      colorbar=dict(title=layer), hoverinfo="skip")


def base_layout(fig, title):
    fig.update_layout(title=title, height=560, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(title="x (km)", constrain="domain"),
                      yaxis=dict(title="y (km)", scaleanchor="x", constrain="domain"),
                      clickmode="event+select", dragmode="pan")


key = f"picks_{site}"
if key not in st.session_state:
    st.session_state[key] = {"area": None, "point": None}
picks = st.session_state[key]

st.caption(f"{site}  |  {n_j * D / 1000:.0f} x {n_i * D / 1000:.0f} km at {D:g} m per cell  |  "
           f"{B.mean() * 100:.1f}% of cells within cell tolerances  |  "
           f"check radius r = {r:g} m")
left, right = st.columns(2)

# ---------------- overview ----------------
with left:
    S = OVERVIEW_STEP
    vals = layer_data(slice(None), slice(None), S)
    xs = (dem["x0"] + (np.arange(vals.shape[1]) * S + (S - 1) / 2) * D) / 1000
    ys = (dem["y0"] - (np.arange(vals.shape[0]) * S + (S - 1) / 2) * D) / 1000
    fig = go.Figure([heat(vals, xs, ys), click_grid(xs, ys, 3)])
    if picks["area"]:
        ax, ay = picks["area"]
        h = DETAIL_HALF * D / 1000
        fig.add_shape(type="rect", x0=ax - h, x1=ax + h, y0=ay - h, y1=ay + h,
                      line=dict(color=OUTLINE, width=2))
    base_layout(fig, "1. Click an area")
    ev = st.plotly_chart(fig, on_select="rerun", selection_mode="points",
                         key=f"overview_{site}", width="stretch")
    p = picked_point(ev)
    if p and p != picks["area"]:
        picks["area"], picks["point"] = p, None
        st.rerun()

# ---------------- detail ----------------
with right:
    if not picks["area"]:
        st.info("Click the left map to open a full-resolution view of that area.")
    else:
        ci, cj = t.xy_to_pixel(dem, picks["area"][0] * 1000, picks["area"][1] * 1000)
        i0 = int(np.clip(ci - DETAIL_HALF, 0, n_i - 2 * DETAIL_HALF - 1))
        j0 = int(np.clip(cj - DETAIL_HALF, 0, n_j - 2 * DETAIL_HALF - 1))
        rows, cols = slice(i0, i0 + 2 * DETAIL_HALF + 1), slice(j0, j0 + 2 * DETAIL_HALF + 1)
        vals = layer_data(rows, cols, 1)
        xs = (dem["x0"] + np.arange(cols.start, cols.stop) * D) / 1000
        ys = (dem["y0"] - np.arange(rows.start, rows.stop) * D) / 1000
        fig = go.Figure([heat(vals, xs, ys), click_grid(xs, ys, 2)])
        if picks["point"]:
            px, py = picks["point"]
            cx, cy = circle_xy(px, py, r / 1000)
            fig.add_trace(go.Scatter(x=cx, y=cy, mode="lines", hoverinfo="skip",
                                     line=dict(color=OUTLINE, width=2), showlegend=False))
        base_layout(fig, "2. Click a landing point")
        ev = st.plotly_chart(fig, on_select="rerun", selection_mode="points",
                             key=f"detail_{site}_{picks['area']}", width="stretch")
        p = picked_point(ev)
        if p and p != picks["point"]:
            picks["point"] = p
            st.rerun()

# ---------------- result ----------------
if picks["point"]:
    px, py = picks["point"][0] * 1000, picks["point"][1] * 1000
    res = t.is_safe(dem, slope, rough, px, py, r, theta_max, rough_max, fp_theta_max, fp_rough_max)
    lat, lon = t.xy_to_latlon(px, py)
    st.subheader(f"Landing point: {lat:.4f} deg lat, {lon:.4f} deg lon")
    if res["warning"]:
        st.warning(res["warning"])
    (st.success if res["ok"] else st.error)(("SAFE - " if res["ok"] else "REJECTED - ") + res["reason"])
    if res["worst_cell_slope"] is not None:
        c = st.columns(4)
        c[0].metric("Worst cell slope", f"{res['worst_cell_slope']:.1f} deg", f"limit {theta_max:g}", delta_color="off", delta_arrow="off")
        c[1].metric("Worst cell roughness", f"{res['worst_cell_roughness']:.2f} m", f"limit {rough_max:g}", delta_color="off", delta_arrow="off")
        if res["footprint_slope"] is not None:
            c[2].metric("Footprint slope", f"{res['footprint_slope']:.1f} deg", f"limit {fp_theta_max:g}", delta_color="off", delta_arrow="off")
            c[3].metric("Footprint roughness", f"{res['footprint_roughness']:.2f} m", f"limit {fp_rough_max:g}", delta_color="off", delta_arrow="off")
        st.caption(f"{res['n_cells']} cells checked. The four numbers above are the tolerances "
                   "a mission would need to land at this point.")

# ---------------- sunlight + Earth visibility ----------------
if picks["point"]:
    st.divider()
    st.subheader("Sunlight and Earth visibility")
    if not os.path.exists(WIDE):
        st.error("Wide-area DEM missing (LDEM_80S_80MPP_ADJ.TIF). Run:  python3 setup_data.py")
        st.stop()
    z_site = float(hz.sample(dem, np.array([px]), np.array([py]))[0])
    t0 = datetime.combine(start_day, datetime.min.time())
    t1 = t0 + timedelta(days=float(n_days))
    p0, p1 = pd.Timestamp(pc.T0), pd.Timestamp(pc.T1)
    if t0 < p0 or t1 > p1:
        st.error(f"Dates outside the precomputed range ({p0:%Y-%m-%d} to {p1:%Y-%m-%d %H:%M} UTC). "
                 "Widen T0 / T1 in precompute.py, then run:  python3 precompute.py")
        st.stop()
    try:
        with st.spinner("Loading Sun and Earth positions (precomputed region table)..."):
            full, lat_c, lon_c = region_table(site)
    except Exception as e:
        st.error(f"Could not load the precomputed Sun/Earth table for {site}: {e}. Run:  python3 precompute.py")
        st.stop()
    part = full[(full["time"] >= t0) & (full["time"] <= t1)]
    table = rg.transfer(part, lat_c, lon_c, float(lat), float(lon))
    mask = hz.cached_horizon(site, WIDE, px, py, h_mast, near_dem=dem if precise else None)
    if refine:
        wide = hz.load_wide_dem(WIDE, px, py)
        for a in (table["sun_az"], table["earth_az"]):
            lo, hi = float(a.min()), float(a.max())
            if hi - lo > 300:                       # track wraps through north: do the full circle
                lo, hi = 0.0, 359.9
            mask = hz.refine_horizon(mask, wide, px, py, h_mast, lo, hi, z_site=z_site,
                                     near_dem=dem if precise else None)
    vis = sky.add_visibility(table, mask)
    stats = sky.window_stats(vis, p_load_w=p_load)
    st.caption(f"{t0:%Y-%m-%d} to {t1:%Y-%m-%d %H:%M} UTC  |  {stats['hours']} hourly steps  |  "
               f"{'precise' if precise else 'quick'} horizon, {mask[0].size} azimuths, mast {h_mast:g} m  |  "
               f"Sun/Earth: precomputed region table, moved to this point")

    m = st.columns(5)
    m[0].metric("Sunlit", f"{stats['illum_pct']:.1f} %")
    m[1].metric("Earth visible", f"{stats['earth_pct']:.1f} %")
    m[2].metric("Sun and Earth together", f"{stats['both_pct']:.1f} %")
    m[3].metric("Longest darkness", f"{stats['t_dark_h']:.0f} h")
    m[4].metric("Battery for longest dark", f"{stats['battery_wh'] / 1000:.1f} kWh")

    ok_l, ok_e = stats["illum_pct"] >= min_sun, stats["earth_pct"] >= min_earth
    verdict = [("Landing safety", res["ok"]), (f"Sunlit >= {min_sun} %", ok_l),
               (f"Earth visible >= {min_earth} %", ok_e)]
    line = "   |   ".join(f"{name}: {'PASS' if ok else 'FAIL'}" for name, ok in verdict)
    (st.success if all(ok for _, ok in verdict) else st.error)(
        ("CANDIDATE SITE - " if all(ok for _, ok in verdict) else "NOT A CANDIDATE - ") + line)

    # snapshot at one time
    times = list(vis["time"])
    when = st.select_slider("Snapshot time (UTC)", options=times, value=times[0],
                            format_func=lambda v: f"{v:%d %b %H:%M}")
    snap = sky.snapshot(vis, when)
    c = st.columns(2)
    c[0].metric("Sun", "VISIBLE" if snap["sun_up"] else "hidden",
                f"elevation {snap['sun_el']:.2f} deg, terrain {float(hz.horizon_at(mask, snap['sun_az'])):.2f} deg", delta_color="off", delta_arrow="off")
    c[1].metric("Earth", "VISIBLE" if snap["earth_up"] else "hidden",
                f"elevation {snap['earth_el']:.2f} deg, terrain {float(hz.horizon_at(mask, snap['earth_az'])):.2f} deg (top edge of Earth's disc counts)", delta_color="off", delta_arrow="off")

    # elevation vs time, with the terrain horizon in the body's direction
    fig = go.Figure()
    for body, color in (("sun", "#f5c518"), ("earth", "#4aa3ff")):
        fig.add_trace(go.Scatter(x=vis["time"], y=vis[f"{body}_el"], name=f"{body.title()} elevation",
                                 line=dict(color=color, width=2)))
        fig.add_trace(go.Scatter(x=vis["time"], y=hz.horizon_at(mask, vis[f"{body}_az"]),
                                 name=f"Terrain in the {body.title()}'s direction",
                                 line=dict(color=color, width=1, dash="dot")))
    fig.add_vline(x=when, line=dict(color="white", width=1))
    for w0, w1 in stats["windows"]:
        fig.add_vrect(x0=w0, x1=w1, fillcolor="#2ecc71", opacity=0.15, line_width=0)
    fig.update_layout(title="Elevation over time (green = Sun and Earth both visible: landing windows)",
                      height=380, margin=dict(l=10, r=10, t=40, b=10), yaxis_title="degrees",
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, key="el_time", width="stretch")

    # horizon profile with the Sun and Earth tracks
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mask[0], y=mask[1], name="Terrain horizon", fill="tozeroy",
                             line=dict(color="#888888", width=1)))
    for body, color in (("sun", "#f5c518"), ("earth", "#4aa3ff")):
        fig.add_trace(go.Scatter(x=vis[f"{body}_az"], y=vis[f"{body}_el"], mode="markers",
                                 name=f"{body.title()} track", marker=dict(color=color, size=3)))
    fig.add_trace(go.Scatter(x=[snap["sun_az"], snap["earth_az"]], y=[snap["sun_el"], snap["earth_el"]],
                             mode="markers", name="At snapshot time",
                             marker=dict(color="white", size=11, symbol="circle-open", line=dict(width=2))))
    fig.update_layout(title="Horizon seen from the landing point", height=380,
                      margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(title="azimuth (deg, 0 = north, 90 = east)", range=[0, 360], dtick=45),
                      yaxis_title="degrees", legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, key="horizon", width="stretch")

    if stats["windows"]:
        st.caption("Landing windows (Sun and Earth both visible): " + ";  ".join(
            f"{a:%d %b %H:%M} to {b:%d %b %H:%M}" for a, b in stats["windows"]))

    # ---------------- compare ----------------
    st.divider()
    st.subheader("Compare sites")
    saved = st.session_state.setdefault("compare", {})
    label = f"{site.split(' (')[0]} {lat:.3f}, {lon:.3f} | mast {h_mast:g} m"
    b = st.columns([1, 1, 4])
    if b[0].button("Add this point"):
        saved[label] = dict(stats, safe=res["ok"])
    if b[1].button("Clear table"):
        saved.clear()
    if saved:
        tab = sky.compare(saved)
        tab.insert(1, "Landing safe", ["yes" if v["safe"] else "no" for v in saved.values()])
        st.dataframe(tab, hide_index=True, width="stretch")
    else:
        st.caption("Pick a point, then press 'Add this point'. Repeat for other points or regions.")
