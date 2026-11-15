#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")

static HANDLE g_hLog = INVALID_HANDLE_VALUE;
static int SafeRead(DWORD address, void* out, DWORD size);

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

/* Dump the application handler std::map (0xF45250: opcode -> member fn,
 * looked up by 0x75FD30). MSVC8 _Tree node: left, parent, right, value...
 * Raw node words are logged so field meanings can be checked. */
static void DumpNode(HANDLE out, DWORD node, DWORD head, int depth, int* count) {
    DWORD words[10]; char line[200]; DWORD written;
    if (depth > 64 || *count > 4000 || node == head || node == 0) return;
    if (!SafeRead(node, words, sizeof(words))) return;
    if (((BYTE*)words)[0x21] != 0) return; /* _Isnil */
    DumpNode(out, words[0], head, depth + 1, count);
    wsprintfA(line, "%u %08X %08X %08X %08X %08X\r\n", words[3], words[4], words[5], words[6], words[7], words[8]);
    WriteFile(out, line, lstrlenA(line), &written, NULL);
    (*count)++;
    DumpNode(out, words[2], head, depth + 1, count);
}
static void DumpHandlerMap(void) {
    DWORD head, root, words[10]; int count = 0;
    HANDLE out;
    if (!SafeRead(0x00F45254, &head, 4) || !SafeRead(head, words, sizeof(words))) return;
    root = words[1];
    out = CreateFileA("handler_map.txt", GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, 0, NULL);
    if (out == INVALID_HANDLE_VALUE) return;
    DumpNode(out, root, head, 0, &count);
    CloseHandle(out);
    RawLogFmt("[MAP] dumped %d handler entries (head=%08X isnil=%02X)", count, head, ((BYTE*)words)[0x21]);
}

static void __cdecl TraceJoinEnter(void* self,int* info) {
    DumpHandlerMap();
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

/* ---- Diagnostic INT3 tracer ------------------------------------------
 * Reads bp.txt from the working directory (absent file = no breakpoints).
 * Line format: <hex VA> [max=N] [expr ...]
 *   expr  reg+hexoff        dword at (reg+off)
 *         reg+hexoff.N      N bytes at (reg+off), N<=64 (hex)
 *         @reg+hexoff+hex2  dword at ([reg+off]+hex2)
 * Logging only: original byte is restored, one single step is taken,
 * then the breakpoint is re-armed until max hits are reached. */
#define MAX_BP 64
typedef struct { BYTE* addr; BYTE orig; int hits, max; char exprs[200]; } Breakpoint;
static Breakpoint g_bp[MAX_BP];
static int g_bpCount;
static DWORD g_rearmTls = TLS_OUT_OF_INDEXES;

static int WriteCode(BYTE* at, BYTE value) {
    DWORD protect;
    if (!VirtualProtect(at, 1, PAGE_EXECUTE_READWRITE, &protect)) return 0;
    *at = value;
    VirtualProtect(at, 1, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), at, 1);
    return 1;
}

static DWORD RegValue(CONTEXT* c, const char* r) {
    if (!memcmp(r,"eax",3)) return c->Eax; if (!memcmp(r,"ebx",3)) return c->Ebx;
    if (!memcmp(r,"ecx",3)) return c->Ecx; if (!memcmp(r,"edx",3)) return c->Edx;
    if (!memcmp(r,"esi",3)) return c->Esi; if (!memcmp(r,"edi",3)) return c->Edi;
    if (!memcmp(r,"esp",3)) return c->Esp; if (!memcmp(r,"ebp",3)) return c->Ebp;
    return 0;
}

static DWORD HexParse(const char** p) {
    DWORD v = 0; const char* s = *p;
    for (;;) {
        char ch = *s; int d;
        if (ch >= '0' && ch <= '9') d = ch - '0';
        else if (ch >= 'a' && ch <= 'f') d = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F') d = ch - 'A' + 10;
        else break;
        v = v * 16 + d; s++;
    }
    *p = s; return v;
}

static volatile LONG g_inSafeRead;
static int SafeRead(DWORD address, void* out, DWORD size) {
    int ok = 1;
    InterlockedIncrement(&g_inSafeRead);
    __try { memcpy(out, (void*)address, size); }
    __except (EXCEPTION_EXECUTE_HANDLER) { ok = 0; }
    InterlockedDecrement(&g_inSafeRead);
    return ok;
}

static int AppendLabel(char* out, const char* start, const char* end) {
    int n = 0;
    out[n++] = ' '; out[n++] = '|'; out[n++] = ' ';
    while (start < end && n < 60) out[n++] = *start++;
    out[n++] = '='; out[n] = 0;
    return n;
}

static void LogBreakpoint(Breakpoint* bp, CONTEXT* c) {
    char line[1400]; int len;
    const char* p = bp->exprs;
    len = wsprintfA(line, "[BP %08X #%d tid=%u] eax=%08X ebx=%08X ecx=%08X edx=%08X esi=%08X edi=%08X esp=%08X ebp=%08X",
        (DWORD)bp->addr, bp->hits, GetCurrentThreadId(), c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Esp, c->Ebp);
    while (*p && len < 1200) {
        const char* start; int indirect = 0; DWORD address, value, count = 0, extra = 0;
        while (*p == ' ') p++;
        if (!*p) break;
        start = p;
        if (*p == '@') { indirect = 1; p++; }
        address = RegValue(c, p); p += 3;
        if (*p == '+') { p++; address += HexParse(&p); }
        if (indirect) { if (*p == '+') { p++; extra = HexParse(&p); } }
        if (*p == '.') { p++; count = HexParse(&p); if (count > 64) count = 64; }
        if (indirect) {
            if (!SafeRead(address, &value, 4)) { len += AppendLabel(line+len, start, p); len += wsprintfA(line+len, "??"); goto next; }
            address = value + extra;
        }
        if (count) {
            BYTE bytes[64]; DWORD i;
            len += AppendLabel(line+len, start, p);
            if (!SafeRead(address, bytes, count)) { len += wsprintfA(line+len, "??"); goto next; }
            for (i = 0; i < count; i++) len += wsprintfA(line+len, "%02X", bytes[i]);
        } else if (SafeRead(address, &value, 4)) {
            { len += AppendLabel(line+len, start, p); len += wsprintfA(line+len, "%08X", value); }
        } else { len += AppendLabel(line+len, start, p); len += wsprintfA(line+len, "??"); }
next:
        while (*p && *p != ' ') p++;
    }
    RawLog(line);
}

