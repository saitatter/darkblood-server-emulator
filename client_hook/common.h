#ifndef DARKBLOOD_HOOK_COMMON_H
#define DARKBLOOD_HOOK_COMMON_H

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>

#define OPTIONS_FILE ".\\darkblood_options.ini"

/* Logging */
void LogInit(void);
void LogClose(void);
void RawLog(const char* str);
void RawLogFmt(const char* fmt, ...);

/* Configuration (darkblood_options.ini next to DarkBlood.exe) */
int ConfigInt(const char* section, const char* key, int fallback);
int ConfigStr(const char* section, const char* key, const char* fallback, char* out, DWORD outSize);
int ConfigClientPatch(const char* key, int fallback);

/* Safe memory access & patching helpers */
extern volatile LONG g_inSafeRead;

int   SafeRead(DWORD address, void* out, DWORD size);
int   WriteCode(BYTE* at, BYTE value);
int   ApplyBytePatch(const char* name, DWORD va, const BYTE* expected, const BYTE* patched, SIZE_T len);
void* InstallInlineHook(void* target, void* hook);
BYTE* HookPushPushPrologue(DWORD va, DWORD imm, void* hook, const char* name);

#endif /* DARKBLOOD_HOOK_COMMON_H */
