# password_util.py

import hashlib
import os

# 비밀번호를 암호화(해싱)하는 함수
def hash_password(password):
    """소금(salt)을 첨가하여 비밀번호를 해싱합니다."""
    salt = os.urandom(32) # 32바이트의 랜덤 솔트 생성
    key = hashlib.pbkdf2_hmac(
        'sha256', # 사용할 해시 알고리즘
        password.encode('utf-8'), # 비밀번호 인코딩
        salt, # 솔트
        100000 # 해싱 반복 횟수
    )
    # 솔트와 키를 합쳐서 저장
    return salt + key

# 입력된 비밀번호가 저장된 해시와 일치하는지 검증하는 함수
def verify_password(stored_password_hash, provided_password):
    """저장된 해시와 입력된 비밀번호를 비교합니다."""
    salt = stored_password_hash[:32] # 저장된 값에서 솔트 추출
    stored_key = stored_password_hash[32:] # 저장된 값에서 키 추출
    # 입력된 비밀번호를 동일한 방식으로 해싱
    new_key = hashlib.pbkdf2_hmac(
        'sha256',
        provided_password.encode('utf-8'),
        salt,
        100000
    )
    # 결과가 일치하는지 확인
    return new_key == stored_key

# --- 이 파일을 직접 실행하여 초기 비밀번호 해시 생성 ---
if __name__ == '__main__':
    # 원하는 비밀번호를 여기에 입력하세요.
    my_password = "Chahdxpfktm12!@!@" 
    hashed = hash_password(my_password)
    
    print("사용할 비밀번호:", my_password)
    print("b'\xfe\xa4\x1d\xd1\xfd\xb4^l\xadC\xf8A\xc6\xaa\xa7x`|\x8f\x1akd\x855E\x92\xb1|JO*\x80\r_Yz\xdbt\x9cF\x89N\x08A\xc2\x13\x0f\xbd[f\x1b|\x06\rm\xe8\x11\xc3\xf2]H\r\x0b\x1d'")
    print(hashed)