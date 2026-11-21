/* Patch: Protocol & Handler Diagnostics (diagnostic_hooks)
 * Config: [client] diagnostic_hooks = 1 (default: enabled)
 *
 * Installs build-specific read-only diagnostic hooks (verified before patching):
 *   - TraceWelcome callsite (0x0096B091 -> 0x00A519A0): logs welcome decode status
 *   - OnJoinServerComplete vtable slot (0x00D4FA90): logs join & dumps handler_map.txt
 *   - OnReceiveUserMessage vtable slot (0x00D4FA8C): logs user messages & tracks 2007
 *   - First-chance C++ exception logger after character selection (0xE06D7363)
 */
#include "patches.h"

static volatile LONG g_diagEnabled       = 0;
static void*         orig_join           = NULL;
static void*         orig_user_message   = NULL;
static volatile LONG g_selectionObserved = 0;
static volatile LONG g_selectionThrows   = 0;

static int __cdecl TraceWelcome(void* reader, void* result) {
    int ok = ((int (__cdecl *)(void*, void*))0x00A519A0)(reader, result);
    DWORD* buffer = *((DWORD**)reader + 1);
    RawLogFmt("[GAME] Welcome decoded=%d reader_ok=%d cursor=%d",
              ok, ((BYTE*)reader)[8], buffer ? (int)buffer[4] : -1);
    return ok;
}

static void __cdecl TraceUserEnter(const unsigned char* data, int size) {
    DWORD opcode;
    if (size >= 4 && data && SafeRead((DWORD)data, &opcode, sizeof(opcode)) && opcode == 2007)
        InterlockedExchange(&g_selectionObserved, 1);
    RawLogFmt("[PROUD] OnReceiveUserMessage bytes=%d data=%p", size, data);
    if (data && size > 0) {
        char line[200];
        int len = 0, i;
        for (i = 0; i < size && i < 48; i++)
            len += wsprintfA(line + len, "%02X ", data[i]);
        line[len] = 0;
        RawLog(line);
    }
}

static void __declspec(naked) TraceUserMessage(void) {
    __asm {
        pushfd
        pushad
        push dword ptr [esp + 52]
        push dword ptr [esp + 52]
        call TraceUserEnter
        add esp, 8
        popad
        popfd
        jmp dword ptr [orig_user_message]
    }
}

/* Dump the application handler std::map (0xF45250: opcode -> member fn). */
static void DumpNode(HANDLE out, DWORD node, DWORD head, int depth, int* count) {
    DWORD words[10];
    char line[200];
    DWORD written;
    if (depth > 64 || *count > 4000 || node == head || node == 0) return;
    if (!SafeRead(node, words, sizeof(words))) return;
    if (((BYTE*)words)[0x21] != 0) return; /* _Isnil */
    DumpNode(out, words[0], head, depth + 1, count);
    wsprintfA(line, "%u %08X %08X %08X %08X %08X\r\n",
              words[3], words[4], words[5], words[6], words[7], words[8]);
    WriteFile(out, line, lstrlenA(line), &written, NULL);
    (*count)++;
    DumpNode(out, words[2], head, depth + 1, count);
}

static void DumpHandlerMap(void) {
    DWORD head, root, words[10];
    int count = 0;
    HANDLE out;
    if (!SafeRead(0x00F45254, &head, 4) || !SafeRead(head, words, sizeof(words))) return;
    root = words[1];
    out = CreateFileA("handler_map.txt", GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, 0, NULL);
    if (out == INVALID_HANDLE_VALUE) return;
    DumpNode(out, root, head, 0, &count);
    CloseHandle(out);
    RawLogFmt("[MAP] dumped %d handler entries (head=%08X isnil=%02X)",
              count, head, ((BYTE*)words)[0x21]);
}

static void __cdecl TraceJoinEnter(void* self, int* info) {
    DumpHandlerMap();
    RawLogFmt("[PROUD] OnJoinServerComplete result=%d self=%p", info ? *info : -1, self);
}

static void __declspec(naked) TraceJoin(void) {
    __asm {
        pushfd
        pushad
        push dword ptr [esp + 40]
        push ecx
        call TraceJoinEnter
        add esp, 8
        popad
        popfd
        jmp dword ptr [orig_join]
    }
}

void Patch_DiagnosticHooks_Install(void) {
    BYTE* call;
    void** slot;
    DWORD protect;

    if (!ConfigClientPatch("diagnostic_hooks", 1)) {
        RawLog("[PATCH] diagnostic_hooks disabled");
        return;
    }
    g_diagEnabled = 1;

    call = (BYTE*)0x0096B091;
    if (call[0] == 0xE8 && (DWORD)(call + 5 + *(LONG*)(call + 1)) == 0x00A519A0) {
        if (VirtualProtect(call, 5, PAGE_EXECUTE_READWRITE, &protect)) {
            *(LONG*)(call + 1) = (BYTE*)TraceWelcome - (call + 5);
            VirtualProtect(call, 5, protect, &protect);
            FlushInstructionCache(GetCurrentProcess(), call, 5);
        }
    }

    slot = (void**)0x00D4FA90;
    if (*slot == (void*)0x00A5D880) {
        if (VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &protect)) {
            orig_join = *slot;
            *slot = TraceJoin;
            VirtualProtect(slot, sizeof(*slot), protect, &protect);
        }
    }

    slot = (void**)0x00D4FA8C;
    if (*slot == (void*)0x00A5EFA0) {
        if (VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &protect)) {
            orig_user_message = *slot;
            *slot = TraceUserMessage;
            VirtualProtect(slot, sizeof(*slot), protect, &protect);
        }
    }
    RawLog("[PATCH] diagnostic_hooks installed");
}

int Patch_DiagnosticHooks_HandleException(PEXCEPTION_POINTERS info) {
    DWORD code;
    if (!g_diagEnabled || g_inSafeRead) return 0;
    code = info->ExceptionRecord->ExceptionCode;

    /* Observe first-chance C++ throws after selection without swallowing them. */
    if (code == 0xE06D7363 && g_selectionObserved &&
        InterlockedIncrement(&g_selectionThrows) <= 16) {
        CONTEXT* c = info->ContextRecord;
        EXCEPTION_RECORD* record = info->ExceptionRecord;
        DWORD stack[128];
        RawLogFmt("[CXX selection] eip=%08X esp=%08X object=%08X info=%08X",
                  c->Eip, c->Esp,
                  record->NumberParameters > 1 ? (DWORD)record->ExceptionInformation[1] : 0,
                  record->NumberParameters > 2 ? (DWORD)record->ExceptionInformation[2] : 0);
        if (SafeRead(c->Esp, stack, sizeof(stack))) {
            int found = 0, i;
            for (i = 0; i < 128 && found < 24; i++) {
                if (stack[i] >= 0x00401000 && stack[i] < 0x00C40000) {
                    RawLogFmt("[CXX frame] stack+%X=%08X", i * 4, stack[i]);
                    found++;
                }
            }
        }
    }
    return 0; /* Observe only; never swallow */
}
