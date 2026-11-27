"""Personal Shop (Player Stalls in town) and Market / Auction House (Broker) Subsystem."""
from dataclasses import dataclass, field
import threading
import time
from typing import Dict, List, Optional, Tuple

from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.player_management.characters import add_gold, add_reward_items, gold_of
from darkblood.games.network.messages import (
    BrokerProduct,
    StallItem,
)


@dataclass
class StallItemData:
    """Stall item offered for sale by a player."""
    item_uid: int
    code: str
    count: int
    price: int
    raw_dict: dict

    def to_wire(self) -> 'StallItem':
        wire_item = Item(owner=UPDATE_OWNER, uid=self.item_uid, code=self.code, count=self.count)
        return StallItem(item=wire_item, price=self.price)


@dataclass
class PersonalStall:
    """Active player stall deployed in town."""
    owner_uid: int
    owner_name: str
    title: str
    items: Dict[int, StallItemData] = field(default_factory=dict)  # item_uid -> StallItemData
    square_id: int = 1
    opened_at: float = field(default_factory=time.time)
    expire_seconds: int = 86400

    def wire_items(self) -> list:
        return [item.to_wire() for item in self.items.values()]


def _persist_chars(store: any, char_ids: List[int]) -> None:
    """Persist only the affected characters atomically when supported by the store."""
    if store is None:
        return
    if hasattr(store, 'get_by_id') and hasattr(store, 'save_chars'):
        pairs = []
        seen = set()
        for cid in char_ids:
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            acc, _ = store.get_by_id(int(cid))
            if acc is not None:
                pairs.append((acc, int(cid)))
        if pairs:
            store.save_chars(pairs)
            return
    store.save()


def _find_char_by_id(store: any, char_id: int) -> Optional[dict]:
    """Resolve a character dict by ID using the store's indexed lookup when available."""
    if hasattr(store, 'get_by_id'):
        _, found = store.get_by_id(int(char_id))
        return found
    return next((c for _, c in store.all_characters() if c.get('id') == char_id), None)


