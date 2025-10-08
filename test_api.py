# test_api.py
from binance.client import Client
from binance.exceptions import BinanceAPIException
import config # 기존의 config.py 파일을 사용합니다.

try:
    # 테스트넷 클라이언트 초기화
    client = Client(config.API_KEY, config.SECRET_KEY, testnet=True)
    client.API_URL = 'https://testnet.binancefuture.com/fapi'

    print("바이낸스 테스트넷 서버에 연결을 시도합니다...")

    # 1. 서버 시간 확인으로 기본 연결 테스트
    server_time = client.futures_time()
    print(f"서버 시간 확인 성공: {server_time}")

    print("\n선물 계좌 정보 조회를 시도합니다...")

    # 2. 실제 계좌 정보 조회 테스트
    account_info = client.futures_account()
    print("계좌 정보 조회 성공!")

    usdt_balance = "0.0"
    for asset in account_info['assets']:
        if asset['asset'] == 'USDT':
            usdt_balance = asset['availableBalance']
            break

    print(f"\n[성공] 사용 가능한 USDT 잔고: {usdt_balance}")

except BinanceAPIException as e:
    print(f"\n[API 오류 발생] 코드: {e.code}, 메시지: {e.message}")
except Exception as e:
    print(f"\n[기타 오류 발생] {e}")