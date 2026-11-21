"""Route client JEvents to asynchronous domain handlers."""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from darkblood.core.serialization.jser import WireError


logger = logging.getLogger(__name__)
Handler = Callable[[Any, int, bytes], Awaitable[None]]


def packet_handler(opcode_or_msg):
    """Register an async controller method as the handler for an opcode or WireMessage."""
    opcode = getattr(opcode_or_msg, 'OPCODE', opcode_or_msg)
    if not isinstance(opcode, int):
        raise TypeError(f'packet_handler expects an int opcode or WireMessage class, got {opcode_or_msg!r}')

    def decorator(fn):
        opcodes = getattr(fn, '_packet_opcodes', ())
        fn._packet_opcodes = (*opcodes, opcode)
        return fn

    return decorator


class PacketDispatcher:
    def __init__(self):
        self._handlers: Dict[int, Tuple[Optional[str], Handler]] = {}

    def register_controller(self, controller_type, session_attr: Optional[str] = None):
        for name in dir(controller_type):
            handler = getattr(controller_type, name)
            opcodes = getattr(handler, '_packet_opcodes', None)
            if opcodes is None:
                if name.startswith('on_') and name[3:].isdigit():
                    opcodes = (int(name[3:]),)
                else:
                    continue
            for opcode in opcodes:
                if opcode in self._handlers:
                    _, previous = self._handlers[opcode]
                    if previous is handler:
                        continue
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
