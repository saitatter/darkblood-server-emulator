"""Arena: 1v1 town duels (5097-5113)."""
from __future__ import annotations

from darkblood.games.network.messages import (
    DuelRefuseAck,
    DuelRefuseReq,
    DuelRequestAck,
    DuelRequestReq,
    DuelResultAck,
    DuelResultReq,
    DuelStartAck,
    DuelStartNot,
    DuelStartReq,
)
from darkblood.games.dispatcher import packet_handler


class DuelHandlers:
    # 1v1 Town Duels (Opcodes 5097 - 5113)

    @packet_handler(DuelRequestReq)
    async def handle_duel_request(self, correlation: int, body: bytes):
        """Opcode 5100 (eERC_DUEL_REQUEST_REQ) -> 5101 (eERC_DUEL_REQUEST_ACK).

        Client table case: 0x006D2610 -> 0x006C0A10.
        Decodes challenged target UID and delivers duel challenge confirmation.
        """
        req = DuelRequestReq.decode(body)
        self.transport.record('duel-request-req', body, target_uid=req.target_uid)
        ack = DuelRequestAck(
            result=0,
            target_uid=req.target_uid,
            target_name="Challenger",
            char_class=1,
            level=20
        )
        await self.reply(ack, correlation, note=f'duel request ack (target={req.target_uid})')

    @packet_handler(DuelStartReq)
    async def handle_duel_start(self, correlation: int, body: bytes):
        """Opcode 5097 (eERC_DUEL_START_REQ) -> 5098 (eERC_DUEL_START_ACK) & 5099 (DuelStartNot).

        Client table case: 0x006D2610 -> 0x006CBE60.
        Initializes duel combat session between two players and starts countdown.
        """
        req = DuelStartReq.decode(body)
        self.transport.record('duel-start-req', body, opponent_uid=req.opponent_uid)
        from darkblood.core.network.proudnet import relay_address
        from darkblood.games.handlers.skills import learned_skill_map, proficiency_values_for_char
        me = self.current_char() or {}
        opponent = self.find_char(req.opponent_uid) or {}
        ack = DuelStartAck(
            result=0,
            challenger_skills=learned_skill_map(me.get('skills', {})),
            champion_skills=learned_skill_map(opponent.get('skills', {})),
            challenger_proficiency=proficiency_values_for_char(me),
            champion_proficiency=proficiency_values_for_char(opponent),
            challenger_level=min(int(me.get('level', 1)), 0xFF),
            champion_level=min(int(opponent.get('level', 1)), 0xFF),
            relay=relay_address(),
        )
        await self.reply(ack, correlation, note=f'duel start ack (opponent={req.opponent_uid})')
        not_start = DuelStartNot()
        await self.send_msg(not_start, note=f'duel start not (opponent={req.opponent_uid})')

    @packet_handler(DuelResultReq)
    async def handle_duel_result(self, correlation: int, body: bytes):
        """Opcode 5105 (eERC_DUEL_RESULT_REQ) -> 5106 (eERC_DUEL_RESULT_ACK).

        Client table case: 0x006D2610 -> 0x006CC6B0.
        Records duel winner/loser and displays victory/defeat banner.
        """
        req = DuelResultReq.decode(body)
        self.transport.record('duel-result-req', body, winner=req.winner_uid, loser=req.loser_uid)
        ack = DuelResultAck(result=0)
        await self.reply(ack, correlation, note='duel result ack')

    @packet_handler(DuelRefuseReq)
    async def handle_duel_refuse(self, correlation: int, body: bytes):
        """Opcode 5112 (eERC_DUEL_REFUSE_REQ) -> 5113 (eERC_DUEL_REFUSE_ACK).

        Client table case: 0x006D2610 -> 0x006B4120.
        Notifies challenger that the challenge was declined.
        """
        req = DuelRefuseReq.decode(body)
        self.transport.record('duel-refuse-req', body, challenger_uid=req.challenger_uid)
        ack = DuelRefuseAck(
            result=0,
            target_uid=req.challenger_uid,
            target_name="Challenger",
            char_class=1,
            level=20
        )
        await self.reply(ack, correlation, note=f'duel refuse ack (challenger={req.challenger_uid})')
