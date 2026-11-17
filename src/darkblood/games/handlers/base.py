"""Base domain service for composition-based message handlers.

Replaces multiple-inheritance mixins with domain services instantiated per session,
preparing the codebase for a 1:1 C# port (BaseService / IMessageHandler).
"""
from typing import Any


class BaseDomainService:
    """Base class for all domain service handlers.

    Receives GameSession via composition rather than inheritance.
    """

    def __init__(self, session: Any = None):
        self.session = session

    @property
    def transport(self):
        return getattr(self.session, 'transport', None) if self.session else None

    @property
    def account(self):
        return getattr(self.session, 'account', 'OfflinePlayer') if self.session else 'OfflinePlayer'

    @account.setter
    def account(self, value):
        if self.session is not None:
            self.session.account = value

    @property
    def char_id(self):
        return getattr(self.session, 'char_id', 1) if self.session else 1

    @property
    def active_char_id(self):
        return getattr(self.session, 'active_char_id', None) if self.session else None

    @active_char_id.setter
    def active_char_id(self, value):
        if self.session is not None:
            self.session.active_char_id = value

    def current_char(self):
        if self.session and hasattr(self.session, 'current_char'):
            return self.session.current_char()
        return None

    def store(self):
        if self.session and hasattr(self.session, 'store'):
            return self.session.store()
        from darkblood.player_management.store import SqliteCharacterStore
        return SqliteCharacterStore()

    def __getattr__(self, name: str) -> Any:
        session = self.__dict__.get('session')
        if session is not None and hasattr(session, name):
            return getattr(session, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
