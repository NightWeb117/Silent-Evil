"""Build the Silent Hill opening alley as Resident Evil rooms.

Output (mod overlay layout): stage1/ROOM1xxN.RDT, stage1/RC1xxC.pak, data/bio_card.dat
"""
import sys, os, struct, json
import numpy as np
from scipy import ndimage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pkg', 'silent-hill-x-resident-evil', 'tools'))
from shmap import chunk_tris, BG
from walk import walk_grid, CELL
from camrender import Frame, S, render_bg, cam_basis
from autocam import plan_cameras
from bss_to_pak import make_tim, lzw_pack

M = 256.0  # SH units per metre

# ----------------------------------------------------------------- level design
# All SH coordinates in metres (x, y(down), z). Rooms: RE stage 1 room ids.
ROOMS = {
    'A': dict(id=0x08, rect=(-271.6, -257.4, 243.4, 255.8),
              cams=[((-267.2, -2.7, 247.3), (-268.6, -0.8, 254.2), 220),
                    ((-267.3, -2.6, 253.6), (-267.4, -0.8, 246.0), 210),
                    ((-268.2, -2.7, 245.6), (-259.0, -0.8, 245.2), 220),
                    ((-258.3, -2.7, 245.4), (-267.5, -0.8, 246.5), 220)],
              start=((-268.6, 254.2), 'north')),
    'B': dict(id=0x09, rect=(-261.4, -257.6, 228.6, 247.0),
              cams=[((-259.6, -2.8, 246.2), (-259.6, -0.8, 235.0), 230),
                    ((-259.0, -2.8, 229.6), (-259.6, -0.8, 242.0), 230)]),
    'C': dict(id=0x12, rect=(-260.6, -246.4, 214.8, 230.6),
              cams=[((-259.4, -2.8, 229.4), (-252.0, -0.8, 226.5), 220),
                    ((-254.0, -2.8, 222.5), (-252.5, -0.9, 216.5), 230),
                    ((-248.3, -2.8, 227.5), (-250.0, -0.9, 219.0), 230),
                    ((-250.0, -2.8, 216.5), (-253.5, -0.9, 224.0), 220)]),
}
# door: in room, trigger centre (x,z), size (w,d) metres, -> room, spawn (x,z), facing, entry cam
DOORS = [
    ('A', (-258.2, 245.2), (0.8, 1.6), 'B', (-259.6, 245.6), 'north', 0),
    ('B', (-259.6, 246.4), (1.6, 0.8), 'A', (-258.9, 245.2), 'west', 3),
    ('B', (-259.6, 229.0), (1.6, 0.8), 'C', (-258.5, 229.4), 'east', 0),
    ('C', (-259.4, 229.4), (0.6, 1.6), 'B', (-259.6, 230.4), 'south', 1),
]
START_ROOM = 'A'

# Atmosphere, following Silent Hill's own progression through this alley: the
# daytime fog preset at the entrance (MAP_EFFECTS_INFOS[1]: fog colour 108,100,116,
# world light 1.1), darkening as "the alley gets darker" (map0_s00 switches to the
# black-fog preset 6, world light 0.44). Fog distances in metres; colours 0..255 as
# they appear on screen. The same values go into the .dep files so the engine fades
# the characters into the same fog.
ATMOS = {
    'A': dict(fog=(108, 100, 116), near=1.5, far=11.0, gain=1.25, amb=0x780, light=230),
    'B': dict(fog=(66, 61, 72), near=1.5, far=10.5, gain=1.05, amb=0x640, light=200),
    'C': dict(fog=(24, 22, 28), near=1.0, far=9.0, gain=0.85, amb=0x500, light=170),
}
DEPTH_BIAS = 25.0          # RE units: walls sit this much farther in the depth image
FIRST_ENTRY_FLAG = (1, 0xFF)   # bank 1 (scenario flags 2), last bit: "alley start done"

# ----------------------------------------------------------------- helpers
# RE facing: angle a faces (cos a, -sin a) in (x, z); R180 maps SH north (-z) to RE +z.
FACING = {'north': 3072, 'south': 1024, 'east': 2048, 'west': 0}


def room_frame(rect):
    x0, x1, z0, z1 = rect
    # R180: RE_x grows as SH x falls, so anchor the SH max corner at RE (1000, 1000)
    return Frame((x1 * M, 0, z1 * M), (1000.0, 0, 1000.0))


