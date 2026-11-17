"""Opcode message dispatcher and handler registry.

Replaces Python multiple-inheritance mixins with a composition-based
handler registry designed for seamless porting to C# (IPacketHandler /
PacketDispatcher pattern).
"""
import inspect
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger('darkblood.games.dispatcher')


class PacketDispatcher:
    """Central registry and dispatcher for JEvent wire messages."""

    def __init__(self):
        # opcode -> handler(session, correlation, body) or handler(correlation, body)
        self._handlers: Dict[int, Callable] = {}

    def register(self, opcode: int, handler: Callable, overwrite: bool = False):
        """Register a single opcode handler."""
        if overwrite or opcode not in self._handlers:
            self._handlers[opcode] = handler

    def register_controller(self, controller: Any, overwrite: bool = False):
        """Register all ``on_<opcode>`` methods from a domain controller instance or class."""
        for name in dir(controller):
            if name.startswith('on_') and name[3:].isdigit():
                opcode = int(name[3:])
                method = getattr(controller, name)
                if callable(method):
                    self.register(opcode, method, overwrite=overwrite)

    def get_handler(self, opcode: int) -> Optional[Callable]:
        return self._handlers.get(opcode)

    async def dispatch(self, session: Any, opcode: int, correlation: int, body: bytes) -> bool:
        """Dispatch a message to its registered handler.

        Supports both modern decoupled handlers (taking session) and
        legacy bound handlers (session already bound to self).
        """
        handler = self._handlers.get(opcode)
        if handler is None:
            legacy_attr = getattr(session, f'on_{opcode}', None)
            if legacy_attr and callable(legacy_attr):
                handler = legacy_attr

        if handler is None:
            logger.debug(f'Unhandled event opcode {opcode} (correlation {correlation})')
            session.transport.record('unhandled-event', body, opcode=opcode)
            return False

        try:
            sig = inspect.signature(handler)
            params = list(sig.parameters.values())

            if len(params) == 3:
                if hasattr(handler, '__self__'):
                    res = handler(correlation, body)
                else:
                    res = handler(session, correlation, body)
            elif len(params) == 2:
                res = handler(correlation, body)
            else:
                res = handler(session, correlation, body)
            if inspect.isawaitable(res):
                await res
            return True
        except Exception as e:
            logger.exception(f'Error handling opcode {opcode}: {e}')
            raise


# Global default dispatcher populated with domain handlers
_default_dispatcher: Optional[PacketDispatcher] = None


def get_default_dispatcher() -> PacketDispatcher:
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = PacketDispatcher()
    return _default_dispatcher
