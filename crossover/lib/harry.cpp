// harry.cpp - Harry Mason (Silent Hill ILM/ANM/TIM) -> RE player EMD.
//
// Pipeline (see crossover/README.md for the format notes):
//   1. Pose Harry's skeleton with the first keyframe of ANIM/HB_BASE.ANM.
//   2. Replay Silent Hill's shared vertex/normal scratch buffers in the ILM's
//      model draw order, so the polygons that stitch neighbouring bones
//      together (thigh->hip, forearm->upper arm...) resolve to real positions.
//   3. Map SH space (+Z forward) onto RE space (+X forward) with a proper
//      rotation, scale so Harry's waist sits at the RE root height, and re-aim
//      every limb segment along the RE rest pose (arms/legs straight down),
//      keeping Harry's own segment lengths.
//   4. Rewrite the EMD's joint offsets to Harry's proportions; keep its
//      animations (rotations) and any objects beyond the 15 body parts.
//   5. Repack the 4bpp / 15-CLUT texture into RE's 8bpp 256x256 layout.
#include "crossover.h"
#include <array>
#include <cmath>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
#include <algorithm>
#include <tuple>

namespace crossover {
namespace {

// ----------------------------------------------------------------- math
using V3 = std::array<double, 3>;
using M3 = std::array<double, 9>;   // row-major

V3 operator+(V3 a, V3 b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
V3 operator-(V3 a, V3 b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
V3 operator*(double s, V3 a) { return {s * a[0], s * a[1], s * a[2]}; }
double dot(V3 a, V3 b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
V3 cross(V3 a, V3 b) { return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]}; }
double norm(V3 a) { return std::sqrt(dot(a, a)); }
V3 mul(const M3& m, V3 v)
{
    return {m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
            m[6] * v[0] + m[7] * v[1] + m[8] * v[2]};
}
M3 mul(const M3& a, const M3& b)
{
    M3 r{};
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
    return r;
}
const M3 I3 = {1, 0, 0, 0, 1, 0, 0, 0, 1};
// SH (+Z forward) -> RE (+X forward), Y down in both; det +1 (no mirroring)
const M3 kM = {0, 0, 1, 0, 1, 0, -1, 0, 0};

M3 RotBetween(V3 a, V3 b)
{
    a = (1.0 / norm(a)) * a;
    b = (1.0 / norm(b)) * b;
    V3 v = cross(a, b);
    double c = dot(a, b);
    if (norm(v) < 1e-9) return c > 0 ? I3 : M3{-1, 0, 0, 0, -1, 0, 0, 0, -1};
    M3 vx = {0, -v[2], v[1], v[2], 0, -v[0], -v[1], v[0], 0};
    M3 vx2 = mul(vx, vx);
    M3 r{};
    double k = 1.0 / (1.0 + c);
    for (int i = 0; i < 9; i++) r[i] = I3[i] + vx[i] + vx2[i] * k;
    return r;
}

// round half to even, like numpy.round
long RoundEven(double x) { return std::lrint(x); }

template <class T> T Rd(const Bytes& d, size_t o)
{
    T v;
    if (o + sizeof(T) > d.size()) throw std::runtime_error("truncated file");
    memcpy(&v, &d[o], sizeof(T));
    return v;
}

// ----------------------------------------------------------------- SH formats
struct ShPrim { uint8_t uv[4][2]; uint16_t clut; uint8_t pi[4], ni[4]; };
struct ShMesh { std::vector<V3> pos, nrm; std::vector<ShPrim> prims; };
struct ShModel { std::string name; int bone; int vofs, nofs; std::vector<ShMesh> meshes; int id; };

std::vector<ShModel> ParseIlm(const Bytes& d)
{
    if (d.empty() || d[0] != 0x30) throw std::runtime_error("HERO.ILM: bad header");
    uint32_t mc = Rd<uint32_t>(d, 8), mo = Rd<uint32_t>(d, 12), mio = Rd<uint32_t>(d, 16);
    std::vector<ShModel> models;
    for (uint32_t i = 0; i < mc; i++) {
        size_t o = mo + i * 16;
        ShModel m;
        char nm[9] = {};
        memcpy(nm, &d.at(o), 8);
        m.name = nm;
        m.bone = (nm[0] - '0') * 10 + (nm[1] - '0');
        int meshCount = d.at(o + 8);
        m.vofs = d.at(o + 9);
        m.nofs = d.at(o + 10);
        uint32_t mh = Rd<uint32_t>(d, o + 12);
        for (int k = 0; k < meshCount; k++) {
            size_t b = mh + k * 24;
            int npr = d.at(b), npos = d.at(b + 1), nnor = d.at(b + 2);
            uint32_t po = Rd<uint32_t>(d, b + 4), xyo = Rd<uint32_t>(d, b + 8),
                     zo = Rd<uint32_t>(d, b + 12), no = Rd<uint32_t>(d, b + 16);
            ShMesh mesh;
            for (int v = 0; v < npos; v++)
                mesh.pos.push_back({(double)Rd<int16_t>(d, xyo + v * 4), (double)Rd<int16_t>(d, xyo + v * 4 + 2),
                                    (double)Rd<int16_t>(d, zo + v * 2)});
            for (int v = 0; v < nnor; v++)
                mesh.nrm.push_back({Rd<int8_t>(d, no + v * 4) / 128.0, Rd<int8_t>(d, no + v * 4 + 1) / 128.0,
                                    Rd<int8_t>(d, no + v * 4 + 2) / 128.0});
            for (int p = 0; p < npr; p++) {
                size_t q = po + p * 20;
                ShPrim pr;
                pr.uv[0][0] = d.at(q); pr.uv[0][1] = d.at(q + 1);
                pr.clut = Rd<uint16_t>(d, q + 2);
                pr.uv[1][0] = d.at(q + 4); pr.uv[1][1] = d.at(q + 5);
                pr.uv[2][0] = d.at(q + 8); pr.uv[2][1] = d.at(q + 9);
                pr.uv[3][0] = d.at(q + 10); pr.uv[3][1] = d.at(q + 11);
                for (int c = 0; c < 4; c++) { pr.pi[c] = d.at(q + 12 + c); pr.ni[c] = d.at(q + 16 + c); }
                mesh.prims.push_back(pr);
            }
            m.meshes.push_back(mesh);
        }
        m.id = d.at(mio + i);
        models.push_back(m);
    }
    return models;
}

struct Pose { M3 R; V3 t; };

std::vector<Pose> AnmWorld(const Bytes& d, int frame)
{
    int kfoff = Rd<int16_t>(d, 0), rc = d.at(2), tc = d.at(3), ks = Rd<int16_t>(d, 4), bc = Rd<int16_t>(d, 6);
    int tshift = d.at(18);
    size_t o = kfoff + (size_t)frame * ks;
    std::vector<V3> tr;
    for (int i = 0; i < tc; i++)
        tr.push_back({(double)(Rd<int8_t>(d, o + 3 * i) * (1 << tshift)), (double)(Rd<int8_t>(d, o + 3 * i + 1) * (1 << tshift)),
                      (double)(Rd<int8_t>(d, o + 3 * i + 2) * (1 << tshift))});
    o += 3 * tc;
    std::vector<M3> rot;
    for (int i = 0; i < rc; i++) {
        M3 r;
        for (int k = 0; k < 9; k++) r[k] = Rd<int8_t>(d, o + 9 * i + k) / 128.0;
        rot.push_back(r);
    }
    std::vector<Pose> W(bc);
    for (int i = 0; i < bc; i++) {
        size_t b = 20 + i * 6;
        int parent = Rd<int8_t>(d, b), ri = Rd<int8_t>(d, b + 1), ti = Rd<int8_t>(d, b + 2);
        V3 bind = {(double)(Rd<int8_t>(d, b + 3) * (1 << tshift)), (double)(Rd<int8_t>(d, b + 4) * (1 << tshift)),
                   (double)(Rd<int8_t>(d, b + 5) * (1 << tshift))};
        M3 R = ri < 0 ? I3 : rot.at(ri);
        V3 t = ti < 0 ? bind : tr.at(ti);
        if (parent < 0) W[i] = {R, t};
        else W[i] = {mul(W[parent].R, R), mul(W[parent].R, t) + W[parent].t};
    }
    return W;
}

struct Tim {
    int bpp = 0;
    int clutW = 0, clutH = 0;
    std::vector<uint16_t> clut;   // clutH rows of clutW
    int w = 0, h = 0;             // in texels
    std::vector<uint8_t> idx;
    size_t end = 0;
};

Tim ParseTim(const Bytes& d, size_t base)
{
    Tim t;
    uint32_t flag = Rd<uint32_t>(d, base + 4);
    t.bpp = (flag & 3) == 0 ? 4 : (flag & 3) == 1 ? 8 : 16;
    size_t o = base + 8;
    if (flag & 8) {
        uint32_t cl = Rd<uint32_t>(d, o);
        t.clutW = Rd<uint16_t>(d, o + 8);
        t.clutH = Rd<uint16_t>(d, o + 10);
        for (int i = 0; i < t.clutW * t.clutH; i++) t.clut.push_back(Rd<uint16_t>(d, o + 12 + i * 2));
        o += cl;
    }
    uint32_t il = Rd<uint32_t>(d, o);
    int hw = Rd<uint16_t>(d, o + 8);
    t.h = Rd<uint16_t>(d, o + 10);
    t.w = t.bpp == 4 ? hw * 4 : hw * 2;
    for (int y = 0; y < t.h; y++)
        for (int x = 0; x < hw * 2; x++) {
            uint8_t b = d.at(o + 12 + y * hw * 2 + x);
            if (t.bpp == 4) { t.idx.push_back(b & 15); t.idx.push_back(b >> 4); }
            else t.idx.push_back(b);
        }
    t.end = o + il;
    return t;
}

// ----------------------------------------------------------------- RE formats
struct ReObj { std::vector<std::array<int16_t, 4>> v, n; Bytes prim; uint32_t nprim; };

struct ReEmd {
    uint32_t dir[5];
    std::vector<V3> rel, world;
    std::vector<int> par;
    std::vector<ReObj> objs;
};

ReEmd ParseEmd(const Bytes& d)
{
    ReEmd e;
    size_t n = d.size() & ~(size_t)3;
    if (n < 20) throw std::runtime_error("RE model file is too small");
    for (int i = 0; i < 5; i++) e.dir[i] = Rd<uint32_t>(d, n - 20 + i * 4);
    uint16_t a = Rd<uint16_t>(d, 0), c = Rd<uint16_t>(d, 4);
    for (int i = 0; i < c; i++)
        e.rel.push_back({(double)Rd<int16_t>(d, 8 + 6 * i), (double)Rd<int16_t>(d, 10 + 6 * i), (double)Rd<int16_t>(d, 12 + 6 * i)});
    e.par.assign(c, -1);
    for (int i = 0; i < c; i++) {
        uint16_t cn = Rd<uint16_t>(d, a + 4 * i), co = Rd<uint16_t>(d, a + 4 * i + 2);
        for (int k = 0; k < cn; k++) e.par[d.at(a + co + k)] = i;
    }
    e.world.resize(c);
    for (int i = 0; i < c; i++) e.world[i] = e.par[i] < 0 ? e.rel[i] : e.rel[i] + e.world[e.par[i]];
    size_t base = e.dir[3];
    if (Rd<uint32_t>(d, base) != 0x41) throw std::runtime_error("RE model: mesh block is not a TMD");
    uint32_t nobj = Rd<uint32_t>(d, base + 8);
    size_t ot = base + 12;
    for (uint32_t i = 0; i < nobj; i++) {
        uint32_t vt = Rd<uint32_t>(d, ot + i * 28), nv = Rd<uint32_t>(d, ot + i * 28 + 4);
        uint32_t nt = Rd<uint32_t>(d, ot + i * 28 + 8), nn = Rd<uint32_t>(d, ot + i * 28 + 12);
        uint32_t pt = Rd<uint32_t>(d, ot + i * 28 + 16), np = Rd<uint32_t>(d, ot + i * 28 + 20);
        ReObj o;
        for (uint32_t k = 0; k < nv; k++)
            o.v.push_back({Rd<int16_t>(d, ot + vt + k * 8), Rd<int16_t>(d, ot + vt + k * 8 + 2),
                           Rd<int16_t>(d, ot + vt + k * 8 + 4), Rd<int16_t>(d, ot + vt + k * 8 + 6)});
        for (uint32_t k = 0; k < nn; k++)
            o.n.push_back({Rd<int16_t>(d, ot + nt + k * 8), Rd<int16_t>(d, ot + nt + k * 8 + 2),
                           Rd<int16_t>(d, ot + nt + k * 8 + 4), Rd<int16_t>(d, ot + nt + k * 8 + 6)});
        size_t p = ot + pt;
        for (uint32_t k = 0; k < np; k++) {
            uint8_t ilen = d.at(p + 1);
            o.prim.insert(o.prim.end(), d.begin() + p, d.begin() + p + 4 + ilen * 4);
            p += 4 + ilen * 4;
        }
        o.nprim = np;
        e.objs.push_back(o);
    }
    if (e.objs.size() < 15 || c != 15) throw std::runtime_error("RE model: not a 15-bone player model");
    return e;
}

// ----------------------------------------------------------------- mapping
struct Map { const char* name; int re; };
// RE bones: 0 torso, 1 head, 2 pelvis, 3-5 leg(+z), 6-8 leg(-z), 9-11 arm(+z),
// 12-14 arm(-z). In the posed SH skeleton the "L" limbs sit at -x, which kM
// sends to RE +z. Order matters: it is the fallback order for stitched-in
// vertices of models that are not drawn (first entry with the same bone).
const Map kModelToRe[] = {
    {"01CHEST_", 0}, {"02HEAD1", 1}, {"02NECK", 1}, {"11HIP_TC", 2}, {"11HIP2_T", 2},
    {"12LMOMO", 3}, {"13LSUNE", 4}, {"14LFOOT", 5}, {"15RMOMO", 6}, {"16RSUNE", 7}, {"17RFOOT", 8},
    {"03LSHOUL", 9}, {"04LJOU", 9}, {"05LZEN", 10}, {"06LHAND", 11},
    {"07RSHOUL", 12}, {"08RJOU", 12}, {"09RZEN", 13}, {"10RHAND", 14},
};
const int kRePivotSh[15] = {1, 2, 11, 12, 13, 14, 15, 16, 17, 4, 5, 6, 8, 9, 10};
const std::map<int, int> kSegmentChild = {{3, 4}, {4, 5}, {6, 7}, {7, 8}, {9, 10}, {10, 11}, {12, 13}, {13, 14}, {0, 1}};
const std::map<int, int> kInherit = {{5, 4}, {8, 7}, {11, 10}, {14, 13}, {1, 0}, {2, -1}};

int ModelRe(const std::string& n)
{
    for (const auto& m : kModelToRe) if (n == m.name) return m.re;
    return -1;
}

struct PolyV { V3 p, n; std::string src; };
struct Poly { int re; std::vector<PolyV> v; std::vector<std::array<int, 2>> uv; int clut; };

} // namespace

bool ConvertHarry(const SilentHillDisc& sh, const Bytes& reEmd, Bytes& out, std::string& err)
{
    try {
        Bytes ilmB, anmB, timB;
        if (!sh.readFile("CHARA/HERO.ILM", ilmB, err) || !sh.readFile("CHARA/HERO.TIM", timB, err) ||
            !sh.readFile("ANIM/HB_BASE.ANM", anmB, err))
            return false;
        std::vector<ShModel> models = ParseIlm(ilmB);
        std::vector<Pose> W = AnmWorld(anmB, 0);
        Tim tim = ParseTim(timB, 0);
        ReEmd re = ParseEmd(reEmd);

        std::vector<V3> Jsh;
        for (auto& w : W) Jsh.push_back(w.t);

        // ---- 2. replay the SH scratch buffers in draw order
        std::map<int, std::pair<V3, std::string>> vbuf;
        std::map<int, V3> nbuf;
        std::vector<Poly> polys;
        for (size_t oi = 0; oi < models.size(); oi++) {
            const ShModel& m = models.at(models[oi].id);
            const Pose& P = W.at(m.bone);
            for (const ShMesh& mesh : m.meshes) {
                for (size_t k = 0; k < mesh.pos.size(); k++) vbuf[m.vofs + (int)k] = {mul(P.R, mesh.pos[k]) + P.t, m.name};
                for (size_t k = 0; k < mesh.nrm.size(); k++) nbuf[m.nofs + (int)k] = mul(P.R, mesh.nrm[k]);
                int reb = ModelRe(m.name);
                if (reb < 0) continue;
                for (const ShPrim& pr : mesh.prims) {
                    int nc = pr.pi[3] == 255 ? 3 : 4;
                    Poly poly;
                    poly.re = reb;
                    poly.clut = pr.clut >> 6;
                    for (int c = 0; c < nc; c++) {
                        auto it = vbuf.find(pr.pi[c]);
                        if (it == vbuf.end()) throw std::runtime_error("HERO.ILM: unresolved vertex");
                        auto nit = nbuf.find(pr.ni[c]);
                        poly.v.push_back({it->second.first, nit == nbuf.end() ? V3{0, 0, 0} : nit->second, it->second.second});
                        poly.uv.push_back({pr.uv[c][0], pr.uv[c][1]});
                    }
                    polys.push_back(poly);
                }
            }
        }
        // models that are not drawn still lend vertices: map them by bone
        std::map<std::string, int> srcRe;
        for (const auto& m : kModelToRe) srcRe[m.name] = m.re;
        for (const auto& m : models)
            if (!srcRe.count(m.name))
                for (const auto& mm : kModelToRe)
                    if ((mm.name[0] - '0') * 10 + (mm.name[1] - '0') == m.bone) { srcRe[m.name] = mm.re; break; }

        // ---- 3. scale + per-segment re-aim
        double ymax = -1e30;
        for (auto& p : polys) for (auto& v : p.v) ymax = std::max(ymax, v.p[1]);
        double reSole = -1e30;
        for (int i = 0; i < 15; i++)
            for (auto& v : re.objs[i].v) reSole = std::max(reSole, v[1] + re.world[i][1]);
        double s = (reSole - re.world[0][1]) / (ymax - Jsh.at(1)[1]);
        auto g = [&](V3 v) { return s * mul(kM, v); };

        M3 R[15];
        for (int k = 0; k < 15; k++) {
            auto it = kSegmentChild.find(k);
            if (it != kSegmentChild.end()) {
                int c = it->second;
                R[k] = RotBetween(g(Jsh[kRePivotSh[c]]) - g(Jsh[kRePivotSh[k]]), re.world[c] - re.world[k]);
            }
        }
        for (auto& [k, p] : kInherit) R[k] = p < 0 ? I3 : R[p];
        V3 nw[15];
        for (int k = 0; k < 15; k++) {
            int p = re.par[k];
            nw[k] = p < 0 ? re.world[0] : nw[p] + mul(R[p], g(Jsh[kRePivotSh[k]] - Jsh[kRePivotSh[p]]));
        }
        auto apply = [&](int k, V3 v) { return nw[k] + mul(R[k], g(v - Jsh[kRePivotSh[k]])); };
        auto applyN = [&](int k, V3 n) {
            V3 r = mul(R[k], mul(kM, n));
            double l = norm(r);
            return l > 0 ? (1.0 / l) * r : r;
        };

        // ---- 5. texture: one 256-colour palette, CLUT row baked into the index
        std::set<int> used;
        for (auto& p : polys) used.insert(p.clut);
        if (used.size() > 16) throw std::runtime_error("HERO.TIM: too many palettes");
        std::map<int, int> slot;
        for (int c : used) { int i = (int)slot.size(); slot[c] = i; }
        uint16_t pal[256] = {};
        for (auto& [c, i] : slot)
            for (int k = 0; k < 16; k++) {
                uint16_t row = tim.clut.at(c * tim.clutW + k);
                uint16_t col = row & 0x7FFF;
                if (col == 0 && (row & 0x8000)) col = 0x8000;   // opaque black stays opaque
                pal[i * 16 + k] = col;
            }
        std::vector<int> owner(tim.idx.size(), -1);
        for (auto& p : polys) {
            int x0 = 255, y0 = 255, x1 = 0, y1 = 0;
            for (auto& uv : p.uv) { x0 = std::min(x0, uv[0]); y0 = std::min(y0, uv[1]); x1 = std::max(x1, uv[0]); y1 = std::max(y1, uv[1]); }
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    if (y < tim.h && x < tim.w) owner[y * tim.w + x] = slot[p.clut];
        }
        std::vector<uint8_t> baked(tim.idx.size());
        for (size_t i = 0; i < baked.size(); i++) baked[i] = (uint8_t)((owner[i] < 0 ? 0 : owner[i]) * 16 + tim.idx[i]);
        if (tim.w != 256) throw std::runtime_error("HERO.TIM: unexpected width");
        std::vector<uint8_t> img(256 * 256, 0);
        int h = std::min(128, tim.h);
        memcpy(img.data(), baked.data(), (size_t)h * 256);
        std::vector<std::vector<std::array<int, 2>>> uvp(polys.size());
        std::vector<int> page(polys.size(), 0);
        std::vector<size_t> spill;
        for (size_t i = 0; i < polys.size(); i++) {
            int mn = 999, mx = -1, vmax = 0;
            for (auto& uv : polys[i].uv) { mn = std::min(mn, uv[0]); mx = std::max(mx, uv[0]); vmax = std::max(vmax, uv[1]); }
            if (vmax >= 128) throw std::runtime_error("HERO.TIM: texture layout not supported");
            if (mx < 128) { uvp[i] = polys[i].uv; page[i] = 0; }
            else if (mn >= 128) { for (auto uv : polys[i].uv) uvp[i].push_back({uv[0] - 128, uv[1]}); page[i] = 1; }
            else spill.push_back(i);
        }
        if (!spill.empty()) {
            int u0 = 999, v0 = 999, u1 = -1, v1 = -1;
            for (size_t i : spill) for (auto& uv : polys[i].uv) {
                u0 = std::min(u0, uv[0]); v0 = std::min(v0, uv[1]); u1 = std::max(u1, uv[0]); v1 = std::max(v1, uv[1]);
            }
            if (u1 - u0 >= 128 || v1 - v0 >= 128) throw std::runtime_error("HERO.TIM: spill region too big");
            for (int y = v0; y <= v1; y++)
                memcpy(&img[(128 + y - v0) * 256], &baked[y * 256 + u0], (size_t)(u1 - u0 + 1));
            for (size_t i : spill) {
                uvp[i].clear();
                for (auto uv : polys[i].uv) uvp[i].push_back({uv[0] - u0, uv[1] - v0 + 128});
                page[i] = 0;
            }
        }

        // ---- objects
        struct Obj {
            std::vector<std::array<int16_t, 3>> v, n;
            std::map<std::array<int16_t, 3>, int> vmap, nmap;
            Bytes prim;
            uint32_t nprim = 0;
        } objs[15];
        auto key = [](V3 p) {
            return std::array<int16_t, 3>{(int16_t)RoundEven(p[0]), (int16_t)RoundEven(p[1]), (int16_t)RoundEven(p[2])};
        };
        auto put = [](Bytes& b, const void* p, size_t n) { b.insert(b.end(), (const uint8_t*)p, (const uint8_t*)p + n); };
        for (size_t pi = 0; pi < polys.size(); pi++) {
            const Poly& poly = polys[pi];
            int k = poly.re;
            Obj& o = objs[k];
            auto vid = [&](V3 p) {
                auto kk = key(p);
                auto it = o.vmap.find(kk);
                if (it != o.vmap.end()) return it->second;
                int id = (int)o.v.size();
                o.vmap[kk] = id; o.v.push_back(kk);
                return id;
            };
            auto nid = [&](V3 n) {
                std::array<int16_t, 3> kk;
                for (int c = 0; c < 3; c++) kk[c] = (int16_t)std::max(-32768L, std::min(32767L, RoundEven(n[c] * 4096)));
                auto it = o.nmap.find(kk);
                if (it != o.nmap.end()) return it->second;
                int id = (int)o.n.size();
                o.nmap[kk] = id; o.n.push_back(kk);
                return id;
            };
            std::vector<V3> P, N;
            for (auto& v : poly.v) {
                int sk = srcRe.at(v.src);
                P.push_back(apply(sk, v.p));
                N.push_back(applyN(sk, v.n));
            }
            std::vector<std::array<int, 3>> tris = {{0, 1, 2}};
            if (poly.v.size() == 4) tris.push_back({1, 3, 2});
            for (auto t : tris) {
                V3 a = P[t[0]] - nw[k], b = P[t[1]] - nw[k], c = P[t[2]] - nw[k];
                V3 fn = cross(b - a, c - a);
                V3 an = N[t[0]] + N[t[1]] + N[t[2]];
                if (dot(fn, an) > 0) std::swap(t[1], t[2]);   // RE: cross(v1-v0,v2-v0) opposes the normal
                int vi[3], ni[3];
                for (int c2 = 0; c2 < 3; c2++) { vi[c2] = vid(P[t[c2]] - nw[k]); ni[c2] = nid(N[t[c2]]); }
                uint16_t cba = page[pi] == 0 ? 0x7800 : 0x7840;
                uint16_t tsb = (uint16_t)(0x80 | page[pi]);
                uint8_t hdr[4] = {9, 6, 0, 0x34};
                put(o.prim, hdr, 4);
                uint8_t uv0[2] = {(uint8_t)uvp[pi][t[0]][0], (uint8_t)uvp[pi][t[0]][1]};
                uint8_t uv1[2] = {(uint8_t)uvp[pi][t[1]][0], (uint8_t)uvp[pi][t[1]][1]};
                uint8_t uv2[2] = {(uint8_t)uvp[pi][t[2]][0], (uint8_t)uvp[pi][t[2]][1]};
                uint16_t pad = 0;
                put(o.prim, uv0, 2); put(o.prim, &cba, 2);
                put(o.prim, uv1, 2); put(o.prim, &tsb, 2);
                put(o.prim, uv2, 2); put(o.prim, &pad, 2);
                for (int c2 = 0; c2 < 3; c2++) {
                    uint16_t nn = (uint16_t)ni[c2], vv = (uint16_t)vi[c2];
                    put(o.prim, &nn, 2); put(o.prim, &vv, 2);
                }
                o.nprim++;
            }
        }

        // ---- write TMD (15 converted objects + the RE model's extra objects)
        struct Blob { Bytes prim; uint32_t np; Bytes v; uint32_t nv; Bytes n; uint32_t nn; };
        std::vector<Blob> blobs;
        for (int k = 0; k < 15; k++) {
            if (objs[k].nprim == 0) throw std::runtime_error("conversion produced an empty body part");
            Blob b{objs[k].prim, objs[k].nprim, {}, (uint32_t)objs[k].v.size(), {}, (uint32_t)objs[k].n.size()};
            for (auto& v : objs[k].v) { int16_t q[4] = {v[0], v[1], v[2], 0}; put(b.v, q, 8); }
            for (auto& v : objs[k].n) { int16_t q[4] = {v[0], v[1], v[2], 0}; put(b.n, q, 8); }
            blobs.push_back(b);
        }
        for (size_t k = 15; k < re.objs.size(); k++) {
            Blob b{re.objs[k].prim, re.objs[k].nprim, {}, (uint32_t)re.objs[k].v.size(), {}, (uint32_t)re.objs[k].n.size()};
            for (auto& v : re.objs[k].v) put(b.v, v.data(), 8);
            for (auto& v : re.objs[k].n) put(b.n, v.data(), 8);
            blobs.push_back(b);
        }
        Bytes tmd, table, body;
        uint32_t nobj = (uint32_t)blobs.size();
        uint32_t off = nobj * 28;
        for (auto& b : blobs) {
            uint32_t po = off; off += (uint32_t)b.prim.size();
            uint32_t vo = off; off += (uint32_t)b.v.size();
            uint32_t no = off; off += (uint32_t)b.n.size();
            uint32_t row[7] = {vo, b.nv, no, b.nn, po, b.np, 0};
            put(table, row, 28);
            body.insert(body.end(), b.prim.begin(), b.prim.end());
            body.insert(body.end(), b.v.begin(), b.v.end());
            body.insert(body.end(), b.n.begin(), b.n.end());
        }
        uint32_t th[3] = {0x41, 0, nobj};
        put(tmd, th, 12);
        tmd.insert(tmd.end(), table.begin(), table.end());
        tmd.insert(tmd.end(), body.begin(), body.end());

        // ---- TIM (8bpp, 256x256, CLUT 256x2 at (0,480) like the RE originals)
        Bytes timOut;
        uint32_t t0[2] = {0x10, 9};
        put(timOut, t0, 8);
        uint32_t clen = 12 + 2 * 256 * 2;
        uint16_t chd[4] = {0, 480, 256, 2};
        put(timOut, &clen, 4); put(timOut, chd, 8);
        put(timOut, pal, 512); put(timOut, pal, 512);
        uint32_t plen = 12 + 256 * 256;
        uint16_t phd[4] = {0, 0, 128, 256};
        put(timOut, &plen, 4); put(timOut, phd, 8);
        put(timOut, img.data(), img.size());

        // ---- EMD: skeleton (joint offsets rewritten) + animations + TMD + TIM + directory
        out.assign(reEmd.begin(), reEmd.begin() + re.dir[3]);
        for (int k = 1; k < 15; k++) {
            V3 rel = nw[k] - nw[re.par[k]];
            for (int c = 0; c < 3; c++) {
                int16_t v = (int16_t)RoundEven(rel[c]);
                memcpy(&out[8 + 6 * k + 2 * c], &v, 2);
            }
        }
        uint32_t tmdOff = (uint32_t)out.size();
        out.insert(out.end(), tmd.begin(), tmd.end());
        while (out.size() % 4) out.push_back(0);
        uint32_t timOff = (uint32_t)out.size();
        out.insert(out.end(), timOut.begin(), timOut.end());
        while (out.size() % 4) out.push_back(0);
        uint32_t dir[5] = {re.dir[0], re.dir[1], re.dir[2], tmdOff, timOff};
        put(out, dir, 20);
        return true;
    } catch (const std::exception& e) {
        err = std::string("Harry conversion failed: ") + e.what();
        return false;
    }
}

} // namespace crossover
