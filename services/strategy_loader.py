"""
LastEdge Trading Engine — Strategy Package Loader & Cryptographic Verifier
services/strategy_loader.py

Verifica e ingesta dinámicamente paquetes de estrategias promovidos desde Strategy Lab
(par de archivos .py + .json). Garantiza que ninguna estrategia con código alterado,
configuración manipulada o interfaz no conforme a BaseStrategy pueda ejecutarse en producción.
"""

from __future__ import annotations

import json
import hashlib
import importlib.util
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Type, List, Union

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyPackageVerifier:
    """Validador criptográfico y estructural de paquetes de estrategias."""

    @staticmethod
    def verify_package(manifest_path: Union[str, Path]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verifica un paquete de estrategia inspeccionando su manifiesto .json y su archivo .py asociado.

        Comprueba:
        1. Existencia y formato JSON válido del manifiesto.
        2. Existencia del archivo de código Python asociado.
        3. Coincidencia exacta bit a bit del SHA-256 del código (code_sha256).
        4. Coincidencia exacta del hash de configuración (config_hash).

        Retorna:
            (is_valid: bool, reason: str, manifest_data: dict)
        """
        m_path = Path(manifest_path)
        if not m_path.exists() or not m_path.is_file():
            return False, f"Manifest file not found: {m_path}", {}

        try:
            with open(m_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            return False, f"Invalid manifest JSON: {e}", {}

        # 1. Campos obligatorios del manifiesto
        required_fields = ["strategy_name", "symbol", "version", "code_sha256"]
        for field in required_fields:
            if field not in manifest or not manifest[field]:
                return False, f"Missing required manifest field: '{field}'", manifest

        # 2. Localizar archivo de código .py
        code_file_name = manifest.get("code_file", f"{m_path.stem}.py")
        code_path = m_path.parent / code_file_name
        if not code_path.exists() or not code_path.is_file():
            return False, f"Strategy code file not found: {code_path}", manifest

        # 3. Verificación criptográfica del código (code_sha256)
        try:
            current_code_sha256 = hashlib.sha256(code_path.read_bytes()).hexdigest()
        except Exception as e:
            return False, f"Error reading code file: {e}", manifest

        registered_code_sha256 = manifest["code_sha256"].strip().lower()
        if current_code_sha256.lower() != registered_code_sha256:
            err_msg = (
                f"Code SHA-256 mismatch for {m_path.stem}! "
                f"Registered: {registered_code_sha256[:12]}..., "
                f"Current on disk: {current_code_sha256[:12]}... (Code was modified post-promotion)"
            )
            logger.error("[StrategyLoader][SECURITY_VIOLATION] %s", err_msg)
            return False, err_msg, manifest

        # 4. Verificación de configuración (config_hash) si está presente
        if "config" in manifest and "config_hash" in manifest and manifest["config_hash"]:
            try:
                config_str = json.dumps(manifest["config"], sort_keys=True)
                current_cfg_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()[:16]
                registered_cfg_hash = str(manifest["config_hash"]).strip().lower()

                if current_cfg_hash.lower() != registered_cfg_hash:
                    err_msg = (
                        f"Config hash mismatch for {m_path.stem}! "
                        f"Registered: {registered_cfg_hash}, Current: {current_cfg_hash}"
                    )
                    logger.error("[StrategyLoader][SECURITY_VIOLATION] %s", err_msg)
                    return False, err_msg, manifest
            except Exception as e:
                return False, f"Error verifying config hash: {e}", manifest

        return True, "OK", manifest


class StrategyLoader:
    """Cargador dinámico de estrategias verificadas."""

    def __init__(self, verifier: Optional[StrategyPackageVerifier] = None):
        self.verifier = verifier or StrategyPackageVerifier()

    def load_strategy_class(self, manifest_path: Union[str, Path]) -> Tuple[Optional[Type[BaseStrategy]], str, Dict[str, Any]]:
        """
        Verifica criptográficamente el paquete y carga la clase de estrategia mediante importlib.

        Retorna:
            (strategy_class, message, manifest)
        """
        is_valid, reason, manifest = self.verifier.verify_package(manifest_path)
        if not is_valid:
            return None, reason, manifest

        m_path = Path(manifest_path)
        code_file_name = manifest.get("code_file", f"{m_path.stem}.py")
        code_path = m_path.parent / code_file_name
        module_name = f"promoted_{m_path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, code_path)
            if spec is None or spec.loader is None:
                return None, f"Failed to create module spec for {code_path}", manifest

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            err_msg = f"Exception executing module {code_path}: {e}"
            logger.error("[StrategyLoader] %s", err_msg)
            return None, err_msg, manifest

        # Buscar la clase de estrategia en el módulo
        target_class_name = manifest.get("strategy_name")
        candidate_class: Optional[Type[BaseStrategy]] = None

        if target_class_name and hasattr(mod, target_class_name):
            attr = getattr(mod, target_class_name)
            if isinstance(attr, type) and issubclass(attr, BaseStrategy) and attr is not BaseStrategy:
                candidate_class = attr

        # Si no se encontró por nombre exacto, buscar cualquier subclase de BaseStrategy
        if candidate_class is None:
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseStrategy) and attr is not BaseStrategy:
                    candidate_class = attr
                    break

        if candidate_class is None:
            return None, f"No compliant BaseStrategy subclass found in {code_path}", manifest

        logger.info(
            "[StrategyLoader] Verified & loaded strategy '%s' from %s (SHA-256: %s)",
            candidate_class.__name__,
            m_path.name,
            manifest["code_sha256"][:12]
        )
        return candidate_class, "OK", manifest


def discover_promoted_strategies(strategies_dir: Optional[Union[str, Path]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Escanea un directorio de estrategias buscando paquetes válidos (*.json con code_sha256).

    Retorna un diccionario indexado por nombre base (e.g. 'eurusd_v1_0_0'):
    {
        'eurusd_v1_0_0': {
            'class': EURUSDPartialStrategy,
            'manifest': {...},
            'manifest_path': Path(...),
            'code_path': Path(...),
            'symbol': 'EURUSD',
            'version': '1.0.0'
        }
    }
    """
    if strategies_dir is None:
        strategies_dir = Path(__file__).parent.parent / "strategies"
    else:
        strategies_dir = Path(strategies_dir)

    if not strategies_dir.exists() or not strategies_dir.is_dir():
        logger.debug("[StrategyLoader] Strategies directory not found: %s", strategies_dir)
        return {}

    loader = StrategyLoader()
    discovered = {}

    for manifest_path in strategies_dir.glob("*.json"):
        # Ignorar archivos que no sean manifiestos de estrategia
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                header = json.load(f)
            if not isinstance(header, dict) or "code_sha256" not in header or "strategy_name" not in header:
                continue
        except Exception:
            continue

        cls, msg, manifest = loader.load_strategy_class(manifest_path)
        if cls is not None:
            base_key = manifest_path.stem.lower()
            code_file = manifest.get("code_file", f"{manifest_path.stem}.py")
            discovered[base_key] = {
                "class": cls,
                "manifest": manifest,
                "manifest_path": manifest_path,
                "code_path": manifest_path.parent / code_file,
                "symbol": manifest.get("symbol", "UNKNOWN").upper(),
                "version": manifest.get("version", "1.0"),
                "strategy_name": manifest.get("strategy_name", cls.__name__),
            }
        else:
            logger.warning("[StrategyLoader] Skipping invalid package %s: %s", manifest_path.name, msg)

    return discovered


def register_promoted_strategies(
    target_registry: Optional[Dict[str, Any]] = None,
    strategies_dir: Optional[Union[str, Path]] = None
) -> int:
    """
    Descubre paquetes promovidos y los registra en el target_registry (o en STRATEGY_REGISTRY por defecto).
    """
    if target_registry is None:
        import strategies
        target_registry = strategies.STRATEGY_REGISTRY

    discovered = discover_promoted_strategies(strategies_dir)
    registered_count = 0

    for base_key, info in discovered.items():
        cls = info["class"]
        symbol = info["symbol"]

        # 1. Registrar por clave base versionada (ej: 'eurusd_v1_0_0')
        target_registry[base_key] = cls
        target_registry[base_key.upper()] = cls

        # 2. Registrar por nombre de estrategia en minúsculas (ej: 'eurusdpartialstrategy')
        strat_name_key = info["strategy_name"].lower()
        target_registry[strat_name_key] = cls

        # 3. Registrar por símbolo si no estaba presente
        if symbol not in target_registry:
            target_registry[symbol] = cls

        # 4. Sincronizar con services.signals.STRATEGY_REGISTRY
        try:
            import services.signals as _signals_svc
            _signals_svc.register_strategy(base_key, cls)
            _signals_svc.register_strategy(strat_name_key, cls)
            if symbol.lower() not in _signals_svc.STRATEGY_REGISTRY:
                _signals_svc.register_strategy(symbol.lower(), cls)
        except Exception as _sig_err:
            logger.debug("[StrategyLoader] Could not sync with services.signals: %s", _sig_err)

        registered_count += 1
        logger.info(
            "[StrategyLoader] Registered promoted strategy '%s' under key '%s'",
            cls.__name__,
            base_key
        )

    return registered_count
