// crossover.h - Silent Hill (PS1) -> Resident Evil (PC) asset pipeline.
//
// Nothing copyrighted ships with this project. Everything here reads the
// player's own copies of both games and generates a small "mod overlay" tree
// (laid out like the RE region tree) that the port loads ahead of the real
// data via config.ini [Assets] ModPath. The RE install itself is never written.
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <functional>

namespace crossover {

using Bytes = std::vector<uint8_t>;

// ---------------------------------------------------------------- disc image
// Reads a PS1 disc image: raw .bin (2352-byte MODE2 sectors), a .cue pointing
// at one, or a cooked 2048-byte .iso.
class Disc {
public:
    bool open(const std::string& path, std::string& err);
    bool readSectors(uint32_t lba, uint32_t count, Bytes& out) const;   // user data, 2048/sector
    // ISO9660 lookup in the root directory, case-insensitive, ";1" optional.
    bool readFile(const std::string& name, Bytes& out) const;
private:
    std::string m_path;
    uint32_t m_sectorSize = 2352;
    uint32_t m_dataOffset = 24;
    uint64_t m_size = 0;
};

// ------------------------------------------------------------ silent hill fs
struct ShRelease {
    const char* id;
    const char* exeName;
    uint32_t crc;          // crc32 of the first 4096 bytes of the executable
    uint32_t tocOffset;
    uint32_t fileCount;
    bool pal;
};

class SilentHillDisc {
public:
    bool open(const std::string& imagePath, std::string& err);
    const ShRelease* release() const { return m_release; }
    // "CHARA/HERO.ILM" style paths, as the decomp's extractor names them.
    bool readFile(const std::string& path, Bytes& out, std::string& err) const;
    std::vector<std::string> listFiles() const;
private:
    struct Entry { std::string path; uint32_t lba; uint32_t size; std::string type; };
    Disc m_disc;
    const ShRelease* m_release = nullptr;
    std::vector<Entry> m_entries;
};

// ------------------------------------------------------------ conversions
// Harry Mason (CHARA/HERO.ILM + HERO.TIM + ANIM/HB_BASE.ANM) rebuilt as a
// RE player model on top of `reCharEmd` (the original Char10.emd / CHAR11.EMD):
// its animations and extra objects are kept, its 15 body parts, joint offsets
// and texture are replaced.
bool ConvertHarry(const SilentHillDisc& sh, const Bytes& reCharEmd, Bytes& out, std::string& err);

// ------------------------------------------------------------ whole mod build
struct BuildOptions {
    std::string reRegionDir;    // e.g. ...\english\USA  (holds Enemy\, Players\, ...)
    std::string shImage;        // Silent Hill .bin / .cue / .iso
    std::string outDir;         // mod overlay root to (re)create
    bool replaceJill = false;   // also swap CHAR11 (Jill) for Harry
};
using Log = std::function<void(const std::string&)>;
bool BuildMod(const BuildOptions& opt, const Log& log, std::string& err);

// Locates the region tree (folder containing Enemy/char10.emd) under a user-
// picked RE folder: accepts the region folder itself, its parent, or a Steam /
// GOG install root ("english/USA", "USA", "usa"). Returns "" when not found.
std::string FindReRegionDir(const std::string& picked);

// helpers shared by the tools
bool ReadWholeFile(const std::string& path, Bytes& out);
bool WriteWholeFile(const std::string& path, const Bytes& data);
bool MakeDirs(const std::string& path);
std::string JoinPath(const std::string& a, const std::string& b);
uint32_t Crc32(const uint8_t* p, size_t n);

} // namespace crossover
