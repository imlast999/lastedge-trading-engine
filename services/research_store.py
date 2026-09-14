"""
Research Store — services/research_store.py
============================================
Servicio de acceso a la Research Database cuantitativa de LastEdge.
Permite inspeccionar experimentos, trazabilidad y estado de validación científica.
"""

from __future__ import annotations

import os
import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_RESEARCH_DB = os.getenv(
    "RESEARCH_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "LastEdge Strategy Lab",
        "data",
        "research.db",
    ),
)


class ResearchStore:
    """Acceso y consulta a la base de datos de investigaciones cuantitativas."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _DEFAULT_RESEARCH_DB
        self._ensure_db()

    def _ensure_db(self):
        """Verifica que la base de datos o directorio existan."""
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS research_experiments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        experiment_id TEXT UNIQUE,
                        strategy_name TEXT,
                        created_at TEXT,
                        status TEXT DEFAULT 'DRAFT',
                        metrics_json TEXT
                    )
                """)
        except Exception as e:
            logger.debug(f"[ResearchStore] init error: {e}")

    def list_experiments(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        decision_status: Optional[str] = None,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        min_pf: Optional[float] = None,
        min_stability: Optional[float] = None,
        sort_by: str = "created_at",
        order: str = "DESC",
        limit: int = 50,
        offset: int = 0,
        **kwargs,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Lista experimentos registrados en la Research Database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                total = conn.execute("SELECT count(*) FROM research_experiments").fetchone()[0]
                rows = conn.execute(
                    "SELECT * FROM research_experiments ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                experiments = [dict(r) for r in rows]
                return experiments, total
        except Exception as e:
            logger.error(f"[ResearchStore] Error list_experiments: {e}")
            return [], 0


_research_store_instance: Optional[ResearchStore] = None


def get_research_store(db_path: Optional[str] = None) -> ResearchStore:
    global _research_store_instance
    if _research_store_instance is None or db_path is not None:
        _research_store_instance = ResearchStore(db_path)
    return _research_store_instance


__all__ = ["ResearchStore", "get_research_store"]
