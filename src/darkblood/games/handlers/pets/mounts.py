"""Mount / Riding handlers and riding catalog helpers."""
import json
import time

from darkblood import REPO_ROOT
from darkblood.games.network import results
from darkblood.core.hashing import jhash
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network.messages.pets import (
    RidingExpireUpdateAck,
    RidingExpireUpdateReq,
    RidingGetListAck,
    RidingGetListReq,
    RidingInfo,
    RidingRideObjectAck,
    RidingRideObjectReq,
)

_MOUNT_ITEMS_CACHE = None


def _load_mount_items() -> dict:
    """Load Type=38 mount item -> {ride_code, valid_hours} from assets/mount_items.json."""
    global _MOUNT_ITEMS_CACHE
    if _MOUNT_ITEMS_CACHE is None:
        path = REPO_ROOT / 'assets' / 'mount_items.json'
        if path.is_file():
            _MOUNT_ITEMS_CACHE = json.loads(path.read_text(encoding='utf-8'))
        else:
            _MOUNT_ITEMS_CACHE = {}
    return _MOUNT_ITEMS_CACHE


def mount_item_info(code: str):
    """Return (ride_code, valid_hours) for a mount item code, or None."""
    if not code:
        return None
    entry = _load_mount_items().get(code)
    if entry:
        return entry['ride_code'], int(entry.get('valid_hours', 720))
    if code.startswith('ridecall'):
        return code, 720
    return None


def build_ridings_map(char: dict) -> dict:
    """Build {jhash(ride_code): RidingInfo} for 2007, 2435, 2436, 2647."""
    if not char:
        return {}
    now = int(time.time())
    ridings = char.get('ridings', {})
    out = {}
    if isinstance(ridings, dict):
        for ride_code, info in ridings.items():
            if not isinstance(info, dict):
                continue
            expire_ts = int(info.get('expire_ts', 0))
            if expire_ts <= 0:
                remain_sec = 30 * 86400
                expire_ts = now + remain_sec
            else:
                remain_sec = expire_ts - now
                if remain_sec <= 0:
                    continue
            rid = jhash(str(ride_code))
            dyes = [bytes.fromhex(h) for h in info.get('dye_colors', []) if isinstance(h, str)]
            out[rid] = RidingInfo(
                dye_colors=dyes[:2],
                riding_id=rid,
                remain_sec=remain_sec,
                expire_date=expire_ts,
            )
    return out


class MountHandlersMixin:
    """Mounts / Riding (2434, 2437, 2646)."""

    @packet_handler(RidingGetListReq)
    async def handle_riding_get_list(self, correlation, body):
        # eEGS_RIDING_GET_LIST_REQ -> 2435 eEGS_RIDING_GET_LIST_ACK (0x0076C5A0)
        ridings = build_ridings_map(self.current_char())
        await self.reply(
            RidingGetListAck(result=0, ridings=ridings),
            correlation,
            note=f'riding get list ack (count={len(ridings)})',
        )

    @packet_handler(RidingRideObjectReq)
    async def handle_riding_ride_object(self, correlation, body):
        # eEGS_RIDING_RIDE_OBJECT_REQ (0x0079CE00) -> 2438 eEGS_RIDING_RIDE_OBJECT_ACK (0x00753A90)
        req = RidingRideObjectReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(RidingRideObjectAck(result=results.NO_EXIST_CHAR), correlation, note='riding ride object fail (no char)')
            return
        current_mount = char.get('mounted_ride_id', 0)
        new_state = 0 if current_mount == req.ride_object_id else req.ride_object_id
        char['mounted_ride_id'] = new_state
        self.save_char()
        await self.reply(
            RidingRideObjectAck(result=0, ride_object_id=new_state),
            correlation,
            note=f'riding ride object ack (ride_id={new_state})',
        )

    @packet_handler(2646)
    async def handle_riding_expire_update(self, correlation, body):
        # eEGS_RIDING_EXPIRE_UPDATE_REQ (0x007A6530) -> 2647 eEGS_RIDING_EXPIRE_UPDATE_ACK (0x007839F0)
        req = RidingExpireUpdateReq.decode(body)
        char = self.current_char()
        updated = []
        if char is not None and req.item_uid:
            items = char.get('items', [])
            used = next((i for i in items if i.get('uid') == req.item_uid), None)
            if used is not None:
                minfo = mount_item_info(used.get('code', ''))
                if minfo is not None:
                    ride_code, valid_hours = minfo
                    now = int(time.time())
                    ridings = char.setdefault('ridings', {})
                    existing = ridings.get(ride_code, {})
                    base_expire = max(now, int(existing.get('expire_ts', 0)))
                    ridings[ride_code] = {
                        'expire_ts': base_expire + max(1, valid_hours) * 3600,
                        'dye_colors': existing.get('dye_colors', []),
                    }
                    count = int(used.get('count', 1)) - 1
                    if count <= 0:
                        items.remove(used)
                        updated.append(Item(
                            owner=UPDATE_OWNER,
                            uid=0,
                            code='',
                            container=used.get('container', 1),
                            slot=used.get('slot', 0),
                            count=0,
                        ))
                    else:
                        used['count'] = count
                        updated.append(Item(owner=UPDATE_OWNER, **used))
                    self.save_char()
        ridings_map = build_ridings_map(char)
        await self.reply(
            RidingExpireUpdateAck(result=0, ridings=ridings_map, items=updated),
            correlation,
            note=f'riding expire update ack (ride={req.riding_id}, count={len(ridings_map)})',
        )
