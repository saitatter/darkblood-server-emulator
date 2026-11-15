"""JSerBuffer/JEvent envelope recovered from client 0xA1EB90/0xB35E50."""
import datetime
import struct


def varuint(value):
    if not 0 <= value <= 0xffffffff:
        raise ValueError('JSerBuffer length must fit uint32')
    result = bytearray()
    while value >= 128:
        result.append(value & 127)
        value >>= 7
    result.append(value | 128)
    return bytes(result)


def wide_string(text):
    raw = text.encode('utf-16le')
    return varuint(len(raw)) + raw


def event(opcode, body=b'', correlation=0):
    # Nonempty body includes a compression boolean; empty body omits it.
    return (struct.pack('<IQ', opcode, correlation) + varuint(len(body))
            + (b'\x00' + body if body else b''))


def welcome():
    # 0x96AF60/0xA519A0. Experimental local session defaults, empty feature map.
    now = datetime.datetime.now()
    body = struct.pack('<IQ', 0, 1) + wide_string('OfflinePlayer')
    body += struct.pack('<II???Q', 0, 0, False, False, False, 0)
    body += b'\x17' + varuint(0)
    body += struct.pack('<IIB', 0, 0, 0) + wide_string('')
    body += struct.pack('<6H', now.year, now.month, now.day, now.hour, now.minute, now.second)
    body += struct.pack('<QQH', 0, 0, 0)
    return event(5020, body)
