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
static volatile LONG g_selectionObserved;
static volatile LONG g_selectionThrows;
static int __cdecl TraceWelcome(void* reader,void* result) {
    int ok=((int (__cdecl *)(void*,void*))0x00a519a0)(reader,result);
    DWORD* buffer=*((DWORD**)reader+1);
    RawLogFmt("[GAME] Welcome decoded=%d reader_ok=%d cursor=%d",ok,((BYTE*)reader)[8],buffer?buffer[4]:-1);
    return ok;
}
static void __cdecl TraceUserEnter(const unsigned char* data,int size) {
    DWORD opcode;
    if (size >= 4 && data && SafeRead((DWORD)data, &opcode, sizeof(opcode)) && opcode == 2007)
        InterlockedExchange(&g_selectionObserved, 1);
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

    /* Observe first-chance C++ throws after selection without swallowing them.
     * Bound output and use SafeRead: this must not hide the original failure. */
    if (code == 0xE06D7363 && g_selectionObserved && !g_inSafeRead &&
        InterlockedIncrement(&g_selectionThrows) <= 16) {
        CONTEXT* c = pExceptionInfo->ContextRecord;
        EXCEPTION_RECORD* record = pExceptionInfo->ExceptionRecord;
        DWORD stack[128];
        RawLogFmt("[CXX selection] eip=%08X esp=%08X object=%08X info=%08X",
            c->Eip, c->Esp,
            record->NumberParameters > 1 ? (DWORD)record->ExceptionInformation[1] : 0,
            record->NumberParameters > 2 ? (DWORD)record->ExceptionInformation[2] : 0);
        if (SafeRead(c->Esp, stack, sizeof(stack))) {
            int found = 0;
            for (int i = 0; i < 128 && found < 24; i++) {
                if (stack[i] >= 0x00401000 && stack[i] < 0x00C40000) {
                    RawLogFmt("[CXX frame] stack+%X=%08X", i * 4, stack[i]);
                    found++;
                }
            }
        }
    }

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

typedef void* (__stdcall *Direct3DCreate9_t)(unsigned int SDKVersion);
static Direct3DCreate9_t orig_Direct3DCreate9 = NULL;

typedef long (__stdcall *CreateDevice_t)(void* self, unsigned int Adapter, unsigned int DeviceType,
                                        void* hFocusWindow, unsigned long BehaviorFlags,
                                        void* pPresentationParameters, void** ppReturnedDeviceInterface);
static CreateDevice_t orig_CreateDevice = NULL;

static long __stdcall Hook_CreateDevice(void* self, unsigned int Adapter, unsigned int DeviceType,
                                        void* hFocusWindow, unsigned long BehaviorFlags,
                                        void* pPresentationParameters, void** ppReturnedDeviceInterface) {
    RawLogFmt("[D3D9] CreateDevice Adapter=%u Type=%u Flags=0x%08X Focus=%p",
              Adapter, DeviceType, BehaviorFlags, hFocusWindow);

    long hr = orig_CreateDevice(self, Adapter, DeviceType, hFocusWindow, BehaviorFlags,
                                pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK (Adapter %u): hr=0x%08X dev=%p", Adapter, hr, *ppReturnedDeviceInterface);
        return hr;
    }
    RawLogFmt("[D3D9] CreateDevice failed (hr=0x%08X); trying Adapter 1...", hr);

    hr = orig_CreateDevice(self, 1, DeviceType, hFocusWindow, BehaviorFlags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK on Adapter 1: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        return hr;
    }

    unsigned long sw_flags = (BehaviorFlags & ~0x44) | 0x20;
    hr = orig_CreateDevice(self, Adapter, DeviceType, hFocusWindow, sw_flags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK with SW VP: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        return hr;
    }

    hr = orig_CreateDevice(self, Adapter, 2, hFocusWindow, sw_flags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK with D3DDEVTYPE_REF: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        return hr;
    }

    RawLogFmt("[D3D9] CreateDevice all fallbacks failed: hr=0x%08X", hr);
    return hr;
}

static void* __stdcall Hook_Direct3DCreate9(unsigned int SDKVersion) {
    RawLogFmt("[D3D9] Direct3DCreate9(SDKVersion=%u)", SDKVersion);
    void* pD3D = orig_Direct3DCreate9(SDKVersion);
    if (!pD3D) {
        RawLog("[D3D9] Direct3DCreate9 returned NULL!");
        return NULL;
    }
    void*** pVtbl = (void***)pD3D;
    void** vtbl = *pVtbl;
    if (vtbl && !orig_CreateDevice) {
        DWORD oldProtect;
        if (VirtualProtect(&vtbl[16], sizeof(void*), PAGE_EXECUTE_READWRITE, &oldProtect)) {
            orig_CreateDevice = (CreateDevice_t)vtbl[16];
            vtbl[16] = (void*)Hook_CreateDevice;
            VirtualProtect(&vtbl[16], sizeof(void*), oldProtect, &oldProtect);
            RawLogFmt("[D3D9] Hooked CreateDevice at %p (orig=%p)", &vtbl[16], orig_CreateDevice);
        }
    }
    return pD3D;
}

/* Return to the server list after a server disconnect instead of exiting.
 * JUserClient::vf0c (0x007869A0) handles the lost connection: it sets
 * 0x00F45204 = 1 (box shown once), sets byte 0 of the object at 0x00F36544
 * (getter 0x00457010) to 1, which makes 0x006E2400 skip input, and opens
 * MB_DisconnectFromServer. That box's OnOK (page_msgbox.xml) runs
 * g_jLobby:ExitGame() = Lua_ExitGame 0x007381E0. While the disconnect flag is
 * set, the hook does what Lua_GoBackToLobby (0x006E25E0) does instead:
 * FadeOut("g_jAppStateMgr:ChangeState(eAS_Lobby)", 0.0) through 0x00406700 /
 * 0x00AD6BA0, and clears both flags. Every other ExitGame call runs the
 * original code. */
#define EXITGAME_VA      0x007381E0
#define DISCONNECT_SHOWN 0x00F45204
#define INPUT_LOCK       0x00F36544
static BYTE* g_exitTrampoline;
static const char g_toLobby[] = "g_jAppStateMgr:ChangeState(eAS_Lobby)";

/* The server list exists only after the startup login: FUN_00472320 calls
 * JLobbyCommon::Login (0x00749EE0, thiscall on getter 0x00456CE0, arg
 * const wchar_t* id, ret 4). Login runs ConnectServer (0x00786B40), waits for
 * 5020 and then for the server list (2403). It refuses while flags +9/+10 of
 * the singleton 0x00F2EE90 (getter 0x0043A180) are set. The welcome handler
 * sets +9 (0x0096B20B), and nothing clears it on disconnect. The hook records
 * the startup id and runs Login again before switching to the Lobby. */
#define LOGIN_VA       0x00749EE0
#define LOGIN_FLAGS    0x00F2EE98   /* +8, +9, +10 of 0x00F2EE90 */
static BYTE* g_loginTrampoline;
static wchar_t g_loginId[64];

static void __cdecl RecordLoginId(const wchar_t* id) {
    int i;
    for (i = 0; i < 63; i++) {
        wchar_t c;
        if (!SafeRead((DWORD)(id + i), &c, sizeof(c))) break;
        g_loginId[i] = c;
        if (!c) break;
    }
    g_loginId[i < 63 ? i : 63] = 0;
    RawLogFmt("[RECONNECT] Login id recorded (%d chars)", lstrlenW(g_loginId));
}

static void __declspec(naked) Hook_Login(void) {
    __asm {
        pushad
        push dword ptr [esp + 0x24]   /* first argument (after pushad + ret) */
        call RecordLoginId
        add esp, 4
        popad
        jmp dword ptr [g_loginTrampoline]
    }
}

/* JUserClient's connect wrapper 0x00A5E800 refuses while the global
 * "connected" bytes 0x00F29AE8..EA are set, and the NetClient left over
 * from the lost session does not connect again either: clearing the bytes
 * alone produced no TCP connect. 0x00A5CF50 (JNetProxy release, called by
 * the destructor 0x00A5D5A0) deletes the NetClient at +0x18, sets it to NULL
 * (the state the constructor 0x00A5D570 starts in) and clears the bytes. The
 * next connect then creates a fresh client through 0x00B59280. The
 * JUserClient singleton comes from 0x004065F0. */
#define NET_CONNECTED 0x00F29AE8

static void ReleaseNetClient(void) {
    volatile BYTE* net = (volatile BYTE*)NET_CONNECTED;
    RawLogFmt("[RECONNECT] releasing NetClient; net flags %d %d %d", net[0], net[1], net[2]);
    __asm {
        mov eax, 0x004065F0
        call eax                 /* JUserClient singleton */
        mov ecx, eax
        mov eax, 0x00A5CF50
        call eax                 /* thiscall release, no args */
    }
}

static void CallLogin(void) {
    const wchar_t* id = g_loginId;
    ReleaseNetClient();
    __asm {
        push id
        mov eax, 0x00456CE0
        call eax                 /* JLobbyCommon singleton (argument stays for Login) */
        mov ecx, eax
        mov eax, LOGIN_VA
        call eax                 /* thiscall Login(id), ret 4 */
    }
}

static void FadeToLobby(void) {
    __asm {
        mov eax, 0x00406700
        call eax                 /* fade/UI singleton */
        mov ecx, eax
        push 0                   /* float 0.0 */
        push offset g_toLobby
        mov eax, 0x00AD6BA0
        call eax                 /* thiscall FadeOut(cmd, time), ret 8 */
    }
}

static void ShowDisconnectBox(void) {
    static const char name[] = "MB_DisconnectFromServer";
    __asm {
        push offset name
        mov eax, 0x00AF57A0
        call eax                 /* cdecl open dialog by name (as 0x00786ADF) */
        add esp, 4
    }
}

static int __cdecl ReturnToLobbyIfDisconnected(void) {
    volatile BYTE* flags = (volatile BYTE*)LOGIN_FLAGS;
    if (*(volatile BYTE*)DISCONNECT_SHOWN != 1) return 0;
    *(volatile BYTE*)DISCONNECT_SHOWN = 0;
    *(volatile BYTE*)INPUT_LOCK = 0;
    RawLogFmt("[RECONNECT] ExitGame after disconnect; login flags %d %d %d",
              flags[0], flags[1], flags[2]);
    if (!g_loginTrampoline || !g_loginId[0]) return 0;   /* fall back to exiting */
    flags[1] = 0;
    flags[2] = 0;
    CallLogin();
    RawLogFmt("[RECONNECT] Login returned; flags %d %d %d", flags[0], flags[1], flags[2]);
    if (!flags[1]) {
        /* Welcome (which sets +9) never arrived: the server is still down.
         * Entering the Lobby without a session leaves the server list
         * stuck after Knock (live), so reopen the box; Ok retries. */
        *(volatile BYTE*)DISCONNECT_SHOWN = 1;
        *(volatile BYTE*)INPUT_LOCK = 1;
        ShowDisconnectBox();
        RawLog("[RECONNECT] server unreachable; disconnect box reopened");
        return 1;
    }
    FadeToLobby();
    RawLog("[RECONNECT] ChangeState(eAS_Lobby)");
    return 1;
}

static void __declspec(naked) Hook_ExitGame(void) {
    __asm {
        push ecx
        call ReturnToLobbyIfDisconnected
        pop ecx
        test eax, eax
        jz original
        ret
    original:
        jmp dword ptr [g_exitTrampoline]
    }
}

/* Patch a "push -1; push imm32" prologue (7 position-independent bytes). */
static BYTE* HookPushPushPrologue(DWORD va, DWORD imm, void* hook, const char* name) {
    BYTE expected[7] = {0x6A,0xFF,0x68};
    BYTE* target = (BYTE*)va;
    BYTE* tramp;
    DWORD protect;
    *(DWORD*)(expected + 3) = imm;
    if (memcmp(target, expected, sizeof(expected))) { RawLogFmt("[RECONNECT] %s prologue mismatch; hook refused", name); return NULL; }
    tramp = (BYTE*)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tramp) return NULL;
    memcpy(tramp, target, 7);
    tramp[7] = 0xE9;
    *(DWORD*)(tramp + 8) = (DWORD)(target + 7) - (DWORD)(tramp + 12);
    if (!VirtualProtect(target, 7, PAGE_EXECUTE_READWRITE, &protect)) { VirtualFree(tramp, 0, MEM_RELEASE); return NULL; }
    target[0] = 0xE9;
    *(DWORD*)(target + 1) = (DWORD)hook - (DWORD)(target + 5);
    target[5] = 0x90; target[6] = 0x90;
    VirtualProtect(target, 7, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), target, 7);
    RawLogFmt("[RECONNECT] %s hook installed", name);
    return tramp;
}

