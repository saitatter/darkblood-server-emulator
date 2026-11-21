/* Patch: Borderless Fullscreen
 * Config: [client] borderless_fullscreen = 1 (default: enabled)
 *
 * Converts the game's exclusive fullscreen D3D9 requests into a windowed
 * device on a monitor-pinned WS_POPUP window. Windowed mode is untouched.
 * Also honours the legacy exclusive_fullscreen.txt opt-out file next to the exe.
 */
#include "patches.h"

typedef long (__stdcall *CreateDevice_t)(void* self, unsigned int Adapter, unsigned int DeviceType,
                                         void* hFocusWindow, unsigned long BehaviorFlags,
                                         void* pPresentationParameters, void** ppReturnedDeviceInterface);
typedef long (__stdcall *Reset_t)(void* self, void* pPresentationParameters);

typedef struct {
    UINT BackBufferWidth, BackBufferHeight, BackBufferFormat, BackBufferCount;
    UINT MultiSampleType; DWORD MultiSampleQuality; UINT SwapEffect;
    HWND hDeviceWindow; BOOL Windowed; BOOL EnableAutoDepthStencil;
    UINT AutoDepthStencilFormat; DWORD Flags; UINT FullScreen_RefreshRateInHz;
    UINT PresentationInterval;
} PresentParams;

static CreateDevice_t orig_CreateDevice = NULL;
static Reset_t        orig_Reset        = NULL;

static HWND           g_deviceWindow     = NULL;
static int            g_borderless       = -1;
static volatile LONG  g_borderlessActive = 0;
static RECT           g_monitorRect;
static WNDPROC        g_origWndProc      = NULL;
static HWND           g_subclassedWindow = NULL;

static int BorderlessEnabled(void) {
    if (g_borderless < 0) {
        int cfg = ConfigClientPatch("borderless_fullscreen", 1);
        int optOut = (GetFileAttributesA("exclusive_fullscreen.txt") != INVALID_FILE_ATTRIBUTES);
        g_borderless = cfg && !optOut;
    }
    return g_borderless;
}

static LRESULT CALLBACK BorderlessWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (g_borderlessActive) {
        if (msg == WM_WINDOWPOSCHANGING) {
            WINDOWPOS* pos = (WINDOWPOS*)lp;
            pos->x = g_monitorRect.left;
            pos->y = g_monitorRect.top;
            pos->cx = g_monitorRect.right - g_monitorRect.left;
            pos->cy = g_monitorRect.bottom - g_monitorRect.top;
            pos->flags &= ~(SWP_NOMOVE | SWP_NOSIZE);
        } else if (msg == WM_STYLECHANGING && wp == (WPARAM)GWL_STYLE) {
            STYLESTRUCT* st = (STYLESTRUCT*)lp;
            st->styleNew = WS_POPUP | WS_VISIBLE | (st->styleNew & (WS_CLIPSIBLINGS | WS_CLIPCHILDREN));
        }
    }
    return IsWindowUnicode(hwnd) ? CallWindowProcW(g_origWndProc, hwnd, msg, wp, lp)
                                 : CallWindowProcA(g_origWndProc, hwnd, msg, wp, lp);
}

static void SubclassForBorderless(HWND hwnd) {
    if (g_subclassedWindow == hwnd) return;
    g_origWndProc = (WNDPROC)(IsWindowUnicode(hwnd)
        ? SetWindowLongW(hwnd, GWL_WNDPROC, (LONG)BorderlessWndProc)
        : SetWindowLongA(hwnd, GWL_WNDPROC, (LONG)BorderlessWndProc));
    if (g_origWndProc) {
        g_subclassedWindow = hwnd;
        RawLog("[D3D9] borderless: window subclassed");
    }
}

static void ApplyBorderless(PresentParams* pp, HWND focus) {
    HWND hwnd;
    MONITORINFO mi;
    int w, h;
    if (!pp || !BorderlessEnabled()) return;
    if (pp->Windowed) {
        if (g_borderlessActive && ((int)pp->BackBufferWidth != g_monitorRect.right - g_monitorRect.left ||
                                   (int)pp->BackBufferHeight != g_monitorRect.bottom - g_monitorRect.top)) {
            g_borderlessActive = 0;
            RawLogFmt("[D3D9] borderless off: windowed %ux%u requested", pp->BackBufferWidth, pp->BackBufferHeight);
        }
        return;
    }
    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : (focus ? focus : g_deviceWindow);
    if (!hwnd) return;
    g_deviceWindow = hwnd;
    mi.cbSize = sizeof(mi);
    if (!GetMonitorInfoA(MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY), &mi)) return;
    w = mi.rcMonitor.right - mi.rcMonitor.left;
    h = mi.rcMonitor.bottom - mi.rcMonitor.top;
    RawLogFmt("[D3D9] borderless: fullscreen %ux%u -> windowed popup %dx%d",
              pp->BackBufferWidth, pp->BackBufferHeight, w, h);
    g_monitorRect = mi.rcMonitor;
    g_borderlessActive = 1;
    SubclassForBorderless(hwnd);
    SetWindowLongA(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
    SetWindowLongA(hwnd, GWL_EXSTYLE,
                   GetWindowLongA(hwnd, GWL_EXSTYLE) & ~(WS_EX_TOPMOST | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME));
    SetWindowPos(hwnd, HWND_NOTOPMOST, mi.rcMonitor.left, mi.rcMonitor.top, w, h,
                 SWP_FRAMECHANGED | SWP_SHOWWINDOW);
    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;
    pp->BackBufferWidth = w;
    pp->BackBufferHeight = h;
}

