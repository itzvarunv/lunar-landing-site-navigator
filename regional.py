"""regional.py - one Horizons table per region, moved exactly to any point inside it.

Why: the Sun (150 million km) and Earth (384 400 km) are so far away that their
DIRECTION in space is the same for every point inside a 20-30 km region (Earth
parallax over 20 km: 20 / 384400 rad = 0.003 deg). What changes from point to
point is only the local compass: which way is up, north and east. So we fetch
az/el once at the region centre C, turn it into a direction vector d, and
re-express d in the local frame of any point P (plan's ENU maths).

Symbols
    phi, lam : latitude, longitude (deg); map x, y in south polar stereographic metres
    U, N, E  : local up, north, east unit vectors
    az, el   : azimuth (deg, clockwise from north), elevation (deg)
    d        : unit vector toward the Sun or Earth, Moon-fixed frame
"""
import numpy as np
import pandas as pd

R_MOON = 1737400.0


def xy_to_latlon(x, y):
    rho = np.hypot(x, y)
    phi = -(90.0 - np.degrees(2 * np.arctan(rho / (2 * R_MOON))))
    lam = np.degrees(np.arctan2(x, y))
    return phi, lam


def enu(phi_deg, lam_deg):
    """Local east, north, up unit vectors (Moon-fixed frame) at latitude phi, longitude lam.
    U = [cos(phi)cos(lam), cos(phi)sin(lam), sin(phi)]
    E = [-sin(lam), cos(lam), 0]
    N = [-sin(phi)cos(lam), -sin(phi)sin(lam), cos(phi)]"""
    p, l = np.radians(phi_deg), np.radians(lam_deg)
    U = np.array([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)])
    E = np.array([-np.sin(l), np.cos(l), 0.0])
    N = np.array([-np.sin(p) * np.cos(l), -np.sin(p) * np.sin(l), np.cos(p)])
    return E, N, U


def azel_to_vec(az, el, frame):
    """d = cos(el)sin(az) E + cos(el)cos(az) N + sin(el) U   (rows = time steps)."""
    E, N, U = frame
    a, e = np.radians(np.asarray(az, float)), np.radians(np.asarray(el, float))
    return (np.outer(np.cos(e) * np.sin(a), E) + np.outer(np.cos(e) * np.cos(a), N)
            + np.outer(np.sin(e), U))


def vec_to_azel(d, frame):
    """el = asin(d . U), az = atan2(d . E, d . N) mod 360."""
    E, N, U = frame
    el = np.degrees(np.arcsin(np.clip(d @ U, -1, 1)))
    az = np.degrees(np.arctan2(d @ E, d @ N)) % 360.0
    return az, el


def transfer(table, lat_c, lon_c, lat_p, lon_p):
    """Sun/Earth table computed at centre C -> the same table as seen from point P."""
    fc, fp = enu(lat_c, lon_c), enu(lat_p, lon_p)
    out = table[["time"]].copy()
    for body in ("sun", "earth"):
        d = azel_to_vec(table[f"{body}_az"], table[f"{body}_el"], fc)
        out[f"{body}_az"], out[f"{body}_el"] = vec_to_azel(d, fp)
    return out.reset_index(drop=True)
