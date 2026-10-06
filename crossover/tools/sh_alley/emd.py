import struct
from collections import Counter
def u32(d,o): return struct.unpack_from('<I',d,o)[0]
def load(path):
    d=open(path,'rb').read(); n=len(d)&~3
    dirs=struct.unpack('<5I',d[n-20:n])
    return d,dirs
def parse_tmd(d,base):
    ver,flags,nobj=struct.unpack_from('<III',d,base)
    ot=base+12; objs=[]
    for i in range(nobj):
        vt,nv,nt,nn,pt,np_,sc=struct.unpack_from('<IIIIIIi',d,ot+i*28)
        verts=[struct.unpack_from('<hhhh',d,ot+vt+k*8) for k in range(nv)]
        norms=[struct.unpack_from('<hhhh',d,ot+nt+k*8) for k in range(nn)]
        prims=[]; p=ot+pt
        for k in range(np_):
            olen,ilen,flag,mode=struct.unpack_from('<BBBB',d,p)
            body=d[p+4:p+4+ilen*4]; prims.append((mode,flag,olen,ilen,body)); p+=4+ilen*4
        objs.append(dict(verts=verts,norms=norms,prims=prims,scale=sc,raw=(vt,nv,nt,nn,pt,np_)))
    return ver,flags,objs
if __name__=='__main__':
    import sys
    d,dirs=load(sys.argv[1]); print([hex(x) for x in dirs])
    ver,fl,objs=parse_tmd(d,dirs[3])
    c=Counter()
    for i,o in enumerate(objs):
        modes=Counter((hex(p[0]),hex(p[1]),p[2],p[3]) for p in o['prims'])
        xs=[v[0] for v in o['verts']];ys=[v[1] for v in o['verts']];zs=[v[2] for v in o['verts']]
        print(i,o['raw'],dict(modes),'bbox',min(xs),max(xs),min(ys),max(ys),min(zs),max(zs))
        for p in o['prims']: c[(p[0],p[4][6:8].hex() if p[0]&4 else '', p[4][2:4].hex() if p[0]&4 else '')]+=1
    print(c.most_common(10))
    t=dirs[4]; print('TIM',struct.unpack_from('<II',d,t))
    clen,cx,cy,cw,ch=struct.unpack_from('<IHHHH',d,t+8); print('clut',cx,cy,cw,ch)
    o=t+8+clen; ilen,ix,iy,iw,ih=struct.unpack_from('<IHHHH',d,o); print('img',ix,iy,iw,ih,'px w',iw*2, 'end',o+ilen, len(d))