class PersonalShopManager:
    """Singleton managing active personal stalls in town."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.stalls: Dict[int, PersonalStall] = {}  # owner_uid -> PersonalStall
        self.lock = threading.Lock()

    @classmethod
    def get(cls) -> 'PersonalShopManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def open_stall(self, owner_uid: int, owner_name: str, title: str,
                   items_spec: list, char: dict, square_id: int = 1) -> Tuple[bool, str, Optional[PersonalStall]]:
        """Open a personal shop stall.

        items_spec: list of (item_uid, count, price)
        Validates inventory and reserves stall items.
        """
        with self.lock:
            if owner_uid in self.stalls:
                return False, "Stall already open", None

            if not title:
                title = f"{owner_name}'s Stall"

            char_items = char.get('items', [])
            stall_items = {}

            for spec in items_spec:
                if len(spec) >= 3:
                    uid, count, price = spec[0], max(1, spec[1]), max(0, spec[2])
                elif len(spec) == 2:
                    uid, count, price = spec[0], 1, max(0, spec[1])
                else:
                    continue

                inv_item = next((i for i in char_items if i.get('uid') == uid), None)
                if not inv_item:
                    return False, f"Item {uid} not in inventory", None
                if inv_item.get('count', 1) < count:
                    return False, f"Insufficient quantity of item {uid}", None

                # Flag item as listed in stall
                inv_item['in_stall'] = True
                stall_items[uid] = StallItemData(
                    item_uid=uid,
                    code=inv_item.get('code', ''),
                    count=count,
                    price=price,
                    raw_dict=dict(inv_item)
                )

            stall = PersonalStall(
                owner_uid=owner_uid,
                owner_name=owner_name,
                title=title,
                items=stall_items,
                square_id=square_id,
                opened_at=time.time(),
                expire_seconds=86400
            )
            self.stalls[owner_uid] = stall
            return True, "Stall opened", stall

    def get_stall(self, owner_uid: int) -> Optional[PersonalStall]:
        with self.lock:
            return self.stalls.get(owner_uid)

    def get_all_stalls(self, square_id: Optional[int] = None) -> List[PersonalStall]:
        with self.lock:
            if square_id is None:
                return list(self.stalls.values())
            return [s for s in self.stalls.values() if s.square_id == square_id]

    def close_stall(self, owner_uid: int, char: Optional[dict] = None,
                    store: Optional[any] = None) -> Tuple[bool, list]:
        """Close stall and unflag unsold items in owner inventory."""
        with self.lock:
            stall = self.stalls.pop(owner_uid, None)
            if not stall:
                return False, []

            returned_items = []
            if char:
                char_items = char.get('items', [])
                for uid, item_data in stall.items.items():
                    inv_item = next((i for i in char_items if i.get('uid') == uid), None)
                    if inv_item:
                        inv_item.pop('in_stall', None)
                        returned_items.append(inv_item)
                if store:
                    _persist_chars(store, [owner_uid])
            return True, returned_items

    def buy_stall_item(self, buyer_char: dict, seller_uid: int, item_uid: int,
                       count: int, store: any) -> Tuple[bool, str, int, list]:
        """Atomically purchase an item from another player's stall.

        Deducts gold from buyer, credits seller, transfers item.
        Returns: (success, error_message, total_price, buyer_new_items)
        """
        with self.lock:
            stall = self.stalls.get(seller_uid)
            if not stall:
                return False, "Stall not found", 0, []

            stall_item = stall.items.get(item_uid)
            if not stall_item:
                return False, "Item not found in stall", 0, []

            buy_count = min(count, stall_item.count)
            if buy_count <= 0:
                return False, "Invalid purchase count", 0, []

            total_cost = stall_item.price * buy_count
            buyer_gold = gold_of(buyer_char)
            if buyer_gold < total_cost:
                return False, "Insufficient gold", 0, []

            # Locate seller character in store to credit gold and remove item
            seller_char = _find_char_by_id(store, seller_uid)

            if not seller_char:
                return False, "Seller record not found", 0, []

            # 1. Deduct gold from buyer
            buyer_char['gold'] = buyer_gold - total_cost

            # 2. Credit gold to seller
            seller_gold = gold_of(seller_char) + total_cost
            seller_char['gold'] = seller_gold

            # 3. Transfer item to buyer
            item_code = stall_item.code
            new_buyer_items = add_reward_items(buyer_char, [(item_code, buy_count)])

            # 4. Remove/decrement item from seller's inventory
            seller_items = seller_char.get('items', [])
            seller_inv_item = next((i for i in seller_items if i.get('uid') == item_uid), None)
            if seller_inv_item:
                curr_cnt = seller_inv_item.get('count', 1)
                if curr_cnt <= buy_count:
                    seller_items.remove(seller_inv_item)
                else:
                    seller_inv_item['count'] = curr_cnt - buy_count

            # 5. Update stall listing
            if stall_item.count <= buy_count:
                del stall.items[item_uid]
            else:
                stall_item.count -= buy_count

            _persist_chars(store, [buyer_char.get('id'), seller_uid])
            return True, "Success", total_cost, new_buyer_items


# --- Broker (Marketplace / Auction House) ---

@dataclass
class BrokerListing:
    """Individual marketplace listing in the Auction House."""
    listing_id: int
    seller_uid: int
    seller_name: str
    item_uid: int
    code: str
    count: int
    price: int
    period_hours: int
    registered_at: float
    raw_dict: dict

    def to_wire(self) -> 'BrokerProduct':
        wire_item = Item(owner=UPDATE_OWNER, uid=self.item_uid, code=self.code, count=self.count)
        return BrokerProduct(
            item=wire_item,
            price=self.price,
            seller_name=self.seller_name,
            expire_time=max(0, int(self.period_hours * 3600 - (time.time() - self.registered_at))),
            unit_price=self.price // max(1, self.count),
            listing_id=self.listing_id
        )


class BrokerManager:
    """Singleton managing global marketplace listings."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.listings: Dict[int, BrokerListing] = {}  # listing_id -> BrokerListing
        self.next_listing_id: int = 1
        self.price_history: Dict[str, List[int]] = {}  # code -> [prices]
        self.lock = threading.Lock()

    @classmethod
    def get(cls) -> 'BrokerManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register_item(self, char: dict, item_uid: int, count: Optional[int],
                      price: int, period_hours: int, store: any) -> Tuple[bool, str, Optional[BrokerListing]]:
        """Register an item from player inventory into the Broker marketplace."""
        with self.lock:
            items = char.get('items', [])
            target = next((i for i in items if i.get('uid') == item_uid), None)
            if not target:
                return False, "Item not found in inventory", None

            curr_cnt = target.get('count', 1)
            reg_cnt = curr_cnt if count is None else min(count, curr_cnt)
            if reg_cnt <= 0:
                return False, "Invalid count", None

            raw_copy = dict(target)
            # Remove/decrement from inventory
            if curr_cnt <= reg_cnt:
                items.remove(target)
            else:
                target['count'] = curr_cnt - reg_cnt

            lid = self.next_listing_id
            self.next_listing_id += 1

            listing = BrokerListing(
                listing_id=lid,
                seller_uid=char.get('id', 1),
                seller_name=char.get('name', 'Unknown'),
                item_uid=item_uid,
                code=target.get('code', ''),
                count=reg_cnt,
                price=price,
                period_hours=period_hours or 24,
                registered_at=time.time(),
                raw_dict=raw_copy,
            )
            self.listings[lid] = listing

            # Track price history
            self.price_history.setdefault(target.get('code', ''), []).append(price)

            _persist_chars(store, [char.get('id')])
            return True, "Item registered", listing

    def _find_listing(self, key: int) -> Optional[BrokerListing]:
        listing = self.listings.get(key)
        if listing is not None:
            return listing
        return next((entry for entry in self.listings.values() if entry.item_uid == key), None)

    def cancel_listing(self, char: dict, listing_id: int, store: any) -> Tuple[bool, str, list]:
        """Cancel a listing and return item to owner inventory."""
        with self.lock:
            listing = self._find_listing(listing_id)
            if not listing:
                return False, "Listing not found", []

            char_uid = char.get('id', 1)
            if listing.seller_uid != char_uid:
                return False, "Not the seller", []

            # Return item to character inventory
            returned = add_reward_items(char, [(listing.code, listing.count)])
            del self.listings[listing.listing_id]
            _persist_chars(store, [char_uid])
            return True, "Listing cancelled", returned

    def buy_listing(self, buyer_char: dict, listing_id: int,
                    count: Optional[int], store: any) -> Tuple[bool, str, int, list, int]:
        """Purchase an item from the Broker marketplace."""
        with self.lock:
            listing = self._find_listing(listing_id)
            if not listing:
                return False, "Listing not found", 0, [], 0

            buyer_uid = buyer_char.get('id', 1)
            if listing.seller_uid == buyer_uid:
                return False, "Cannot buy own listing", 0, [], 0

            buy_cnt = listing.count if count is None else min(count, listing.count)
            total_price = listing.price * buy_cnt // max(1, listing.count)
            buyer_gold = gold_of(buyer_char)
            if buyer_gold < total_price:
                return False, "Insufficient gold", 0, [], 0

            # Credit seller
            seller_char = _find_char_by_id(store, listing.seller_uid)

            # Deduct buyer gold
            buyer_char['gold'] = buyer_gold - total_price

            if seller_char:
                add_gold(seller_char, total_price)

            # Grant item to buyer
            new_items = add_reward_items(buyer_char, [(listing.code, buy_cnt)])
            bought_uid = listing.item_uid

            # Update/remove listing
            if listing.count <= buy_cnt:
                del self.listings[listing.listing_id]
            else:
                listing.count -= buy_cnt
                listing.price -= total_price

            _persist_chars(store, [buyer_uid, listing.seller_uid])
            return True, "Purchase successful", total_price, new_items, bought_uid

    def get_listings(self, page: int = 0, page_size: int = 20,
                     category: int = 0, filter_name: str = '') -> Tuple[list, int]:
        with self.lock:
            results = list(self.listings.values())
            if filter_name:
                results = [r for r in results if filter_name.lower() in r.code.lower() or filter_name.lower() in r.seller_name.lower()]
            total = len(results)
            start = page * page_size
            end = start + page_size
            return [r.to_wire() for r in results[start:end]], total

    def get_my_listings(self, char_id: int) -> list:
        with self.lock:
            return [r.to_wire() for r in self.listings.values() if r.seller_uid == char_id]

    def get_price_stats(self, code: str) -> Tuple[int, int]:
        with self.lock:
            prices = self.price_history.get(code, [])
            if not prices:
                return 0, 0
            return sum(prices) // len(prices), min(prices)
