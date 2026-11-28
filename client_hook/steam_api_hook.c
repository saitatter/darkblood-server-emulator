/* Dark Blood offline Steam API shim & modular patch loader.
 *
 * Each runtime hook / byte patch lives in its own file under patches/*.c and
 * is enabled or disabled via darkblood_options.ini next to DarkBlood.exe
 * (edited by tools/launcher/launcher.py).
 */
#include "common.h"
#include "patches/patches.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")

/* ---- Vectored Exception Handler --------------------------------------- */

static LONG WINAPI VectoredHandler(PEXCEPTION_POINTERS pExceptionInfo) {
    DWORD code = pExceptionInfo->ExceptionRecord->ExceptionCode;
    BYTE* addr = (BYTE*)pExceptionInfo->ExceptionRecord->ExceptionAddress;

    if (Patch_DebugTools_HandleException(pExceptionInfo))
        return EXCEPTION_CONTINUE_EXECUTION;

    if (Patch_DiagnosticHooks_HandleException(pExceptionInfo))
        return EXCEPTION_CONTINUE_EXECUTION;

    if (Patch_AutoReconnect_HandleException(pExceptionInfo))
        return EXCEPTION_CONTINUE_EXECUTION;

    if ((code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_ILLEGAL_INSTRUCTION) && !g_inSafeRead) {
        CONTEXT* c = pExceptionInfo->ContextRecord;
        DWORD* stack = (DWORD*)c->Esp;
        HANDLE dump;
        int i;
        RawLogFmt("[EXCEPTION] code=%X eip=%p eax=%p ecx=%p edx=%p esp=%p ebp=%p",
                  code, c->Eip, c->Eax, c->Ecx, c->Edx, c->Esp, c->Ebp);
        for (i = 0; i < 32; i++) RawLogFmt("stack+%X: %p", i * 4, stack[i]);
        dump = CreateFileA("crash_image.bin", GENERIC_WRITE, FILE_SHARE_READ,
                           NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (dump != INVALID_HANDLE_VALUE) {
            BYTE* image = (BYTE*)GetModuleHandleA(NULL);
            DWORD size = ((IMAGE_NT_HEADERS*)(image + ((IMAGE_DOS_HEADER*)image)->e_lfanew))->OptionalHeader.SizeOfImage;
            BYTE zeros[4096] = {0};
            DWORD written, off;
            MEMORY_BASIC_INFORMATION mbi;
            for (off = 0; off < size; off += 4096) {
                BYTE* src;
                VirtualQuery(image + off, &mbi, sizeof(mbi));
                src = (mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
                      ? (image + off) : zeros;
                WriteFile(dump, src, min(4096, size - off), &written, NULL);
            }
            CloseHandle(dump);
        }
    }

    if (code == 0xC0000096) {
        BYTE op = *addr;
        if (op == 0xFA || op == 0xFB) {
            pExceptionInfo->ContextRecord->Eip += 1;
            return EXCEPTION_CONTINUE_EXECUTION;
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

/* ---- Modular patch installation (runs after unpacking in SteamAPI_Init) - */

static volatile LONG g_hooksInstalled = 0;

static void InstallAllPatches(void) {
    if (InterlockedCompareExchange(&g_hooksInstalled, 1, 0) != 0) return;

    RawLog("[INIT] Loading patches from " OPTIONS_FILE);

    /* Core network redirect (always installed; reads [network] host/port/relay_port) */
    Patch_NetworkRedirect_Install();

    /* Improvements & QoL */
    Patch_PeerUpdateInterval_Install();
    Patch_CharSlots_Install();
    Patch_AutoReconnect_Install();
    Patch_BorderlessFullscreen_Install();

    /* Hacks & Gameplay */
    Patch_SkipLogos_Install();
    Patch_SkipTutorialAlways_Install();
    Patch_GmChannel_Install();

    /* Diagnostics & Dev tools */
    Patch_DiagnosticHooks_Install();
    Patch_DebugTools_Install();

    RawLog("[INIT] All configured patches processed");
}

/* ---- Steam API offline mocks ------------------------------------------ */

__declspec(dllexport) int __cdecl SteamAPI_Init(void) {
    InstallAllPatches();
    Patch_DebugTools_StartSampler();
    RawLog("[STEAM] SteamAPI_Init -> OK");
    return 1;
}

__declspec(dllexport) int __cdecl SteamAPI_InitSafe(void) { return SteamAPI_Init(); }

__declspec(dllexport) int __cdecl SteamAPI_RestartAppIfNecessary(unsigned int unOwnAppID) {
    RawLogFmt("[STEAM] SteamAPI_RestartAppIfNecessary(%u) -> Bypass (0)", unOwnAppID);
    return 0;
}

__declspec(dllexport) int  __cdecl SteamAPI_IsSteamRunning(void) { return 1; }
__declspec(dllexport) void __cdecl SteamAPI_Shutdown(void) {}
__declspec(dllexport) void __cdecl SteamAPI_RunCallbacks(void) {}
__declspec(dllexport) void __cdecl Steam_RunCallbacks(void) {}

/* Local account: DARKBLOOD_ACCOUNT env var (set by multibox/launcher) takes
 * priority, then [launcher] account in darkblood_options.ini, else "OfflinePlayer". */
static char g_account[64];

static const char* Account(void) {
    if (!g_account[0]) {
        DWORD n = GetEnvironmentVariableA("DARKBLOOD_ACCOUNT", g_account, sizeof(g_account));
        if (n == 0 || n >= sizeof(g_account)) {
            ConfigStr("launcher", "account", "OfflinePlayer", g_account, sizeof(g_account));
            if (!g_account[0]) lstrcpyA(g_account, "OfflinePlayer");
        }
    }
    return g_account;
}

static unsigned int AccountId(void) {
    /* FNV-1a; "OfflinePlayer" keeps the old account id 1 */
    const char* p = Account();
    unsigned int h = 2166136261u;
    if (!lstrcmpA(p, "OfflinePlayer")) return 1;
    while (*p) { h ^= (unsigned char)*p++; h *= 16777619u; }
    return h ? h : 2;
}

static int __fastcall UserHandle(void* self, void* unused) { (void)self; (void)unused; return 1; }
static int __fastcall UserLoggedOn(void* self, void* unused) { (void)self; (void)unused; return 1; }
static void* __fastcall UserSteamID(void* self, void* unused, unsigned __int64* out) {
    (void)self; (void)unused;
    *out = 0x0110000100000000ULL | AccountId();
    return out;
}
static const char* __fastcall PersonaName(void* self, void* unused) {
    (void)self; (void)unused;
    return Account();
}

/* Slot 13 (+0x34) GetAuthSessionTicket(void* ticket, int cbMax, uint32* pcb) */
static unsigned int __fastcall UserAuthTicket(void* self, void* unused, char* ticket, int cbMax, unsigned int* pcb) {
    const char* name = Account();
    int len = 0;
    (void)self; (void)unused;
    if (ticket && cbMax > 6) {
        lstrcpynA(ticket, "DBACC:", cbMax);
        len = 6;
        while (name[len - 6] && len < cbMax - 1) { ticket[len] = name[len - 6]; len++; }
        ticket[len++] = ';';
    }
    if (pcb) *pcb = (unsigned int)len;
    RawLogFmt("[STEAM] GetAuthSessionTicket account=%s (%d bytes)", name, len);
    return 1;
}

static void __fastcall UserSlot16(void* self, void* unused, unsigned int value) {
    (void)self; (void)unused;
    RawLogFmt("[STEAM] SteamUser slot 16 (%u), offline no-op", value);
}

static void* user_vtable[] = {
    UserHandle, UserLoggedOn, UserSteamID,
    NULL, NULL, NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL, UserAuthTicket, NULL, NULL,
    UserSlot16
};

/* Offline ISteamUserStats (STEAMUSERSTATS_INTERFACE_VERSION011 slot order) */
static unsigned int stats_seen = 0;

static void StatsLog(int slot) {
    if (slot < 32 && !(stats_seen & (1u << slot))) {
        stats_seen |= 1u << slot;
        RawLogFmt("[STEAM] SteamUserStats slot %d (+0x%X), offline stub", slot, slot * 4);
    }
}

#define STATS0(n) static unsigned __int64 __fastcall Stats##n(void* s, void* e) \
    { (void)s; (void)e; StatsLog(n); return 0; }
#define STATS(n, ...) static unsigned __int64 __fastcall Stats##n(void* s, void* e, __VA_ARGS__) \
    { (void)s; (void)e; StatsLog(n); return 0; }
#define STATSS(n, ...) static const char* __fastcall Stats##n(void* s, void* e, __VA_ARGS__) \
    { (void)s; (void)e; StatsLog(n); return ""; }

STATS0(0)                                    /* RequestCurrentStats() */
STATS(1, int a, int b)                       /* GetStat(name, float*) */
STATS(2, int a, int b)                       /* GetStat(name, int32*) */
STATS(3, int a, int b)                       /* SetStat(name, float) */
STATS(4, int a, int b)                       /* SetStat(name, int32) */
STATS(5, int a, int b, int c, int d)         /* UpdateAvgRateStat(name, float, double) */
STATS(6, int a, int b)                       /* GetAchievement(name, bool*) */
STATS(7, int a)                              /* SetAchievement(name) */
STATS(8, int a)                              /* ClearAchievement(name) */
STATS(9, int a, int b, int c)                /* GetAchievementAndUnlockTime */
STATS0(10)                                   /* StoreStats() */
STATS(11, int a)                             /* GetAchievementIcon(name) */
STATSS(12, int a, int b)                     /* GetAchievementDisplayAttribute */
STATS(13, int a, int b, int c)               /* IndicateAchievementProgress */
STATS0(14)                                   /* GetNumAchievements() */
STATSS(15, int a)                            /* GetAchievementName(index) */
STATS(16, int a, int b)                      /* RequestUserStats(CSteamID) */
STATS(17, int a, int b, int c, int d)        /* GetUserStat(id, name, float*) */
STATS(18, int a, int b, int c, int d)        /* GetUserStat(id, name, int32*) */
STATS(19, int a, int b, int c, int d)        /* GetUserAchievement */
STATS(20, int a, int b, int c, int d, int f) /* GetUserAchievementAndUnlockTime */
STATS(21, int a)                             /* ResetAllStats(bool) */
STATS(22, int a, int b, int c)               /* FindOrCreateLeaderboard */
STATS(23, int a)                             /* FindLeaderboard(name) */

static void* stats_vtable[] = {
    Stats0, Stats1, Stats2, Stats3, Stats4, Stats5, Stats6, Stats7, Stats8,
    Stats9, Stats10, Stats11, Stats12, Stats13, Stats14, Stats15, Stats16,
    Stats17, Stats18, Stats19, Stats20, Stats21, Stats22, Stats23
};

static void** stats_interface   = stats_vtable;
static void*  friends_vtable[]  = { PersonaName };
static void** user_interface    = user_vtable;
static void** friends_interface = friends_vtable;

__declspec(dllexport) void* __cdecl SteamApps(void)      { RawLog("SteamApps"); return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUser(void)      { RawLog("SteamUser"); return &user_interface; }
__declspec(dllexport) void* __cdecl SteamFriends(void)   { RawLog("SteamFriends"); return &friends_interface; }
__declspec(dllexport) void* __cdecl SteamUtils(void)     { return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUserStats(void) { return &stats_interface; }
__declspec(dllexport) void* __cdecl SteamNetworking(void){ return (void*)1; }
__declspec(dllexport) void* __cdecl SteamClient(void)    { return (void*)1; }

/* Keep the complete export surface: the packer resolves imports dynamically
 * and exits before the game entry point if even one export is absent. */
__declspec(dllexport) int __cdecl GetHSteamPipe(void) { return 1; }
__declspec(dllexport) int __cdecl GetHSteamUser(void) { return 1; }
__declspec(dllexport) int __cdecl SteamAPI_GetHSteamPipe(void) { return 1; }
__declspec(dllexport) int __cdecl SteamAPI_GetHSteamUser(void) { return 1; }
__declspec(dllexport) const char* __cdecl SteamAPI_GetSteamInstallPath(void) { return "."; }
__declspec(dllexport) void __cdecl SteamAPI_RegisterCallResult(void* p, unsigned __int64 id) { (void)p; (void)id; RawLog("RegisterCallResult"); }
__declspec(dllexport) void __cdecl SteamAPI_RegisterCallback(void* p, int id) { (void)p; RawLogFmt("RegisterCallback %d", id); }
__declspec(dllexport) void __cdecl SteamAPI_UnregisterCallResult(void* p, unsigned __int64 id) { (void)p; (void)id; }
__declspec(dllexport) void __cdecl SteamAPI_UnregisterCallback(void* p) { (void)p; }
__declspec(dllexport) void __cdecl SteamAPI_SetBreakpadAppID(unsigned int id) { (void)id; }
__declspec(dllexport) void __cdecl SteamAPI_SetMiniDumpComment(const char* text) { (void)text; }
__declspec(dllexport) void __cdecl SteamAPI_SetTryCatchCallbacks(int enable) { (void)enable; }
__declspec(dllexport) void __cdecl SteamAPI_UseBreakpadCrashHandler(void) {}
__declspec(dllexport) void __cdecl SteamAPI_WriteMiniDump(unsigned int code, void* info, unsigned int build) { (void)code; (void)info; (void)build; }

#define NULL_EXPORT(name) __declspec(dllexport) void* __cdecl name(void) { RawLog(#name); return NULL; }
NULL_EXPORT(SteamController)
NULL_EXPORT(SteamGameServer)
NULL_EXPORT(SteamGameServerApps)
NULL_EXPORT(SteamGameServerHTTP)
NULL_EXPORT(SteamGameServerNetworking)
NULL_EXPORT(SteamGameServerStats)
NULL_EXPORT(SteamGameServerUtils)
NULL_EXPORT(SteamHTTP)
NULL_EXPORT(SteamMatchmaking)
NULL_EXPORT(SteamMatchmakingServers)
NULL_EXPORT(SteamRemoteStorage)
NULL_EXPORT(SteamScreenshots)
NULL_EXPORT(SteamUGC)
NULL_EXPORT(SteamUnifiedMessages)
NULL_EXPORT(VR_GetControlPanel)
NULL_EXPORT(VR_Init)
NULL_EXPORT(VR_Shutdown)
NULL_EXPORT(SteamGameServer_BSecure)
NULL_EXPORT(SteamGameServer_GetHSteamPipe)
NULL_EXPORT(SteamGameServer_GetHSteamUser)
NULL_EXPORT(SteamGameServer_GetIPCCallCount)
__declspec(dllexport) unsigned __int64 __cdecl SteamGameServer_GetSteamID(void) { return 0; }
NULL_EXPORT(SteamGameServer_Init)
NULL_EXPORT(SteamGameServer_InitSafe)
NULL_EXPORT(SteamGameServer_RunCallbacks)
NULL_EXPORT(SteamGameServer_Shutdown)
NULL_EXPORT(Steam_GetHSteamUserCurrent)
NULL_EXPORT(Steam_RegisterInterfaceFuncs)
__declspec(dllexport) void* g_pSteamClientGameServer = NULL;

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    (void)hinstDLL; (void)lpReserved;
    if (fdwReason == DLL_PROCESS_ATTACH) {
        LogInit();
        RawLog("=== Dark Blood offline research shim (modular) ===");
        AddVectoredExceptionHandler(1, VectoredHandler);
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        LogClose();
    }
    return TRUE;
}