static void InstallLoginHook(void) {
    g_loginTrampoline = HookPushPushPrologue(LOGIN_VA, 0x00BFC409, Hook_Login, "Login");
}

static void InstallExitGameHook(void) {
    /* push 0; push 0; push 2; call 0x004488D0 -- position-independent pushes. */
    static const BYTE expected[] = {0x6A,0x00,0x6A,0x00,0x6A,0x02,0xE8};
    BYTE* target = (BYTE*)EXITGAME_VA;
    DWORD protect;
    if (memcmp(target, expected, sizeof(expected))) { RawLog("[RECONNECT] ExitGame prologue mismatch; hook refused"); return; }
    g_exitTrampoline = (BYTE*)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!g_exitTrampoline) return;
    memcpy(g_exitTrampoline, target, 6);
    g_exitTrampoline[6] = 0xE9;
    *(DWORD*)(g_exitTrampoline + 7) = (DWORD)(target + 6) - (DWORD)(g_exitTrampoline + 11);
    if (!VirtualProtect(target, 6, PAGE_EXECUTE_READWRITE, &protect)) return;
    target[0] = 0xE9;
    *(DWORD*)(target + 1) = (DWORD)Hook_ExitGame - (DWORD)(target + 5);
    target[5] = 0x90;
    VirtualProtect(target, 6, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), target, 6);
    RawLog("[RECONNECT] ExitGame hook installed");
}

