import struct, numpy as np, sys
from emd import load, parse_tmd
from sh import parse_tim, rgb555
from chris import skeleton
from render import render, sheet
def rotm(x,y,z):
    sx,sy,sz=[a*2*np.pi/4096 for a in (-x,y,-z)]
    S=np.sin; C=np.cos
    return np.array([[C(sz)*C(sy), -C(sy)*S(sz), S(sy)],
        [S(sx)*S(sy)*C(sz)+C(sx)*S(sz), C(sx)*C(sz)-S(sx)*S(sz)*S(sy), -S(sx)*C(sy)],
        [S(sx)*S(sz)-C(sx)*S(sy)*C(sz), S(sz)*S(sy)*C(sx)+S(sx)*C(sz), C(sx)*C(sy)]])
def posed_tris(path, anim, fi):
    d,dirs=load(path); _,_,objs=parse_tmd(d,dirs[3]); rel,par,world=skeleton(d)
    a,fo,cnt,fs=struct.unpack_from('<4H',d,0)
    edd=dirs[2]; n,off=struct.unpack_from('<HH',d,edd+anim*4)
    fidx,timing=struct.unpack_from('<HH',d,edd+off+4*(fi%n))
    fr=struct.unpack_from('<%dh'%(fs//2),d,fo+fidx*fs)
    W=[None]*cnt
    for k in range(cnt):
        R=rotm(*fr[6+3*k:9+3*k])
        if par[k]<0: W[k]=(R,np.array(fr[0:3],float))
        else:
            PR,Pt=W[par[k]]; W[k]=(PR@R, PR@rel[k]+Pt)
    tim=parse_tim(d[dirs[4]:]); texs=[rgb555(tim['clut']['data'][r])[tim['idx']] for r in range(tim['clut']['h'])]
    tris=[]
    for i,o in enumerate(objs[:cnt]):
        R,t=W[i]; V=np.array([v[:3] for v in o['verts']],float)@R.T+t
        for mode,flag,olen,ilen,body in o['prims']:
            u0,v0,cba,u1,v1,tsb,u2,v2,_,n0,i0,n1,i1,n2,i2=struct.unpack('<BBHBBHBBH6H',body)
            off=(tsb&0x1f)*128
            tris.append((V[[i0,i1,i2]],np.array([(u0+off,v0),(u1+off,v1),(u2+off,v2)],float),texs[((cba>>6)&0x1ff)-480],None))
    return tris, n
if __name__=='__main__':
    path=sys.argv[1]; out=sys.argv[2]; shots=[tuple(map(int,s.split(':'))) for s in sys.argv[3:]]
    ims=[]; labels=[]
    for anim,fi in shots:
        tris,n=posed_tris(path,anim,fi)
        ims.append(render(tris,300,'side',bounds=(np.array([-1500,-3000,-1500]),np.array([1500,100,1500])))); labels.append(f'anim {anim} f{fi}/{n}')
    sheet(ims,labels).save(out)
