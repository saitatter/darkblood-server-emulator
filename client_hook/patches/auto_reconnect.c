/* Patch: Auto-Reconnect (Return to Server List on Disconnect)
 * Config: [client] auto_reconnect = 1 (default: enabled)
 *
 * Hooks Lua_ExitGame (0x007381E0) and JLobbyCommon::Login (0x00749EE0) so that
 * confirming MB_DisconnectFromServer releases the stale NetClient, forgets
 * stale remote/local JUsers, resets the local character UID to -1, retries
 * Login, and fades back to eAS_Lobby instead of closing the client.
 *
 * Also handles the two verified post-reconnect null-lookup VEH recovery sites
 * (world-map refresh 0x0059C161/0x0059C173 and stale peer model 0x0076F98D).
 */
#include "patches.h"

#define EXITGAME_VA      0x007381E0
#define DISCONNECT_SHOWN 0x00F45204
#define INPUT_LOCK       0x00F36544
#define LOGIN_VA         0x00749EE0
#define LOGIN_FLAGS      0x00F2EE98 /* +8, +9, +10 of 0x00F2EE90 */
#define NET_CONNECTED    0x00F29AE8
#define NETUSERMGR       0x00F2EE90

static volatile LONG g_autoReconnectEnabled = 0;
static BYTE*         g_exitTrampoline       = NULL;
static BYTE*         g_loginTrampoline      = NULL;
static wchar_t       g_loginId[64];
static const char    g_toLobby[] = "g_jAppStateMgr:ChangeState(eAS_Lobby)";

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
        push dword ptr [esp + 0x24] /* first argument (after pushad + ret) */
        call RecordLoginId
        add esp, 4
        popad
        jmp dword ptr [g_loginTrampoline]
    }
}

static void ReleaseNetClient(void) {
    volatile BYTE* net = (volatile BYTE*)NET_CONNECTED;
    RawLogFmt("[RECONNECT] releasing NetClient; net flags %d %d %d", net[0], net[1], net[2]);
    __asm {
        mov eax, 0x004065F0
        call eax /* JUserClient singleton */
        mov ecx, eax
        mov eax, 0x00A5CF50
        call eax /* thiscall release, no args */
    }
}

static void CallLogin(void) {
    const wchar_t* id = g_loginId;
    ReleaseNetClient();
    __asm {
        push id
        mov eax, 0x00456CE0
        call eax /* JLobbyCommon singleton (argument stays for Login) */
        mov ecx, eax
        mov eax, LOGIN_VA
        call eax /* thiscall Login(id), ret 4 */
    }
}

static void FadeToLobby(void) {
    __asm {
        mov eax, 0x00406700
        call eax /* fade/UI singleton */
        mov ecx, eax
        push 0   /* float 0.0 */
        push offset g_toLobby
        mov eax, 0x00AD6BA0
        call eax /* thiscall FadeOut(cmd, time), ret 8 */
    }
}

static void ShowDisconnectBox(void) {
    static const char name[] = "MB_DisconnectFromServer";
    __asm {
        push offset name
        mov eax, 0x00AF57A0
        call eax /* cdecl open dialog by name (as 0x00786ADF) */
        add esp, 4
    }
}

static void ResetLocalUserUid(void) {
    DWORD holder = 0, user = 0, uid[2] = {0, 0};
    if (!SafeRead(NETUSERMGR + 0x78, &holder, 4) || !holder) return;
    if (!SafeRead(holder, &user, 4) || !user) return;
    if (!SafeRead(user + 0x10, uid, 8)) return;
    RawLogFmt("[RECONNECT] local user %08X uid %08X:%08X -> -1", user, uid[1], uid[0]);
    ((volatile DWORD*)(user + 0x10))[0] = 0xFFFFFFFF;
    ((volatile DWORD*)(user + 0x10))[1] = 0xFFFFFFFF;
}

static void __stdcall RemoveUser(DWORD lo, DWORD hi) {
    __asm {
        mov eax, 0x0043A180
        call eax /* user manager singleton */
        mov ecx, eax
        push hi
        push lo
        mov eax, 0x009662E0
        call eax
    }
}

