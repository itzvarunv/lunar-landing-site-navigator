"""terrain.py - PLAN1 stage 1: landing safety.

A DEM is passed around as a dict:
    z  : 2D numpy array of surface heights (m). z[i, j], i = row, j = column.
    D  : cell size (m)
    x0 : x (m) of the centre of cell (0, 0)   -> x = x0 + j*D
    y0 : y (m) of the centre of cell (0, 0)   -> y = y0 - i*D
x, y are south polar stereographic metres (pole at 0, 0).
"""
import numpy as np

R_MOON = 1737400.0  # Moon radius R (m)


def load_dem(path, crop=None):
    """Read a GeoTIFF. crop = (x_min, y_min, x_max, y_max) in metres, or None.

    Uses a rasterio windowed read, so only the crop is loaded into memory.
    """
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(path) as src:
        if crop is None:
            window = None
            transform = src.transform
        else:
            window = from_bounds(*crop, transform=src.transform)
            window = window.round_offsets().round_lengths()
            transform = src.window_transform(window)
        z = src.read(1, window=window).astype("float32")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        if src.scales[0] != 1.0 or src.offsets[0] != 0.0:   # packed files store centimetres
            z = z * np.float32(src.scales[0]) + np.float32(src.offsets[0])
    D = transform.a
    return {"z": z, "D": D, "x0": transform.c + D / 2, "y0": transform.f - D / 2}


def pixel_to_xy(dem, i, j):
    """Cell (i, j) -> x, y (m)."""
    return dem["x0"] + j * dem["D"], dem["y0"] - i * dem["D"]


def xy_to_pixel(dem, x, y):
    """x, y (m) -> nearest cell (i, j)."""
    j = int(round((x - dem["x0"]) / dem["D"]))
    i = int(round((dem["y0"] - y) / dem["D"]))
    return i, j


def xy_to_latlon(x, y):
    """South polar stereographic x, y (m) -> latitude phi, longitude lambda (deg)."""
    rho = np.sqrt(x ** 2 + y ** 2)
    phi = -(90.0 - np.degrees(2 * np.arctan(rho / (2 * R_MOON))))
    lam = np.degrees(np.arctan2(x, y))
    return phi, lam


def slope_map(dem):
    """Slope (deg) per cell from the central-difference gradient.

    dz/dx = (z[i, j+1] - z[i, j-1]) / (2D)
    dz/dy = (z[i-1, j] - z[i+1, j]) / (2D)
    slope = atan(sqrt((dz/dx)^2 + (dz/dy)^2))
    Border cells and cells next to no-data come out as NaN.
    """
    z, D = dem["z"], dem["D"]
    slope = np.full(z.shape, np.nan, dtype="float32")
    dzdx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * D)
    dzdy = (z[:-2, 1:-1] - z[2:, 1:-1]) / (2 * D)
    slope[1:-1, 1:-1] = np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))
    return slope


def roughness_map(dem, k=3):
    """Roughness (m) per cell: fit a plane to the k x k window around the cell,
    roughness = max |z - plane| inside that window. k must be odd.
    Border cells and windows touching no-data come out as NaN.
    """
    z, D = dem["z"], dem["D"]
    h = k // 2
    rough = np.full(z.shape, np.nan, dtype="float32")
    off = (np.arange(k) - h) * D            # window offsets (m), symmetric about 0
    sxx = k * np.sum(off ** 2)              # sum of x^2 over the window
    xs = off[None, :]                       # x varies along columns
    ys = -off[:, None]                      # y decreases as row index grows
    step = 256                              # rows per chunk, keeps memory small
    n_rows = z.shape[0] - 2 * h
    for r0 in range(0, n_rows, step):
        r1 = min(r0 + step, n_rows)
        block = z[r0:r1 + 2 * h]
        win = np.lib.stride_tricks.sliding_window_view(block, (k, k))
        c = win.mean(axis=(2, 3))
        a = (win * xs).sum(axis=(2, 3)) / sxx
        b = (win * ys).sum(axis=(2, 3)) / sxx
        plane = c[..., None, None] + a[..., None, None] * xs + b[..., None, None] * ys
        rough[r0 + h:r1 + h, h:-h] = np.abs(win - plane).max(axis=(2, 3))
    return rough


def safe_set(slope, roughness, theta_max, rough_max):
    """B: boolean map, True where slope < theta_max AND roughness < rough_max.
    NaN (no data) -> False (red)."""
    return (slope < theta_max) & (roughness < rough_max)


