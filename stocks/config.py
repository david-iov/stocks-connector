"""Configuration loading and typed access."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class IndicatorParams:
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    sma_fast: int = 20
    sma_slow: int = 50
    volume_lookback: int = 20
    volume_spike_mult: float = 1.5


@dataclass
class Weights:
    rsi: float = 1.0
    macd: float = 1.2
    ma_cross: float = 1.0
    trend: float = 0.8
    volume: float = 0.6


@dataclass
class Thresholds:
    strong_buy: float = 1.5
    buy: float = 0.5
    sell: float = -0.5
    strong_sell: float = -1.5


@dataclass
class Config:
    watchlist: list[str] = field(default_factory=list)   # the active, resolved list
    groups: dict[str, list[str]] = field(default_factory=dict)
    default_group: str = "all"
    history_period: str = "6mo"
    interval: str = "1d"
    indicators: IndicatorParams = field(default_factory=IndicatorParams)
    weights: Weights = field(default_factory=Weights)
    thresholds: Thresholds = field(default_factory=Thresholds)

    def resolve_group(self, name: str) -> list[str]:
        """Return the tickers for a named group. 'all' = union of every group."""
        if name == "all":
            seen: dict[str, None] = {}
            for tickers in self.groups.values():
                for t in tickers:
                    seen.setdefault(t, None)
            return list(seen)
        if name not in self.groups:
            raise KeyError(
                f"unknown group {name!r}; available: {', '.join(['all', *self.groups])}"
            )
        return list(self.groups[name])


def load_config(path: str | Path) -> Config:
    """Read a YAML config file into a typed Config, falling back to defaults.

    Supports two layouts:
      * grouped:  `watchlists: {core: [...], quantum: [...]}` + `default_group`
      * flat:     `watchlist: [...]`  (treated as a single group named 'core')
    """
    data = yaml.safe_load(Path(path).read_text()) or {}

    groups: dict[str, list[str]] = {}
    for name, tickers in (data.get("watchlists") or {}).items():
        groups[str(name)] = [str(t).upper() for t in (tickers or [])]
    if data.get("watchlist"):  # legacy flat list
        groups.setdefault("core", [str(t).upper() for t in data["watchlist"]])

    default_group = data.get("default_group", "all")

    cfg = Config(
        groups=groups,
        default_group=default_group,
        history_period=data.get("history_period", "6mo"),
        interval=data.get("interval", "1d"),
        indicators=IndicatorParams(**(data.get("indicators") or {})),
        weights=Weights(**(data.get("weights") or {})),
        thresholds=Thresholds(**(data.get("thresholds") or {})),
    )
    cfg.watchlist = cfg.resolve_group(default_group) if groups else []
    return cfg
