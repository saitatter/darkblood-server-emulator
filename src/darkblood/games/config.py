"""Local offline world configuration: server list, channels, slots."""
from darkblood.games.network.messages import ChannelSquare, GameServer


# Experimental local server list (map key -> entry).
OFFLINE_SERVER_ID = 1
SERVERS = [(OFFLINE_SERVER_ID, dict(name='Offline'))]


CHAR_SLOTS = 4  # first u8 of 2009: shown as "4 SLOT" on character select (observed)


SQUARES = [dict(square_id=1, name='Channel 1')]


def db_entry(name, u16=0, u64=0, flag_a=False, flag_b=False, flag_c=True):
    return GameServer(name=name, u16=u16, u64=u64, flag_a=flag_a, flag_b=flag_b, flag_c=flag_c).encode()


def square_entry(square_id, name, a=0, b=100, c=0):
    return ChannelSquare(square_id=square_id, name=name, a=a, load=b, c=c).encode()
