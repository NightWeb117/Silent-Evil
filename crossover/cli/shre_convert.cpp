// shre_convert - command-line asset builder for the Silent Hill x RE crossover.
//
//   shre_convert --re <RE folder> --sh <Silent Hill .cue/.bin/.iso> --out <mod folder> [--jill]
//   shre_convert --sh <image> --list                 (list Silent Hill's files)
//   shre_convert --sh <image> --extract <SH path> <file>
#include "../lib/crossover.h"
#include <cstdio>
#include <cstring>
#include <string>

using namespace crossover;

static int Usage()
{
    fprintf(stderr,
            "usage:\n"
            "  shre_convert --re <RE folder> --sh <Silent Hill .cue/.bin/.iso> --out <mod folder> [--jill]\n"
            "  shre_convert --sh <image> --list\n"
            "  shre_convert --sh <image> --extract <CHARA/HERO.ILM> <output file>\n");
    return 2;
}

int main(int argc, char** argv)
{
    BuildOptions opt;
    bool list = false;
    std::string exPath, exOut;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&](std::string& dst) { if (i + 1 >= argc) return false; dst = argv[++i]; return true; };
        if (a == "--re") { if (!next(opt.reRegionDir)) return Usage(); }
        else if (a == "--sh") { if (!next(opt.shImage)) return Usage(); }
        else if (a == "--out") { if (!next(opt.outDir)) return Usage(); }
        else if (a == "--jill") opt.replaceJill = true;
        else if (a == "--list") list = true;
        else if (a == "--extract") { if (!next(exPath) || !next(exOut)) return Usage(); }
        else return Usage();
    }
    std::string err;
    if (list || !exPath.empty()) {
        SilentHillDisc sh;
        if (opt.shImage.empty() || !sh.open(opt.shImage, err)) { fprintf(stderr, "error: %s\n", err.c_str()); return 1; }
        if (list) {
            printf("%s\n", sh.release()->id);
            for (auto& f : sh.listFiles()) printf("%s\n", f.c_str());
            return 0;
        }
        Bytes b;
        if (!sh.readFile(exPath, b, err) || !WriteWholeFile(exOut, b)) { fprintf(stderr, "error: %s\n", err.c_str()); return 1; }
        return 0;
    }
    if (opt.reRegionDir.empty() || opt.shImage.empty() || opt.outDir.empty()) return Usage();
    if (!BuildMod(opt, [](const std::string& s) { printf("%s\n", s.c_str()); fflush(stdout); }, err)) {
        fprintf(stderr, "error: %s\n", err.c_str());
        return 1;
    }
    return 0;
}