static long __stdcall Hook_Reset(void* self, void* pPresentationParameters) {
    ApplyBorderless((PresentParams*)pPresentationParameters, NULL);
    return orig_Reset(self, pPresentationParameters);
}

static void HookDeviceReset(void* device) {
    void** vtbl = *(void***)device;
    DWORD protect;
    if (orig_Reset || !vtbl) return;
    if (VirtualProtect(&vtbl[16], sizeof(void*), PAGE_EXECUTE_READWRITE, &protect)) {
        orig_Reset = (Reset_t)vtbl[16]; /* IDirect3DDevice9::Reset */
        vtbl[16] = (void*)Hook_Reset;
        VirtualProtect(&vtbl[16], sizeof(void*), protect, &protect);
        RawLog("[D3D9] Hooked IDirect3DDevice9::Reset");
    }
}

static long __stdcall Hook_CreateDevice(void* self, unsigned int Adapter, unsigned int DeviceType,
                                        void* hFocusWindow, unsigned long BehaviorFlags,
                                        void* pPresentationParameters, void** ppReturnedDeviceInterface) {
    long hr;
    unsigned long sw_flags;
    RawLogFmt("[D3D9] CreateDevice Adapter=%u Type=%u Flags=0x%08X Focus=%p Windowed=%d %ux%u",
              Adapter, DeviceType, BehaviorFlags, hFocusWindow,
              pPresentationParameters ? ((PresentParams*)pPresentationParameters)->Windowed : -1,
              pPresentationParameters ? ((PresentParams*)pPresentationParameters)->BackBufferWidth : 0,
              pPresentationParameters ? ((PresentParams*)pPresentationParameters)->BackBufferHeight : 0);
    ApplyBorderless((PresentParams*)pPresentationParameters, (HWND)hFocusWindow);

    hr = orig_CreateDevice(self, Adapter, DeviceType, hFocusWindow, BehaviorFlags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK (Adapter %u): hr=0x%08X dev=%p", Adapter, hr, *ppReturnedDeviceInterface);
        HookDeviceReset(*ppReturnedDeviceInterface);
        return hr;
    }
    RawLogFmt("[D3D9] CreateDevice failed (hr=0x%08X); trying Adapter 1...", hr);

    hr = orig_CreateDevice(self, 1, DeviceType, hFocusWindow, BehaviorFlags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK on Adapter 1: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        HookDeviceReset(*ppReturnedDeviceInterface);
        return hr;
    }

    sw_flags = (BehaviorFlags & ~0x44) | 0x20;
    hr = orig_CreateDevice(self, Adapter, DeviceType, hFocusWindow, sw_flags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK with SW VP: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        HookDeviceReset(*ppReturnedDeviceInterface);
        return hr;
    }

    hr = orig_CreateDevice(self, Adapter, 2, hFocusWindow, sw_flags,
                           pPresentationParameters, ppReturnedDeviceInterface);
    if (hr >= 0 && *ppReturnedDeviceInterface) {
        RawLogFmt("[D3D9] CreateDevice OK with D3DDEVTYPE_REF: hr=0x%08X dev=%p", hr, *ppReturnedDeviceInterface);
        HookDeviceReset(*ppReturnedDeviceInterface);
        return hr;
    }

    RawLogFmt("[D3D9] CreateDevice all fallbacks failed: hr=0x%08X", hr);
    return hr;
}

void Patch_BorderlessFullscreen_Install(void) {
    typedef void* (__stdcall *Create9_t)(unsigned int);
    HMODULE d3d9;
    Create9_t create;
    void* d3d;
    void** vtbl;
    DWORD protect;

    if (!BorderlessEnabled()) {
        RawLog("[PATCH] borderless_fullscreen disabled");
        return;
    }
    d3d9 = LoadLibraryA("d3d9.dll");
    create = d3d9 ? (Create9_t)GetProcAddress(d3d9, "Direct3DCreate9") : NULL;
    d3d = create ? create(32) : NULL; /* D3D_SDK_VERSION */
    if (!d3d) {
        RawLog("[D3D9] borderless: no IDirect3D9; hook skipped");
        return;
    }
    vtbl = *(void***)d3d;
    if (vtbl[16] != (void*)Hook_CreateDevice &&
        VirtualProtect(&vtbl[16], sizeof(void*), PAGE_EXECUTE_READWRITE, &protect)) {
        orig_CreateDevice = (CreateDevice_t)vtbl[16];
        vtbl[16] = (void*)Hook_CreateDevice;
        VirtualProtect(&vtbl[16], sizeof(void*), protect, &protect);
        RawLog("[D3D9] borderless: CreateDevice vtable hook installed");
    }
    ((unsigned long (__stdcall*)(void*))vtbl[2])(d3d); /* Release */
}
