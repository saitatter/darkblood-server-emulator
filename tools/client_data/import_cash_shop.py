#!/usr/bin/env python3
"""Provision a local server Cash Shop catalog from an extracted client table."""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from darkblood.games.game_data.cash_shop import CATALOG_PATH, HEADER, parse_catalog
from darkblood.games.game_data.client_dict import data_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=data_root() / 'item_cash.lua',
                        help='extracted item_cash.lua (defaults to the configured client data directory)')
    parser.add_argument('--output', type=Path, default=CATALOG_PATH,
                        help='new TSV file (defaults to the server catalog path)')
    args = parser.parse_args()
    try:
        text = args.source.read_text(encoding='utf-8-sig')
        section = re.search(r'DictCash:LoadProductList\(\{(.*?)\}\),\s*"DictCash:LoadProductList"', text, re.S)
        if section is None:
            raise ValueError('missing DictCash:LoadProductList table')
        entries = re.findall(r'\{([^{}]*)\}', section[1])
        if len(entries) != len(re.findall(r'\bProductID\s*=', section[1])):
            raise ValueError('unexpected layout in product table')
        rows = []
        for entry in entries:
            product = re.search(r'\bProductID\s*=\s*(\d+)\b', entry)
            item = re.search(r'\bItemID\s*=\s*"([^"\n]+)"', entry)
            count = re.search(r'\bItemCount\s*=\s*(\d+)\b', entry)
            if product is None or item is None or count is None:
                raise ValueError(f'incomplete product entry {len(rows) + 1}')
            rows.append((int(product[1]), item[1], int(count[1])))
        catalog = '\n'.join([HEADER] + [f'{p}\t{i}\t{n}' for p, i, n in sorted(rows)]) + '\n'
        parse_catalog(catalog)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(catalog)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Wrote {len(rows)} products to {args.output}')


if __name__ == '__main__':
    main()