def is_floor(P):
    """Same floor test as walk.walk_grid: near-horizontal and at ground height. Floors
    never hide a character standing on them, so they stay out of the depth image."""
    nrm = np.cross(P[1] - P[0], P[2] - P[0]); nn = np.linalg.norm(nrm)
    if nn == 0:
        return True
    return abs(nrm[1] / nn) > 0.85 and P[:, 1].max() > -0.6 * 256 and P[:, 1].min() < 0.4 * 256


def load_world():
    tris = chunk_tris(os.path.join(BG, 'THRF905.IPD')) + chunk_tris(os.path.join(BG, 'THRF906.IPD'))
    for t in tris:
        t['occ'] = not is_floor(t['P'])
    return tris


def depth_file(ob, atm):
    """SHD2 depth image for the engine (see TmdRenderer.cpp SceneDepth_Update)."""
    H, W = ob.shape
    v = np.where(np.isfinite(ob), np.minimum((ob + DEPTH_BIAS) / 2.0, 65534), 65535).astype('<u2')
    re_m = S * M
    hdr = b'SHD2' + struct.pack('<HH', W, H) + bytes(atm['fog']) + bytes([255]) + \
        struct.pack('<ff', atm['near'] * re_m, atm['far'] * re_m)
    return hdr + v.tobytes()


def rects_from_mask(mask):
    """Greedy cover of True cells by axis-aligned rectangles. Returns (r0, c0, r1, c1) inclusive."""
    m = mask.copy()
    out = []
    H, W = m.shape
    for r in range(H):
        c = 0
        while c < W:
            if not m[r, c]:
                c += 1; continue
            c1 = c
            while c1 + 1 < W and m[r, c1 + 1]:
                c1 += 1
            r1 = r
            while r1 + 1 < H and m[r1 + 1, c:c1 + 1].all():
                r1 += 1
            m[r:r1 + 1, c:c1 + 1] = False
            out.append((r, c, r1, c1))
            c = c1 + 1
    return out


class Grid:
    def __init__(self, tris):
        allp = np.concatenate([t['P'] for t in tris])
        self.lo = allp.min(0)[[0, 2]] - 256
        hi = allp.max(0)[[0, 2]] + 256
        floor, block = walk_grid(tris, self.lo, hi)
        self.free = floor & ~block
        walk = floor & ~ndimage.binary_dilation(block, iterations=3)
        self.walk = ndimage.binary_opening(walk, iterations=2)

    def idx(self, xm, zm):
        return int((zm * M - self.lo[1]) / CELL), int((xm * M - self.lo[0]) / CELL)

    def cell_center(self, iz, ix):
        return (self.lo[0] + (ix + 0.5) * CELL) / M, (self.lo[1] + (iz + 0.5) * CELL) / M


# ----------------------------------------------------------------- per-room build
def plan_room(key, world, grid, reach, log=print):
    """Walkable cells of this room and an automatic camera set covering them."""
    R = ROOMS[key]
    fr = room_frame(R['rect'])
    x0, x1, z0, z1 = R['rect']
    tris_re = [(fr.to_re(t['P']), t['uv'], t) for t in world]
    iz0, ix0 = grid.idx(x0, z0); iz1, ix1 = grid.idx(x1, z1)
    win = (slice(iz0, iz1 + 1), slice(ix0, ix1 + 1))
    walk = reach[win] & ndimage.binary_erosion(grid.free, iterations=2)[win]
    if walk.sum() < 50:
        walk = reach[win]
    cells = np.argwhere(walk)
    cells_sh = np.array([grid.cell_center(iz0 + r, ix0 + c) for r, c in cells])
    log('  %s: planning cameras over %d cells' % (key, len(cells)))
    cams, Q = plan_cameras(fr, tris_re, grid, cells_sh, log=log)
    return dict(fr=fr, tris_re=tris_re, win=win, walk=walk, cells=cells, cells_sh=cells_sh, cams=cams, Q=Q,
                iz0=iz0, ix0=ix0)


def cam_at(plan, xm, zm):
    d = ((plan['cells_sh'] - np.array([xm, zm])) ** 2).sum(1)
    return int(plan['Q'][int(d.argmin())].argmax())


