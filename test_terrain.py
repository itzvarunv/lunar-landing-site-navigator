"""Checks terrain.py on made-up grids with known answers."""
import numpy as np
import terrain as t

D = 5.0
n = 400
jj, ii = np.meshgrid(np.arange(n), np.arange(n))
x = 1000 + jj * D
y = 3000 - ii * D

# 1. tilted plane: slope must be exactly 6 deg, roughness 0
z = (np.tan(np.radians(6)) * x).astype("float64")
dem = {"z": z, "D": D, "x0": 1000.0, "y0": 3000.0}
s = t.slope_map(dem); r = t.roughness_map(dem)
print("plane slope  (expect 6):", round(float(np.nanmean(s)), 4), " roughness (expect 0):", round(float(np.nanmax(r)), 6))
a, b, c, fs, fr = t.plane_fit(dem, *t.cells_in_circle(dem, 2000, 2000, 100)[:2])
print("plane_fit slope (expect 6):", round(fs, 4), " roughness (expect 0):", round(fr, 6))

# 2. flat ground with one 2 m bump at cell (200, 200)
z2 = np.zeros((n, n)); z2[200, 200] = 2.0
dem2 = {"z": z2, "D": D, "x0": 1000.0, "y0": 3000.0}
S2, R2 = t.slope_map(dem2), t.roughness_map(dem2)
bx, by = t.pixel_to_xy(dem2, 200, 200)
print("on the bump   :", t.is_safe(dem2, S2, R2, bx, by, 50, 8.0, 0.5, 8.0, 0.5))
print("300 m away    :", t.is_safe(dem2, S2, R2, bx + 300, by, 50, 8.0, 0.5, 8.0, 0.5))
print("at map edge   :", t.is_safe(dem2, S2, R2, 1010, 2000, 50, 8.0, 0.5, 8.0, 0.5)["reason"])
print("r < D warning :", t.is_safe(dem2, S2, R2, bx + 300, by, 1, 8.0, 0.5, 8.0, 0.5)["warning"])

# 3. circle touch rule: r = 1 m centred on a cell centre touches exactly 1 cell;
#    centred on a cell corner touches 4
print("cells, centre :", t.cells_in_circle(dem2, bx, by, 1)[0].size, "(expect 1)")
print("cells, corner :", t.cells_in_circle(dem2, bx + D/2, by + D/2, 1)[0].size, "(expect 4)")
print("xy round trip :", t.xy_to_pixel(dem2, bx, by), "(expect (200, 200))")
print("lat/lon of (0, 86870 m):", [round(float(v), 3) for v in t.xy_to_latlon(0.0, 86870.0)])

# 4. broad hump: every cell individually fine, but the footprint as a whole is not
zz = 3.0 * np.exp(-(((x - 2000) ** 2 + (y - 2000) ** 2) / (2 * 60.0 ** 2)))
dem3 = {"z": zz, "D": D, "x0": 1000.0, "y0": 3000.0}
S3, R3 = t.slope_map(dem3), t.roughness_map(dem3)
print("broad hump    :", t.is_safe(dem3, S3, R3, 2000, 2000, 100, 8.0, 0.5, 8.0, 0.5))
print("hump, looser :", t.is_safe(dem3, S3, R3, 2000, 2000, 100, 8.0, 0.5, 8.0, 2.0)["ok"], "(expect True)")
