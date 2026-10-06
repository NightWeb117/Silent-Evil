// launcher.cpp - Silent Hill x Resident Evil crossover launcher (Win32).
//
// Bring-your-own-games: the player points the launcher at their Resident Evil
// (PC) install and their Silent Hill (PS1) disc image. The launcher converts
// the Silent Hill assets into a mod overlay folder beside itself, points the
// port's config.ini at the untouched RE install + that overlay + a separate
// save folder, and starts residentevil.exe. Nothing is written into either
// game's own files.
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <cwctype>
#include <string>
#include "../lib/crossover.h"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "comdlg32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(linker, "\"/manifestdependency:type='win32' name='Microsoft.Windows.Common-Controls' " \
                        "version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

namespace {

const wchar_t* kTitle = L"Silent Hill x Resident Evil - Launcher";
const wchar_t* kGameExe = L"residentevil.exe";
const wchar_t* kModDir = L"mods\\silent-hill";
const UINT WM_APP_LOG = WM_APP + 1;
const UINT WM_APP_DONE = WM_APP + 2;

enum {
    ID_RE_EDIT = 100, ID_RE_BROWSE, ID_SH_EDIT, ID_SH_BROWSE, ID_JILL, ID_BUILD, ID_PLAY, ID_LOG, ID_OPENMOD
};

HWND g_wnd, g_reEdit, g_shEdit, g_jill, g_build, g_play, g_log, g_openMod;
HFONT g_font;
bool g_busy = false;
bool g_playAfterBuild = false;
std::wstring g_exeDir;

// ---------------------------------------------------------------- strings
std::string ToUtf8(const std::wstring& w)
{
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), &s[0], n, nullptr, nullptr);
    return s;
}

std::wstring FromUtf8(const std::string& s)
{
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &w[0], n);
    return w;
}

std::wstring GetText(HWND h)
{
    int n = GetWindowTextLengthW(h);
    std::wstring s(n + 1, L'\0');
    GetWindowTextW(h, &s[0], n + 1);
    s.resize(n);
    return s;
}

std::wstring Join(const std::wstring& a, const std::wstring& b)
{
    if (a.empty()) return b;
    return (a.back() == L'\\' || a.back() == L'/') ? a + b : a + L"\\" + b;
}

bool Exists(const std::wstring& p) { return GetFileAttributesW(p.c_str()) != INVALID_FILE_ATTRIBUTES; }

// ---------------------------------------------------------------- settings
std::wstring IniPath() { return Join(g_exeDir, L"launcher.ini"); }

std::wstring IniGet(const wchar_t* key)
{
    wchar_t buf[1024] = L"";
    GetPrivateProfileStringW(L"Launcher", key, L"", buf, 1024, IniPath().c_str());
    return buf;
}

void IniSet(const wchar_t* key, const std::wstring& v)
{
    WritePrivateProfileStringW(L"Launcher", key, v.c_str(), IniPath().c_str());
}

// ---------------------------------------------------------------- log
void Log(const std::wstring& line)
{
    int len = GetWindowTextLengthW(g_log);
    SendMessageW(g_log, EM_SETSEL, len, len);
    std::wstring s = line + L"\r\n";
    SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)s.c_str());
}

// Posted from the worker thread; the UI thread owns the edit control.
void PostLog(const std::string& utf8)
{
    PostMessageW(g_wnd, WM_APP_LOG, 0, (LPARAM)new std::wstring(FromUtf8(utf8)));
}

void SetBusy(bool busy)
{
    g_busy = busy;
    EnableWindow(g_build, !busy);
    EnableWindow(g_play, !busy);
    EnableWindow(g_reEdit, !busy);
    EnableWindow(g_shEdit, !busy);
    EnableWindow(GetDlgItem(g_wnd, ID_RE_BROWSE), !busy);
    EnableWindow(GetDlgItem(g_wnd, ID_SH_BROWSE), !busy);
    EnableWindow(g_jill, !busy);
}

