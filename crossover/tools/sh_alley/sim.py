import sys, os, struct; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_rooms import *
from build_alley import ROOMS, DOORS, room_frame, M
import numpy as np
out=sys.argv[1]; st=os.path.join(out,'stage1')
rooms={}
for k,R in ROOMS.items():
    d=open(os.path.join(st,'ROOM1%02X0.RDT'%R['id']),'rb').read(); h=parse_rdt(d)
    B=parse_boundaries(d,h['ptrs']['boundaries']); Z=[]
    off=h['ptrs']['cam_switch']
    while True:
        to,frm=struct.unpack_from('<hh',d,off)
        if to==-1: break
        pts=struct.unpack_from('<8H',d,off+4); Z.append(dict(to=to,frm=frm,quad=[(pts[i],pts[i+1]) for i in range(0,8,2)])); off+=20
    # init script: doors + start
    io=h['ptrs']['init_scd']; size,=struct.unpack_from('<H',d,io); ops=d[io+2:io+size]
    rooms[k]=dict(h=h,B=B,Z=Z,ops=ops,fr=room_frame(R['rect']))
    print(k,'id %02X'%R['id'],'boxes',len(B['recs']),'zones',len(Z),'init bytes',len(ops))
RAD=int(sys.argv[2]) if len(sys.argv)>2 else 450   # generous player radius in RE units (~26 cm)
def clear(k,x,z,r=RAD): return not blocked(rooms[k]['B'],x,z,r)
def which_cam(k,x,z,cur):
    for zn in rooms[k]['Z']:
        if zn['frm']==cur and zn['to']!=9 and zone_contains(zn,x,z): return zn['to']
    return cur
# start
R=ROOMS['A']; fr=rooms['A']['fr']; (sx,sz),_=R['start']; p=fr.to_re(np.array([sx*M,0,sz*M]))
print('start RE',p.astype(int),'clear',clear('A',p[0],p[2]),'cam after load',which_cam('A',p[0],p[2],0))
for (src,(dx,dz),(w,dd),dst,(sx,sz),facing,cam) in DOORS:
    fs=rooms[src]['fr']; fd=rooms[dst]['fr']
    trig=fs.to_re(np.array([dx*M,0,dz*M])); spawn=fd.to_re(np.array([sx*M,0,sz*M]))
    # does the spawn sit inside a door trigger of the destination room? (would bounce back)
    bounce=False
    for (s2,(dx2,dz2),(w2,d2),*_ ) in DOORS:
        if s2!=dst: continue
        if abs(sx-dx2)<=w2/2 and abs(sz-dz2)<=d2/2: bounce=True
    print('door %s->%s trigger clear %s  spawn %s clear %s  bounce %s  entry cam %d -> %d'%(src,dst,clear(src,trig[0],trig[2],0),spawn.astype(int),clear(dst,spawn[0],spawn[2]),bounce,cam,which_cam(dst,spawn[0],spawn[2],cam)))
# route walk
route=[('A',[(-268.6,254.2),(-267.3,252.5),(-267.3,250),(-267.3,246.6),(-265,245.4),(-261,245.3),(-258.6,245.2)]),
       ('B',[(-259.6,245.6),(-259.6,242),(-259.6,238),(-259.6,234),(-259.6,230.4),(-259.6,229.2)]),
       ('C',[(-259.3,229.4),(-256,229.3),(-253,229.3),(-252.0,227),(-252.0,223),(-251.9,219.5),(-251.5,218)])]
for k,pts in route:
    fr=rooms[k]['fr']; cam=None; bad=[]
    for a,b in zip(pts,pts[1:]):
        for t in np.linspace(0,1,12):
            x=a[0]+(b[0]-a[0])*t; z=a[1]+(b[1]-a[1])*t; p=fr.to_re(np.array([x*M,0,z*M]))
            if not clear(k,p[0],p[2]): bad.append((round(x,2),round(z,2)))
    print('route',k,'blocked points:',len(bad), bad[:6])
