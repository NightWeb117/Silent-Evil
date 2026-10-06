"""Automatic fixed-camera placement for a generated room.

Silent Hill follows Harry with a free camera that stays a few metres behind and above
him; Resident Evil cuts between fixed shots. To get RE's fixed shots with Silent
Hill's framing, every walkable spot should be covered by a camera that (a) actually
sees the player there - judged against the rendered occluder depth, the same image the
engine uses to hide him - and (b) is close enough that he reads at a sensible size.

plan_cameras() generates candidate shots (camera ~2.6 m up, 3-7 m back from a target
point, looking slightly down past it), scores every candidate on every walk cell, then
greedily picks the few that cover the room best.
"""
import numpy as np
from camrender import render_bg, cam_basis

M = 256.0
CAM_H = -2.6          # SH metres, Y down: 2.6 m above the ground
LOOK_H = -0.8
FOV = 260             # RE projection distance at 320 px: ~63 deg horizontal
BODY = (-0.15, -0.9, -1.55)   # SH metres: shins, waist, head
LW, LH = 80, 60       # low-res evaluation render


def _project(f, n, r, u, fov, P):
    d = P - f
    z = d @ n
    zs = np.maximum(z, 1.0)
    sx = 160 + (d @ r) * fov / zs
    sy = 120 + (d @ u) * fov / zs
    return sx, sy, z


def evaluate(tris_re, frm, to, pts_feet_re, fov=FOV):
    """Per point: quality in [0,1] of seeing the player standing there from this camera."""
    _, ob, zb = render_bg(tris_re, frm, to, fov * LW / 320.0, W=LW, H=LH, ss=1, with_depth=2)
    f, n, r, u = cam_basis(frm, to)
    vis = np.zeros(len(pts_feet_re))
    centre = None
    ztorso = None
    for h in BODY:
        P = pts_feet_re + np.array([0, h * M * 6.65, 0])
        sx, sy, z = _project(f, n, r, u, fov, P)
        inside = (z > 900) & (sx > 12) & (sx < 308) & (sy > 8) & (sy < 236)
        ix = np.clip((sx * LW / 320).astype(int), 0, LW - 1)
        iy = np.clip((sy * LH / 240).astype(int), 0, LH - 1)
        occ = ob[iy, ix]
        seen = inside & (occ > z - 60)
        vis += seen / len(BODY)
        if h == -0.9:
            centre = 1.0 - np.clip(np.abs(sx - 160) / 160, 0, 1) * 0.5 - np.clip(np.abs(sy - 130) / 120, 0, 1) * 0.3
            ztorso = z
    # on-screen height of a 1.7 m figure, in 240-line pixels
    hpx = 1.7 * M * 6.65 * fov / np.maximum(ztorso, 1)
    size = np.clip(hpx / 50.0, 0, 1) * np.where(hpx > 180, 180.0 / np.maximum(hpx, 1), 1.0)
    q = np.where(vis >= 0.99, 1.0, vis * 0.5) * size * centre
    # empty sky / void in the frame reads as "outside the level" - penalise it
    void = np.isinf(zb[LH // 4:]).mean()
    q *= max(0.0, 1.0 - max(0.0, void - 0.15) * 2.0)
    return q


def plan_cameras(fr, tris_re, grid, walk_cells_sh, max_cams=8, log=print):
    """walk_cells_sh: (N,2) SH metres (x,z) of walkable cells in this room.
    Returns (cams, Q) - cams as dicts {frm,to,fov} in RE coords, Q (N, len(cams))."""
    pts_feet = np.array([fr.to_re(np.array([x * M, 0.0, z * M])) for x, z in walk_cells_sh])
    # cull triangles far from this room for speed
    lo = walk_cells_sh.min(0) - 12; hi = walk_cells_sh.max(0) + 12
    keep = []
    for P, UV, t in tris_re:
        c = t['P'].mean(0) / M
        if lo[0] <= c[0] <= hi[0] and lo[1] <= c[2] <= hi[1]:
            keep.append((P, UV, t))
    tris_re = keep

    # targets: walk cells every ~1.2 m
    tgt = walk_cells_sh[np.unique((walk_cells_sh / 1.2).round().astype(int), axis=0, return_index=True)[1]]
    cands = []
    for tx, tz in tgt:
        for a in np.arange(0, 2 * np.pi, np.pi / 6):
            dx, dz = np.cos(a), np.sin(a)
            for dist in (3.5, 5.0, 6.5):
                cx, cz = tx - dx * dist, tz - dz * dist
                iz, ix = grid.idx(cx, cz)
                if not (0 <= iz < grid.free.shape[0] and 0 <= ix < grid.free.shape[1]):
                    continue
                if not grid.reach_near[iz, ix]:
                    continue
                frm = np.array([cx * M, CAM_H * M, cz * M])
                to = np.array([(tx + dx * 1.0) * M, LOOK_H * M, (tz + dz * 1.0) * M])
                cands.append((frm, to))
    # thin out: random subset if very many
    rng = np.random.default_rng(1)
    if len(cands) > 260:
        cands = [cands[i] for i in rng.choice(len(cands), 260, replace=False)]
    log('    %d candidate cameras' % len(cands))
    Qc = []
    for frm, to in cands:
        Qc.append(evaluate(tris_re, fr.to_re(frm), fr.to_re(to), pts_feet))
    Qc = np.array(Qc)          # (C, N)

    chosen = []
    best = np.zeros(len(pts_feet))
    for _ in range(max_cams):
        gain = np.maximum(Qc - best[None], 0).sum(1)
        k = int(gain.argmax())
        if gain[k] < 0.02 * len(pts_feet) and len(chosen) >= 1:
            break
        chosen.append(k)
        best = np.maximum(best, Qc[k])
    log('    picked %d cameras, coverage mean %.2f, poor cells %.0f%%' %
        (len(chosen), best.mean(), 100 * (best < 0.3).mean()))
    cams = [dict(frm=fr.to_re(cands[k][0]), to=fr.to_re(cands[k][1]), fov=FOV) for k in chosen]
    return cams, Qc[chosen].T
