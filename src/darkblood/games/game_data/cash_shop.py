"""Server-owned catalog for offline Cash Shop purchases."""
from functools import lru_cache

from darkblood import DATA


CATALOG_PATH = DATA / 'cash_shop.tsv'
HEADER = 'product_id\titem_code\tquantity'


def parse_catalog(text):
    lines = iter(text.splitlines())
    if next(lines, None) != HEADER:
        raise ValueError(f'expected catalog header {HEADER!r}')
    products = {}
    for line_number, line in enumerate(lines, start=2):
        if not line.strip():
            continue
        try:
            product, code, quantity = line.split('\t')
            product_id, count = int(product), int(quantity)
            if not (0 < product_id <= 0xffffffff and 0 < count <= 0xffff):
                raise ValueError('expected a positive uint32 product ID and uint16 quantity')
            if not code or code.strip() != code:
                raise ValueError('expected an item code without surrounding whitespace')
            if product_id in products:
                raise ValueError(f'duplicate product ID {product_id}')
        except ValueError as exc:
            raise ValueError(f'line {line_number}: {exc}') from exc
        products[product_id] = (code, count)
    if not products:
        raise ValueError('catalog has no products')
    return products


@lru_cache(maxsize=1)
def load_catalog():
    return parse_catalog(CATALOG_PATH.read_text(encoding='utf-8-sig'))
