#ifndef DARKBLOOD_PATCHES_H
#define DARKBLOOD_PATCHES_H

#include "../common.h"

/* Core network redirect ([network] host, port, relay_port) */
void Patch_NetworkRedirect_Install(void);

/* Improvements & QoL */
void Patch_BorderlessFullscreen_Install(void);
void Patch_AutoReconnect_Install(void);
int  Patch_AutoReconnect_HandleException(PEXCEPTION_POINTERS info);
void Patch_PeerUpdateInterval_Install(void);
void Patch_CharSlots_Install(void);

/* Hacks & Gameplay */
void Patch_SkipLogos_Install(void);
void Patch_SkipTutorialAlways_Install(void);
void Patch_GmChannel_Install(void);

/* Diagnostics & Dev tools */
void Patch_DiagnosticHooks_Install(void);
int  Patch_DiagnosticHooks_HandleException(PEXCEPTION_POINTERS info);
void Patch_DebugTools_Install(void);
void Patch_DebugTools_StartSampler(void);
int  Patch_DebugTools_HandleException(PEXCEPTION_POINTERS info);

#endif /* DARKBLOOD_PATCHES_H */
