"""Strategy registry."""

from __future__ import annotations

from .base import Order, Strategy
from .buy_hold import BuyHold
from .dca import DCA
from .dca_btd import DCABTD
from .fear_greed import FearGreed
from .rsi import RSI

REGISTRY: dict[str, type[Strategy]] = {
    BuyHold.name: BuyHold,
    DCA.name: DCA,
    DCABTD.name: DCABTD,
    FearGreed.name: FearGreed,
    RSI.name: RSI,
}


def get(name: str) -> type[Strategy]:
    if name not in REGISTRY:
        raise KeyError(
            f"Unknown strategy {name!r}. Available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]


__all__ = ["Order", "Strategy", "REGISTRY", "get"]
