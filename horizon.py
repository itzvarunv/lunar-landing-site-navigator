"""horizon.py - PLAN1 stage 2: terrain horizon around a point.

h(az) = max over d of atan( (z_terrain(d) - z_site - h_mast - d^2/(2R)) / d )

    az      : azimuth, degrees clockwise from local north (0 = north, 90 = east)
    d       : ground distance from the site along that azimuth (m)
    z_site  : surface height at the site (m)
    h_mast  : height of the observer (solar panel / antenna) above the surface (m)
    R       : Moon radius (m); d^2/(2R) is how far the curved surface drops away
"""
import os

import numpy as np

from terrain import R_MOON, load_dem

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
D_MAX = 150000.0     # search range (m)
STEP_NEAR = 20.0     # sample spacing next to the site (m)
STEP_FAR = 500.0     # sample spacing far out (m)
GROWTH = 0.02        # spacing grows by 2 % of the distance in between


def ray_distances(d_max=D_MAX, step_near=STEP_NEAR):
    """Distances (m) at which terrain is sampled along each ray: step_near steps
    next to the site, growing to 500 m far out."""
    d, out = step_near, []
    while d <= d_max:
        out.append(d)
        d += min(max(GROWTH * d, step_near), STEP_FAR)
    return np.array(out)


def north_east(x, y):
    """Unit vectors of local north and east at map point (x, y), in map coords.
    South polar stereographic: the pole is at (0, 0), so north points away from it."""
    rho = np.hypot(x, y)
    north = np.array([x / rho, y / rho])
    east = np.array([north[1], -north[0]])
    return north, east


def map_scale(x, y):
    """Stereographic scale factor k = map distance / ground distance at (x, y)."""
    return 1.0 + (x ** 2 + y ** 2) / (4 * R_MOON ** 2)


def sample(dem, x, y):
    """Bilinear interpolation of dem heights at map points x, y (arrays).
    Points outside the DEM or next to no-data give NaN."""
    z, D = dem["z"], dem["D"]
    fj = (x - dem["x0"]) / D
    fi = (dem["y0"] - y) / D
    j0 = np.floor(fj).astype(int)
    i0 = np.floor(fi).astype(int)
    ok = (i0 >= 0) & (j0 >= 0) & (i0 < z.shape[0] - 1) & (j0 < z.shape[1] - 1)
    i0c, j0c = np.where(ok, i0, 0), np.where(ok, j0, 0)
    ti, tj = fi - i0, fj - j0
    val = (z[i0c, j0c] * (1 - ti) * (1 - tj) + z[i0c, j0c + 1] * (1 - ti) * tj
           + z[i0c + 1, j0c] * ti * (1 - tj) + z[i0c + 1, j0c + 1] * ti * tj)
    return np.where(ok, val, np.nan)


def load_wide_dem(path, x, y, d_max=D_MAX):
    """Windowed read of the wide-area DEM: only the square that the rays can reach."""
    m = d_max * 1.02
    return load_dem(path, crop=(x - m, y - m, x + m, y + m))


def horizon_mask(dem, x, y, h_mast, az_deg=None, z_site=None, d_max=D_MAX, near_dem=None):
    """Horizon angle h (deg) for each azimuth in az_deg (default 0..359, 1 deg steps).

    dem      : wide-area DEM dict (see terrain.load_dem)
    x, y     : site position, map metres
    z_site   : site surface height (m); if None it is read from the DEM
    near_dem : None  -> QUICK mode: wide-area (80 m) DEM only, for screening.
               a 5 m site DEM -> PRECISE mode: wherever a ray is inside the 5 m
               DEM its heights are used, the wide-area DEM beyond its edge;
               rays are sampled every 5 m near the site instead of every 20 m.
    Vectorised: all azimuths are computed in one array operation.
    Returns (az_deg, h_deg).
    """
    if az_deg is None:
        az_deg = np.arange(360.0)
    az = np.radians(np.asarray(az_deg, dtype="float64"))
    if z_site is None:
        z_site = np.nan
        if near_dem is not None:
            z_site = float(sample(near_dem, np.array([x]), np.array([y]))[0])
        if np.isnan(z_site):
            z_site = float(sample(dem, np.array([x]), np.array([y]))[0])
    north, east = north_east(x, y)
    step_near = STEP_NEAR if near_dem is None else near_dem["D"]
    d = ray_distances(d_max, step_near)                        # ground distances (m)
    ux = np.cos(az) * north[0] + np.sin(az) * east[0]          # ray directions on the map
    uy = np.cos(az) * north[1] + np.sin(az) * east[1]
    k = map_scale(x, y)
    px = x + np.outer(ux, d) * k                               # sample points (n_az, n_d)
    py = y + np.outer(uy, d) * k
    zt = sample(dem, px, py)
    if near_dem is not None:
        zn = sample(near_dem, px, py)
        zt = np.where(np.isnan(zn), zt, zn)
    ang = np.degrees(np.arctan((zt - z_site - h_mast - d ** 2 / (2 * R_MOON)) / d))
    h = np.nanmax(np.where(np.isnan(ang), -90.0, ang), axis=1)
    return np.asarray(az_deg, dtype="float64"), h


def refine_horizon(mask, dem, x, y, h_mast, az_lo, az_hi, step=0.1, z_site=None, near_dem=None):
    """Recompute the horizon every `step` deg between az_lo and az_hi and merge
    it into mask = (az_deg, h_deg). Returns the new, sorted mask."""
    az_new = np.arange(az_lo, az_hi + step / 2, step) % 360.0
    az_new, h_new = horizon_mask(dem, x, y, h_mast, az_new, z_site, near_dem=near_dem)
    az = np.concatenate([mask[0], az_new])
    h = np.concatenate([mask[1], h_new])
    az, idx = np.unique(np.round(az, 6), return_index=True)
    return az, h[idx]


def horizon_at(mask, az_deg):
    """Horizon angle (deg) at any azimuth, by linear interpolation (wraps at 360)."""
    az, h = mask
    return np.interp(np.asarray(az_deg) % 360.0, az, h, period=360.0)


def cache_path(region, x, y, h_mast, mode):
    name = f"{region}_x{x:.0f}_y{y:.0f}_mast{h_mast:g}_{mode}.npy"
    return os.path.join(CACHE, name.replace(" ", "_"))


def cached_horizon(region, wide_path, x, y, h_mast, near_dem=None):
    """Horizon mask for a point, from cache if present, else computed and saved.
    near_dem=None -> quick mode (80 m only); a 5 m site DEM -> precise mode."""
    mode = "quick" if near_dem is None else "precise"
    path = cache_path(region, x, y, h_mast, mode)
    if os.path.exists(path):
        a = np.load(path)
        return a[0], a[1]
    dem = load_wide_dem(wide_path, x, y)
    mask = horizon_mask(dem, x, y, h_mast, near_dem=near_dem)
    os.makedirs(CACHE, exist_ok=True)
    np.save(path, np.vstack(mask))
    return mask
