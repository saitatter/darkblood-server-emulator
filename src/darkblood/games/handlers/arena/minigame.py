"""Arena: Rock-paper-scissors minigame (GBB, 2715-2720)."""
from __future__ import annotations

import random
from darkblood.games.network.messages import (
    GbbChallengeAck,
    GbbChallengeReq,
    GbbGiveupAck,
    MinigameGbbStartAck,
)
from darkblood.games.dispatcher import packet_handler


class GbbHandlers:
    # Rock-Paper-Scissors Minigame (GBB: Opcodes 2715 - 2720)

    @packet_handler(2715)
    async def handle_minigame_gbb_start(self, correlation: int, body: bytes):
        """Opcode 2715 (eEGS_MINIGAME_GBB_START_REQ, 0x007A8280) -> 2716."""
        await self.reply(MinigameGbbStartAck(result=0), correlation, note='minigame gbb start ack')

    @packet_handler(2717)
    async def handle_gbb_challenge(self, correlation: int, body: bytes):
        """Opcode 2717 (eEGS_GBB_CHALLENGE_REQ, 0x007A8300) -> 2718."""
        req = GbbChallengeReq.decode(body)
        server_choice = random.randint(0, 2)
        if req.choice == server_choice:
            outcome = 0  # draw
        elif (req.choice - server_choice) % 3 == 1:
            outcome = 1  # win
        else:
            outcome = 2  # lose
        await self.reply(GbbChallengeAck(result=0, server_choice=server_choice, outcome=outcome),
                         correlation, note=f'gbb challenge ack (user={req.choice} srv={server_choice} out={outcome})')

    @packet_handler(2719)
    async def handle_gbb_giveup(self, correlation: int, body: bytes):
        """Opcode 2719 (eEGS_GBB_GIVEUP_REQ, 0x007A83A0) -> 2720."""
        await self.reply(GbbGiveupAck(result=0), correlation, note='gbb giveup ack')
