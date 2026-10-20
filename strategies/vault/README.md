# LastEdge Private Strategies Vault

> **Security & IP Protection Notice:**  
> All files inside this directory (`strategies/vault/`) are strictly ignored by Git in the public repository.  
> This directory is designed to hold your proprietary, licensed, or client-specific trading strategies without exposing your alpha to public version control.

---

## 1. How It Works

- **Auto-Discovery:** Whenever the Trading Engine initializes, it dynamically scans `strategies/vault/` for:
  1. Standalone Python strategy files (`*.py`) inheriting from `BaseStrategy`.
  2. Promoted strategy packages (`*.json` manifest sidecars paired with `*.py` code).
- **Symbol Precedence:** Any strategy discovered in this vault automatically overrides the default public strategy for the matching trading symbol (e.g. `XAUUSD`, `EURUSD`, `BTCEUR`).
- **Independent Git Repository:** You can turn this folder into its own standalone, private Git repository:
  ```bash
  cd "c:\LastEdge\LastEdge Trading Engine\strategies\vault"
  git clone <YOUR_PRIVATE_REPO_URL> .
  ```
  Or run the automated synchronization script from the project root:
  ```bash
  .\sync_vault.bat <YOUR_PRIVATE_REPO_URL>
  ```

---

## 2. Creating a Private Strategy

1. Inherit from `BaseStrategy` defined in `strategies.base`.
2. Implement `calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame` and `generate_signal(self, df: pd.DataFrame) -> Signal`.
3. Set your target symbol attribute (e.g. `symbol = "XAUUSD"`).
4. Save the file in this folder (e.g. `strategies/vault/xauusd_proprietary.py`).
5. On the next engine run or reload, it will automatically activate and show:
   ```
   [StrategyVault] Activated proprietary strategy 'XAUUSDProprietary' mapped to symbol 'XAUUSD'
   ```
