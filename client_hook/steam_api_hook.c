#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")

static HANDLE g_hLog = INVALID_HANDLE_VALUE;

static void RawLog(const char* str) {
    if (g_hLog != INVALID_HANDLE_VALUE && str) {
        DWORD written = 0;
        int len = 0;
        while (str[len]) len++;
        WriteFile(g_hLog, str, len, &written, NULL);
        WriteFile(g_hLog, "\r\n", 2, &written, NULL);
        FlushFileBuffers(g_hLog);
    }
}

static void RawLogFmt(const char* fmt, ...) {
    char buf[1024];
    va_list va;
    va_start(va, fmt);
    wvsprintfA(buf, fmt, va);
    va_end(va);
    RawLog(buf);
}

// Inline hook helper
static void* InstallInlineHook(void* target, void* hook) {
    DWORD oldProtect;
    static const BYTE expected[] = {0x8b,0xff,0x55,0x8b,0xec};
    /* Only this verified x86 hotpatch prologue is relocatable without a full
     * instruction relocator. Refuse all other layouts. */
    if (!target || memcmp(target,expected,5)) { RawLog("[NET] Unsupported API prologue; hook refused"); return NULL; }

    BYTE* trampoline = (BYTE*)VirtualAlloc(NULL, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if(!trampoline) return NULL;
    memcpy(trampoline, target, 5);
    trampoline[5] = 0xE9;
    *(DWORD*)(trampoline + 6) = (DWORD)((BYTE*)target + 5) - (DWORD)(trampoline + 10);

    if (!VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &oldProtect)) {VirtualFree(trampoline,0,MEM_RELEASE);return NULL;}
    *(BYTE*)target = 0xE9;
    *(DWORD*)((BYTE*)target + 1) = (DWORD)hook - ((DWORD)target + 5);

    VirtualProtect(target, 5, oldProtect, &oldProtect);
    FlushInstructionCache(GetCurrentProcess(),target,5);
    FlushInstructionCache(GetCurrentProcess(),trampoline,10);
    return trampoline;
}

// NtTerminateProcess hook
typedef LONG (NTAPI *NtTerminateProcess_t)(HANDLE, LONG);
static NtTerminateProcess_t orig_NtTerminateProcess = NULL;

static LONG NTAPI Hook_NtTerminateProcess(HANDLE ProcessHandle, LONG ExitStatus) {
    RawLogFmt("[GUARD] NtTerminateProcess(handle=%p, status=0x%X) BLOCKED! Caller: %p", ProcessHandle, ExitStatus, _ReturnAddress());
    // Dump caller stack
    DWORD* pStack;
    __asm { mov pStack, esp }
    for (int i = 0; i < 16; i++) {
        DWORD val = pStack[i];
        if (val >= 0x00400000 && val <= 0x7FFFFFFF) {
            RawLogFmt("  esp+0x%X: %p", i * 4, val);
        }
    }
    RawLog("[GUARD] Halting caller thread.");
    Sleep(INFINITE);
    return 0;
}

// ExitProcess hook
typedef void (WINAPI *ExitProcess_t)(UINT);
static ExitProcess_t orig_ExitProcess = NULL;

static void WINAPI Hook_ExitProcess(UINT uExitCode) {
    RawLogFmt("[GUARD] ExitProcess(code=%u) BLOCKED! Caller: %p", uExitCode, _ReturnAddress());
    Sleep(INFINITE);
}

// Winsock connect redirector
typedef int (WSAAPI *connect_t)(SOCKET, const struct sockaddr*, int);
static connect_t orig_connect = NULL;

static void* orig_join = NULL;
static void* orig_user_message = NULL;
static int __cdecl TraceWelcome(void* reader,void* result) {
    int ok=((int (__cdecl *)(void*,void*))0x00a519a0)(reader,result);
    DWORD* buffer=*((DWORD**)reader+1);
    RawLogFmt("[GAME] Welcome decoded=%d reader_ok=%d cursor=%d",ok,((BYTE*)reader)[8],buffer?buffer[4]:-1);
    return ok;
}
static void __cdecl TraceUserEnter(const unsigned char* data,int size) {
    RawLogFmt("[PROUD] OnReceiveUserMessage bytes=%d data=%p",size,data);
    if(data && size>0) {
        char line[200]; int len=0;
        for(int i=0;i<size && i<48;i++) len+=wsprintfA(line+len,"%02X ",data[i]);
        line[len]=0; RawLog(line);
    }
}
static void __declspec(naked) TraceUserMessage(void) {
    __asm {
        pushfd
        pushad
        push dword ptr [esp+52]
        push dword ptr [esp+52]
        call TraceUserEnter
        add esp,8
        popad
        popfd
        jmp dword ptr [orig_user_message]
    }
}
static void __cdecl TraceJoinEnter(void* self,int* info) {
    RawLogFmt("[PROUD] OnJoinServerComplete result=%d self=%p",info?*info:-1,self);
}
static void __declspec(naked) TraceJoin(void) {
    __asm {
        pushfd
        pushad
        push dword ptr [esp+40]
        push ecx
        call TraceJoinEnter
        add esp,8
        popad
        popfd
        jmp dword ptr [orig_join]
    }
}

