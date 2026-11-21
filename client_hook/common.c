#include "common.h"

static HANDLE g_hLog = INVALID_HANDLE_VALUE;
volatile LONG g_inSafeRead = 0;

void LogInit(void) {
    /* One log per window: with several clients the shared hook_log.txt was
     * overwritten by every process (multibox). DARKBLOOD_ACCOUNT names it. */
    char logName[96] = "hook_log.txt";
    char acc[48];
    if (GetEnvironmentVariableA("DARKBLOOD_ACCOUNT", acc, sizeof(acc)) && acc[0] && acc[0] != ' ')
        wsprintfA(logName, "hook_log.%s.txt", acc);
    g_hLog = CreateFileA(logName, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                         NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}

void LogClose(void) {
    if (g_hLog != INVALID_HANDLE_VALUE) {
        CloseHandle(g_hLog);
        g_hLog = INVALID_HANDLE_VALUE;
    }
}

void RawLog(const char* str) {
    if (g_hLog != INVALID_HANDLE_VALUE && str) {
        DWORD written = 0;
        int len = 0;
        while (str[len]) len++;
        WriteFile(g_hLog, str, len, &written, NULL);
        WriteFile(g_hLog, "\r\n", 2, &written, NULL);
        FlushFileBuffers(g_hLog);
    }
}

void RawLogFmt(const char* fmt, ...) {
    char buf[1024];
    va_list va;
    va_start(va, fmt);
    wvsprintfA(buf, fmt, va);
    va_end(va);
    RawLog(buf);
}

int ConfigInt(const char* section, const char* key, int fallback) {
    return (int)GetPrivateProfileIntA(section, key, fallback, OPTIONS_FILE);
}

int ConfigStr(const char* section, const char* key, const char* fallback, char* out, DWORD outSize) {
    if (!out || outSize == 0) return 0;
    return (int)GetPrivateProfileStringA(section, key, fallback ? fallback : "", out, outSize, OPTIONS_FILE);
}

int ConfigClientPatch(const char* key, int fallback) {
    return ConfigInt("client", key, fallback) != 0;
}

int SafeRead(DWORD address, void* out, DWORD size) {
    int ok = 1;
    InterlockedIncrement(&g_inSafeRead);
    __try {
        memcpy(out, (void*)address, size);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ok = 0;
    }
    InterlockedDecrement(&g_inSafeRead);
    return ok;
}

int WriteCode(BYTE* at, BYTE value) {
    DWORD protect;
    if (!VirtualProtect(at, 1, PAGE_EXECUTE_READWRITE, &protect)) return 0;
    *at = value;
    VirtualProtect(at, 1, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), at, 1);
    return 1;
}

int ApplyBytePatch(const char* name, DWORD va, const BYTE* expected, const BYTE* patched, SIZE_T len) {
    BYTE* at = (BYTE*)va;
    DWORD protect;
    if (memcmp(at, expected, len)) {
        RawLogFmt("[PATCH] %s: unexpected bytes at %08X, not applied", name, va);
        return 0;
    }
    if (!VirtualProtect(at, len, PAGE_EXECUTE_READWRITE, &protect)) return 0;
    memcpy(at, patched, len);
    VirtualProtect(at, len, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), at, len);
    RawLogFmt("[PATCH] %s applied at %08X", name, va);
    return 1;
}

void* InstallInlineHook(void* target, void* hook) {
    DWORD oldProtect;
    static const BYTE expected[] = {0x8B, 0xFF, 0x55, 0x8B, 0xEC};
    /* Only this verified x86 hotpatch prologue is relocatable without a full
     * instruction relocator. Refuse all other layouts. */
    if (!target || memcmp(target, expected, 5)) {
        RawLog("[HOOK] Unsupported API prologue; hook refused");
        return NULL;
    }

    BYTE* trampoline = (BYTE*)VirtualAlloc(NULL, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline) return NULL;
    memcpy(trampoline, target, 5);
    trampoline[5] = 0xE9;
    *(DWORD*)(trampoline + 6) = (DWORD)((BYTE*)target + 5) - (DWORD)(trampoline + 10);

    if (!VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &oldProtect)) {
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return NULL;
    }
    *(BYTE*)target = 0xE9;
    *(DWORD*)((BYTE*)target + 1) = (DWORD)hook - ((DWORD)target + 5);

    VirtualProtect(target, 5, oldProtect, &oldProtect);
    FlushInstructionCache(GetCurrentProcess(), target, 5);
    FlushInstructionCache(GetCurrentProcess(), trampoline, 10);
    return trampoline;
}

/* Patch a "push -1; push imm32" prologue (7 position-independent bytes). */
BYTE* HookPushPushPrologue(DWORD va, DWORD imm, void* hook, const char* name) {
    BYTE expected[7] = {0x6A, 0xFF, 0x68};
    BYTE* target = (BYTE*)va;
    BYTE* tramp;
    DWORD protect;
    *(DWORD*)(expected + 3) = imm;
    if (memcmp(target, expected, sizeof(expected))) {
        RawLogFmt("[HOOK] %s prologue mismatch; hook refused", name);
        return NULL;
    }
    tramp = (BYTE*)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tramp) return NULL;
    memcpy(tramp, target, 7);
    tramp[7] = 0xE9;
    *(DWORD*)(tramp + 8) = (DWORD)(target + 7) - (DWORD)(tramp + 12);
    if (!VirtualProtect(target, 7, PAGE_EXECUTE_READWRITE, &protect)) {
        VirtualFree(tramp, 0, MEM_RELEASE);
        return NULL;
    }
    target[0] = 0xE9;
    *(DWORD*)(target + 1) = (DWORD)hook - (DWORD)(target + 5);
    target[5] = 0x90;
    target[6] = 0x90;
    VirtualProtect(target, 7, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), target, 7);
    FlushInstructionCache(GetCurrentProcess(), tramp, 12);
    RawLogFmt("[HOOK] %s hook installed", name);
    return tramp;
}
