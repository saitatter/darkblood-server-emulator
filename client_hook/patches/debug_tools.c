/* Patch: In-Process Breakpoint Tracer (bp.txt) & Main-Thread Sampler (sample.txt)
 * Config: [client] debug_tools = 1 (default: enabled)
 *
 * Inert unless bp.txt or sample.txt exists in the game working directory.
 *   bp.txt line format: <hex VA> [max=N] [expr ...]
 *     reg+hexoff        dword at (reg+off)
 *     reg+hexoff.N      N bytes at (reg+off), N<=64 (hex)
 *     @reg+hexoff+hex2  dword at ([reg+off]+hex2)
 *   sample.txt: optional interval in ms (100..60000, default 5000); runs 10 min.
 */
#include "patches.h"

#define MAX_BP 64

typedef struct {
    BYTE* addr;
    BYTE  orig;
    int   hits, max;
    char  exprs[200];
} Breakpoint;

static volatile LONG g_debugToolsEnabled = 0;
static Breakpoint    g_bp[MAX_BP];
static int           g_bpCount    = 0;
static DWORD         g_rearmTls   = TLS_OUT_OF_INDEXES;
static DWORD         g_mainThread = 0;

static DWORD RegValue(CONTEXT* c, const char* r) {
    if (!memcmp(r, "eax", 3)) return c->Eax;
    if (!memcmp(r, "ebx", 3)) return c->Ebx;
    if (!memcmp(r, "ecx", 3)) return c->Ecx;
    if (!memcmp(r, "edx", 3)) return c->Edx;
    if (!memcmp(r, "esi", 3)) return c->Esi;
    if (!memcmp(r, "edi", 3)) return c->Edi;
    if (!memcmp(r, "esp", 3)) return c->Esp;
    if (!memcmp(r, "ebp", 3)) return c->Ebp;
    return 0;
}

static DWORD HexParse(const char** p) {
    DWORD v = 0;
    const char* s = *p;
    for (;;) {
        char ch = *s;
        int d;
        if (ch >= '0' && ch <= '9') d = ch - '0';
        else if (ch >= 'a' && ch <= 'f') d = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F') d = ch - 'A' + 10;
        else break;
        v = v * 16 + d;
        s++;
    }
    *p = s;
    return v;
}

static int AppendLabel(char* out, const char* start, const char* end) {
    int n = 0;
    out[n++] = ' ';
    out[n++] = '|';
    out[n++] = ' ';
    while (start < end && n < 60) out[n++] = *start++;
    out[n++] = '=';
    out[n] = 0;
    return n;
}

static void LogBreakpoint(Breakpoint* bp, CONTEXT* c) {
    char line[1400];
    int len;
    const char* p = bp->exprs;
    len = wsprintfA(line, "[BP %08X #%d tid=%u] eax=%08X ebx=%08X ecx=%08X edx=%08X esi=%08X edi=%08X esp=%08X ebp=%08X",
                    (DWORD)bp->addr, bp->hits, GetCurrentThreadId(),
                    c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Esp, c->Ebp);
    while (*p && len < 1200) {
        const char* start;
        int indirect = 0;
        DWORD address, value, count = 0, extra = 0;
        while (*p == ' ') p++;
        if (!*p) break;
        start = p;
        if (*p == '@') { indirect = 1; p++; }
        address = RegValue(c, p);
        p += 3;
        if (*p == '+') { p++; address += HexParse(&p); }
        if (indirect && *p == '+') { p++; extra = HexParse(&p); }
        if (*p == '.') { p++; count = HexParse(&p); if (count > 64) count = 64; }
        if (indirect) {
            if (!SafeRead(address, &value, 4)) {
                len += AppendLabel(line + len, start, p);
                len += wsprintfA(line + len, "??");
                goto next;
            }
            address = value + extra;
        }
        if (count) {
            BYTE bytes[64];
            DWORD i;
            len += AppendLabel(line + len, start, p);
            if (!SafeRead(address, bytes, count)) {
                len += wsprintfA(line + len, "??");
                goto next;
            }
            for (i = 0; i < count; i++) len += wsprintfA(line + len, "%02X", bytes[i]);
        } else if (SafeRead(address, &value, 4)) {
            len += AppendLabel(line + len, start, p);
            len += wsprintfA(line + len, "%08X", value);
        } else {
            len += AppendLabel(line + len, start, p);
            len += wsprintfA(line + len, "??");
        }
next:
        while (*p && *p != ' ') p++;
    }
    RawLog(line);
}

