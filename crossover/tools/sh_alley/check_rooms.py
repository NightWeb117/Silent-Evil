import sys, os, struct, glob; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdt import *
from PIL import Image, ImageDraw
from render import sheet
import numpy as np, struct

def pak_rgb(b):
    raw = PakDecoder(b).run(); w, h = struct.unpack_from('<HH', raw, 16)
    px = np.frombuffer(raw, '<u2', w*h, 20).reshape(h, w)
    r=(px&31)*255//31; g=((px>>5)&31)*255//31; bl=((px>>10)&31)*255//31     # PS1 order (R low)
    return np.stack([r,g,bl],-1).astype(np.uint8)

def zone_contains(z, x, zz):
    (x0,y0),(x1,y1),(x2,y2),(x3,y3) = z['quad']
    dx, dz = x-x0, zz-y0
    if (x1-x0)*dz > (y1-y0)*dx: return False
    if (x3-x0)*dz < (y3-y0)*dx: return False
    dx2, dz2 = x-x2, zz-y2
    if (x1-x2)*dz2 < (y1-y2)*dx2: return False
    if (x3-x2)*dz2 > (y3-y2)*dx2: return False
    return True

def blocked(B, x, z, r=0):
    for b in B['recs']:
        if b['xmin']-r <= x <= b['xmax']+r and b['zmin']-r <= z <= b['zmax']+r: return True
    return False

def check(room_path, stage_dir, rid):
    d = open(room_path,'rb').read(); h = parse_rdt(d)
    B = parse_boundaries(d, h['ptrs']['boundaries']); Z = parse_cam_switch(d, h['ptrs']['cam_switch'])
    print(os.path.basename(room_path), 'cams', h['ncam'], 'boxes', len(B['recs']), 'quad counts', B['counts'], 'zones', len(Z))
    ims = []
    for ci, cam in enumerate(h['cams']):
        bg = pak_rgb(open(os.path.join(stage_dir, 'RC1%02X%X.pak' % (rid, ci)),'rb').read())
        im = Image.fromarray(bg).resize((640,480)); dr = ImageDraw.Draw(im)
        for b in B['recs']:
            cs=[(b['xmin'],0,b['zmin']),(b['xmax'],0,b['zmin']),(b['xmax'],0,b['zmax']),(b['xmin'],0,b['zmax'])]
            p,z=project(cam,cs)
            if (z<300).any(): continue
            dr.line([tuple(q*2) for q in p]+[tuple(p[0]*2)],fill=(255,40,40),width=1)
        # zones that switch AWAY from this camera, drawn in cyan
        for zn in Z:
            if zn['frm']!=ci or zn['to']==9: continue
            cs=[(x,0,zz) for (x,zz) in zn['quad']]
            p,z=project(cam,cs)
            if (z<300).any(): continue
            dr.line([tuple(q*2) for q in p]+[tuple(p[0]*2)],fill=(60,220,255),width=1)
        dr.text((6,6),'cam %d'%ci,fill=(255,255,0)); ims.append(im)
    return h, B, Z, ims

if __name__=='__main__':
    out=sys.argv[1]; st=os.path.join(out,'stage1')
    for rid in (0x08,0x09,0x12):
        h,B,Z,ims=check(os.path.join(st,'ROOM1%02X0.RDT'%rid), st, rid)
        rows=[sheet(ims[i:i+2]) for i in range(0,len(ims),2)]
        H=sum(r.height for r in rows); W=max(r.width for r in rows); g=Image.new('RGB',(W,H)); y=0
        for r in rows: g.paste(r,(0,y)); y+=r.height
        g.save('check_%02X.png'%rid)
