import pyotp
import qrcode

# 1. 고유한 비밀 키 생성 (이 키는 안전하게 보관해야 합니다)
# 16자리 이상의 랜덤한 문자열로 생성됩니다.
secret_key = pyotp.random_base32()

# 2. Google Authenticator에 표시될 정보 설정
user_id = "master"
issuer_name = "Binance Station Alpha" # 앱 이름

# 3. Google Authenticator가 인식할 URI 생성
uri = pyotp.totp.TOTP(secret_key).provisioning_uri(
    name=user_id,
    issuer_name=issuer_name
)

print("--- OTP 설정 정보 ---")
print(f"비밀 키: {secret_key}")
print("이 키는 분실 시 복구가 불가능하니 안전한 곳에 백업하세요.")
print("-" * 20)
print("URI:", uri)
print("-" * 20)

# 4. URI 정보를 QR 코드로 생성하여 이미지 파일로 저장
qr_img = qrcode.make(uri)
qr_img.save("otp_qrcode.png")

print("✅ 'otp_qrcode.png' 파일이 생성되었습니다.")
print("Google Authenticator 앱으로 이 QR 코드를 스캔하여 계정을 추가하세요.")