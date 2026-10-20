"""Only this vault handles encrypted credential material; no plaintext serialization."""

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from .config import settings
from .services import fail


class CredentialVault:
    @staticmethod
    def cipher():
        key = settings.llm_encryption_key.get_secret_value()
        if not key and settings.llm_encryption_key_file:
            try:
                path = Path(settings.llm_encryption_key_file)
                if path.stat().st_mode & 0o077:
                    fail(
                        503, "LLM_MASTER_KEY_PERMISSIONS", "加密主密钥文件须仅服务账号可读（0600）"
                    )
                key = path.read_text().strip()
            except OSError:
                fail(503, "LLM_MASTER_KEY_UNAVAILABLE", "无法读取部署提供的加密主密钥")
        if not key:
            fail(
                503,
                "LLM_MASTER_KEY_MISSING",
                "尚未部署密钥加密主密钥，请由运维配置环境变量或受控密钥文件",
            )
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            fail(503, "LLM_MASTER_KEY_INVALID", "加密主密钥格式无效")

    @classmethod
    def encrypt(cls, key: SecretStr):
        return cls.cipher().encrypt(key.get_secret_value().encode()).decode()

    @classmethod
    def decrypt(cls, ciphertext):
        if not ciphertext:
            fail(409, "LLM_CREDENTIAL_MISSING", "未配置 API Key，无法测试或调用")
        try:
            return SecretStr(cls.cipher().decrypt(ciphertext.encode()).decode())
        except (InvalidToken, UnicodeError):
            fail(
                503, "LLM_CREDENTIAL_DECRYPT_FAILED", "密钥解密失败，请核对部署主密钥或重新配置凭据"
            )
