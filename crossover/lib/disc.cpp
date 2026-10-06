// disc.cpp - PS1 disc image reading + the Silent Hill SILENT. file table.
#include "crossover.h"
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

namespace crossover {

// --------------------------------------------------------------- utilities
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

bool ReadWholeFile(const std::string& path, Bytes& out)
{
    std::ifstream f(U8(path), std::ios::binary);
    if (!f) return false;
    f.seekg(0, std::ios::end);
    std::streamoff n = f.tellg();
    if (n < 0) return false;
    f.seekg(0);
    out.resize((size_t)n);
    if (n) f.read((char*)out.data(), n);
    return (bool)f;
}

bool WriteWholeFile(const std::string& path, const Bytes& data)
{
    std::ofstream f(U8(path), std::ios::binary | std::ios::trunc);
    if (!f) return false;
    f.write((const char*)data.data(), (std::streamsize)data.size());
    return (bool)f;
}

bool MakeDirs(const std::string& path)
{
    std::error_code ec;
    fs::create_directories(U8(path), ec);
    return fs::is_directory(U8(path), ec);
}

std::string JoinPath(const std::string& a, const std::string& b)
{
    if (a.empty()) return b;
    char last = a.back();
    if (last == '/' || last == '\\') return a + b;
#ifdef _WIN32
    return a + "\\" + b;
#else
    return a + "/" + b;
#endif
}

uint32_t Crc32(const uint8_t* p, size_t n)
{
    static uint32_t table[256];
    static bool init = false;
    if (!init) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        init = true;
    }
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) c = table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

static std::string Lower(std::string s)
{
    for (auto& c : s) c = (char)std::tolower((unsigned char)c);
    return s;
}