static int WSAAPI Hook_connect(SOCKET s, const struct sockaddr* name, int namelen) {
    if (name && name->sa_family == AF_INET) {
        if(namelen < sizeof(struct sockaddr_in)) {WSASetLastError(WSAEINVAL);return SOCKET_ERROR;}
        struct sockaddr_in redirected=*(const struct sockaddr_in*)name;
        struct sockaddr_in* sin = &redirected;
        char ip[32];
        strcpy(ip, inet_ntoa(sin->sin_addr));
        int port = ntohs(sin->sin_port);
        RawLogFmt("[NET] connect() -> %s:%d ==> 127.0.0.1:%d", ip, port,port);

        sin->sin_addr.s_addr = inet_addr("127.0.0.1");
        return orig_connect ? orig_connect(s,(const struct sockaddr*)sin, sizeof(*sin)) : SOCKET_ERROR;
    }
    return orig_connect ? orig_connect(s, name, namelen) : -1;
}

// Vectored Exception Handler
LONG WINAPI VectoredHandler(PEXCEPTION_POINTERS pExceptionInfo) {
    DWORD code = pExceptionInfo->ExceptionRecord->ExceptionCode;
    BYTE* addr = (BYTE*)pExceptionInfo->ExceptionRecord->ExceptionAddress;

    if(code==EXCEPTION_ACCESS_VIOLATION || code==EXCEPTION_ILLEGAL_INSTRUCTION) {
        CONTEXT* c=pExceptionInfo->ContextRecord;
        RawLogFmt("[EXCEPTION] code=%X eip=%p eax=%p ecx=%p edx=%p esp=%p ebp=%p",code,c->Eip,c->Eax,c->Ecx,c->Edx,c->Esp,c->Ebp);
        DWORD* stack=(DWORD*)c->Esp;
        for(int i=0;i<32;i++) RawLogFmt("stack+%X: %p",i*4,stack[i]);
        HANDLE dump=CreateFileA("crash_image.bin",GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
        if(dump!=INVALID_HANDLE_VALUE) {
            BYTE* image=(BYTE*)GetModuleHandleA(NULL);
            DWORD size=((IMAGE_NT_HEADERS*)(image+((IMAGE_DOS_HEADER*)image)->e_lfanew))->OptionalHeader.SizeOfImage;
            BYTE zeros[4096]={0}; DWORD written; MEMORY_BASIC_INFORMATION mbi;
            for(DWORD off=0;off<size;off+=4096) {
                VirtualQuery(image+off,&mbi,sizeof(mbi));
                BYTE* src=(mbi.State==MEM_COMMIT && !(mbi.Protect&(PAGE_NOACCESS|PAGE_GUARD)))?image+off:zeros;
                WriteFile(dump,src,min(4096,size-off),&written,NULL);
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

static void InstallHooks() {
    if(orig_connect) return;
    BYTE* call=(BYTE*)0x0096b091;
    if(call[0]==0xe8 && (DWORD)(call+5+*(LONG*)(call+1))==0x00a519a0) {
        DWORD protect;
        if(VirtualProtect(call,5,PAGE_EXECUTE_READWRITE,&protect)) {
            *(LONG*)(call+1)=(BYTE*)TraceWelcome-(call+5);
            VirtualProtect(call,5,protect,&protect);
            FlushInstructionCache(GetCurrentProcess(),call,5);
        }
    }
    /* Build-specific diagnostic vtable hook; verified before mutation. */
    void** slot=(void**)0x00d4fa90;
    if(*slot==(void*)0x00a5d880) {
        DWORD protect;
        if(VirtualProtect(slot,sizeof(*slot),PAGE_READWRITE,&protect)) {
            orig_join=*slot; *slot=TraceJoin;
            VirtualProtect(slot,sizeof(*slot),protect,&protect);
        }
    }
    slot=(void**)0x00d4fa8c;
    if(*slot==(void*)0x00a5efa0) {
        DWORD protect;
        if(VirtualProtect(slot,sizeof(*slot),PAGE_READWRITE,&protect)) {
            orig_user_message=*slot; *slot=TraceUserMessage;
            VirtualProtect(slot,sizeof(*slot),protect,&protect);
        }
    }
    RawLog("[INIT] Installing loopback network redirect after unpacking");
    HMODULE hWs2 = LoadLibraryA("ws2_32.dll");
    if (hWs2) {
        orig_connect = (connect_t)InstallInlineHook((void*)GetProcAddress(hWs2, "connect"), (void*)Hook_connect);
    }
    RawLog("[INIT] Network hook setup complete");
}

// Steam API mocks
__declspec(dllexport) int __cdecl SteamAPI_Init() { InstallHooks(); RawLog("[STEAM] SteamAPI_Init -> OK"); return 1; }
__declspec(dllexport) int __cdecl SteamAPI_InitSafe() { return SteamAPI_Init(); }
__declspec(dllexport) int __cdecl SteamAPI_RestartAppIfNecessary(unsigned int unOwnAppID) {
    RawLogFmt("[STEAM] SteamAPI_RestartAppIfNecessary(%u) -> Bypass (0)", unOwnAppID);
    return 0;
}
__declspec(dllexport) int __cdecl SteamAPI_IsSteamRunning() { return 1; }
__declspec(dllexport) void __cdecl SteamAPI_Shutdown() {}
__declspec(dllexport) void __cdecl SteamAPI_RunCallbacks() {}
__declspec(dllexport) void __cdecl Steam_RunCallbacks() {}
static int __fastcall UserHandle(void* self, void* unused) { return 1; }
static int __fastcall UserLoggedOn(void* self, void* unused) { return 1; }
static void* __fastcall UserSteamID(void* self, void* unused, unsigned __int64* out) {
    *out=0x0110000100000001ULL; return out;
}
static const char* __fastcall PersonaName(void* self, void* unused) { return "OfflinePlayer"; }
static void* user_vtable[] = { UserHandle, UserLoggedOn, UserSteamID };
static void* friends_vtable[] = { PersonaName };
static void** user_interface = user_vtable;
static void** friends_interface = friends_vtable;
__declspec(dllexport) void* __cdecl SteamApps() { RawLog("SteamApps"); return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUser() { RawLog("SteamUser"); return &user_interface; }
__declspec(dllexport) void* __cdecl SteamFriends() { RawLog("SteamFriends"); return &friends_interface; }
__declspec(dllexport) void* __cdecl SteamUtils() { return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUserStats() { return (void*)1; }
__declspec(dllexport) void* __cdecl SteamNetworking() { return (void*)1; }
__declspec(dllexport) void* __cdecl SteamClient() { return (void*)1; }

/* Keep the complete export surface: the packer resolves imports dynamically
 * and exits before the game entry point if even one export is absent. */
__declspec(dllexport) int __cdecl GetHSteamPipe() { return 1; }
__declspec(dllexport) int __cdecl GetHSteamUser() { return 1; }
__declspec(dllexport) int __cdecl SteamAPI_GetHSteamPipe() { return 1; }
__declspec(dllexport) int __cdecl SteamAPI_GetHSteamUser() { return 1; }
__declspec(dllexport) const char* __cdecl SteamAPI_GetSteamInstallPath() { return "."; }
__declspec(dllexport) void __cdecl SteamAPI_RegisterCallResult(void* p, unsigned __int64 id) { RawLog("RegisterCallResult"); }
__declspec(dllexport) void __cdecl SteamAPI_RegisterCallback(void* p, int id) { RawLogFmt("RegisterCallback %d",id); }
__declspec(dllexport) void __cdecl SteamAPI_UnregisterCallResult(void* p, unsigned __int64 id) {}
__declspec(dllexport) void __cdecl SteamAPI_UnregisterCallback(void* p) {}
__declspec(dllexport) void __cdecl SteamAPI_SetBreakpadAppID(unsigned int id) {}
__declspec(dllexport) void __cdecl SteamAPI_SetMiniDumpComment(const char* text) {}
__declspec(dllexport) void __cdecl SteamAPI_SetTryCatchCallbacks(int enable) {}
__declspec(dllexport) void __cdecl SteamAPI_UseBreakpadCrashHandler() {}
__declspec(dllexport) void __cdecl SteamAPI_WriteMiniDump(unsigned int code,void* info,unsigned int build) {}
#define NULL_EXPORT(name) __declspec(dllexport) void* __cdecl name() { RawLog(#name); return NULL; }
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
__declspec(dllexport) unsigned __int64 __cdecl SteamGameServer_GetSteamID() { return 0; }
NULL_EXPORT(SteamGameServer_Init)
NULL_EXPORT(SteamGameServer_InitSafe)
NULL_EXPORT(SteamGameServer_RunCallbacks)
NULL_EXPORT(SteamGameServer_Shutdown)
NULL_EXPORT(Steam_GetHSteamUserCurrent)
NULL_EXPORT(Steam_RegisterInterfaceFuncs)
__declspec(dllexport) void* g_pSteamClientGameServer = NULL;

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        g_hLog = CreateFileA("hook_log.txt", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        RawLog("=== Dark Blood offline research shim ===");
        AddVectoredExceptionHandler(1, VectoredHandler);
        /* Do not patch kernel32/ntdll: cutting a five-byte prologue can split
         * instructions and the packer also checks API integrity. */
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        if (g_hLog != INVALID_HANDLE_VALUE) {
            CloseHandle(g_hLog);
            g_hLog = INVALID_HANDLE_VALUE;
        }
    }
    return TRUE;
}
