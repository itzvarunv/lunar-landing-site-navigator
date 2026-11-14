import numpy as np, pandas as pd, regional as rg
rng = np.random.default_rng(1)
d_true = rng.normal(size=(500, 3)); d_true /= np.linalg.norm(d_true, axis=1)[:, None]
C = rg.xy_to_latlon(-500.0, 121500.0); P = rg.xy_to_latlon(5700.0, 120900.0)
fc, fp = rg.enu(*C), rg.enu(*P)
azc, elc = rg.vec_to_azel(d_true, fc); azp, elp = rg.vec_to_azel(d_true, fp)
tab = pd.DataFrame({"time": range(500), "sun_az": azc, "sun_el": elc, "earth_az": azc, "earth_el": elc})
out = rg.transfer(tab, *C, *P)
print("round trip, max az err %.2e deg, max el err %.2e deg" % (np.abs((out.sun_az - azp + 180) % 360 - 180).max(), np.abs(out.sun_el - elp).max()))
print("orthonormal frame:", np.allclose(np.array(fp) @ np.array(fp).T, np.eye(3)))
# how much does moving 6.2 km change a low Sun's elevation? (expect ~ angular separation of the points)
sep = np.degrees(np.arccos(np.clip(np.dot(fc[2], fp[2]), -1, 1)))
print("C->P separation %.4f deg; max el change for el~0 bodies: %.4f deg" % (sep, np.abs(elp - elc)[np.abs(elc) < 5].max()))
