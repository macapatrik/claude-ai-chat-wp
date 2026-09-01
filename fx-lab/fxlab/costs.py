"""Model obchodnich nakladu.

Naklady se v backtestu ucetne oddeluji od hrubeho P&L. Diky tomu jde
v reportu videt, kolik ze ziskove hrany sezraly poplatky - coz je u
intradenniho FX obvykle to nejdulezitejsi cislo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Naklady na obchod.

    Vsechny hodnoty jsou v USD na 100 000 jednotek (1 standardni lot),
    krome spreadu a slippage, ktere jsou v pipech.

    Pozor: `spread_pips` zadavej jako TYPICKY spread sveho brokera v dobe,
    kdy obchodujes. Spready se v prubehu dne meni radove - v asijske session
    a kolem zprav jsou nekolikanasobne. Pokud mas v datech sloupec `spread`,
    engine pouzije ten a tuhle hodnotu ignoruje.
    """

    spread_pips: float = 1.0
    """Typicky spread. OANDA EURUSD ~1.0-1.3, ECN broker ~0.1-0.3."""

    slippage_pips: float = 0.2
    """Skluz na jedne strane obchodu. U stop prikazu byva vyssi."""

    commission_per_100k: float = 0.0
    """Komise round-turn za 1 lot. OANDA 0, ECN brokeri ~7 USD."""

    swap_long_per_100k: float = -7.0
    """Swap za drzeni long pozice pres noc. Zaporne = plati se."""

    swap_short_per_100k: float = 2.0
    """Swap za drzeni short pozice pres noc."""

    pip_size: float = 0.0001
    """Velikost pipu. 0.0001 pro vetsinu paru, 0.01 pro JPY pary."""

    triple_swap_weekday: int = 2
    """Den, kdy se uctuje trojity swap (0=Po). U vetsiny brokeru streda."""

    def round_trip_cost(self, units: float) -> float:
        """Naklad na kompletni obchod (vstup + vystup) v USD.

        Spread se plati jednou za round-trip, slippage na obou stranach.
        """
        units = abs(units)
        spread_cost = self.spread_pips * self.pip_size * units
        slip_cost = 2.0 * self.slippage_pips * self.pip_size * units
        commission = self.commission_per_100k * units / 100_000.0
        return spread_cost + slip_cost + commission

    def swap_cost(self, units: float, side: str, nights: int = 1) -> float:
        """Naklad za drzeni pozice pres noc v USD. Kladne = naklad."""
        if nights <= 0:
            return 0.0
        rate = self.swap_long_per_100k if side == "long" else self.swap_short_per_100k
        return -rate * abs(units) / 100_000.0 * nights


# Prednastavene profily. Cisla jsou orientacni - over si je u sveho brokera,
# u vetsiny je najdes v sekci "Trading conditions" nebo primo v platforme.

OANDA_EURUSD = CostModel(
    spread_pips=1.2,
    slippage_pips=0.2,
    commission_per_100k=0.0,
    swap_long_per_100k=-8.0,
    swap_short_per_100k=1.5,
)

ECN_EURUSD = CostModel(
    spread_pips=0.2,
    slippage_pips=0.3,
    commission_per_100k=7.0,
    swap_long_per_100k=-8.0,
    swap_short_per_100k=1.5,
)

ZERO_COST = CostModel(
    spread_pips=0.0,
    slippage_pips=0.0,
    commission_per_100k=0.0,
    swap_long_per_100k=0.0,
    swap_short_per_100k=0.0,
)
"""Jen pro testy a pro porovnani "kolik by strategie vydelala bez nakladu"."""
