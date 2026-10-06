import numpy as np
from shmap import *
CELL = 0.1 * 256  # 10 cm in SH units

def tri_raster(P, grid_origin, shape):
    """Return grid indices (iz, ix) covered by triangle P (xz) - SH units."""
    xs = (P[:, 0] - grid_origin[0]) / CELL; zs = (P[:, 2] - grid_origin[1]) / CELL
    x0, x1 = int(np.floor(xs.min())), int(np.ceil(xs.max())); z0, z1 = int(np.floor(zs.min())), int(np.ceil(zs.max()))
    x0 = max(x0, 0); z0 = max(z0, 0); x1 = min(x1, shape[1] - 1); z1 = min(z1, shape[0] - 1)
    if x1 < x0 or z1 < z0: return None
    gx, gz = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(z0, z1 + 1) + 0.5)
    d = (zs[1] - zs[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (zs[0] - zs[2])
    if abs(d) < 1e-9:
        return None
    a = ((zs[1] - zs[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gz - zs[2])) / d
    b = ((zs[2] - zs[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gz - zs[2])) / d
    m = (a >= -0.05) & (b >= -0.05) & (1 - a - b >= -0.05)
    return (slice(z0, z1 + 1), slice(x0, x1 + 1), m)

def seg_raster(p, q, grid_origin, shape, out):
    n = int(max(abs(q[0] - p[0]), abs(q[2] - p[2])) / CELL * 2) + 2
    for t in np.linspace(0, 1, n):
        x = p[0] + (q[0] - p[0]) * t; z = p[2] + (q[2] - p[2]) * t
        ix = int((x - grid_origin[0]) / CELL); iz = int((z - grid_origin[1]) / CELL)
        if 0 <= ix < shape[1] and 0 <= iz < shape[0]: out[iz, ix] = True

def walk_grid(tris, lo, hi):
    shape = (int((hi[1] - lo[1]) / CELL) + 1, int((hi[0] - lo[0]) / CELL) + 1)
    floor = np.zeros(shape, bool); floor_y = np.full(shape, np.nan); block = np.zeros(shape, bool)
    for t in tris:
        P = t['P']
        n = np.cross(P[1] - P[0], P[2] - P[0]); nn = np.linalg.norm(n)
        if nn == 0: continue
        n /= nn
        ymin, ymax = P[:, 1].min(), P[:, 1].max()   # Y down: floor ~0, up is negative
        if abs(n[1]) > 0.85 and ymax > -0.6 * 256 and ymin < 0.4 * 256:
            r = tri_raster(P, lo, shape)
            if r: floor[r[0], r[1]] |= r[2]
        elif abs(n[1]) < 0.5 and ymin < -0.3 * 256 and ymax > -1.6 * 256:
            # vertical-ish surface overlapping body height: block its footprint
            for i in range(3):
                seg_raster(P[i], P[(i + 1) % 3], lo, shape, block)
        elif abs(n[1]) >= 0.5 and ymin < -0.35 * 256 and ymax > -1.6 * 256:
            r = tri_raster(P, lo, shape)          # raised flat-ish stuff (boxes, ledges)
            if r: block[r[0], r[1]] |= r[2]
    return floor, block