def cells_in_circle(dem, x0, y0, r):
    """Y: every cell the circle (centre x0, y0, radius r, metres) TOUCHES.

    Returns (rows, cols, crosses_edge). A cell is touched when the nearest
    point of its square to the circle centre is within r.
    """
    D = dem["D"]
    n_i, n_j = dem["z"].shape
    fj = (x0 - dem["x0"]) / D               # centre in fractional cell units
    fi = (dem["y0"] - y0) / D
    rc = r / D
    crosses_edge = (fj - rc < -0.5 or fj + rc > n_j - 0.5
                    or fi - rc < -0.5 or fi + rc > n_i - 0.5)
    i_lo = max(int(np.floor(fi - rc)), 0)
    i_hi = min(int(np.ceil(fi + rc)), n_i - 1)
    j_lo = max(int(np.floor(fj - rc)), 0)
    j_hi = min(int(np.ceil(fj + rc)), n_j - 1)
    ii, jj = np.meshgrid(np.arange(i_lo, i_hi + 1), np.arange(j_lo, j_hi + 1), indexing="ij")
    di = np.maximum(np.abs(ii - fi) - 0.5, 0)   # distance to nearest point of the cell
    dj = np.maximum(np.abs(jj - fj) - 0.5, 0)
    touch = di ** 2 + dj ** 2 <= rc ** 2
    return ii[touch], jj[touch], crosses_edge


def plane_fit(dem, rows, cols):
    """Least-squares plane z = a*x + b*y + c through the given cells.

    Solves A^T A p = A^T z for p = [a, b, c].
    Returns a, b, c, footprint_slope (deg), roughness (m) = max |z - plane|.
    """
    x, y = pixel_to_xy(dem, rows, cols)
    z = dem["z"][rows, cols].astype("float64")
    xm, ym = x.mean(), y.mean()             # centre the coordinates (numerical stability)
    A = np.column_stack([x - xm, y - ym, np.ones_like(z)])
    (a, b, c0), *_ = np.linalg.lstsq(A, z, rcond=None)
    resid = z - A @ np.array([a, b, c0])
    c = c0 - a * xm - b * ym
    slope = np.degrees(np.arctan(np.sqrt(a ** 2 + b ** 2)))
    return a, b, c, slope, float(np.abs(resid).max())


def is_safe(dem, slope, roughness, x0, y0, r,
            theta_max, rough_max, fp_theta_max, fp_rough_max):
    """Landing check for a circle (centre x0, y0, radius r, metres).

    All four tolerances are given by the user:
        theta_max    : max slope of any single cell (deg)
        rough_max    : max roughness of any single cell (m)
        fp_theta_max : max slope of the plane fitted to the whole footprint (deg)
        fp_rough_max : max |z - plane| over the whole footprint (m)
    Accept iff every touched cell is within the cell tolerances (Y subset of B)
    AND the footprint plane fit is within the footprint tolerances.

    Also returns what the spot actually measures (worst_cell_slope,
    worst_cell_roughness, footprint_slope, footprint_roughness), i.e. the
    tolerances a mission would need to land here.
    """
    out = {"ok": False, "reason": "", "warning": "", "n_cells": 0, "n_unsafe": 0,
           "worst_cell_slope": None, "worst_cell_roughness": None,
           "footprint_slope": None, "footprint_roughness": None}
    if r < dem["D"]:
        out["warning"] = (f"Footprint radius {r:g} m is smaller than the map "
                          f"resolution {dem['D']:g} m - this result means little.")
    rows, cols, crosses_edge = cells_in_circle(dem, x0, y0, r)
    if crosses_edge or rows.size == 0:
        out["reason"] = "Too close to the map boundary."
        return out
    out["n_cells"] = int(rows.size)
    s_y, r_y = slope[rows, cols], roughness[rows, cols]
    if np.isnan(dem["z"][rows, cols]).any() or np.isnan(s_y).any() or np.isnan(r_y).any():
        out["reason"] = "Footprint contains no-data cells."
        return out
    out["worst_cell_slope"] = float(s_y.max())
    out["worst_cell_roughness"] = float(r_y.max())
    if rows.size >= 3:
        _, _, _, fs, fr = plane_fit(dem, rows, cols)
        out["footprint_slope"], out["footprint_roughness"] = float(fs), fr
    n_unsafe = int((~((s_y < theta_max) & (r_y < rough_max))).sum())
    out["n_unsafe"] = n_unsafe
    problems = []
    if n_unsafe:
        problems.append(f"{n_unsafe} of {rows.size} footprint cells are outside tolerance "
                        f"(worst cell: {out['worst_cell_slope']:.1f} deg, "
                        f"{out['worst_cell_roughness']:.2f} m)")
    if out["footprint_slope"] is not None and out["footprint_slope"] >= fp_theta_max:
        problems.append(f"footprint slope {out['footprint_slope']:.1f} deg >= {fp_theta_max:g} deg")
    if out["footprint_roughness"] is not None and out["footprint_roughness"] >= fp_rough_max:
        problems.append(f"footprint roughness {out['footprint_roughness']:.2f} m >= {fp_rough_max:g} m")
    if problems:
        out["reason"] = "; ".join(problems) + "."
        return out
    out["ok"] = True
    out["reason"] = "All footprint cells and the footprint plane fit are within tolerance."
    return out
