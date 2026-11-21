"""Shared access to the owning game session."""
from darkblood.core.serialization.jser import event


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

    async def send_msg(self, message, note: str = None, compress: bool = False):
        """Encode a typed WireMessage (using its OPCODE) and send it as an unsolicited notice."""
        await self.reply(message, correlation=0, note=note, compress=compress)
