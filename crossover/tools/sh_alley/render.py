"""Tiny software rasterizer for previewing models (orthographic, z-buffered, textured)."""
import numpy as np
from PIL import Image


def render(tris, size=512, view='front', bounds=None, light=(0.3, -0.5, -0.8)):
    """tris: list of (P (3,3) world coords, UV (3,2) pixel coords, tex HxWx3 uint8 or None, color)
    Coordinates: PS1 style, +Y down. 'front' looks along +Z toward -Z? we just project x,y; depth = z."""
    P = np.array([t[0] for t in tris], float)
    if view == 'side':
        P = P[:, :, [2, 1, 0]] * np.array([1, 1, -1])
    elif view == 'back':
        P = P * np.array([-1, 1, -1])
    elif view == 'side2':
        P = P[:, :, [2, 1, 0]] * np.array([-1, 1, 1])
    if bounds is None:
        lo = P.reshape(-1, 3).min(0); hi = P.reshape(-1, 3).max(0)
    else:
        lo, hi = bounds
    span = max(hi[0] - lo[0], hi[1] - lo[1]) * 1.05
    cx = (lo[0] + hi[0]) / 2; cy = (lo[1] + hi[1]) / 2
    sc = size / span
    img = np.full((size, size, 3), 40, np.uint8)
    zb = np.full((size, size), np.inf)
    L = np.array(light, float); L /= np.linalg.norm(L)
    for (P0, UV, tex, col), Pv in zip(tris, P):
        x = (Pv[:, 0] - cx) * sc + size / 2
        y = (Pv[:, 1] - cy) * sc + size / 2
        z = Pv[:, 2]
        n = np.cross(Pv[1] - Pv[0], Pv[2] - Pv[0]); nn = np.linalg.norm(n)
        if nn == 0: continue
        shade = 0.45 + 0.55 * abs(np.dot(n / nn, L))
        x0, x1 = int(max(0, np.floor(x.min()))), int(min(size - 1, np.ceil(x.max())))
        y0, y1 = int(max(0, np.floor(y.min()))), int(min(size - 1, np.ceil(y.max())))
        if x1 < x0 or y1 < y0: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-9: continue
        a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
        b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
        c = 1 - a - b
        m = (a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6)
        if not m.any(): continue
        zz = a * z[0] + b * z[1] + c * z[2]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        m &= zz < sub
        if not m.any(): continue
        if tex is not None:
            u = a * UV[0][0] + b * UV[1][0] + c * UV[2][0]
            v = a * UV[0][1] + b * UV[1][1] + c * UV[2][1]
            ui = np.clip(u.astype(int), 0, tex.shape[1] - 1); vi = np.clip(v.astype(int), 0, tex.shape[0] - 1)
            rgb = tex[vi, ui].astype(float)
        else:
            rgb = np.broadcast_to(np.array(col, float), gx.shape + (3,))
        rgb = np.clip(rgb * shade, 0, 255).astype(np.uint8)
        sub[m] = zz[m]
        img[y0:y1 + 1, x0:x1 + 1][m] = rgb[m]
    return Image.fromarray(img)


def sheet(images, labels=None):
    w = sum(i.width for i in images); h = max(i.height for i in images)
    out = Image.new('RGB', (w, h + (20 if labels else 0)), (20, 20, 20))
    x = 0
    from PIL import ImageDraw
    dr = ImageDraw.Draw(out)
    for k, i in enumerate(images):
        out.paste(i, (x, 20 if labels else 0))
        if labels: dr.text((x + 6, 4), labels[k], fill=(230, 230, 230))
        x += i.width
    return out