static void LoadBreakpoints(void) {
    char text[8192];
    DWORD read = 0;
    char* line;
    char* end;
    HANDLE file = CreateFileA("bp.txt", GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    ReadFile(file, text, sizeof(text) - 1, &read, NULL);
    CloseHandle(file);
    text[read] = 0;
    g_rearmTls = TlsAlloc();
    for (line = text; *line && g_bpCount < MAX_BP; line = end) {
        const char* p = line;
        Breakpoint* bp;
        BYTE first;
        end = line;
        while (*end && *end != '\n') end++;
        if (*end) *end++ = 0;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\r' || !*p) continue;
        bp = &g_bp[g_bpCount];
        bp->addr = (BYTE*)HexParse(&p);
        bp->max = 16;
        bp->hits = 0;
        while (*p == ' ') p++;
        if (!memcmp(p, "max=", 4)) {
            p += 4;
            bp->max = (int)HexParse(&p);
            while (*p == ' ') p++;
        }
        lstrcpynA(bp->exprs, p, sizeof(bp->exprs));
        {
            char* q = bp->exprs;
            while (*q) { if (*q == '\r') *q = 0; else q++; }
        }
        if (!SafeRead((DWORD)bp->addr, &first, 1)) {
            RawLogFmt("[BP] %08X unreadable", (DWORD)bp->addr);
            continue;
        }
        bp->orig = first;
        if (WriteCode(bp->addr, 0xCC)) {
            g_bpCount++;
            RawLogFmt("[BP] armed %08X orig=%02X %s", (DWORD)bp->addr, first, bp->exprs);
        }
    }
}

static DWORD SampleInterval(void) {
    char text[16] = {0};
    DWORD got = 0, ms = 0;
    int i;
    HANDLE f = CreateFileA("sample.txt", GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        ReadFile(f, text, sizeof(text) - 1, &got, NULL);
        CloseHandle(f);
    }
    for (i = 0; text[i] >= '0' && text[i] <= '9'; i++) ms = ms * 10 + (text[i] - '0');
    return (ms >= 100 && ms <= 60000) ? ms : 5000;
}

static DWORD WINAPI SamplerThread(LPVOID unused) {
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, g_mainThread);
    DWORD interval = SampleInterval();
    int round, rounds = (int)(600000 / interval);
    (void)unused;
    if (!thread) return 0;
    for (round = 0; round < rounds; round++) {
        CONTEXT c;
        DWORD stack[256];
        char line[1400];
        int len, i, found = 0;
        Sleep(interval);
        c.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (SuspendThread(thread) == (DWORD)-1) break;
        if (!GetThreadContext(thread, &c)) { ResumeThread(thread); break; }
        if (!SafeRead(c.Esp, stack, sizeof(stack))) memset(stack, 0, sizeof(stack));
        ResumeThread(thread);
        len = wsprintfA(line, "[SAMPLE %d] eip=%08X esp=%08X:", round, c.Eip, c.Esp);
        for (i = 0; i < 256 && found < 40; i++) {
            if (stack[i] >= 0x00401000 && stack[i] < 0x00C40000) {
                len += wsprintfA(line + len, " %X", stack[i]);
                found++;
            }
        }
        RawLog(line);
    }
    CloseHandle(thread);
    return 0;
}

void Patch_DebugTools_Install(void) {
    if (!ConfigClientPatch("debug_tools", 1)) {
        RawLog("[PATCH] debug_tools disabled");
        return;
    }
    g_debugToolsEnabled = 1;
    LoadBreakpoints();
}

void Patch_DebugTools_StartSampler(void) {
    if (!g_debugToolsEnabled) return;
    if (!g_mainThread && GetFileAttributesA("sample.txt") != INVALID_FILE_ATTRIBUTES) {
        g_mainThread = GetCurrentThreadId();
        CloseHandle(CreateThread(NULL, 0, SamplerThread, NULL, 0, NULL));
    }
}

int Patch_DebugTools_HandleException(PEXCEPTION_POINTERS info) {
    DWORD code;
    CONTEXT* c;
    int i;
    if (!g_debugToolsEnabled) return 0;
    code = info->ExceptionRecord->ExceptionCode;
    c = info->ContextRecord;
    if (code == EXCEPTION_BREAKPOINT) {
        for (i = 0; i < g_bpCount; i++) {
            Breakpoint* bp = &g_bp[i];
            if ((BYTE*)info->ExceptionRecord->ExceptionAddress != bp->addr) continue;
            bp->hits++;
            LogBreakpoint(bp, c);
            WriteCode(bp->addr, bp->orig);
            c->Eip = (DWORD)bp->addr;
            if (bp->hits < bp->max) {
                TlsSetValue(g_rearmTls, bp);
                c->EFlags |= 0x100;
            }
            return 1;
        }
    } else if (code == EXCEPTION_SINGLE_STEP && g_rearmTls != TLS_OUT_OF_INDEXES) {
        Breakpoint* bp = (Breakpoint*)TlsGetValue(g_rearmTls);
        if (bp) {
            TlsSetValue(g_rearmTls, NULL);
            WriteCode(bp->addr, 0xCC);
            return 1;
        }
    }
    return 0;
}
