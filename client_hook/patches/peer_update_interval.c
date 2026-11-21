/* Patch: Faster Town Peer Sync (peer_update_interval)
 * Config: [client] peer_update_interval = 1 (default: enabled)
 *
 * The budgeted P2P sender (0x00966B90) allows one position revision per peer
 * every 2000 ms (add eax, 0x7D0 at 0x00966C9C). Lowering it to 100 ms (0x64)
 * makes town peer movement substantially smoother on loopback/LAN while
 * preserving the per-update peer budget.
 */
#include "patches.h"

void Patch_PeerUpdateInterval_Install(void) {
    static const BYTE expected[] = {0x05, 0xD0, 0x07, 0x00, 0x00}; /* add eax, 2000 */
    static const BYTE patched[]  = {0x05, 0x64, 0x00, 0x00, 0x00}; /* add eax, 100  */

    if (!ConfigClientPatch("peer_update_interval", 1)) {
        RawLog("[PATCH] peer_update_interval disabled");
        return;
    }
    ApplyBytePatch("peer_update_interval", 0x00966C9C, expected, patched, sizeof(expected));
}