static std::string Trim(const std::string& s)
{
    size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

// --------------------------------------------------------------- Disc
bool Disc::open(const std::string& path, std::string& err)
{
    std::string img = path;
    std::error_code ec;
    if (Lower(U8(path).extension().string()) == ".cue") {
        std::ifstream cue(U8(path));
        if (!cue) { err = "Cannot open " + path; return false; }
        std::string line, file;
        while (std::getline(cue, line)) {
            std::string t = Trim(line);
            if (Lower(t.substr(0, 5)) == "file ") {
                size_t q1 = t.find('"'), q2 = t.rfind('"');
                file = (q1 != std::string::npos && q2 > q1) ? t.substr(q1 + 1, q2 - q1 - 1)
                                                            : Trim(t.substr(5, t.rfind(' ') - 5));
                break;
            }
        }
        if (file.empty()) { err = "The .cue sheet names no data file"; return false; }
        fs::path p = U8(path).parent_path() / U8(file);
        img = FromPath(p);
    }
    m_path = img;
    m_size = fs::file_size(U8(img), ec);
    if (ec || m_size < 17 * 2048) { err = "Cannot read disc image " + img; return false; }

    std::ifstream f(U8(img), std::ios::binary);
    uint8_t head[16];
    f.read((char*)head, 16);
    static const uint8_t sync[12] = {0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0};
    if (memcmp(head, sync, 12) == 0) {
        m_sectorSize = 2352;
        // mode byte of the PVD sector decides the user-data offset
        uint8_t mode = 2;
        f.seekg(16 * 2352 + 15);
        f.read((char*)&mode, 1);
        m_dataOffset = (mode == 1) ? 16 : 24;
    } else {
        m_sectorSize = 2048;
        m_dataOffset = 0;
    }
    Bytes pvd;
    if (!readSectors(16, 1, pvd) || memcmp(&pvd[1], "CD001", 5) != 0) {
        err = "Not a PlayStation disc image (no ISO9660 volume found): " + img;
        return false;
    }
    return true;
}

bool Disc::readSectors(uint32_t lba, uint32_t count, Bytes& out) const
{
    std::ifstream f(U8(m_path), std::ios::binary);
    if (!f) return false;
    out.resize((size_t)count * 2048);
    for (uint32_t i = 0; i < count; i++) {
        uint64_t off = (uint64_t)(lba + i) * m_sectorSize + m_dataOffset;
        if (off + 2048 > m_size) return false;
        f.seekg((std::streamoff)off);
        f.read((char*)&out[(size_t)i * 2048], 2048);
        if (!f) return false;
    }
    return true;
}

bool Disc::readFile(const std::string& name, Bytes& out) const
{
    Bytes pvd;
    if (!readSectors(16, 1, pvd)) return false;
    const uint8_t* root = &pvd[156];
    uint32_t lba, size;
    memcpy(&lba, root + 2, 4);
    memcpy(&size, root + 10, 4);
    Bytes dir;
    if (!readSectors(lba, (size + 2047) / 2048, dir)) return false;
    std::string want = Lower(name);
    for (size_t sec = 0; sec < dir.size(); sec += 2048) {
        size_t p = sec;
        while (p < sec + 2048 && dir[p] != 0) {
            uint8_t len = dir[p];
            uint8_t nlen = dir[p + 32];
            std::string n((const char*)&dir[p + 33], nlen);
            n = Lower(n);
            size_t semi = n.find(';');
            if (semi != std::string::npos) n = n.substr(0, semi);
            if (n == want || n + "." == want || n == want + ".") {
                uint32_t flba, fsize;
                memcpy(&flba, &dir[p + 2], 4);
                memcpy(&fsize, &dir[p + 10], 4);
                if (!readSectors(flba, (fsize + 2047) / 2048, out)) return false;
                out.resize(fsize);
                return true;
            }
            p += len;
        }
    }
    return false;
}

// --------------------------------------------------------------- Silent Hill
// From the decomp's tools/silentassets/extract.py (final releases only - the
// demos and prototypes use other table layouts and other model data).
static const char* kDirsNtsc[] = {"1ST", "ANIM", "BG", "CHARA", "ITEM", "MISC", "SND", "TEST",
                                  "TIM", "VIN", "XA", "", "", "", "", ""};
static const char* kDirsPal[] = {"1ST", "ANIM", "BG", "CHARA", "ITEM", "MISC", "SND", "TEST",
                                 "TIM", "VIN", "VIN2", "VIN3", "VIN4", "VIN5", "XA", ""};
static const char* kTypes[] = {"TIM", "VAB", "BIN", "DMS", "ANM", "PLM", "IPD", "ILM",
                               "TMD", "DAT", "KDT", "CMP", "TXT", "UU1", "UU2", ""};

static const ShRelease kReleases[] = {
    {"NTSC-U 1.1 (SLUS-00707)", "SLUS_007.07", 0xCF9CD8E5, 0xB91C, 2074, false},
    {"NTSC-J Rev 0 (SLPM-86192)", "SLPM_861.92", 0x1532C55C, 0xB91C, 2074, false},
    {"NTSC-J Rev 1/2 (SLPM-86192)", "SLPM_861.92", 0xEB733CAA, 0xB91C, 2074, false},
    {"PAL (SLES-01514)", "SLES_015.14", 0x337E4A60, 0xB8FC, 2310, true},
};

bool SilentHillDisc::open(const std::string& imagePath, std::string& err)
{
    if (!m_disc.open(imagePath, err)) return false;
    Bytes cnf;
    std::string bootName;
    if (m_disc.readFile("SYSTEM.CNF", cnf)) {
        std::string s(cnf.begin(), cnf.end());
        size_t p = s.find("cdrom:");
        if (p != std::string::npos) {
            p += 6;
            while (p < s.size() && (s[p] == '\\' || s[p] == '/')) p++;
            size_t e = s.find_first_of(";\r\n", p);
            bootName = s.substr(p, e - p);
        }
    }
    Bytes exe;
    if (bootName.empty() || !m_disc.readFile(bootName, exe) || exe.size() < 4096) {
        err = "This disc image has no PlayStation boot executable - is it Silent Hill?";
        return false;
    }
    uint32_t crc = Crc32(exe.data(), 4096);
    for (const auto& r : kReleases) {
        if (r.crc == crc) m_release = &r;
    }
    if (!m_release) {
        char buf[160];
        snprintf(buf, sizeof(buf),
                 "Unsupported disc (%s, crc %08X). Supported: Silent Hill NTSC-U 1.1, NTSC-J, PAL.",
                 bootName.c_str(), crc);
        err = buf;
        return false;
    }
    if (m_release->tocOffset + m_release->fileCount * 12 > exe.size()) {
        err = "Silent Hill executable is truncated";
        return false;
    }
    const char** dirs = m_release->pal ? kDirsPal : kDirsNtsc;
    m_entries.clear();
    for (uint32_t i = 0; i < m_release->fileCount; i++) {
        uint32_t meta, f1, f2;
        memcpy(&meta, &exe[m_release->tocOffset + i * 12], 4);
        memcpy(&f1, &exe[m_release->tocOffset + i * 12 + 4], 4);
        memcpy(&f2, &exe[m_release->tocOffset + i * 12 + 8], 4);
        std::string name;
        for (int sh = 4; sh < 28; sh += 6) name += (char)(32 + ((f1 >> sh) & 63));
        for (int sh = 0; sh < 24; sh += 6) name += (char)(32 + ((f2 >> sh) & 63));
        name = Trim(name);
        Entry e;
        e.type = kTypes[(f2 >> 24) & 15];
        e.path = std::string(dirs[f1 & 15]) + "/" + name + (e.type.empty() ? "" : "." + e.type);
        e.lba = meta & 0x7FFFF;
        e.size = (meta >> 19) * 256;
        m_entries.push_back(e);
    }
    return true;
}

bool SilentHillDisc::readFile(const std::string& path, Bytes& out, std::string& err) const
{
    std::string want = Lower(path);
    for (const auto& e : m_entries) {
        if (Lower(e.path) == want) {
            if (e.size == 0) break;
            if (!m_disc.readSectors(e.lba, (e.size + 2047) / 2048, out)) {
                err = "Read error in the Silent Hill disc image (" + path + ")";
                return false;
            }
            out.resize(e.size);
            return true;
        }
    }
    err = "Silent Hill file not found on disc: " + path;
    return false;
}

std::vector<std::string> SilentHillDisc::listFiles() const
{
    std::vector<std::string> v;
    for (const auto& e : m_entries) v.push_back(e.path);
    return v;
}

} // namespace crossover
