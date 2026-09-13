# LastEdge Trading Engine — Strategy Contract & Dynamic Loader

> **Module:** `LastEdge Trading Engine`  
> **Canonical Authoring Authority:** `LastEdge Strategy Lab` (`docs/STRATEGY_CONTRACT.md`)  
> **Source Package:** `strategies/`  

---

## 1. Unified Interface Invariants

Trading Engine strictly executes strategies conforming to the **Canonical Strategy Contract** defined in Strategy Lab. Every strategy is an immutable subclass of `BaseStrategy`:

- **Warmup Invariant:** `metadata.required_history >= 50` bars minimum.
- **Return Type:** `detect_setup(df)` returns a structured dictionary with keys `type`, `entry`, `sl`, `tp`, `context` (or `None`).
- **Zero Business Logic in Engine:** The engine does not invent or alter signals; it strictly executes risk checks and order placement based on the strategy's emitted signals.

---

## 2. Dynamic Strategy Registration & Loading

Strategies promoted from Strategy Lab are placed in `strategies/` as Python files with sidecar `.json` manifests:

```python
import importlib.util
from strategies.base import BaseStrategy

def load_strategy_from_file(filepath: str) -> BaseStrategy:
    spec = importlib.util.spec_from_file_location("promoted_strategy", filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in dir(mod):
        cls = getattr(mod, attr)
        if isinstance(cls, type) and issubclass(cls, BaseStrategy) and cls is not BaseStrategy:
            return cls()
    raise ValueError(f"No BaseStrategy subclass found in {filepath}")
```
