/* Patch: GM command channel
 * Config: [client] gm_channel = 1 (default: enabled)
 *
 * Lets the launcher run any GM console command in this client as if it had
 * been typed in chat with the '%' prefix. A message-only window
 * "DarkBloodGmChannel" titled "DarkBloodGm:<pid>" is created on the thread
 * that runs SteamAPI_Init (the game thread). The launcher sends WM_COPYDATA
 * (dwData = GM_CHANNEL_MAGIC, UTF-16 command, '%' optional); the window
 * procedure runs on the game thread and repeats the chat path at 0x00547B38:
 *
 *   0x004065F0() -> 0x00450A90 (GM auth, al & 1)
 *   0x004063F0() -> 0x006DBFD0(0x37) = Page_Cheat
 *   Page_Cheat->0x004F2D90(std::wstringstream& of "%cmd args")   (command map +0xC0)
 *
 * The chat path wraps the text in basic_stringstream<wchar_t>(str, in|out)
 * (0x00547B60) and destroys it with ??_D (0x00547B95). The string and stream
 * are built and destroyed with the game's own MSVCP80 functions, whose
 * addresses are read from live call sites (the packer rewrites import calls to
 * `nop; call rel32`): wstring(const wchar_t*) at 0x004DF2F7, ~wstring at
 * 0x00547B29, the stream constructor at 0x00547B60 and ??_D at 0x00547B95.
 * All four targets must lie in an msvcp module.
 *
 * Reply (SendMessage result): 1 executed, 2 GM auth off, 3 no Page_Cheat
 * (not in game yet), 4 hook not resolved, 5 exception, 0 bad message.
 */
#include <string.h>
#include "patches.h"

#define GM_CHANNEL_MAGIC 0x444247u /* 'DBG' */
#define GM_CMD_MAX 512

typedef void* (__cdecl *Getter_t)(void);
typedef unsigned char (__fastcall *GmAuth_t)(void* self, void* edx);
typedef void* (__fastcall *GetPage_t)(void* self, void* edx, int id);
typedef void (__fastcall *Exec_t)(void* self, void* edx, void* stream);
typedef void* (__fastcall *WstrCtor_t)(void* self, void* edx, const wchar_t* s);
typedef void (__fastcall *WstrDtor_t)(void* self, void* edx);
/* basic_stringstream(const wstring&, openmode) on a class with virtual bases:
 * the trailing hidden int (1) tells the constructor to build them. */
typedef void* (__fastcall *SsCtor_t)(void* self, void* edx, const void* str, int mode, int mostDerived);
typedef void (__fastcall *SsDtor_t)(void* self, void* edx); /* ??_D vbase destructor */

static WstrCtor_t g_wstrCtor = NULL;
static WstrDtor_t g_wstrDtor = NULL;
static SsCtor_t   g_ssCtor   = NULL;
static SsDtor_t   g_ssDtor   = NULL;

static void* CallTarget(DWORD site) {
    BYTE op = 0;
    LONG rel = 0;
    if (!SafeRead(site, &op, 1) || op != 0xE8) return NULL;
    if (!SafeRead(site + 1, &rel, 4)) return NULL;
    return (void*)(site + 5 + rel);
}

static int InMsvcp(void* addr) {
    HMODULE mod = NULL;
    char name[MAX_PATH];
    if (!addr || !GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                     GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                     (LPCSTR)addr, &mod)) return 0;
    if (!GetModuleFileNameA(mod, name, sizeof(name))) return 0;
    CharLowerA(name);
    return strstr(name, "msvcp") != NULL;
}