// ---------------------------------------------------------------- pickers
std::wstring PickFolder(HWND owner)
{
    std::wstring result;
    IFileOpenDialog* dlg = nullptr;
    if (SUCCEEDED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dlg)))) {
        DWORD opts = 0;
        dlg->GetOptions(&opts);
        dlg->SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
        dlg->SetTitle(L"Select your Resident Evil (PC) folder");
        if (SUCCEEDED(dlg->Show(owner))) {
            IShellItem* item = nullptr;
            if (SUCCEEDED(dlg->GetResult(&item))) {
                PWSTR path = nullptr;
                if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
                    result = path;
                    CoTaskMemFree(path);
                }
                item->Release();
            }
        }
        dlg->Release();
    }
    return result;
}

std::wstring PickDiscImage(HWND owner)
{
    wchar_t file[MAX_PATH * 4] = L"";
    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner = owner;
    ofn.lpstrFilter = L"PS1 disc image (*.cue;*.bin;*.iso;*.img)\0*.cue;*.bin;*.iso;*.img\0All files\0*.*\0";
    ofn.lpstrFile = file;
    ofn.nMaxFile = (DWORD)(sizeof(file) / sizeof(file[0]));
    ofn.lpstrTitle = L"Select your Silent Hill (PS1) disc image";
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY;
    return GetOpenFileNameW(&ofn) ? std::wstring(file) : std::wstring();
}

// ---------------------------------------------------------------- build / play
struct BuildJob {
    crossover::BuildOptions opt;
};

DWORD WINAPI BuildThread(LPVOID p)
{
    BuildJob* job = (BuildJob*)p;
    std::string err;
    bool ok = crossover::BuildMod(job->opt, PostLog, err);
    if (!ok) PostLog("ERROR: " + err);
    delete job;
    PostMessageW(g_wnd, WM_APP_DONE, ok ? 1 : 0, 0);
    return 0;
}

std::wstring Stamp()
{
    // What the generated assets were built from; a change triggers a rebuild.
    return GetText(g_reEdit) + L"|" + GetText(g_shEdit) + L"|" +
           (SendMessageW(g_jill, BM_GETCHECK, 0, 0) == BST_CHECKED ? L"jill" : L"") + L"|format1";
}

bool ModIsCurrent()
{
    return Exists(Join(Join(g_exeDir, kModDir), L"enemy\\char10.emd")) && IniGet(L"BuiltFrom") == Stamp();
}

void StartBuild(bool thenPlay)
{
    std::wstring re = GetText(g_reEdit), sh = GetText(g_shEdit);
    if (re.empty() || sh.empty()) {
        MessageBoxW(g_wnd, L"Choose your Resident Evil folder and your Silent Hill disc image first.", kTitle,
                    MB_ICONINFORMATION);
        return;
    }
    IniSet(L"ResidentEvil", re);
    IniSet(L"SilentHill", sh);
    IniSet(L"ReplaceJill", SendMessageW(g_jill, BM_GETCHECK, 0, 0) == BST_CHECKED ? L"1" : L"0");
    BuildJob* job = new BuildJob;
    job->opt.reRegionDir = ToUtf8(re);
    job->opt.shImage = ToUtf8(sh);
    job->opt.outDir = ToUtf8(Join(g_exeDir, kModDir));
    job->opt.replaceJill = SendMessageW(g_jill, BM_GETCHECK, 0, 0) == BST_CHECKED;
    g_playAfterBuild = thenPlay;
    SetBusy(true);
    Log(L"--- Building Silent Hill assets ---");
    HANDLE t = CreateThread(nullptr, 0, BuildThread, job, 0, nullptr);
    if (t) CloseHandle(t);
    else { delete job; SetBusy(false); Log(L"ERROR: could not start the build thread"); }
}

