"""Bounded connected low-price blocks; financial evaluation owns selection."""


def cheap_contiguous_blocks(prices: dict[int, float]) -> tuple[tuple[int, int], ...]:
    """Offer connected sublevel sets, never join separated cheap quarters.

    Raising the price threshold grows or merges connected components. At most
    two components per interval are created, rather than every possible pair.
    Protected intervals are absent from prices and therefore hard boundaries.
    """
    blocks: set[tuple[int, int]] = set()
    for ceiling in sorted(set(prices.values())):
        start = end = None
        for index in sorted(i for i, price in prices.items() if price <= ceiling):
            if end is None or index != end + 1:
                if start is not None and end is not None:
                    blocks.add((start, end))
                start = index
            end = index
        if start is not None and end is not None:
            blocks.add((start, end))
    return tuple(sorted(blocks))
