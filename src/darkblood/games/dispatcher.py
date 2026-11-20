"""Route client JEvents to asynchronous domain handlers."""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from darkblood.core.serialization.jser import WireError


logger = logging.getLogger(__name__)
Handler = Callable[[Any, int, bytes], Awaitable[None]]


class PacketDispatcher:
    def __init__(self):
        self._handlers: Dict[int, Tuple[Optional[str], Handler]] = {}

    def register_controller(self, controller_type, session_attr: Optional[str] = None):
        for name in dir(controller_type):
            if not name.startswith('on_') or not name[3:].isdigit():
                continue
            opcode = int(name[3:])
            handler = getattr(controller_type, name)
            if opcode in self._handlers:
                _, previous = self._handlers[opcode]
                raise ValueError(f'Opcode {opcode} registered by {previous.__qualname__} and {handler.__qualname__}')
            self._handlers[opcode] = (session_attr, handler)

    async def dispatch(self, session, opcode: int, correlation: int, body: bytes):
        route = self._handlers.get(opcode)
        if route is None:
            session.transport.record('unhandled-event', body, opcode=opcode)
            return
        session_attr, handler = route
        controller = getattr(session, session_attr) if session_attr else session
        try:
            await handler(controller, correlation, body)
        except WireError as exc:
            # Generated decoders are strict. A body that does not match its
            # schema is recorded and dropped; the connection stays open.
            logger.warning('Malformed opcode %d body (%s): %s', opcode, exc, body.hex())
            session.transport.record('bad-request', body, opcode=opcode, error=str(exc))
        except Exception:
            logger.exception('Error handling opcode %d', opcode)
            raise