// Point the port's config.ini at the user's RE tree, our overlay and our saves.
bool WriteGameConfig(std::wstring& err)
{
    std::string region = crossover::FindReRegionDir(ToUtf8(GetText(g_reEdit)));
    if (region.empty()) { err = L"The Resident Evil folder is no longer valid."; return false; }
    std::wstring wregion = FromUtf8(region);
    while (!wregion.empty() && (wregion.back() == L'\\' || wregion.back() == L'/')) wregion.pop_back();
    size_t cut = wregion.find_last_of(L"\\/");
    std::wstring base = cut == std::wstring::npos ? L"." : wregion.substr(0, cut);
    std::wstring version = cut == std::wstring::npos ? wregion : wregion.substr(cut + 1);
    for (auto& c : version) c = (wchar_t)towupper(c);
    if (version != L"USA" && version != L"JPN") version = L"USA";

    std::wstring cfg = Join(g_exeDir, L"config.ini");
    std::wstring tmpl = Join(g_exeDir, L"config.ini.template");
    if (!Exists(cfg) && Exists(tmpl)) CopyFileW(tmpl.c_str(), cfg.c_str(), TRUE);
    bool ok = WritePrivateProfileStringW(L"Assets", L"Path", base.c_str(), cfg.c_str()) &&
              WritePrivateProfileStringW(L"Assets", L"Version", version.c_str(), cfg.c_str()) &&
              WritePrivateProfileStringW(L"Assets", L"ModPath", kModDir, cfg.c_str()) &&
              WritePrivateProfileStringW(L"Save", L"Path", L"SAVE", cfg.c_str());
    if (!ok) { err = L"Could not write " + cfg; return false; }
    CreateDirectoryW(Join(g_exeDir, L"SAVE").c_str(), nullptr);
    return true;
}

