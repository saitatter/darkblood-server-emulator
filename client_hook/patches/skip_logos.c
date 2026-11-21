/* Patch: Skip Start-Up Logos (skip_logos)
 * Config: [client] skip_logos = 0 (default: disabled)
 *
 * JAppStateLogo next-clip (0x006F3950): turns `je` at 0x006F39AB into `jmp`
 * so the logo queue is treated as empty immediately, ending the logo state
 * (0x006F2E10) on startup.
 */
#include "patches.h"

void Patch_SkipLogos_Install(void) {
    static const BYTE expected[] = {0x74, 0x0D}; /* je +0x0D  */
    static const BYTE patched[]  = {0xEB, 0x0D}; /* jmp +0x0D */

    if (!ConfigClientPatch("skip_logos", 0)) {
        RawLog("[PATCH] skip_logos disabled");
        return;
    }
    ApplyBytePatch("skip_logos", 0x006F39AB, expected, patched, sizeof(expected));
}
