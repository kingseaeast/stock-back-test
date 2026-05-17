"""Strategy registry."""

from __future__ import annotations

from .base import Order, Strategy
from .buy_hold import BuyHold
from .dca import DCA

REGISTRY: dict[str, type[Strategy]] = {
    BuyHold.name: BuyHold,
    DCA.name: DCA,
}


def get(name: str) -> type[Strategy]:
    if name not in REGISTRY:
        raise KeyError(
            f"Unknown strategy {name!r}. Available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]


__all__ = ["Order", "Strategy", "REGISTRY", "get"]