def build_room(key, plan, plans, grid, reach, out_dir, template, log=print):
    R = ROOMS[key]
    fr = plan['fr']
    tris_re = plan['tris_re']
    cams = plan['cams']
    win, walk, iz0, ix0 = plan['win'], plan['walk'], plan['iz0'], plan['ix0']

    # --- backgrounds (+ depth images for the engine's occlusion)
    for ci, c in enumerate(cams):
        atm = ATMOS[key]
        re_m = S * M
        rgb, ob = render_bg(tris_re, c['frm'], c['to'], c['fov'], gain=atm['gain'], gamma=0.62,
                            fog=tuple(x / 255.0 for x in atm['fog']),
                            fog_near=atm['near'] * re_m, fog_far=atm['far'] * re_m, with_depth=True)
        c['rgb'] = rgb
        pak = lzw_pack(make_tim(rgb))
        open(os.path.join(out_dir, 'RC1%02X%X.pak' % (R['id'], ci)), 'wb').write(pak)
        open(os.path.join(out_dir, 'RC1%02X%X.dep' % (R['id'], ci)), 'wb').write(depth_file(ob, atm))
    log('  %s: %d backgrounds' % (key, len(cams)))
    free = grid.free[win]

    # --- collision: blocked cells near the walkable path, plus a closed border
    reach_w = reach[win]
    near = ndimage.binary_dilation(reach_w, iterations=10)
    blocked = ~reach_w & near
    blocked[0, :] = blocked[-1, :] = True
    blocked[:, 0] = blocked[:, -1] = True
    # 20 cm cells: max-pool 2x2 keeps walls solid, fewer records
    H2, W2 = (blocked.shape[0] + 1) // 2, (blocked.shape[1] + 1) // 2
    b2 = np.zeros((H2 * 2, W2 * 2), bool); b2[:blocked.shape[0], :blocked.shape[1]] = blocked
    b2 = b2.reshape(H2, 2, W2, 2).any((1, 3))
    boxes = []
    for (r0, c0, r1, c1) in rects_from_mask(b2):
        ax0, az0 = grid.cell_center(iz0 + r0 * 2, ix0 + c0 * 2)
        ax1, az1 = grid.cell_center(iz0 + r1 * 2 + 1, ix0 + c1 * 2 + 1)
        p0 = fr.to_re(np.array([(ax0 - 0.05) * M, 0, (az0 - 0.05) * M]))
        p1 = fr.to_re(np.array([(ax1 + 0.05) * M, 0, (az1 + 0.05) * M]))
        boxes.append((int(min(p0[0], p1[0])), int(min(p0[2], p1[2])), int(max(p0[0], p1[0])), int(max(p0[2], p1[2]))))
    log('  %s: %d collision boxes' % (key, len(boxes)))

    # --- camera regions: each walkable cell -> best camera that sees the player there
    cells = plan['cells']
    best = plan['Q'].argmax(1)
    assign = np.full(walk.shape, -1, int)
    assign[cells[:, 0], cells[:, 1]] = best
    # majority filter so zones are not speckled
    filled = assign.copy()
    for _ in range(2):
        votes = np.stack([ndimage.uniform_filter((filled == k).astype(float), 7) for k in range(len(cams))])
        filled = np.where(walk, votes.argmax(0), -1)
    # grow regions a little past the walk mask so the player is always inside one
    grown = filled.copy()
    dist, (ri, ci2) = ndimage.distance_transform_edt(filled < 0, return_indices=True)
    grown = filled[ri, ci2]
    zones = []  # per camera list of (camTo, (xmin, zmin, xmax, zmax))
    for k in range(len(cams)):
        reg = grown == k
        H3, W3 = (reg.shape[0] + 2) // 3, (reg.shape[1] + 2) // 3
        r3 = np.zeros((H3 * 3, W3 * 3), bool); r3[:reg.shape[0], :reg.shape[1]] = reg
        r3 = r3.reshape(H3, 3, W3, 3).mean((1, 3)) >= 0.5
        for (r0, c0, r1, c1) in rects_from_mask(r3):
            ax0, az0 = grid.cell_center(iz0 + r0 * 3, ix0 + c0 * 3)
            ax1, az1 = grid.cell_center(iz0 + r1 * 3 + 2, ix0 + c1 * 3 + 2)
            p0 = fr.to_re(np.array([(ax0 - 0.05) * M, 0, (az0 - 0.05) * M]))
            p1 = fr.to_re(np.array([(ax1 + 0.05) * M, 0, (az1 + 0.05) * M]))
            zones.append((k, (int(min(p0[0], p1[0])), int(min(p0[2], p1[2])), int(max(p0[0], p1[0])), int(max(p0[2], p1[2])))))
    log('  %s: %d camera zones' % (key, len(zones)))

    # --- doors
    door_recs = []
    for (src, (dx, dz), (w, dd), dst, (sx_, sz_), facing, cam) in DOORS:
        if src != key:
            continue
        dst_fr = room_frame(ROOMS[dst]['rect'])
        a = fr.to_re(np.array([(dx - w / 2) * M, 0, (dz - dd / 2) * M]))
        b = fr.to_re(np.array([(dx + w / 2) * M, 0, (dz + dd / 2) * M]))
        sp = dst_fr.to_re(np.array([sx_ * M, 0, sz_ * M]))
        door_recs.append(dict(x=int(min(a[0], b[0])), z=int(min(a[2], b[2])), w=int(abs(a[0] - b[0])), d=int(abs(a[2] - b[2])),
                              dest=ROOMS[dst]['id'], cam=cam_at(plans[dst], sx_, sz_), sx=int(sp[0]), sz=int(sp[2]),
                              dir=FACING[facing]))
    start = None
    if 'start' in R:
        (sx_, sz_), facing = R['start']
        sp = fr.to_re(np.array([sx_ * M, 0, sz_ * M]))
        start = (int(sp[0]), int(sp[2]), FACING[facing])

    rdt = write_rdt(template, cams, zones, boxes, door_recs, start, walk_bounds(fr, R['rect']), ATMOS[key])
    for v in (0, 1):   # Chris / Jill scenario files
        open(os.path.join(out_dir, 'ROOM1%02X%d.RDT' % (R['id'], v)), 'wb').write(rdt)
    return dict(cams=cams, boxes=boxes, zones=zones, doors=door_recs, frame=fr, start=start)


