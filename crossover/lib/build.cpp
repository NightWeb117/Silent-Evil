// build.cpp - Generates the mod overlay tree from the player's own game files.
#include "crossover.h"
#include <cctype>
#include <cstdio>
#include <filesystem>

namespace fs = std::filesystem;

namespace crossover {

static fs::path U8(const std::string& s)
{
#if defined(__cpp_char8_t)
    return fs::path(std::u8string(s.begin(), s.end()));
#else
    return fs::u8path(s);
#endif
}

static std::string FromPath(const fs::path& p)
{
    auto u = p.u8string();
    return std::string(u.begin(), u.end());
}

static bool IEquals(const std::string& a, const std::string& b)
{
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); i++)
        if (std::tolower((unsigned char)a[i]) != std::tolower((unsigned char)b[i])) return false;
    return true;
}

// Case-insensitive child lookup (Linux installs keep the original's mixed case).
static std::string FindChild(const std::string& dir, const std::string& name, bool wantDir)
{
    std::error_code ec;
    for (auto it = fs::directory_iterator(U8(dir), ec); !ec && it != fs::directory_iterator(); it.increment(ec)) {
        std::string n = FromPath(it->path().filename());
        if (IEquals(n, name) && (wantDir ? it->is_directory(ec) : it->is_regular_file(ec)))
            return FromPath(it->path());
    }
    return "";
}

static std::string FindRel(std::string dir, const std::string& rel, bool lastIsDir)
{
    size_t p = 0;
    while (!dir.empty()) {
        size_t q = rel.find('/', p);
        std::string part = rel.substr(p, q == std::string::npos ? std::string::npos : q - p);
        bool last = q == std::string::npos;
        dir = FindChild(dir, part, last ? lastIsDir : true);
        if (last) break;
        p = q + 1;
    }
    return dir;
}

std::string FindReRegionDir(const std::string& picked)
{
    static const char* kTries[] = {"", "USA", "english/USA", "English/USA"};
    for (const char* t : kTries) {
        std::string dir = *t ? FindRel(picked, t, true) : picked;
        if (dir.empty()) continue;
        if (!FindRel(dir, "Enemy/char10.emd", false).empty()) return dir;
    }
    return "";
}

static bool ConvertOne(const SilentHillDisc& sh, const std::string& region, const std::string& rel,
                       const std::string& outDir, const Log& log, std::string& err)
{
    std::string src = FindRel(region, rel, false);
    Bytes in, out;
    if (src.empty() || !ReadWholeFile(src, in)) {
        err = "Resident Evil file not found: " + rel;
        return false;
    }
    if (!ConvertHarry(sh, in, out, err)) return false;
    std::string dst = JoinPath(outDir, "enemy");
    if (!MakeDirs(dst)) { err = "Cannot create " + dst; return false; }
    std::string name = rel.substr(rel.rfind('/') + 1);
    for (auto& c : name) c = (char)std::tolower((unsigned char)c);
    dst = JoinPath(dst, name);
    if (!WriteWholeFile(dst, out)) { err = "Cannot write " + dst; return false; }
    log("  wrote enemy/" + name + " (" + std::to_string(out.size()) + " bytes)");
    return true;
}

bool BuildMod(const BuildOptions& opt, const Log& log, std::string& err)
{
    std::string region = FindReRegionDir(opt.reRegionDir);
    if (region.empty()) {
        err = "That folder does not look like a Resident Evil (PC) install: no Enemy\\char10.emd under it, "
              "its USA folder or english\\USA.";
        return false;
    }
    log("Resident Evil data: " + region);

    SilentHillDisc sh;
    if (!sh.open(opt.shImage, err)) return false;
    log(std::string("Silent Hill disc: ") + sh.release()->id);

    if (!MakeDirs(opt.outDir)) { err = "Cannot create " + opt.outDir; return false; }
    // Remove what an earlier build generated so a re-run never mixes versions.
    std::error_code ec;
    fs::remove_all(U8(JoinPath(opt.outDir, "enemy")), ec);

    log("Converting Harry Mason -> Chris's model slot...");
    if (!ConvertOne(sh, region, "Enemy/char10.emd", opt.outDir, log, err)) return false;
    if (opt.replaceJill) {
        log("Converting Harry Mason -> Jill's model slot...");
        if (!ConvertOne(sh, region, "Enemy/char11.emd", opt.outDir, log, err)) return false;
    }

    std::string manifest = "Silent Hill x Resident Evil crossover - generated assets\n"
                           "format=1\n"
                           "silent_hill=" + std::string(sh.release()->id) + "\n"
                           "harry_replaces=" + std::string(opt.replaceJill ? "chris,jill" : "chris") + "\n"
                           "Generated from your own game files. Do not redistribute.\n";
    Bytes mb(manifest.begin(), manifest.end());
    WriteWholeFile(JoinPath(opt.outDir, "crossover.txt"), mb);
    log("Done.");
    return true;
}

} // namespace crossover
