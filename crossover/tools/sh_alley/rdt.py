"""RE1 PC room (RDT) reader + background PAK codec."""
import struct, sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pkg', 'silent-hill-x-resident-evil', 'tools'))
from pak_view import PakDecoder

def pak_decode(b):
    raw = PakDecoder(b).run()
    w, h = struct.unpack_from('<HH', raw, 16)
    px = np.frombuffer(raw, '<u2', w * h, 20).reshape(h, w)
    r = ((px >> 10) & 31) * 255 // 31; g = ((px >> 5) & 31) * 255 // 31; bl = (px & 31) * 255 // 31
    return np.stack([r, g, bl], -1).astype(np.uint8)

def parse_rdt(d):
    hdr = dict(spr=d[0], ncam=d[1], nobj=d[2], nitem=d[3])
    ptr_names = ['cam_switch', 'boundaries', 'object_models', 'item_models', 'walk_zones', 'footstep', 'init_scd',
                 'scd', 'scd2', 'pl_anim_hdr', 'pl_anim_base', 'messages', 'item_icons', 'eff_idx', 'eff_data',
                 'eff_spr', 'snd', 'vh', 'vb']
    ptrs = {}
    for i, n in enumerate(ptr_names):
        v, = struct.unpack_from('<I', d, 0x48 + 4 * i)
        ptrs[n] = v - 3 + 3 if v == 0 else v - 3 + 3  # stored = target-(base+3) -> target = v+3? see below
    cams = []
    for i in range(hdr['ncam']):
        o = 0x94 + i * 0x2C
        mp, tp, fx, fy, fz, tx, ty, tz, roll, res, fov = struct.unpack_from('<2I9i', d, o)
        cams.append(dict(mask=mp, timmask=tp, frm=(fx, fy, fz), to=(tx, ty, tz), roll=roll, fov=fov))
    hdr['ptrs'] = ptrs; hdr['cams'] = cams
    return hdr

def parse_boundaries(d, off):
    cx, cz, q0, q1, q2, q3, unused = struct.unpack_from('<hh5i', d, off)
    n = q0 + q1 + q2 + q3
    recs = []
    for i in range(n):
        xmax, zmax, xmin, zmin, shape, flags = struct.unpack_from('<hhhhHH', d, off + 0x18 + i * 12)
        recs.append(dict(xmax=xmax, zmax=zmax, xmin=xmin, zmin=zmin, shape=shape & 0xFF, step=shape >> 8, flags=flags))
    return dict(cx=cx, cz=cz, counts=(q0, q1, q2, q3), recs=recs)

def parse_cam_switch(d, off):
    out = []
    while True:
        to, frm = struct.unpack_from('<hh', d, off)
        if to == -1 or (to & 0xFFFF) == 0xFFFF: break
        pts = struct.unpack_from('<8H', d, off + 4)
        out.append(dict(to=to, frm=frm, quad=[(pts[i], pts[i + 1]) for i in range(0, 8, 2)]))
        off += 20
        if len(out) > 200: break
    return out

def view(cam):
    f = np.array(cam['frm'], float); t = np.array(cam['to'], float)
    dv = t - f; L = np.linalg.norm(dv); h = np.hypot(dv[0], dv[2])
    n = dv / L; r = np.array([dv[2] / h, 0, -dv[0] / h]); u = np.cross(n, r)
    return f, n, r, u, float(cam['fov'])

def project(cam, P):
    f, n, r, u, fov = view(cam)
    d = np.asarray(P, float) - f
    z = d @ n
    return np.stack([160 + (d @ r) * fov / z, 120 + (d @ u) * fov / z], -1), z