static int ResolveStringFunctions(void) {
    void* ctor;
    void* dtor;
    void* ssCtor;
    void* ssDtor;
    if (g_wstrCtor && g_wstrDtor && g_ssCtor && g_ssDtor) return 1;
    ctor = CallTarget(0x004DF2F7);   /* wstring(const wchar_t*) */
    dtor = CallTarget(0x00547B29);   /* ~wstring() */
    ssCtor = CallTarget(0x00547B60); /* wstringstream(const wstring&, int) (chat path) */
    ssDtor = CallTarget(0x00547B95); /* wstringstream ??_D (chat path) */
    if (!InMsvcp(ctor) || !InMsvcp(dtor) || !InMsvcp(ssCtor) || !InMsvcp(ssDtor)) {
        RawLogFmt("[GM] channel: msvcp functions not resolved (%08lX %08lX %08lX %08lX)",
                  (DWORD)ctor, (DWORD)dtor, (DWORD)ssCtor, (DWORD)ssDtor);
        return 0;
    }
    g_wstrCtor = (WstrCtor_t)ctor;
    g_wstrDtor = (WstrDtor_t)dtor;
    g_ssCtor = (SsCtor_t)ssCtor;
    g_ssDtor = (SsDtor_t)ssDtor;
    return 1;
}

static int RunCommand(const wchar_t* cmd) {
    /* MSVCP80 std::wstring (28 bytes) and std::wstringstream, padded; both are
     * constructed in place by the game's own constructors. */
    __declspec(align(8)) BYTE wstr[64];
    __declspec(align(8)) BYTE stream[1024];
    void* mgr;
    void* page;
    int result = 5;
    if (!ResolveStringFunctions()) return 4;
    __try {
        mgr = ((Getter_t)0x004065F0)();
        if (!mgr || !(((GmAuth_t)0x00450A90)(mgr, NULL) & 1)) return 2;
        page = ((GetPage_t)0x006DBFD0)(((Getter_t)0x004063F0)(), NULL, 0x37);
        if (!page) return 3;
        g_wstrCtor(wstr, NULL, cmd);
        g_ssCtor(stream, NULL, wstr, 3 /* in | out */, 1);
        ((Exec_t)0x004F2D90)(page, NULL, stream);
        g_ssDtor(stream, NULL);
        g_wstrDtor(wstr, NULL);
        result = 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        RawLogFmt("[GM] channel: exception 0x%08X running a command", GetExceptionCode());
        result = 5;
    }
    return result;
}

static LRESULT CALLBACK GmChannelWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_COPYDATA) {
        const COPYDATASTRUCT* cds = (const COPYDATASTRUCT*)lp;
        wchar_t cmd[GM_CMD_MAX + 2];
        size_t chars;
        int rc;
        char narrow[GM_CMD_MAX * 3 + 8];
        if (!cds || cds->dwData != GM_CHANNEL_MAGIC || !cds->lpData) return 0;
        chars = cds->cbData / sizeof(wchar_t);
        if (chars == 0 || chars > GM_CMD_MAX) return 0;
        memcpy(cmd, cds->lpData, chars * sizeof(wchar_t));
        cmd[chars] = 0;
        if (cmd[chars - 1] == 0) chars--;
        while (chars && cmd[0] == L'%') { memmove(cmd, cmd + 1, chars * sizeof(wchar_t)); chars--; }
        if (!chars) return 0;
        /* The chat path hands the executor the whole chat line, '%' included. */
        memmove(cmd + 1, cmd, (chars + 1) * sizeof(wchar_t));
        cmd[0] = L'%';
        rc = RunCommand(cmd);
        WideCharToMultiByte(CP_UTF8, 0, cmd, -1, narrow, sizeof(narrow), NULL, NULL);
        RawLogFmt("[GM] channel: %s -> %d", narrow, rc);
        return rc;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

void Patch_GmChannel_Install(void) {
    WNDCLASSEXW wc;
    wchar_t title[64];
    HWND hwnd;
    if (!ConfigClientPatch("gm_channel", 1)) {
        RawLog("[PATCH] gm_channel disabled");
        return;
    }
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = GmChannelWndProc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"DarkBloodGmChannel";
    if (!RegisterClassExW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
        RawLogFmt("[GM] channel: RegisterClassEx failed (%lu)", GetLastError());
        return;
    }
    wsprintfW(title, L"DarkBloodGm:%lu", GetCurrentProcessId());
    hwnd = CreateWindowExW(0, wc.lpszClassName, title, 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, wc.hInstance, NULL);
    if (!hwnd) {
        RawLogFmt("[GM] channel: CreateWindowEx failed (%lu)", GetLastError());
        return;
    }
    RawLogFmt("[GM] channel ready: %ls on thread %lu", title, GetCurrentThreadId());
}
