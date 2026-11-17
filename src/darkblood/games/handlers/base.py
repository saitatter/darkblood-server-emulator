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

    @property
    def char_id(self):
        return getattr(self.session, 'char_id', 1) if self.session else 1

    def current_char(self):
        if self.session and hasattr(self.session, 'current_char'):
            return self.session.current_char()
        return None

    def store(self):
        if self.session and hasattr(self.session, 'store'):
            return self.session.store()
        from darkblood.player_management.store import SqliteCharacterStore
        return SqliteCharacterStore()
