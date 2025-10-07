def calculate_target_price(
    entry_price: float,
    leverage: int,
    target_roi_percent: float,
    position_type: str,
    fee_rate: float = 0.0004  # 바이낸스 선물 Taker 수수료 0.04%를 기본값으로 설정
) -> float:
    """
    레버리지, 목표 수익률, 수수료를 고려하여 목표 가격을 계산합니다.

    Args:
        entry_price (float): 진입 가격
        leverage (int): 레버리지 배율
        target_roi_percent (float): 목표 수익률 (%)
        position_type (str): 포지션 종류 ('long' 또는 'short')
        fee_rate (float, optional): 거래 수수료율. Defaults to 0.0004.

    Returns:
        float: 계산된 목표 가격
    """
    # 퍼센트(%)로 받은 수익률을 소수점(decimal)으로 변환
    target_roi = target_roi_percent / 100.0

    if position_type.lower() == 'long':
        # 롱 포지션 목표 가격 공식 적용
        numerator = entry_price * (1 + (target_roi / leverage) + fee_rate)
        denominator = 1 - fee_rate
        target_price = numerator / denominator
        return target_price
    
    elif position_type.lower() == 'short':
        # 숏 포지션 목표 가격 공식 적용
        numerator = entry_price * (1 - (target_roi / leverage) - fee_rate)
        denominator = 1 + fee_rate
        target_price = numerator / denominator
        return target_price
    
    else:
        # 포지션 타입이 잘못 입력된 경우 오류 발생
        raise ValueError("Position type must be 'long' or 'short'")

# --- 코드 사용 예시 ---
if __name__ == "__main__":
    # 예시 1: 롱 포지션
    long_entry_price = 30000  # BTC 진입 가격: $30,000
    long_leverage = 10        # 레버리지: 10x
    long_roi_target = 20      # 목표 수익률: 20%

    long_target = calculate_target_price(
        entry_price=long_entry_price,
        leverage=long_leverage,
        target_roi_percent=long_roi_target,
        position_type='long'
    )
    
    print("--- 롱 포지션 시뮬레이션 ---")
    print(f"진입 가격: ${long_entry_price:,.2f}")
    print(f"레버리지: {long_leverage}x, 목표 수익률: {long_roi_target}%")
    print(f"▶ 목표 매도(청산) 가격: ${long_target:,.2f}\n")


    # 예시 2: 숏 포지션
    short_entry_price = 30000 # BTC 진입 가격: $30,000
    short_leverage = 20       # 레버리지: 20x
    short_roi_target = 50     # 목표 수익률: 50%

    short_target = calculate_target_price(
        entry_price=short_entry_price,
        leverage=short_leverage,
        target_roi_percent=short_roi_target,
        position_type='short'
    )

    print("--- 숏 포지션 시뮬레이션 ---")
    print(f"진입 가격: ${short_entry_price:,.2f}")
    print(f"레버리지: {short_leverage}x, 목표 수익률: {short_roi_target}%")
    print(f"▶ 목표 매수(청산) 가격: ${short_target:,.2f}")