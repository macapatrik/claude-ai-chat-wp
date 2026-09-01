"""fxlive - ziva exekucni vrstva nad fxlab.

Bot pouziva PRESNE TY SAME objekty strategii jako backtest. Neni tu druha
implementace logiky, kterou by slo rozladit.

Vrstvy:
    broker.py   napojeni na brokera (OANDA / papir)
    risk.py     limity, sizing, vypinaci podminky - ma pravo veta
    state.py    stav prezivajici restart + append-only zaznam
    runner.py   hlavni smycka

Spusteni:
    python3 scripts/run_bot.py --strategy london --dry-run
"""

from .broker import (
    Account, Broker, BrokerError, BrokerPosition, OandaBroker,
    OrderResult, PaperBroker, TransientError,
)
from .risk import Rejected, RiskLimits, RiskManager, RiskState
from .runner import Runner, RunnerConfig
from .state import BotState, Journal, StateStore

__all__ = [
    "Account", "Broker", "BrokerError", "BrokerPosition", "OandaBroker",
    "OrderResult", "PaperBroker", "TransientError",
    "Rejected", "RiskLimits", "RiskManager", "RiskState",
    "Runner", "RunnerConfig",
    "BotState", "Journal", "StateStore",
]
