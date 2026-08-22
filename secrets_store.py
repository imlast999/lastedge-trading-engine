"""
Módulo para manejo seguro de credenciales MT5 (P3.2 Security)
============================================================
Obtiene la clave de cifrado Fernet prioritariamente desde la variable de entorno MT5_ENCRYPTION_KEY.
Elimina la dependencia insegura de almacenar mt5_key.key en el directorio raíz.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = "mt5_credentials.enc"
KEY_FILE = "mt5_key.key"


def _get_encryption_key() -> bytes:
    """
    Obtiene la clave de encriptación Fernet.
    Prioridad:
    1. Variable de entorno MT5_ENCRYPTION_KEY.
    2. Archivo mt5_key.key (para retrocompatibilidad local).
    3. Genera una nueva clave si no existe ninguna.
    """
    env_key = os.getenv("MT5_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode('utf-8') if isinstance(env_key, str) else env_key

    if os.path.exists(KEY_FILE):
        logger.warning(
            "[SECURITY WARNING] Se está utilizando 'mt5_key.key' desde el disco. "
            "Se recomienda definir MT5_ENCRYPTION_KEY en el entorno .env y eliminar el archivo local."
        )
        with open(KEY_FILE, 'rb') as f:
            return f.read().strip()

    # Si no existe ni env var ni archivo, generar una clave temporal e informar
    new_key = Fernet.generate_key()
    logger.info(f"Nueva clave de encriptación generada. Puedes añadirla a tu .env: MT5_ENCRYPTION_KEY={new_key.decode()}")
    return new_key


def save_credentials(login: int | str, password: str, server: str) -> bool:
    """Guarda las credenciales de MT5 de forma encriptada."""
    try:
        key = _get_encryption_key()
        fernet = Fernet(key)

        credentials = {
            'login': int(login) if str(login).isdigit() else login,
            'password': password,
            'server': server
        }

        encrypted_data = fernet.encrypt(json.dumps(credentials).encode())

        with open(CREDENTIALS_FILE, 'wb') as f:
            f.write(encrypted_data)

        logger.info("Credenciales MT5 guardadas exitosamente de forma encriptada.")
        return True
    except Exception as e:
        logger.error(f"Error guardando credenciales: {e}")
        return False


def load_credentials() -> Optional[Dict[str, Any]]:
    """Carga las credenciales de MT5 desde el archivo encriptado."""
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            return None

        key = _get_encryption_key()
        fernet = Fernet(key)

        with open(CREDENTIALS_FILE, 'rb') as f:
            encrypted_data = f.read()

        decrypted_data = fernet.decrypt(encrypted_data)
        credentials = json.loads(decrypted_data.decode())

        return credentials
    except Exception as e:
        logger.error(f"Error desencriptando credenciales MT5: {e}")
        return None


def clear_credentials() -> bool:
    """Elimina las credenciales almacenadas."""
    try:
        if os.path.exists(CREDENTIALS_FILE):
            os.remove(CREDENTIALS_FILE)
        if os.path.exists(KEY_FILE):
            os.remove(KEY_FILE)
        logger.info("Credenciales eliminadas exitosamente.")
        return True
    except Exception as e:
        logger.error(f"Error eliminando credenciales: {e}")
        return False


def credentials_exist() -> bool:
    """Verifica si existen credenciales guardadas."""
    return os.path.exists(CREDENTIALS_FILE)