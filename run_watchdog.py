"""
LastEdge Trading Engine — MT5 Watchdog Service Runner
run_watchdog.py
"""

import sys
from pathlib import Path

# Add Trading Engine root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.mt5_watchdog import main

if __name__ == "__main__":
    main()
