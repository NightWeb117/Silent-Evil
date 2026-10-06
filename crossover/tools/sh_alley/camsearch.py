import sys, itertools; sys.path.insert(0,'.')
from build_alley import *
import camrender
from PIL import Image
world=load_world()
camrender.textured_orig=camrender.textured
def void_frac(fr, frm, to, fov, tris):
    camrender.textured=lambda tri: (None,None)
    img=render_bg(tris, fr.to_re(np.array(frm)*M), fr.to_re(np.array(to)*M), fov, fog_near=1e9, fog_far=2e9, ss=1, W=80, H=60)
    camrender.textured=camrender.textured_orig
    return (img[15:].sum(-1)==0).mean()
def search(room, positions, targets, fovs=(200,220,240), top=4):
    R=ROOMS[room]; fr=room_frame(R['rect'])
    tris=[(fr.to_re(t['P']),t['uv'],t) for t in world]
    res=[]
    for p in positions:
        for tgt in targets:
            for fv in fovs:
                frm=(p[0],-2.7,p[1]); to=(tgt[0],-0.8,tgt[1])
                res.append((void_frac(fr,frm,to,fv,tris),frm,to,fv))
    res.sort(key=lambda r:r[0])
    return res[:top]
if __name__=='__main__':
    pos=[(-266.6,261.0),(-266.6,258.3),(-270.6,258.5),(-270.6,261.0),(-268.0,261.0),(-266.8,254.6),(-270.4,254.5)]
    tg=[(-268.4,259.0),(-267.4,252.0),(-270.0,257.0),(-268.0,255.0)]
    for r in search('A',pos,tg): print(round(r[0],3), r[1], r[2], r[3])
