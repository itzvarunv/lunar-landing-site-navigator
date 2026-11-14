"""Checks horizon.py: made-up terrain with known answers, then the real DEMs."""
import time
import numpy as np
import terrain as t
import horizon as hz

R = t.R_MOON
# ---- 1. made-up: flat sphere surface (z = 0 everywhere), observer on a 10 m mast.
# Exact horizon dip for eye height H on a sphere: -acos(R / (R + H)).
n = 2001; Dc = 200.0
flat = {"z": np.zeros((n, n), "float32"), "D": Dc, "x0": -200000.0, "y0": 320000.0}
x0, y0 = 0.0, 120000.0
az, h = hz.horizon_mask(flat, x0, y0, 10.0)
print("flat + 10 m mast : h = %.4f deg (exact dip %.4f)" % (h.mean(), -np.degrees(np.arccos(R / (R + 10)))))

# ---- 2. made-up: a 1000 m block 20 km due EAST of the site. Expect a peak at az = 90
# of atan((1000 - 20000^2/2R)/20000) and nothing special at az = 270.
wall = {"z": np.zeros((n, n), "float32"), "D": Dc, "x0": -200000.0, "y0": 320000.0}
north, east = hz.north_east(x0, y0)
wx, wy = x0 + east[0] * 20000, y0 + east[1] * 20000
i, j = t.xy_to_pixel(wall, wx, wy)
wall["z"][i - 3:i + 4, j - 3:j + 4] = 1000.0   # 1.4 km block
az, h = hz.horizon_mask(wall, x0, y0, 0.0)
print("wall east        : peak at az = %d deg, h = %.3f deg (expect 90, %.3f); h at 270 = %.3f"
      % (az[h.argmax()], h.max(), np.degrees(np.arctan((1000 - 20000**2 / (2 * R)) / 20000)), h[270]))

# ---- 3. real data: plan formula vs exact 3D geometry on the 80 m DEM
WIDE = "data/raw/LDEM_80S_80MPP_ADJ.TIF"
x, y = 5700.0, 120900.0          # the Malapert point clicked in the UI test
t0 = time.time(); dem = hz.load_wide_dem(WIDE, x, y); t_load = time.time() - t0
t0 = time.time(); az, h = hz.horizon_mask(dem, x, y, 0.0); t1 = time.time() - t0
t0 = time.time(); az01, h01 = hz.horizon_mask(dem, x, y, 0.0, np.arange(0, 360, 0.1)); t2 = time.time() - t0
print("real DEM         : load %.1f s | 360 azimuths %.2f s | 3600 azimuths %.2f s | samples per ray %d"
      % (t_load, t1, t2, hz.ray_distances().size))
print("Malapert horizon : min %.2f  median %.2f  max %.2f deg" % (h.min(), np.median(h), h.max()))
print("1 deg vs 0.1 deg : largest peak missed by 1 deg sampling = %.2f deg"
      % max(h01[k*10:(k+1)*10].max() - max(h[k], h[(k+1) % 360]) for k in range(360)))


def xyz(px, py, z):
    """Map point + height -> 3D position (m), Moon-centred."""
    rho = np.hypot(px, py); lat = -(np.pi / 2 - 2 * np.arctan(rho / (2 * R))); lon = np.arctan2(px, py)
    r = R + z
    return np.stack([r * np.cos(lat) * np.cos(lon), r * np.cos(lat) * np.sin(lon), r * np.sin(lat)], -1)


zs = float(hz.sample(dem, np.array([x]), np.array([y]))[0])
P = xyz(x, y, zs); up = P / np.linalg.norm(P)
lon = np.arctan2(x, y); lat = np.arcsin(up[2])
e3 = np.array([-np.sin(lon), np.cos(lon), 0.0])
n3 = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
# same sample points, exact 3D elevation instead of the flat + d^2/(2R) formula
north, east = hz.north_east(x, y); d = hz.ray_distances(); k = hz.map_scale(x, y)
worst, exact_h, az_err = 0.0, [], 0.0
for a_deg in range(360):
    a = np.radians(a_deg)
    px = x + (np.cos(a) * north[0] + np.sin(a) * east[0]) * d * k
    py = y + (np.cos(a) * north[1] + np.sin(a) * east[1]) * d * k
    zt = hz.sample(dem, px, py)
    V = xyz(px, py, zt) - P
    el = np.degrees(np.arcsin((V @ up) / np.linalg.norm(V, axis=-1)))
    azx = np.degrees(np.arctan2(V @ e3, V @ n3))
    az_err = max(az_err, np.nanmax(np.abs((azx - a_deg + 180) % 360 - 180)))
    exact_h.append(np.nanmax(el))
diff = h - np.array(exact_h)
print("plan formula vs exact 3D geometry: horizon differs by max %.3f deg; ray azimuth drifts by max %.2f deg over 150 km"
      % (np.abs(diff).max(), az_err))

# ---- 4. quick (80 m only) vs precise (5 m near + 80 m far)
d5 = t.load_dem("data/raw/Site23_final_adj_5mpp_surf.tif")
t0 = time.time(); az, hp = hz.horizon_mask(dem, x, y, 0.0, near_dem=d5); tp = time.time() - t0
print("precise mode     : %.2f s, %d samples per ray | median %.2f  max %.2f deg" % (tp, hz.ray_distances(step_near=5.0).size, np.median(hp), hp.max()))
print("quick vs precise : median |diff| %.2f deg, max %.2f deg, differ by > 0.1 deg in %d of 360 directions"
      % (np.median(np.abs(hp - h)), np.abs(hp - h).max(), (np.abs(hp - h) > 0.1).sum()))
for m in (0, 2, 5, 10):
    _, hq = hz.horizon_mask(dem, x, y, float(m)); _, hpm = hz.horizon_mask(dem, x, y, float(m), near_dem=d5)
    print("mast %2d m        : quick median %.2f max %.2f | precise median %.2f max %.2f deg" % (m, np.median(hq), hq.max(), np.median(hpm), hpm.max()))
