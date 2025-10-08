import asyncio
import websockets
import json

async def test_binance_websocket():
    # --- 테스트하고 싶은 주소의 주석을 해제하고 사용하세요 ---
    
    # 1. 실제 서버 주소
    # uri = "wss://fstream.binance.com/ws/btcusdt@depth5@1000ms"
    
    # 2. 테스트넷 서버 주소
    uri = "wss://stream.binancefuture.com/ws/btcusdt@depth5@1000ms"
    
    print(f"'{uri}' 주소로 연결을 시도합니다...")

    try:
        async with websockets.connect(uri) as websocket:
            print("WebSocket 연결 성공!")
            print("실시간 데이터를 수신합니다... (Ctrl+C로 종료)")
            
            # 5개의 메시지만 받고 종료 (무한 루프 방지)
            for i in range(5):
                message = await websocket.recv()
                print("\n[데이터 수신 성공]")
                # 받은 데이터(JSON)를 보기 좋게 출력
                print(json.dumps(json.loads(message), indent=2))

    except Exception as e:
        print(f"\n[연결 실패] 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    asyncio.run(test_binance_websocket())