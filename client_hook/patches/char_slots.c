/* Patch: 14 Character Slots Counter Display (char_slots_14)
 * Config: [client] char_slots_14 = 1 (default: enabled)
 *
 * The client natively supports multi-page character select (6 models per page,
 * page arrows in 0x006DC220, page switcher in 0x006F1CC0) and reads the account
 * slot limit from opcode 2009 (stored in 0x00F23330). Only the "X / 6" counter
 * formatter at 0x006DD5E0 hardcodes `push 6` (0x006DD64A: 6A 06).
 * Patching 6A 06 -> 6A 0E updates the display to "X / 14" (one per subclass).
 */
#include "patches.h"

void Patch_CharSlots_Install(void) {
    static const BYTE expected[] = {0x6A, 0x06}; /* push 6  */
    static const BYTE patched[]  = {0x6A, 0x0E}; /* push 14 */

    if (!ConfigClientPatch("char_slots_14", 1)) {
        RawLog("[PATCH] char_slots_14 disabled");
        return;
    }
    ApplyBytePatch("char_slots_14", 0x006DD64A, expected, patched, sizeof(expected));
}