def walk_bounds(fr, rect):
    x0, x1, z0, z1 = rect
    a = fr.to_re(np.array([x0 * M, 0, z0 * M])); b = fr.to_re(np.array([x1 * M, 0, z1 * M]))
    return int(min(a[0], b[0])), int(min(a[2], b[2])), int(max(a[0], b[0])), int(max(a[2], b[2]))


# ----------------------------------------------------------------- RDT writer
def write_rdt(template, cams, zones, boxes, doors, start, bounds, atm=None):
    d = bytearray(template)
    ncam_t = d[1]
    assert len(cams) <= ncam_t, 'template has too few camera slots'
    tail = bytearray()
    base = (len(d) + 3) & ~3
    d += b'\0' * (base - len(d))

    def add(blob):
        nonlocal tail
        off = base + len(tail)
        tail += blob
        tail += b'\0' * ((-len(tail)) % 4)
        return off

    # header counts: no sprites, no omodels, no items
    d[0] = 0; d[1] = len(cams); d[2] = 0; d[3] = 0
    # ambient + lights: dim, cold, one soft directional key light
    amb = atm['amb'] if atm else 0x380
    key = atm['light'] if atm else 150
    struct.pack_into('<3h', d, 6, amb, amb + 0x10, amb + 0x28)
    for i in range(3):
        o = 0x0C + i * 0x14
        if i == 0:
            struct.pack_into('<3i4BHh', d, o, 0, -6000, 0, key, key, min(255, key + 8), 0, 1, 0)
        else:
            struct.pack_into('<3i4BHh', d, o, 0, 0, 0, 0, 0, 0, 0, 1, 0)

    empty_mask = add(struct.pack('<i', 0))
    for i, c in enumerate(cams):
        o = 0x94 + i * 0x2C
        f = [int(round(v)) for v in c['frm']]; t = [int(round(v)) for v in c['to']]
        struct.pack_into('<2I9i', d, o, empty_mask, 0, f[0], f[1], f[2], t[0], t[1], t[2], 0, 0, c['fov'])

    # camera switch zones: one group per camera (header + zones to every other camera)
    zb = bytearray()
    for k in range(len(cams)):
        zb += struct.pack('<hh8H', 9, k, *(0,) * 8)   # group header (never tested)
        for (to, (xa, za, xb, zb_)) in zones:
            if to == k:
                continue
            zb += struct.pack('<hh8H', to, k, xa, za, xa, zb_, xb, zb_, xb, za)
    zb += struct.pack('<hh8H', -1, -1, *(0,) * 8)
    ptr_zone = add(bytes(zb))

    # collision boundaries, split into quadrants around the room centre
    cx = (bounds[0] + bounds[2]) // 2; cz = (bounds[1] + bounds[3]) // 2
    quads = [[], [], [], []]
    for (xa, za, xb, zb_) in boxes:
        for q in range(4):
            lowx, lowz = q & 1, (q >> 1) & 1
            okx = (xa < cx) if lowx else (xb >= cx)
            okz = (za < cz) if lowz else (zb_ >= cz)
            if okx and okz:
                quads[q].append(struct.pack('<hhhhHH', xb, zb_, xa, za, 1, 0x0300))
    bb = struct.pack('<hh5i', cx, cz, *[len(q) for q in quads], 0) + b''.join(b''.join(q) for q in quads)
    ptr_blk = add(bb)

    # NPC walk zone + footstep catch-all
    x0, z0, x1, z1 = bounds
    ptr_walk = add(struct.pack('<BB4hHH', 1, 0, x0, z0, x1, z1, 0x3FF, 0))
    ptr_foot = add(struct.pack('<H5H', 1, 0, 0, 0xFFFF, 0xFFFF, 0x2D))

    # init script
    ops = bytearray()
    if start:
        sx, sz, sdir = start
        bank, sel = FIRST_ENTRY_FLAG
        body = struct.pack('<BBhhhhhh', 0x20, 0, 0, sdir, 0, sx, 0, sz) + bytes([0x05, bank, sel, 0])
        ops += bytes([0x01, 4 + len(body)]) + bytes([0x04, bank, sel, 1]) + body + bytes([0x03, 0x00])
    for slot, dr in enumerate(doors):
        # +0x17 probe flags: 0x41 = fires when the player WALKS into the box (own position),
        # no action button - the alley has no visible doors
        # +0x08 = 0xFE: the crossover's quick cut (no RE door animation); +0x0B bit 0x40: no door sound
        rec = struct.pack('<4H6B4H2B', dr['x'], dr['z'], dr['w'], dr['d'], 0xFE, 0x00, 0x04, dr['cam'] | 0x40, 0x00,
                          dr['dest'], dr['sx'], 0, dr['sz'], dr['dir'], 0x00, 0x41)
        assert len(rec) == 24
        ops += bytes([0x0C, slot]) + rec
    ops += bytes([0x00])
    init = struct.pack('<H', 2 + len(ops)) + ops
    init += b'\0' * (len(init) & 1) + struct.pack('<H', 0)
    ptr_init = add(init)
    ptr_scd = add(struct.pack('<H', 0))
    ptr_evt = add(struct.pack('<I', 0))

    for name, off in (('cam_switch', ptr_zone), ('boundaries', ptr_blk), ('walk_zones', ptr_walk),
                      ('footstep', ptr_foot), ('init_scd', ptr_init), ('scd', ptr_scd), ('scd2', ptr_evt)):
        idx = ['cam_switch', 'boundaries', 'object_models', 'item_models', 'walk_zones', 'footstep', 'init_scd',
               'scd', 'scd2'].index(name)
        struct.pack_into('<I', d, 0x48 + 4 * idx, off)
    return bytes(d) + bytes(tail)


