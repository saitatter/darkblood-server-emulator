/* Patch: Network Redirect (IPv4 connect() hook)
 *
 * Redirects outgoing IPv4 connect() calls to the configured server host and
 * ports from darkblood_options.ini:
 *   [network]
 *   host = 127.0.0.1
 *   port = 9400        (rewrites game connections targeting port 9400)
 *   relay_port = 9401  (rewrites relay connections targeting port 9401)
 *
 * Copies the input sockaddr_in before mutating so caller buffers remain intact,
 * and falls back to 127.0.0.1 if the configured host cannot be resolved.
 */
#include "patches.h"

#define DEFAULT_GAME_PORT  9400
#define DEFAULT_RELAY_PORT 9401

typedef int (WSAAPI *connect_t)(SOCKET, const struct sockaddr*, int);
typedef int (WSAAPI *WSAConnect_t)(SOCKET, const struct sockaddr*, int, LPWSABUF, LPWSABUF, LPQOS, LPQOS);
static connect_t    orig_connect    = NULL;
static WSAConnect_t orig_WSAConnect = NULL;

static char  g_targetHost[128] = "127.0.0.1";
static ULONG g_targetAddr      = 0;
static int   g_gamePort        = DEFAULT_GAME_PORT;
static int   g_relayPort       = DEFAULT_RELAY_PORT;

static ULONG ResolveTargetHost(const char* host) {
    ULONG addr;
    struct hostent* he;
    if (!host || !host[0]) return inet_addr("127.0.0.1");
    addr = inet_addr(host);
    if (addr != INADDR_NONE) return addr;
    he = gethostbyname(host);
    if (he && he->h_addrtype == AF_INET && he->h_addr_list && he->h_addr_list[0]) {
        memcpy(&addr, he->h_addr_list[0], sizeof(addr));
        return addr;
    }
    RawLogFmt("[NET] Failed to resolve host '%s'; falling back to 127.0.0.1", host);
    return inet_addr("127.0.0.1");
}

static void FormatIpv4(ULONG addr, char* out, size_t outSize) {
    const unsigned char* b = (const unsigned char*)&addr;
    if (!out || outSize < 16) return;
    wsprintfA(out, "%u.%u.%u.%u", (unsigned)b[0], (unsigned)b[1], (unsigned)b[2], (unsigned)b[3]);
}

static int RedirectSockAddr(const char* apiName, const struct sockaddr* name, int namelen,
                            struct sockaddr_in* out) {
    char origIp[32], dstIp[32];
    int origPort, dstPort;

    if (namelen < (int)sizeof(struct sockaddr_in)) {
        WSASetLastError(WSAEINVAL);
        return -1;
    }
    *out = *(const struct sockaddr_in*)name;
    FormatIpv4(out->sin_addr.s_addr, origIp, sizeof(origIp));
    origPort = ntohs(out->sin_port);

    if (g_targetAddr == 0) {
        g_targetAddr = ResolveTargetHost(g_targetHost);
    }
    dstPort = origPort;
    if (origPort == DEFAULT_GAME_PORT && g_gamePort > 0 && g_gamePort <= 65535) {
        dstPort = g_gamePort;
    } else if (origPort == DEFAULT_RELAY_PORT && g_relayPort > 0 && g_relayPort <= 65535) {
        dstPort = g_relayPort;
    }

    out->sin_addr.s_addr = g_targetAddr;
    out->sin_port = htons((u_short)dstPort);

    FormatIpv4(g_targetAddr, dstIp, sizeof(dstIp));
    RawLogFmt("[NET] %s() -> %s:%d ==> %s:%d", apiName, origIp, origPort, dstIp, dstPort);
    return 1;
}

static int WSAAPI Hook_connect(SOCKET s, const struct sockaddr* name, int namelen) {
    if (name && name->sa_family == AF_INET) {
        struct sockaddr_in redirected;
        if (RedirectSockAddr("connect", name, namelen, &redirected) < 0) return SOCKET_ERROR;
        return orig_connect ? orig_connect(s, (const struct sockaddr*)&redirected, sizeof(redirected))
                            : SOCKET_ERROR;
    }
    return orig_connect ? orig_connect(s, name, namelen) : SOCKET_ERROR;
}

static int WSAAPI Hook_WSAConnect(SOCKET s, const struct sockaddr* name, int namelen,
                                  LPWSABUF lpCallerData, LPWSABUF lpCalleeData,
                                  LPQOS lpSQOS, LPQOS lpGQOS) {
    if (name && name->sa_family == AF_INET) {
        struct sockaddr_in redirected;
        if (RedirectSockAddr("WSAConnect", name, namelen, &redirected) < 0) return SOCKET_ERROR;
        return orig_WSAConnect ? orig_WSAConnect(s, (const struct sockaddr*)&redirected, sizeof(redirected),
                                                 lpCallerData, lpCalleeData, lpSQOS, lpGQOS)
                               : SOCKET_ERROR;
    }
    return orig_WSAConnect ? orig_WSAConnect(s, name, namelen, lpCallerData, lpCalleeData, lpSQOS, lpGQOS)
                           : SOCKET_ERROR;
}

void Patch_NetworkRedirect_Install(void) {
    HMODULE hWs2;
    if (orig_connect) return;

    ConfigStr("network", "host", "127.0.0.1", g_targetHost, sizeof(g_targetHost));
    g_gamePort  = ConfigInt("network", "port", DEFAULT_GAME_PORT);
    g_relayPort = ConfigInt("network", "relay_port", DEFAULT_RELAY_PORT);
    if (g_gamePort < 1 || g_gamePort > 65535)   g_gamePort = DEFAULT_GAME_PORT;
    if (g_relayPort < 1 || g_relayPort > 65535) g_relayPort = DEFAULT_RELAY_PORT;

    /* Defer DNS resolution until Winsock is initialized by the game, unless it is an IPv4 literal. */
    {
        ULONG literal = inet_addr(g_targetHost);
        g_targetAddr = (literal != INADDR_NONE) ? literal : 0;
    }

    RawLogFmt("[NET] Installing network redirect -> %s (game=%d, relay=%d)",
              g_targetHost, g_gamePort, g_relayPort);
    hWs2 = LoadLibraryA("ws2_32.dll");
    if (hWs2) {
        orig_connect = (connect_t)InstallInlineHook(
            (void*)GetProcAddress(hWs2, "connect"), (void*)Hook_connect);
        orig_WSAConnect = (WSAConnect_t)InstallInlineHook(
            (void*)GetProcAddress(hWs2, "WSAConnect"), (void*)Hook_WSAConnect);
    }
    RawLogFmt("[NET] Network hook setup: connect=%s WSAConnect=%s",
              orig_connect ? "ok" : "fail", orig_WSAConnect ? "ok" : "skip");
}
