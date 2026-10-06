import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_rooms import *
from build_alley import ROOMS, DOORS, room_frame, M
from scipy import ndimage
import numpy as np, struct
out=sys.argv[1]; R_=int(sys.argv[2]) if len(sys.argv)>2 else 450
st=os.path.join(out,'stage1')
def room_free(key):
    R=ROOMS[key]; d=open(os.path.join(st,'ROOM1%02X0.RDT'%R['id']),'rb').read(); h=parse_rdt(d)
    B=parse_boundaries(d,h['ptrs']['boundaries'])
    xs=[b['xmin'] for b in B['recs']]+[b['xmax'] for b in B['recs']]; zs=[b['zmin'] for b in B['recs']]+[b['zmax'] for b in B['recs']]
    x0,x1,z0,z1=min(xs),max(xs),min(zs),max(zs); step=50
    W=(x1-x0)//step+1; H=(z1-z0)//step+1
    occ=np.zeros((H,W),bool)
    for b in B['recs']:
        a=max(0,(b['xmin']-R_-x0)//step); bb=min(W-1,(b['xmax']+R_-x0)//step+1)
        c=max(0,(b['zmin']-R_-z0)//step); dd=min(H-1,(b['zmax']+R_-z0)//step+1)
        occ[c:dd+1,a:bb+1]=True
    return (x0,z0,step),~occ
def idx(g,p): x0,z0,s=g; return (int((p[2]-z0)//s), int((p[0]-x0)//s))
fails=0
# for each room: start/spawns must reach every door trigger centre in that room
for key,R in ROOMS.items():
    fr=room_frame(R['rect']); g,free=room_free(key); lab,_=ndimage.label(free)
    pts={}
    if 'start' in R: pts['start']=fr.to_re(np.array([R['start'][0][0]*M,0,R['start'][0][1]*M]))
    for (src,(dx,dz),wd,dst,(sx,sz),f,c) in DOORS:
        if src==key: pts['door->'+dst]=fr.to_re(np.array([dx*M,0,dz*M]))
        if dst==key: pts['spawn<-'+src]=fr.to_re(np.array([sx*M,0,sz*M]))
    if key=='C': pts['corpse']=fr.to_re(np.array([-251.9*M,0,219.5*M]))
    labs={k:lab[idx(g,p)] for k,p in pts.items()}
    # door triggers: test the nearest free cell within the trigger box (player only needs to touch it)
    print(key, {k:int(v) for k,v in labs.items()})
    comps=set(v for k,v in labs.items() if not k.startswith('door'))
    if 0 in comps or len(comps)!=1: print('  !! not all start/spawn points share one free region'); fails+=1
print('radius',R_,'FAILS',fails)
