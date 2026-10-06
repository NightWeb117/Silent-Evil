import struct, numpy as np, sys
from emd import load, parse_tmd
from sh import parse_tim, rgb555
from render import render, sheet
def skeleton(d, base=0):
    a,f,c,s=struct.unpack_from('<4H',d,base)
    rel=[np.array(struct.unpack_from('<3h',d,base+8+6*i),float) for i in range(c)]
    par=[-1]*c
    for i in range(c):
        n,o=struct.unpack_from('<HH',d,base+a+4*i)
        for ch in d[base+a+o:base+a+o+n]: par[ch]=i
    world=[None]*c
    for i in range(c):
        world[i]=rel[i]+(world[par[i]] if par[i]>=0 else 0)
    return rel,par,world
def emd_tris(path, which=None):
    d,dirs=load(path); _,_,objs=parse_tmd(d,dirs[3]); rel,par,world=skeleton(d)
    tim=parse_tim(d[dirs[4]:]); texs=[rgb555(tim['clut']['data'][r])[tim['idx']] for r in range(tim['clut']['h'])]
    tris=[]
    for i,o in enumerate(objs):
        if i>=len(world): continue
        if which is not None and i not in which: continue
        V=np.array([v[:3] for v in o['verts']],float)+world[i]
        for mode,flag,olen,ilen,body in o['prims']:
            u0,v0,cba,u1,v1,tsb,u2,v2,_,n0,i0,n1,i1,n2,i2=struct.unpack('<BBHBBHBBH6H',body)
            off=(tsb&0x1f)*128
            tris.append((V[[i0,i1,i2]],np.array([(u0+off,v0),(u1+off,v1),(u2+off,v2)],float),texs[(cba>>6)&0x1ff-480 if False else ((cba>>6)&0x1ff)-480],None))
    return tris,world
if __name__=='__main__':
    tris,world=emd_tris(sys.argv[1])
    print('bones world', [tuple(w.astype(int)) for w in world])
    sheet([render(tris,400,v) for v in ('front','side','back','side2')],['front(-z look)','side','back','side2']).save(sys.argv[2])