static void LoadBreakpoints(void) {
    char text[8192]; DWORD read = 0; char* line; char* end;
    HANDLE file = CreateFileA("bp.txt", GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    ReadFile(file, text, sizeof(text) - 1, &read, NULL);
    CloseHandle(file);
    text[read] = 0;
    g_rearmTls = TlsAlloc();
    for (line = text; *line && g_bpCount < MAX_BP; line = end) {
        const char* p = line; Breakpoint* bp; BYTE first;
        end = line; while (*end && *end != '\n') end++;
        if (*end) *end++ = 0;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\r' || !*p) continue;
        bp = &g_bp[g_bpCount];
        bp->addr = (BYTE*)HexParse(&p); bp->max = 16; bp->hits = 0;
        while (*p == ' ') p++;
        if (!memcmp(p, "max=", 4)) { p += 4; bp->max = (int)HexParse(&p); while (*p == ' ') p++; }
        lstrcpynA(bp->exprs, p, sizeof(bp->exprs));
        { char* q = bp->exprs; while (*q) { if (*q == '\r') *q = 0; else q++; } }
        if (!SafeRead((DWORD)bp->addr, &first, 1)) { RawLogFmt("[BP] %08X unreadable", (DWORD)bp->addr); continue; }
        bp->orig = first;
        if (WriteCode(bp->addr, 0xCC)) { g_bpCount++; RawLogFmt("[BP] armed %08X orig=%02X %s", (DWORD)bp->addr, first, bp->exprs); }
    }
}

static int HandleBreakpoint(PEXCEPTION_POINTERS info) {
    DWORD code = info->ExceptionRecord->ExceptionCode;
    CONTEXT* c = info->ContextRecord;
    int i;
    if (code == EXCEPTION_BREAKPOINT) {
        for (i = 0; i < g_bpCount; i++) {
            Breakpoint* bp = &g_bp[i];
            if ((BYTE*)info->ExceptionRecord->ExceptionAddress != bp->addr) continue;
            bp->hits++;
            LogBreakpoint(bp, c);
            WriteCode(bp->addr, bp->orig);
            c->Eip = (DWORD)bp->addr;
            if (bp->hits < bp->max) { TlsSetValue(g_rearmTls, bp); c->EFlags |= 0x100; }
            return 1;
        }
    } else if (code == EXCEPTION_SINGLE_STEP && g_rearmTls != TLS_OUT_OF_INDEXES) {
        Breakpoint* bp = (Breakpoint*)TlsGetValue(g_rearmTls);
        if (bp) { TlsSetValue(g_rearmTls, NULL); WriteCode(bp->addr, 0xCC); return 1; }
    }
    return 0;
}

// Vectored Exception Handler
LONG WINAPI VectoredHandler(PEXCEPTION_POINTERS pExceptionInfo) {
    DWORD code = pExceptionInfo->ExceptionRecord->ExceptionCode;
    BYTE* addr = (BYTE*)pExceptionInfo->ExceptionRecord->ExceptionAddress;
    if (HandleBreakpoint(pExceptionInfo)) return EXCEPTION_CONTINUE_EXECUTION;

    if((code==EXCEPTION_ACCESS_VIOLATION || code==EXCEPTION_ILLEGAL_INSTRUCTION) && !g_inSafeRead) {
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
    LoadBreakpoints();
}


/* Periodic main-thread sampler (diagnostic): logs EIP and code-range return
 * addresses from the stack every 5 s. Enabled when sample.txt exists. */
static DWORD g_mainThreadId;
static DWORD WINAPI SamplerThread(LPVOID unused) {
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, g_mainThreadId);
    int round;
    if (!thread) return 0;
    for (round = 0; round < 120; round++) {
        CONTEXT c; DWORD stack[256]; char line[1400]; int len, i, found = 0;
        Sleep(5000);
        c.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (SuspendThread(thread) == (DWORD)-1) break;
        if (!GetThreadContext(thread, &c)) { ResumeThread(thread); break; }
        if (!SafeRead(c.Esp, stack, sizeof(stack))) memset(stack, 0, sizeof(stack));
        ResumeThread(thread);
        len = wsprintfA(line, "[SAMPLE %d] eip=%08X esp=%08X:", round, c.Eip, c.Esp);
        for (i = 0; i < 256 && found < 40; i++)
            if (stack[i] >= 0x00401000 && stack[i] < 0x00C40000) { len += wsprintfA(line + len, " %X", stack[i]); found++; }
        RawLog(line);
    }
    CloseHandle(thread);
    return 0;
}

// Steam API mocks
__declspec(dllexport) int __cdecl SteamAPI_Init() { InstallHooks();
    if (!g_mainThreadId && GetFileAttributesA("sample.txt") != INVALID_FILE_ATTRIBUTES) { g_mainThreadId = GetCurrentThreadId(); CloseHandle(CreateThread(NULL, 0, SamplerThread, NULL, 0, NULL)); } RawLog("[STEAM] SteamAPI_Init -> OK"); return 1; }
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
