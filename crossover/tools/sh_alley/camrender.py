"""Render SH map geometry as an RE-style pre-rendered background (RE projection)."""
import numpy as np
from shmap import texture

S = 6.65                     # RE units per SH unit (matches the Harry conversion)
R180 = np.diag([-1.0, 1.0, -1.0])   # SH (-Z north) -> RE (+Z north), proper rotation


class Frame:
    """SH world -> RE room coordinates for one room."""
    def __init__(self, anchor_sh, anchor_re):
        self.a_sh = np.array(anchor_sh, float)
        self.a_re = np.array(anchor_re, float)

    def to_re(self, p):
        p = np.asarray(p, float)
        return (p - self.a_sh) @ R180.T * S + self.a_re

    def to_sh(self, p):
        p = np.asarray(p, float)
        return (p - self.a_re) @ R180.T / S + self.a_sh


def cam_basis(frm, to):
    f = np.array(frm, float); t = np.array(to, float)
    dv = t - f; L = np.linalg.norm(dv); h = np.hypot(dv[0], dv[2])
    n = dv / L; r = np.array([dv[2] / h, 0, -dv[0] / h]); u = np.cross(n, r)
    return f, n, r, u


def textured(tri):
    tx = texture(tri['mat']) if tri['mat'] else None
    if tx is None:
        return None, None
    pals, tim = tx
    row = min(tri['clut'], len(pals) - 1)
    rgb = pals[row]
    clut = tim['clut']['data'][row]
    alpha = (clut[tim['idx']] != 0)           # PS1: colour 0x0000 is transparent
    return rgb, alpha


def render_bg(tris_re, frm, to, fov, W=320, H=240, ss=3, fog=(0.0, 0.0, 0.0), fog_near=1500.0,
              fog_far=26000.0, gain=1.0, near=150.0, gamma=1.0, with_depth=False):
    """tris_re: list of (P (3,3) RE coords, uv (3,2), sh_tri dict). Returns HxWx3 uint8
    (and, with_depth, the (H*ss)x(W*ss) view-space Z of the visible OCCLUDING surface -
    inf where the visible surface is floor (tri['occ'] False) or nothing).

    Fog is applied after the gamma lift, so `fog` (0..1) is the exact on-screen colour and
    the engine can fade the models into the same colour over the same view-space range."""
    f, n, r, u = cam_basis(frm, to)
    Wb, Hb = W * ss, H * ss
    fb = fov * ss
    img = np.zeros((Hb, Wb, 3), np.float32)
    zb = np.full((Hb, Wb), np.inf, np.float32)
    ob = np.full((Hb, Wb), np.inf, np.float32)
    cache = {}
    for P, UV, tri in tris_re:
        d = P - f
        cz = d @ n
        if (cz < near).all():
            continue
        cx = d @ r; cy = d @ u
        V = np.stack([cx, cy, cz], 1)
        # clip against near plane (Sutherland-Hodgman on one plane)
        poly = [(V[i], UV[i]) for i in range(3)]
        out = []
        for i in range(len(poly)):
            a, ua = poly[i]; b, ub = poly[(i + 1) % len(poly)]
            ina, inb = a[2] >= near, b[2] >= near
            if ina: out.append((a, ua))
            if ina != inb:
                t = (near - a[2]) / (b[2] - a[2])
                out.append((a + (b - a) * t, ua + (ub - ua) * t))
        if len(out) < 3:
            continue
        key = (tri['mat'], tri['clut'])
        if key not in cache:
            cache[key] = textured(tri)
        rgb, alpha = cache[key]
        occ = tri.get('occ', True)
        for k in range(1, len(out) - 1):
            _raster(img, zb, ob, occ, [out[0], out[k], out[k + 1]], fb, Wb, Hb, rgb, alpha)
    col = np.clip(img * gain, 0, 255)
    if gamma != 1.0:
        col = 255.0 * (col / 255.0) ** gamma
    fogk = np.clip((zb - fog_near) / (fog_far - fog_near), 0, 1)[..., None]
    col = col * (1 - fogk) + np.array(fog, np.float32) * 255 * fogk
    small = col.reshape(H, ss, W, ss, 3).mean((1, 3))
    small = np.clip(small + 0.5, 0, 255).astype(np.uint8)
    return (small, ob) if with_depth else small


def _raster(img, zb, ob, occ, tri, fb, Wb, Hb, rgb, alpha):
    V = np.array([t[0] for t in tri]); UV = np.array([t[1] for t in tri])
    sx = Wb / 2 + V[:, 0] * fb / V[:, 2]
    sy = Hb / 2 + V[:, 1] * fb / V[:, 2]
    x0, x1 = int(max(0, np.floor(sx.min()))), int(min(Wb - 1, np.ceil(sx.max())))
    y0, y1 = int(max(0, np.floor(sy.min()))), int(min(Hb - 1, np.ceil(sy.max())))
    if x1 < x0 or y1 < y0:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    den = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
    if abs(den) < 1e-9:
        return
    a = ((sy[1] - sy[2]) * (gx - sx[2]) + (sx[2] - sx[1]) * (gy - sy[2])) / den
    b = ((sy[2] - sy[0]) * (gx - sx[2]) + (sx[0] - sx[2]) * (gy - sy[2])) / den
    c = 1 - a - b
    m = (a >= -1e-4) & (b >= -1e-4) & (c >= -1e-4)
    if not m.any():
        return
    iz = a / V[0, 2] + b / V[1, 2] + c / V[2, 2]
    z = 1.0 / iz
    sub = zb[y0:y1 + 1, x0:x1 + 1]
    if rgb is not None:
        u = (a * UV[0, 0] / V[0, 2] + b * UV[1, 0] / V[1, 2] + c * UV[2, 0] / V[2, 2]) * z
        v = (a * UV[0, 1] / V[0, 2] + b * UV[1, 1] / V[1, 2] + c * UV[2, 1] / V[2, 2]) * z
        ui = np.clip(u.astype(int), 0, rgb.shape[1] - 1); vi = np.clip(v.astype(int), 0, rgb.shape[0] - 1)
        m &= alpha[vi, ui]
        col = rgb[vi, ui].astype(np.float32)
    else:
        col = np.full(gx.shape + (3,), 90, np.float32)
    m &= z < sub
    if not m.any():
        return
    sub[m] = z[m]
    ob[y0:y1 + 1, x0:x1 + 1][m] = z[m] if occ else np.inf
    img[y0:y1 + 1, x0:x1 + 1][m] = col[m]
