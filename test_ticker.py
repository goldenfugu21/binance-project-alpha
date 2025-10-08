import asyncio
from binance import AsyncClient, BinanceSocketManager
import json

async def test_futures_ticker(ticker='BTCUSDT'):
    """
    python-binance 라이브러리를 사용해 바이낸스 선물 Ticker 데이터를 수신하는 테스트 스크립트.
    """
    
    # 이 코드는 기본적으로 실제 서버(Live)에 접속합니다.
    print(f"바이낸스 선물 '{ticker}' 실시간 Ticker 데이터 수신을 시도합니다...")
    print("(실제 서버 주소: fstream.binance.com)")

    try:
        # API 키 없이도 Public 데이터 수신은 가능합니다.
        client = await AsyncClient.create()
        bm = BinanceSocketManager(client)
        
        # 선물 Ticker 소켓에 연결
        futures_socket = bm.symbol_ticker_futures_socket(ticker)
        
        async with futures_socket as tscm:
            print("\n[성공] WebSocket 연결이 수립되었습니다.")
            print("5개의 실시간 데이터를 수신한 후 자동으로 종료됩니다...")
            
            for i in range(5):
                res = await tscm.recv()
                print(f"\n--- 데이터 {i+1} 수신 ---")
                # json.dumps를 사용해 보기 좋게 출력
                print(json.dumps(res, indent=2))

    except Exception as e:
        print(f"\n[실패] 오류가 발생했습니다: {e}")
    finally:
        # 클라이언트 세션 종료
        if 'client' in locals() and client:
            await client.close_connection()
            print("\n클라이언트 연결을 종료했습니다.")


if __name__ == "__main__":
    try:
        asyncio.run(test_futures_ticker())
    except KeyboardInterrupt:
        print("\n사용자에 의해 프로그램이 중단되었습니다.")