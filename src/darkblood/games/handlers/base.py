"""Shared access to the owning game session."""
from darkblood.core.serialization.jser import event
from darkblood.core.network.proudnet import SQUARE_UID_MASK


class BaseDomainService:
    def __init__(self, session):
        self.session = session

    @property
    def transport(self):
        return self.session.transport

    @property
    def account(self):
        return self.session.account

    @property
    def char_id(self):
        return self.session.char_id

    def current_char(self):
        return self.session.current_char()

    def store(self):
        return self.session.store()

    @staticmethod
    def char_id_from_uid(uid):
        """Character id inside a client UID.

        Peers are announced with the server key (31) in bits 54-58, so the
        client sends e.g. 0x07C0000000000001 for character 1. Live 2026-11-21:
        the unmasked lookup found no player, so no 5051 reached the invitee.
        """
        return int(uid) & SQUARE_UID_MASK if uid and uid > 0 else int(uid or 0)

    def find_char(self, uid):
        """Stored character dict for a client UID (any account), or None."""
        _, char = self.store().get_by_id(self.char_id_from_uid(uid))
        return char

    def save_char(self):
        """Persist only the active character when one is selected, else fall back to full save."""
        if self.session.active_char_id is not None:
            self.store().save_char(self.account, self.session.active_char_id)
        else:
            self.store().save()

    async def reply(self, message, correlation: int = 0, note: str = None, compress: bool = False):
        """Encode a typed WireMessage (using its OPCODE) and send it as a JEvent reply."""
        await self.transport.send_event(
            event(message.OPCODE, message.encode(), correlation, compress=compress),
            note=note,
        )

    @staticmethod
    async def send_to(sessions, packet, note: str = None):
        """Send one event to each session, skipping sessions without a transport or
        whose connection dropped. `packet` is event bytes or a WireMessage (sent
        unsolicited, correlation 0)."""
        if hasattr(packet, 'OPCODE'):
            packet = event(packet.OPCODE, packet.encode())
        for session in sessions:
            transport = getattr(session, 'transport', None)
            if transport is None:
                continue
            try:
                await transport.send_event(packet, note=note)
            except (ConnectionError, OSError):
                pass

    async def send_msg(self, message, note: str = None, compress: bool = False):
        """Encode a typed WireMessage (using its OPCODE) and send it as an unsolicited notice."""
        await self.reply(message, correlation=0, note=note, compress=compress)