static void ForgetRemoteUsers(void) {
    DWORD holder = 0, self = 0, selfUid[2] = {0, 0}, map = 0, head = 0, node = 0;
    DWORD uids[64][2];
    int count = 0, steps = 0, i;
    BYTE nil = 1;
    if (SafeRead(NETUSERMGR + 0x78, &holder, 4) && holder && SafeRead(holder, &self, 4) && self)
        SafeRead(self + 0x10, selfUid, 8);
    {
        DWORD category = 4, mgr;
        __asm {
            mov eax, 0x0043A180
            call eax
            mov mgr, eax
        }
        mgr += 0x9C;
        __asm {
            lea eax, category
            push eax
            mov ecx, mgr
            mov eax, 0x00965A80
            call eax
            mov map, eax
        }
    }
    if (!map || !SafeRead(map + 4, &head, 4) || !head || !SafeRead(head, &node, 4)) return;
    while (node && node != head && count < 64 && steps++ < 1024) {
        DWORD key[2], next = 0, left = 0, parent = 0;
        if (!SafeRead(node + 0x21, &nil, 1) || nil) break;
        if (!SafeRead(node + 0x10, key, 8)) break;
        uids[count][0] = key[0];
        uids[count][1] = key[1];
        count++;
        if (!SafeRead(node + 8, &next, 4)) break;
        if (SafeRead(next + 0x21, &nil, 1) && !nil) {
            while (SafeRead(next, &left, 4) && SafeRead(left + 0x21, &nil, 1) && !nil) next = left;
            node = next;
        } else {
            DWORD right = 0;
            if (!SafeRead(node + 4, &parent, 4)) break;
            while (SafeRead(parent + 0x21, &nil, 1) && !nil &&
                   SafeRead(parent + 8, &right, 4) && right == node) {
                node = parent;
                if (!SafeRead(node + 4, &parent, 4)) break;
            }
            node = parent;
        }
    }
    for (i = 0; i < count; i++) {
        RawLogFmt("[RECONNECT] user map entry %08X:%08X%s", uids[i][1], uids[i][0],
                  uids[i][0] == selfUid[0] && uids[i][1] == selfUid[1] ? " (local)" : "");
        RemoveUser(uids[i][0], uids[i][1]);
    }
    RawLogFmt("[RECONNECT] removed %d user(s) from the user map", count);
}

static int __cdecl ReturnToLobbyIfDisconnected(void) {
    volatile BYTE* flags = (volatile BYTE*)LOGIN_FLAGS;
    if (*(volatile BYTE*)DISCONNECT_SHOWN != 1) return 0;
    *(volatile BYTE*)DISCONNECT_SHOWN = 0;
    *(volatile BYTE*)INPUT_LOCK = 0;
    RawLogFmt("[RECONNECT] ExitGame after disconnect; login flags %d %d %d",
              flags[0], flags[1], flags[2]);
    if (!g_loginTrampoline || !g_loginId[0]) return 0; /* fall back to exiting */
    flags[1] = 0;
    flags[2] = 0;
    CallLogin();
    RawLogFmt("[RECONNECT] Login returned; flags %d %d %d", flags[0], flags[1], flags[2]);
    if (!flags[1]) {
        *(volatile BYTE*)DISCONNECT_SHOWN = 1;
        *(volatile BYTE*)INPUT_LOCK = 1;
        ShowDisconnectBox();
        RawLog("[RECONNECT] server unreachable; disconnect box reopened");
        return 1;
    }
    ForgetRemoteUsers();
    ResetLocalUserUid();
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

static void InstallExitGameHook(void) {
    /* push 0; push 0; push 2; call 0x004488D0 -- position-independent pushes. */
    static const BYTE expected[] = {0x6A, 0x00, 0x6A, 0x00, 0x6A, 0x02, 0xE8};
    BYTE* target = (BYTE*)EXITGAME_VA;
    DWORD protect;
    if (memcmp(target, expected, sizeof(expected))) {
        RawLog("[RECONNECT] ExitGame prologue mismatch; hook refused");
        return;
    }
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
    FlushInstructionCache(GetCurrentProcess(), g_exitTrampoline, 11);
    RawLog("[RECONNECT] ExitGame hook installed");
}

void Patch_AutoReconnect_Install(void) {
    if (!ConfigClientPatch("auto_reconnect", 1)) {
        RawLog("[PATCH] auto_reconnect disabled");
        return;
    }
    g_autoReconnectEnabled = 1;
    InstallExitGameHook();
    g_loginTrampoline = HookPushPushPrologue(LOGIN_VA, 0x00BFC409, Hook_Login, "Login");
}

int Patch_AutoReconnect_HandleException(PEXCEPTION_POINTERS info) {
    DWORD code;
    BYTE* addr;
    if (!g_autoReconnectEnabled || g_inSafeRead) return 0;
    code = info->ExceptionRecord->ExceptionCode;
    addr = (BYTE*)info->ExceptionRecord->ExceptionAddress;

    /* World-map page refresh after reconnect (0x0059C161 / 0x0059C173). */
    if (code == EXCEPTION_ACCESS_VIOLATION &&
        (addr == (BYTE*)0x0059C161 || addr == (BYTE*)0x0059C173) &&
        info->ContextRecord->Eax == 0 && addr[0] == 0x8B && (addr[2] == 0xF8 || addr[2] == 0xFC)) {
        info->ContextRecord->Eip = 0x0059C2F4;
        RawLogFmt("[RECOVER] world-map null lookup at %p: map refresh skipped", addr);
        return 1;
    }

    /* Stale peer model lookup after reconnect (0x0076F98D). */
    if (code == EXCEPTION_ACCESS_VIOLATION && addr == (BYTE*)0x0076F98D &&
        info->ContextRecord->Edi == 0 && addr[0] == 0x8B && addr[1] == 0x07) {
        static LONG hits = 0;
        info->ContextRecord->Eip = 0x0076FA74;
        if (InterlockedIncrement(&hits) <= 3)
            RawLog("[RECOVER] stale peer model lookup at 0076F98D skipped");
        return 1;
    }
    return 0;
}
