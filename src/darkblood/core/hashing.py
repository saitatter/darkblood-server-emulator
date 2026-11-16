"""JHashString (client 0x00B3B5A0)."""

def jhash(text: str) -> int:
    """JHashString key (0x00B3B5A0 -> 0x00B3AD70).

    DJB2 (seed 5381, h = h * 33 + c) over the UTF-16LE bytes of the string,
    each byte sign-extended. DictMap:LoadSquare (0x0098FD00) keys squares this
    way by their ``SquareID`` string from Data/Dict/maplist.lua.
    """
    h = 5381
    for byte in text.encode('utf-16le'):
        h = (h * 33 + (byte - 256 if byte > 127 else byte)) & 0xffffffff
    return h
