# LastEdge — Unified Strategy Contract Specification

> **Shared Specification:** `LastEdge Trading Engine` & `LastEdge Strategy Lab`  
> **Source File:** `strategies/base.py`  

---

## 1. Unified Contract Definition

Both `LastEdge Trading Engine` and `LastEdge Strategy Lab` enforce identical strategy interfaces. A strategy is an immutable Python class inheriting from `BaseStrategy`.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd

@dataclass
class StrategyMetadata:
    required_history: int       # Number of warmup bars required (min 50)
    symbol: str                 # Trading symbol (e.g. 'EURUSD')
    timeframe: str              # Timeframe string (e.g. 'H1')
    strategy_name: str          # Canonical name (e.g. 'eurusd_simple')
    version: str                # Semantic version (e.g. '2.0.0')

class BaseStrategy(ABC):
    @property
    @abstractmethod
    def metadata(self) -> StrategyMetadata:
        """Returns metadata configuration for the strategy."""
        pass

    @property
    def required_history(self) -> int:
        return self.metadata.required_history

    @property
    def symbol(self) -> str:
        return self.metadata.symbol

    @property
    def timeframe(self) -> str:
        return self.metadata.timeframe

    @abstractmethod
    def _get_default_config(self) -> Dict[str, Any]:
        """Returns default configuration parameters."""
        pass

    @abstractmethod
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
        """Calculates indicators and appends columns to df."""
        pass

    @abstractmethod
    def detect_setup(self, df: pd.DataFrame, config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Scans latest bar for entry signals.
        Returns:
            Dict: {'type': 'BUY'|'SELL', 'entry': float, 'sl': float, 'tp': float, 'context': dict}
            None: if no signal is present.
        """
        pass
```

---

## 2. Standardized Return Schema

When `detect_setup(df)` detects a valid trade signal, it returns a dictionary with the following mandatory keys:

```json
{
  "type": "BUY",
  "entry": 1.08500,
  "sl": 1.08100,
  "tp": 1.09300,
  "context": {
    "atr": 0.00267,
    "ema_fast": 1.08450,
    "ema_slow": 1.08200,
    "signal_bar_time": "2026-08-22T16:00:00Z"
  }
}
```

---

## 3. Dynamic Strategy Loading

Trading Engine dynamically loads promoted strategies without code modifications:
```python
import importlib.util

def load_strategy_module(filepath: str) -> BaseStrategy:
    spec = importlib.util.spec_from_file_location("dynamic_strategy", filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Find subclass of BaseStrategy
    for attr in dir(mod):
        cls = getattr(mod, attr)
        if isinstance(cls, type) and issubclass(cls, BaseStrategy) and cls is not BaseStrategy:
            return cls()
    raise ValueError("No BaseStrategy found in " + filepath)
```