static void InstallHooks() {
    if(orig_connect) return;
    InstallExitGameHook();
    InstallLoginHook();
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
/* Client 0x786B1B..0x786B28 calls SteamUser vtable +0x40 with one
 * stack argument. Preserve the x86 thiscall stack cleanup via fastcall.
 * This offline stub does not implement the remaining SteamUser methods. */
static void __fastcall UserSlot16(void* self, void* unused, unsigned int value) {
    (void)self; (void)unused;
    RawLogFmt("[STEAM] SteamUser slot 16 (%u), offline no-op", value);
}
static void* user_vtable[] = {
    UserHandle, UserLoggedOn, UserSteamID,
    NULL, NULL, NULL, NULL, NULL, NULL, NULL,
    NULL, NULL, NULL, NULL, NULL, NULL,
    UserSlot16
};
/* Offline ISteamUserStats (slot order of STEAMUSERSTATS_INTERFACE_VERSION011).
 * Client JSteamMgr::FindLeaderboards (0x0092CE00), reached from SquarePlay
 * (call at 0x007004E5), calls slot 23 (+0x5C) FindLeaderboard(const char*)
 * and skips the request when the returned SteamAPICall_t is 0. The former
 * placeholder pointer 1 crashed at 0x0092CF06. Each stub pops the exact
 * thiscall argument bytes of its SDK signature and returns 0 / false / "". */
static unsigned int stats_seen;
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
STATS0(0)                                   /* RequestCurrentStats() */
STATS(1, int a, int b)                      /* GetStat(name, float*) */
STATS(2, int a, int b)                      /* GetStat(name, int32*) */
STATS(3, int a, int b)                      /* SetStat(name, float) */
STATS(4, int a, int b)                      /* SetStat(name, int32) */
STATS(5, int a, int b, int c, int d)        /* UpdateAvgRateStat(name, float, double) */
STATS(6, int a, int b)                      /* GetAchievement(name, bool*) */
STATS(7, int a)                             /* SetAchievement(name) */
STATS(8, int a)                             /* ClearAchievement(name) */
STATS(9, int a, int b, int c)               /* GetAchievementAndUnlockTime */
STATS0(10)                                  /* StoreStats() */
STATS(11, int a)                            /* GetAchievementIcon(name) */
STATSS(12, int a, int b)                    /* GetAchievementDisplayAttribute */
STATS(13, int a, int b, int c)              /* IndicateAchievementProgress */
STATS0(14)                                  /* GetNumAchievements() */
STATSS(15, int a)                           /* GetAchievementName(index) */
STATS(16, int a, int b)                     /* RequestUserStats(CSteamID) */
STATS(17, int a, int b, int c, int d)       /* GetUserStat(id, name, float*) */
STATS(18, int a, int b, int c, int d)       /* GetUserStat(id, name, int32*) */
STATS(19, int a, int b, int c, int d)       /* GetUserAchievement */
STATS(20, int a, int b, int c, int d, int f) /* GetUserAchievementAndUnlockTime */
STATS(21, int a)                            /* ResetAllStats(bool) */
STATS(22, int a, int b, int c)              /* FindOrCreateLeaderboard */
STATS(23, int a)                            /* FindLeaderboard(name) */
static void* stats_vtable[] = {
    Stats0, Stats1, Stats2, Stats3, Stats4, Stats5, Stats6, Stats7, Stats8,
    Stats9, Stats10, Stats11, Stats12, Stats13, Stats14, Stats15, Stats16,
    Stats17, Stats18, Stats19, Stats20, Stats21, Stats22, Stats23
};
static void** stats_interface = stats_vtable;
static void* friends_vtable[] = { PersonaName };
static void** user_interface = user_vtable;
static void** friends_interface = friends_vtable;
__declspec(dllexport) void* __cdecl SteamApps() { RawLog("SteamApps"); return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUser() { RawLog("SteamUser"); return &user_interface; }
__declspec(dllexport) void* __cdecl SteamFriends() { RawLog("SteamFriends"); return &friends_interface; }
__declspec(dllexport) void* __cdecl SteamUtils() { return (void*)1; }
__declspec(dllexport) void* __cdecl SteamUserStats() { return &stats_interface; }
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
