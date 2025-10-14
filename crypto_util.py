import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _get_key_from_password(password: str) -> bytes:
    """비밀번호로부터 암호화 키를 생성합니다."""
    salt = b'salt_for_api_keys_' # 암호화/복호화에 동일한 솔트 사용
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def encrypt_data(data: str, password: str) -> bytes:
    """주어진 비밀번호를 기반으로 데이터를 암호화합니다."""
    key = _get_key_from_password(password)
    f = Fernet(key)
    return f.encrypt(data.encode())

def decrypt_data(encrypted_data: bytes, password: str) -> str:
    """주어진 비밀번호를 기반으로 데이터를 복호화합니다."""
    key = _get_key_from_password(password)
    f = Fernet(key)
    decrypted_bytes = f.decrypt(encrypted_data)
    return decrypted_bytes.decode('utf-8')