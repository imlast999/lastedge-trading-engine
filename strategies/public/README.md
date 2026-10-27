# LastEdge Public Benchmark Strategies 🌐

Este directorio contiene las **estrategias públicas de referencia** de LastEdge. Están diseñadas con una arquitectura abierta y pedagógica para permitir que cualquier usuario o desarrollador que clone el repositorio pueda:

1. **Probar el flujo completo de ejecución**: Probar la ingesta de datos, cálculo de indicadores y generación de señales en los 3 activos soportados (`EURUSD`, `XAUUSD`, `BTCEUR`).
2. **Realizar Backtests de Referencia**: Ejecutar simulaciones históricas y walk-forward en el **Strategy Lab** sin requerir acceso a las estrategias propietarias del Vault privado.
3. **Servir como plantilla para nuevas estrategias**: Cada archivo sigue estrictamente el contrato unificado [`BaseStrategy`](../base.py) y [`SignalIntent`](../base.py).

---

## 📊 Estrategias Disponibles

| Estrategia | Par | Timeframe | Lógica Cuantitativa | Indicadores Principales |
| :--- | :---: | :---: | :--- | :--- |
| **`eurusd_public_trend`** | `EURUSD` | `H1` | Seguimiento de tendencia clásico con filtro macro y confirmación de momentum. | Cruce EMA(20/50), Filtro EMA(200), RSI(14) [45-65], ATR(14) |
| **`xauusd_public_breakout`** | `XAUUSD` | `H1` | Ruptura de rango (Donchian Breakout) a favor de la tendencia intermedia. | Canales Donchian(20), Filtro EMA(50), ATR(14) |
| **`btceur_public_momentum`** | `BTCEUR` | `H1` | Momentum y continuación de tendencia adaptado a la volatilidad cripto. | Cruce MACD(12,26,9), Filtro EMA(100), RSI(14), ATR(14) |

---

## 🚀 Cómo Ejecutar Backtests con las Estrategias Públicas

### Desde la API / Strategy Lab:
Las estrategias en `strategies/public/` son descubiertas y registradas automáticamente por `discover_dynamic_strategies()`.
Puedes lanzar un backtest contra cualquiera de ellas enviando un request a:
```http
POST /api/research/backtest
Content-Type: application/json

{
  "strategy": "eurusd_public_trend",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "bars": 1000
}
```

### Desde la App Móvil o Web:
Abre la pestaña **Strategy Lab**, selecciona el símbolo deseado (`EURUSD`, `XAUUSD` o `BTCEUR`) y verás la estrategia pública listada en el selector junto con sus parámetros por defecto listos para optimizar o probar.

---

## 🔒 Separación Open-Core vs Private Vault

LastEdge opera bajo un modelo **Open-Core**:
- **`strategies/public/` (Este directorio)**: Código abierto, lógica canónica, reproducible y documentada.
- **`strategies/vault/` & `strategies/private/`**: Excluidas del control de versiones público (`.gitignore`). Contienen modelos alfa propietarios, optimizaciones multifactoriales, lógica institucional de gestión de liquidez y parámetros de alta frecuencia.
