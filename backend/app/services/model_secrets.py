from cryptography.fernet import Fernet, InvalidToken

from backend.app.config import get_settings


class ModelSecretError(RuntimeError):
    pass


def encrypt_model_secret(secret: str) -> str:
    value = secret.strip()
    if not value:
        raise ModelSecretError("Model API key cannot be empty.")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_model_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ModelSecretError("Encrypted model API key cannot be decrypted.") from exc


def model_secret_encryption_configured() -> bool:
    return bool((get_settings().model_secret_encryption_key or "").strip())


def _fernet() -> Fernet:
    key = (get_settings().model_secret_encryption_key or "").strip()
    if not key:
        raise ModelSecretError("MODEL_SECRET_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ModelSecretError("MODEL_SECRET_ENCRYPTION_KEY is not a valid Fernet key.") from exc
