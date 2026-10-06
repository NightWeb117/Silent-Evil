"""Silent Hill (PS1) ILM / ANM / TIM readers."""
import struct
import numpy as np


def parse_ilm(d):
    assert d[0] == 0x30
    nameoff, mc, mo, mio = struct.unpack_from('<IIII', d, 4)
    models = []
    for i in range(mc):
        o = mo + i * 16
        name = d[o:o + 8].split(b'\0')[0].decode('ascii', 'replace')
        meshcount, vofs, nofs, _, mh = struct.unpack_from('<BBBBI', d, o + 8)
        meshes = []
        for m in range(meshcount):
            b = mh + m * 24
            npr, npos, nnor, nunk, po, xyo, zo, no, uo = struct.unpack_from('<BBBBIIIII', d, b)
            xy = [struct.unpack_from('<hh', d, xyo + k * 4) for k in range(npos)]
            z = [struct.unpack_from('<h', d, zo + k * 2)[0] for k in range(npos)]
            nr = [struct.unpack_from('<bbbB', d, no + k * 4) for k in range(nnor)]
            prims = []
            for k in range(npr):
                q = po + k * 20
                u0, v0, clut, u1, v1, tp, u2, v2, u3, v3 = struct.unpack_from('<BBHBBHBBBB', d, q)
                prims.append(dict(uv=[(u0, v0), (u1, v1), (u2, v2), (u3, v3)], clut=clut, tpage=tp,
                                  pi=list(d[q + 12:q + 16]), ni=list(d[q + 16:q + 20])))
            meshes.append(dict(pos=np.array([(x, y, zz) for (x, y), zz in zip(xy, z)], float).reshape(-1, 3),
                               norm=np.array([n[:3] for n in nr], float).reshape(-1, 3) / 128.0,
                               prims=prims))
        models.append(dict(name=name, bone=int(name[:2]), vofs=vofs, nofs=nofs, meshes=meshes, id=d[mio + i]))
    return models


class Anm:
    def __init__(self, d):
        (self.kfoff, self.rc, self.tc, self.ks, self.bc, self.flags, self.end,
         self.kc, self.tshift, _) = struct.unpack_from('<hBBhhiiHBB', d, 0)
        self.d = d
        self.bones = []
        for i in range(self.bc):
            p, ri, ti, x, y, z = struct.unpack_from('<bbbbbb', d, 20 + i * 6)
            self.bones.append(dict(parent=p, rot=ri, tr=ti, bind=np.array([x, y, z], float) * (1 << self.tshift)))
        self.nframes = (len(d) - self.kfoff) // self.ks

    def frame(self, f):
        o = self.kfoff + f * self.ks
        tr = [np.array(struct.unpack_from('<bbb', self.d, o + 3 * i), float) * (1 << self.tshift) for i in range(self.tc)]
        o += 3 * self.tc
        rot = [np.array(struct.unpack_from('<9b', self.d, o + 9 * i), float).reshape(3, 3) / 128.0 for i in range(self.rc)]
        return tr, rot

    def world(self, f, transpose=False):
        tr, rot = self.frame(f)
        W = [None] * self.bc
        for i, b in enumerate(self.bones):
            R = np.eye(3) if b['rot'] < 0 else rot[b['rot']]
            if transpose: R = R.T
            t = b['bind'] if b['tr'] < 0 else tr[b['tr']]
            if b['parent'] < 0:
                W[i] = (R, t.copy())
            else:
                PR, Pt = W[b['parent']]
                W[i] = (PR @ R, PR @ t + Pt)
        return W


def parse_tim(d):
    magic, flag = struct.unpack_from('<II', d, 0)
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[flag & 3]
    o = 8; clut = None
    if flag & 8:
        cl, cx, cy, cw, ch = struct.unpack_from('<IHHHH', d, o)
        clut = dict(x=cx, y=cy, w=cw, h=ch,
                    data=np.frombuffer(d, '<u2', cw * ch, o + 12).reshape(ch, cw).copy())
        o += cl
    il, ix, iy, iw, ih = struct.unpack_from('<IHHHH', d, o)
    raw = np.frombuffer(d, np.uint8, iw * 2 * ih, o + 12).reshape(ih, iw * 2)
    if bpp == 4:
        idx = np.zeros((ih, iw * 4), np.uint8); idx[:, 0::2] = raw & 15; idx[:, 1::2] = raw >> 4
    elif bpp == 8:
        idx = raw.copy()
    else:
        idx = None
    return dict(bpp=bpp, clut=clut, x=ix, y=iy, w=iw, h=ih, idx=idx, end=o + il)


def rgb555(c):
    c = np.asarray(c, np.uint32)
    r = (c & 31) << 3; g = ((c >> 5) & 31) << 3; b = ((c >> 10) & 31) << 3
    return np.stack([r, g, b], -1).astype(np.uint8)
