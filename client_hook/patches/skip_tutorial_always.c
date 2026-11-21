/* Patch: Always Allow Tutorial Skip (skip_tutorial_always)
 * Config: [client] skip_tutorial_always = 0 (default: disabled)
 *
 * JAppStateTutorial Esc (0x006FBC50): the skip dialog normally checks user
 * manager +0x65/+0x66 == 0, which 0x006F8A10 sets only when the character
 * list (2009) already held a character of the class group, preventing a new
 * account's first character from skipping. Replaces `sete bl` at 0x006FBCEE
 * with `mov bl, 1; nop`.
 */
#include "patches.h"

void Patch_SkipTutorialAlways_Install(void) {
    static const BYTE expected[] = {0x0F, 0x94, 0xC3}; /* sete bl       */
    static const BYTE patched[]  = {0xB3, 0x01, 0x90}; /* mov bl, 1;nop */

    if (!ConfigClientPatch("skip_tutorial_always", 0)) {
        RawLog("[PATCH] skip_tutorial_always disabled");
        return;
    }
    ApplyBytePatch("skip_tutorial_always", 0x006FBCEE, expected, patched, sizeof(expected));
}