void Play()
{
    if (!ModIsCurrent()) { StartBuild(true); return; }
    std::wstring err;
    if (!WriteGameConfig(err)) { MessageBoxW(g_wnd, err.c_str(), kTitle, MB_ICONERROR); return; }
    std::wstring exe = Join(g_exeDir, kGameExe);
    if (!Exists(exe)) {
        MessageBoxW(g_wnd, (L"Cannot find " + exe + L"\n\nPut the launcher next to the game executable.").c_str(),
                    kTitle, MB_ICONERROR);
        return;
    }
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi = {};
    std::wstring cmd = L"\"" + exe + L"\"";
    if (!CreateProcessW(exe.c_str(), &cmd[0], nullptr, nullptr, FALSE, 0, nullptr, g_exeDir.c_str(), &si, &pi)) {
        MessageBoxW(g_wnd, L"Could not start the game.", kTitle, MB_ICONERROR);
        return;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    Log(L"Game started.");
}

// ---------------------------------------------------------------- window
int g_dpi = 96;
int S(int v) { return MulDiv(v, g_dpi, 96); }

HWND Make(const wchar_t* cls, const wchar_t* text, DWORD style, int x, int y, int w, int h, int id, DWORD ex = 0)
{
    HWND c = CreateWindowExW(ex, cls, text, WS_CHILD | WS_VISIBLE | style, S(x), S(y), S(w), S(h), g_wnd,
                             (HMENU)(INT_PTR)id, GetModuleHandleW(nullptr), nullptr);
    SendMessageW(c, WM_SETFONT, (WPARAM)g_font, TRUE);
    return c;
}

void CreateControls()
{
    Make(L"STATIC", L"Bring your own games: this launcher reads your Resident Evil (PC) install and your Silent Hill "
                    L"(PS1) disc image, converts Harry Mason into Resident Evil, and keeps both games' files untouched.",
         0, 12, 10, 556, 34, 0);
    Make(L"STATIC", L"Resident Evil (PC) folder:", 0, 12, 52, 556, 18, 0);
    g_reEdit = Make(L"EDIT", IniGet(L"ResidentEvil").c_str(), ES_AUTOHSCROLL | WS_TABSTOP, 12, 72, 456, 24, ID_RE_EDIT,
                    WS_EX_CLIENTEDGE);
    Make(L"BUTTON", L"Browse...", BS_PUSHBUTTON | WS_TABSTOP, 476, 71, 92, 26, ID_RE_BROWSE);
    Make(L"STATIC", L"Silent Hill (PS1, NTSC-U 1.1 / NTSC-J / PAL) disc image (.cue, .bin or .iso):", 0, 12, 104, 556,
         18, 0);
    g_shEdit = Make(L"EDIT", IniGet(L"SilentHill").c_str(), ES_AUTOHSCROLL | WS_TABSTOP, 12, 124, 456, 24, ID_SH_EDIT,
                    WS_EX_CLIENTEDGE);
    Make(L"BUTTON", L"Browse...", BS_PUSHBUTTON | WS_TABSTOP, 476, 123, 92, 26, ID_SH_BROWSE);
    g_jill = Make(L"BUTTON", L"Also replace Jill with Harry (experimental)", BS_AUTOCHECKBOX | WS_TABSTOP, 12, 156, 400,
                  22, ID_JILL);
    if (IniGet(L"ReplaceJill") == L"1") SendMessageW(g_jill, BM_SETCHECK, BST_CHECKED, 0);
    g_log = Make(L"EDIT", L"", ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | WS_VSCROLL, 12, 186, 556, 150, ID_LOG,
                 WS_EX_CLIENTEDGE);
    g_openMod = Make(L"BUTTON", L"Open mod folder", BS_PUSHBUTTON | WS_TABSTOP, 12, 346, 130, 32, ID_OPENMOD);
    g_build = Make(L"BUTTON", L"Rebuild assets", BS_PUSHBUTTON | WS_TABSTOP, 318, 346, 120, 32, ID_BUILD);
    g_play = Make(L"BUTTON", L"Play", BS_DEFPUSHBUTTON | WS_TABSTOP, 448, 346, 120, 32, ID_PLAY);
    Log(ModIsCurrent() ? L"Assets are built. Press Play." : L"Choose both games, then press Play to build and start.");
}

LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE:
        g_wnd = h;
        CreateControls();
        return 0;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_RE_BROWSE: {
            std::wstring p = PickFolder(h);
            if (!p.empty()) {
                SetWindowTextW(g_reEdit, p.c_str());
                if (crossover::FindReRegionDir(ToUtf8(p)).empty())
                    Log(L"Warning: no Enemy\\char10.emd found under that folder.");
            }
            return 0;
        }
        case ID_SH_BROWSE: {
            std::wstring p = PickDiscImage(h);
            if (!p.empty()) SetWindowTextW(g_shEdit, p.c_str());
            return 0;
        }
        case ID_BUILD: StartBuild(false); return 0;
        case ID_PLAY: Play(); return 0;
        case ID_OPENMOD: {
            std::wstring dir = Join(g_exeDir, kModDir);
            CreateDirectoryW(Join(g_exeDir, L"mods").c_str(), nullptr);
            CreateDirectoryW(dir.c_str(), nullptr);
            ShellExecuteW(h, L"open", dir.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
            return 0;
        }
        }
        break;
    case WM_APP_LOG: {
        std::wstring* s = (std::wstring*)lp;
        Log(*s);
        delete s;
        return 0;
    }
    case WM_APP_DONE:
        SetBusy(false);
        if (wp) {
            IniSet(L"BuiltFrom", Stamp());
            if (g_playAfterBuild) Play();
        } else {
            MessageBoxW(h, L"Building the Silent Hill assets failed - see the log for why.", kTitle, MB_ICONERROR);
        }
        return 0;
    case WM_CLOSE:
        if (g_busy) return 0;   // let the build finish
        break;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

} // namespace

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int show)
{
    SetProcessDPIAware();
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    INITCOMMONCONTROLSEX icc = {sizeof(icc), ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&icc);

    wchar_t self[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, self, (DWORD)(sizeof(self) / sizeof(self[0])));
    g_exeDir = self;
    g_exeDir = g_exeDir.substr(0, g_exeDir.find_last_of(L"\\/"));

    HDC dc = GetDC(nullptr);
    g_dpi = GetDeviceCaps(dc, LOGPIXELSX);
    ReleaseDC(nullptr, dc);
    NONCLIENTMETRICSW ncm = {sizeof(ncm)};
    SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(ncm), &ncm, 0);
    g_font = CreateFontIndirectW(&ncm.lfMessageFont);

    WNDCLASSW wc = {};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.hIcon = LoadIcon(nullptr, IDI_APPLICATION);
    wc.lpszClassName = L"ShReCrossoverLauncher";
    RegisterClassW(&wc);

    RECT r = {0, 0, MulDiv(580, g_dpi, 96), MulDiv(390, g_dpi, 96)};
    DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    AdjustWindowRect(&r, style, FALSE);
    HWND w = CreateWindowW(wc.lpszClassName, kTitle, style, CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left,
                           r.bottom - r.top, nullptr, nullptr, inst, nullptr);
    ShowWindow(w, show);

    MSG m;
    while (GetMessageW(&m, nullptr, 0, 0)) {
        if (!IsDialogMessageW(w, &m)) {
            TranslateMessage(&m);
            DispatchMessageW(&m);
        }
    }
    CoUninitialize();
    return 0;
}
