"""Shared access to the owning game session."""


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
