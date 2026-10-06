"""Silent Hill IPD (map chunk) / PLM reader -> world-space textured triangles."""
import struct, os
import numpy as np
from sh import parse_tim, rgb555


def lm_parse(d, base):
    assert d[base] == 0x30, hex(d[base])
    matc = d[base + 3]
    mato, = struct.unpack_from('<I', d, base + 4)
    mc = d[base + 8]
    mho, moo = struct.unpack_from('<II', d, base + 12)
    mats = []
    for i in range(matc):
        o = base + mato + i * 24
        mats.append(d[o:o + 8].split(b'\0')[0].decode('ascii', 'replace'))
    models = {}
    order = []
    for i in range(mc):
        o = base + mho + i * 16
        name = d[o:o + 8].split(b'\0')[0].decode('ascii', 'replace')
        meshcount, vofs, nofs, flags = d[o + 8], d[o + 9], d[o + 10], d[o + 11]
        mh, = struct.unpack_from('<I', d, o + 12)
        meshes = []
        for m in range(meshcount):
            b = base + mh + m * 24
            npr, npos, nnor, nunk = d[b], d[b + 1], d[b + 2], d[b + 3]
            po, xyo, zo, no, uo = struct.unpack_from('<5I', d, b + 4)
            pos = []
            for k in range(npos):
                x, y = struct.unpack_from('<hh', d, base + xyo + k * 4)
                z, = struct.unpack_from('<h', d, base + zo + k * 2)
                pos.append((x, y, z))
            prims = []
            for k in range(npr):
                q = base + po + k * 20
                u0, v0, b0, u1, v1, f6, f7, u2, v2, u3, v3 = struct.unpack_from('<BBHBBBBBBBB', d, q)
                prims.append(dict(uv=[(u0, v0), (u1, v1), (u2, v2), (u3, v3)], mat=f7 & 0x7F, trans=f7 >> 7,
                                  pi=list(d[q + 12:q + 16]), ni=list(d[q + 16:q + 20]), b0=b0, f6=f6))
            meshes.append(dict(pos=np.array(pos, float).reshape(-1, 3), prims=prims, nunk=nunk))
        models[name] = dict(name=name, vofs=vofs, nofs=nofs, meshes=meshes, flags=flags, index=i)
        order.append(name)
    morder = [d[base + moo + i] for i in range(mc)] if moo else list(range(mc))
    return dict(mats=mats, models=models, names=order, order=morder)


def ipd_parse(d):
    assert d[0] == 0x14
    cx, cz = struct.unpack_from('<bb', d, 2)
    lmo, = struct.unpack_from('<I', d, 4)
    mc, mbc, moc = d[8], d[9], d[10]
    mio, mbo = struct.unpack_from('<II', d, 0x14)
    lm = lm_parse(d, lmo)
    infos = []
    for i in range(mc):
        o = mio + i * 16
        infos.append(dict(glob=d[o], name=d[o + 4:o + 12].split(b'\0')[0].decode('ascii', 'replace'),
                          hdr=struct.unpack_from('<I', d, o + 12)[0]))
    insts = []
    for i in range(mbc):
        o = mbo + i * 24
        cnt = d[o]
        io, = struct.unpack_from('<I', d, o + 12)
        for k in range(cnt):
            q = io + k * 36
            idx, = struct.unpack_from('<I', d, q)
            m = np.array(struct.unpack_from('<9h', d, q + 4), float).reshape(3, 3) / 4096.0
            t = np.array(struct.unpack_from('<3i', d, q + 24), float)
            insts.append(dict(model=idx, R=m, t=t, buf=i))
    return dict(chunk=(cx, cz), lm=lm, infos=infos, insts=insts)


BG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shassets', 'BG')
_tex_cache = {}


def texture(name):
    if name not in _tex_cache:
        p = os.path.join(BG, name + '.TIM')
        if not os.path.exists(p):
            _tex_cache[name] = None
        else:
            t = parse_tim(open(p, 'rb').read())
            _tex_cache[name] = [rgb555(t['clut']['data'][r])[t['idx']] for r in range(t['clut']['h'])], t
    return _tex_cache[name]


def model_tris(lm, model, R, t):
    """World-space triangles for one LM model instance (SH units, Y down)."""
    out = []
    buf = {}
    for mesh in model['meshes']:
        wp = mesh['pos'] @ R.T + t
        for k, p in enumerate(wp): buf[model['vofs'] + k] = p
        for pr in mesh['prims']:
            idx = pr['pi'] if pr['pi'][3] != 255 else pr['pi'][:3]
            if any(i not in buf for i in idx): continue
            P = [buf[i] for i in idx]
            mat = lm['mats'][pr['mat']] if pr['mat'] < len(lm['mats']) else None
            corners = [(0, 1, 2)] if len(idx) == 3 else [(0, 1, 2), (1, 3, 2)]
            for c in corners:
                out.append(dict(P=np.array([P[i] for i in c]), uv=np.array([pr['uv'][i] for i in c], float),
                                mat=mat, clut=pr['b0'] >> 6, trans=pr['trans'], model=model['name']))
    return out


_glb = {}


def global_plm(prefix):
    if prefix not in _glb:
        p = os.path.join(BG, prefix + '_GLB.PLM')
        _glb[prefix] = lm_parse(open(p, 'rb').read(), 0) if os.path.exists(p) else None
    return _glb[prefix]


def chunk_tris(path, prefix='THR', place=None):
    d = open(path, 'rb').read()
    ip = ipd_parse(d)
    cx, cz = place if place else ip['chunk']
    origin = np.array([cx * 40 * 256, 0, cz * 40 * 256], float)
    tris = []
    for inst in ip['insts']:
        info = ip['infos'][inst['model']]
        lm = global_plm(prefix) if info['glob'] else ip['lm']
        if lm is None or info['name'] not in lm['models']: continue
        tris += model_tris(lm, lm['models'][info['name']], inst['R'], inst['t'] + origin)
    return tris
