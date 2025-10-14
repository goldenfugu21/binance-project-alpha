# api_key_encryptor.py

import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import getpass

# 암호화 함수
def encrypt_data(data: str, password: str) -> bytes:
    """주어진 비밀번호를 기반으로 데이터를 암호화합니다."""
    salt = b'salt_for_api_keys_' # 고정된 솔트 (실제로는 랜덤 생성 후 저장해야 더 안전)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    # 비밀번호로부터 암호화 키 생성
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    # 데이터를 암호화
    return f.encrypt(data.encode())

if __name__ == '__main__':
    print("--- API 키 암호화 유틸리티 ---")
    
    # 보안을 위해 비밀번호 입력 시 보이지 않도록 처리
    login_password = getpass.getpass("API 키를 암호화할 때 사용할 로그인 비밀번호를 입력하세요: ")
    api_key = input("암호화할 API 키를 입력하세요: ")

    encrypted_api_key = encrypt_data(api_key, login_password)

    print("\n" + "="*50)
    print("암호화가 완료되었습니다.")
    print("이 암호화된 값을 복사하여 환경 변수에 저장하세요.")
    print(f"환경 변수 이름 예시: ENC_BINANCE_API_KEY")
    print("\n암호화된 값:")
    # 문자열로 변환하여 출력
    print(encrypted_api_key.decode('utf-8'))
    print("="*50)