def write_bio_card(src, dst, room_id):
    b = bytearray(open(src, 'rb').read())
    b[0x200] = 0          # stage 1
    b[0x201] = room_id
    open(dst, 'wb').write(b)


def main(re_region, out_root, preview=None):
    world = load_world()
    grid = Grid(world)
    # reachable walk area from the start point
    lab, n = ndimage.label(grid.free)
    (sx, sz), _ = ROOMS[START_ROOM]['start']
    reach = lab == lab[grid.idx(sx, sz)]          # everything connected to the start
    grid.reach = reach
    st = os.path.join(out_root, 'stage1'); os.makedirs(st, exist_ok=True)
    template = open(os.path.join(re_region, 'Stage1', 'ROOM1060.RDT'), 'rb').read()
    grid.reach_near = reach
    plans = {key: plan_room(key, world, grid, reach) for key in ROOMS}
    info = {}
    for key in ROOMS:
        info[key] = build_room(key, plans[key], plans, grid, reach, st, template)
    os.makedirs(os.path.join(out_root, 'data'), exist_ok=True)
    write_bio_card(os.path.join(re_region, 'Data', 'bio_card.dat'), os.path.join(out_root, 'data', 'bio_card.dat'),
                   ROOMS[START_ROOM]['id'])
    return info


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
