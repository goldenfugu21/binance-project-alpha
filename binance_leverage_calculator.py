import sys
import asyncio
import websockets
import json
import math
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox, QGroupBox
)
from PyQt5.QtGui import QFont, QDoubleValidator
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QThread

from binance.client import Client
from binance.exceptions import BinanceAPIException
import config

# --- (WebSocket 워커, 핵심 계산 로직은 변경 없음) ---
class BinanceWorker(QObject):
    data_received = pyqtSignal(dict)
    connection_error = pyqtSignal(str)
    def __init__(self, symbol):
        super().__init__(); self.symbol = symbol.lower(); self.running = False
        self.websocket_uri = f"wss://stream.binance.com:9443/ws/{self.symbol}@depth5@100ms"
    def run(self):
        self.running = True; asyncio.run(self.connect_and_listen())
    async def connect_and_listen(self):
        try:
            async with websockets.connect(self.websocket_uri) as websocket:
                while self.running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        self.data_received.emit(json.loads(message))
                    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                        print(f"{self.symbol} WebSocket 연결 문제 발생, 재연결 시도..."); break
        except Exception as e: self.connection_error.emit(f"WebSocket 연결 실패: {e}")
    def stop(self): self.running = False

def calculate_target_price(
    entry_price: float, leverage: int, target_roi_percent: float, position_type: str, fee_rate: float = 0.0004
) -> float:
    target_roi = target_roi_percent / 100.0
    if position_type.lower() == 'long':
        return entry_price * (1 + (target_roi / leverage) + fee_rate) / (1 - fee_rate)
    elif position_type.lower() == 'short':
        return entry_price * (1 - (target_roi / leverage) - fee_rate) / (1 + fee_rate)
    raise ValueError("Position type must be 'long' or 'short'")

# --- GUI 애플리케이션 클래스 정의 ---
class BinanceCalculatorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Binance 레버리지 목표 가격 계산기 (Testnet Mode)")
        self.setGeometry(100, 100, 800, 600)
        
        try:
            self.client = Client(config.API_KEY, config.SECRET_KEY, testnet=True)
            self.client.API_URL = 'https://testnet.binancefuture.com/fapi'; self.client.futures_ping()
            print("바이낸스 테스트넷 클라이언트 초기화 성공.")
        except Exception as e:
            QMessageBox.critical(self, "API 연결 실패", f"API 키 또는 연결을 확인해주세요.\n오류: {e}"); sys.exit()

        self.current_selected_symbol = "BTCUSDT"; self.position_type = None
        self.worker_thread = None; self.worker = None; self.available_balance = 0.0
        self.best_ask_price = 0.0; self.best_bid_price = 0.0
        self.symbol_info = {}; self.tick_size = 0.0

        self.initUI()
        self.start_worker(); self.update_asset_balance(); self.fetch_symbol_info()

    def initUI(self):
        main_layout = QHBoxLayout()
        left_panel_layout = QVBoxLayout(); left_panel_layout.setAlignment(Qt.AlignTop)
        label_font = QFont("Arial", 10); input_font = QFont("Arial", 10); result_font = QFont("Arial", 14, QFont.Bold); button_font = QFont("Arial", 10, QFont.Bold)
        
        asset_group_box = QGroupBox("자산 현황 (USDT)"); asset_layout = QVBoxLayout()
        self.balance_label = QLabel("사용 가능: $0.00", self); self.balance_label.setFont(QFont("Arial", 11, QFont.Bold))
        asset_layout.addWidget(self.balance_label); asset_group_box.setLayout(asset_layout); left_panel_layout.addWidget(asset_group_box)

        symbol_group_box = QGroupBox("거래 종목 선택"); symbol_layout = QVBoxLayout()
        self.symbol_combo = QComboBox(self); self.symbol_combo.setFont(input_font)
        self.symbol_combo.addItem("BTCUSDT"); self.symbol_combo.addItem("ETHUSDT"); self.symbol_combo.addItem("BNBUSDT")
        self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        symbol_layout.addWidget(self.symbol_combo); symbol_group_box.setLayout(symbol_layout); left_panel_layout.addWidget(symbol_group_box)

        input_group_box = QGroupBox("거래 정보 입력"); input_form_layout = QVBoxLayout()
        
        entry_price_layout = QHBoxLayout(); entry_price_label = QLabel("기준 가격:")
        self.entry_price_input = QLineEdit(self); self.entry_price_input.setValidator(QDoubleValidator(0.0, 1e9, 8)); self.entry_price_input.setText("0.00")
        self.entry_price_input.textChanged.connect(self.calculate_and_display_target)
        entry_price_layout.addWidget(entry_price_label); entry_price_layout.addWidget(self.entry_price_input); input_form_layout.addLayout(entry_price_layout)

        leverage_layout = QHBoxLayout(); leverage_label = QLabel("레버리지 (x):")
        self.leverage_input = QLineEdit(self); self.leverage_input.setValidator(QDoubleValidator(1.0, 125.0, 0)); self.leverage_input.setText("10")
        self.leverage_input.textChanged.connect(self.calculate_and_display_target)
        leverage_layout.addWidget(leverage_label); leverage_layout.addWidget(self.leverage_input); input_form_layout.addLayout(leverage_layout)

        roi_layout = QHBoxLayout(); roi_label = QLabel("목표 수익률 (%):")
        self.roi_input = QLineEdit(self); self.roi_input.setValidator(QDoubleValidator(0.01, 1e6, 2)); self.roi_input.setText("10")
        self.roi_input.textChanged.connect(self.calculate_and_display_target)
        roi_layout.addWidget(roi_label); roi_layout.addWidget(self.roi_input); input_form_layout.addLayout(roi_layout)
        
        quantity_layout = QHBoxLayout(); quantity_label = QLabel("총 주문 수량:")
        self.quantity_input = QLineEdit(self); self.quantity_input.setValidator(QDoubleValidator(0.0, 1e6, 8)); self.quantity_input.setText("0.001")
        self.max_quantity_button = QPushButton("MAX", self); self.max_quantity_button.clicked.connect(self.set_max_quantity)
        quantity_layout.addWidget(quantity_label); quantity_layout.addWidget(self.quantity_input); quantity_layout.addWidget(self.max_quantity_button)
        input_form_layout.addLayout(quantity_layout)
        
        # --- [신규] 그리드 주문 설정 UI ---
        grid_layout = QHBoxLayout()
        grid_count_label = QLabel("분할 개수:")
        self.grid_count_input = QLineEdit(self); self.grid_count_input.setText("1") # 기본값은 1 (단일 주문)
        self.grid_count_input.setValidator(QDoubleValidator(1, 100, 0))
        grid_interval_label = QLabel("가격 간격(Tick):")
        self.grid_interval_input = QLineEdit(self); self.grid_interval_input.setText("10") # 예시 기본값
        self.grid_interval_input.setValidator(QDoubleValidator(0, 1e6, 8))
        grid_layout.addWidget(grid_count_label); grid_layout.addWidget(self.grid_count_input)
        grid_layout.addWidget(grid_interval_label); grid_layout.addWidget(self.grid_interval_input)
        input_form_layout.addLayout(grid_layout)
        # --- UI 추가 종료 ---
        
        input_group_box.setLayout(input_form_layout); left_panel_layout.addWidget(input_group_box)

        position_type_group_box = QGroupBox("포지션 선택"); position_type_layout = QHBoxLayout()
        self.long_button = QPushButton("롱 (Long)", self); self.long_button.clicked.connect(lambda: self.set_position_type('long'))
        self.short_button = QPushButton("숏 (Short)", self); self.short_button.clicked.connect(lambda: self.set_position_type('short'))
        position_type_layout.addWidget(self.long_button); position_type_layout.addWidget(self.short_button)
        position_type_group_box.setLayout(position_type_layout); left_panel_layout.addWidget(position_type_group_box)
        
        result_group_box = QGroupBox("계산 결과"); result_layout = QVBoxLayout()
        self.target_price_label = QLabel("목표 평균 가격: N/A", self); self.target_price_label.setFont(result_font); self.target_price_label.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self.target_price_label); result_group_box.setLayout(result_layout); left_panel_layout.addWidget(result_group_box)

        order_group_box = QGroupBox("주문 실행"); order_layout = QHBoxLayout()
        self.place_entry_order_button = QPushButton("포지션 진입", self); self.place_entry_order_button.setStyleSheet("background-color: #28a745; color: white; padding: 12px;"); self.place_entry_order_button.clicked.connect(self.place_entry_order)
        self.place_target_order_button = QPushButton("목표가 주문 (청산)", self); self.place_target_order_button.setStyleSheet("background-color: #007BFF; color: white; padding: 12px;"); self.place_target_order_button.clicked.connect(self.place_target_order)
        order_layout.addWidget(self.place_entry_order_button); order_layout.addWidget(self.place_target_order_button)
        order_group_box.setLayout(order_layout); left_panel_layout.addWidget(order_group_box)
        main_layout.addLayout(left_panel_layout, 2)

        # ... (우측 호가창 UI는 변경 없음)
        right_panel_layout = QVBoxLayout(); right_panel_layout.setAlignment(Qt.AlignTop)
        self.order_book_group_box = QGroupBox(f"{self.current_selected_symbol} 실시간 호가"); order_book_layout = QVBoxLayout()
        self.ask_label = QLabel("매도 호가:"); order_book_layout.addWidget(self.ask_label)
        self.ask_price_labels = []
        for i in range(5):
            label = QLabel(f"Sell {i+1}: N/A", self); label.setFont(input_font); label.setStyleSheet("color: #f44336;")
            label.mousePressEvent = lambda event, idx=i: self.on_order_book_price_clicked(self.ask_price_labels[idx].text())
            self.ask_price_labels.append(label); order_book_layout.addWidget(label)
        order_book_layout.addSpacing(10); line = QLabel("--------------------"); line.setAlignment(Qt.AlignCenter); order_book_layout.addWidget(line); order_book_layout.addSpacing(10)
        self.bid_label = QLabel("매수 호가:"); order_book_layout.addWidget(self.bid_label)
        self.bid_price_labels = []
        for i in range(5):
            label = QLabel(f"Buy {i+1}: N/A", self); label.setFont(input_font); label.setStyleSheet("color: #4CAF50;")
            label.mousePressEvent = lambda event, idx=i: self.on_order_book_price_clicked(self.bid_price_labels[idx].text())
            self.bid_price_labels.append(label); order_book_layout.addWidget(label)
        self.order_book_group_box.setLayout(order_book_layout); right_panel_layout.addWidget(self.order_book_group_box)
        main_layout.addLayout(right_panel_layout, 3)

        self.setLayout(main_layout); self.update_button_style(); self.calculate_and_display_target()

    def adjust_price_to_tick_size(self, price):
        if self.tick_size == 0.0: return price
        return math.floor(price / self.tick_size) * self.tick_size

    def fetch_symbol_info(self):
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == self.current_selected_symbol:
                    self.symbol_info = s
                    for f in s['filters']:
                        if f['filterType'] == 'PRICE_FILTER':
                            self.tick_size = float(f['tickSize']); print(f"{self.current_selected_symbol} 정보 로드 완료. Tick Size: {self.tick_size}"); return
        except Exception as e:
            print(f"종목 정보 로드 실패: {e}"); self.tick_size = 0.0
    
    def update_asset_balance(self):
        try:
            balances = self.client.futures_account_balance()
            for balance in balances:
                if balance['asset'] == 'USDT':
                    self.available_balance = float(balance['availableBalance']); self.balance_label.setText(f"사용 가능: ${self.available_balance:,.2f}"); return
        except Exception as e: self.balance_label.setText("자산 로드 실패")

    # --- [변경] 그리드 주문 로직을 포함하도록 주문 함수 수정 ---
    def place_order_logic(self, order_type):
        try:
            # 1. 공통 정보 가져오기
            symbol = self.current_selected_symbol
            total_quantity = float(self.quantity_input.text())
            grid_count = int(self.grid_count_input.text())
            
            if self.position_type is None:
                QMessageBox.warning(self, "주문 오류", "포지션 타입을 먼저 선택해주세요."); return
            if grid_count < 1:
                QMessageBox.warning(self, "주문 오류", "분할 개수는 1 이상이어야 합니다."); return

            # 2. 기준 가격 및 주문 방향 결정
            if order_type == 'entry':
                title = "포지션 진입"
                center_price = float(self.entry_price_input.text())
                side = Client.SIDE_BUY if self.position_type == 'long' else Client.SIDE_SELL
            elif order_type == 'target':
                title = "목표가 주문 (청산)"
                price_str = self.target_price_label.text().split(': $')[-1].replace(',', '')
                if "N/A" in price_str: QMessageBox.warning(self, "주문 오류", "목표 가격을 먼저 계산해주세요."); return
                center_price = float(price_str)
                side = Client.SIDE_SELL if self.position_type == 'long' else Client.SIDE_BUY
            else: return

            # 3. 그리드 주문 리스트 생성
            orders_to_place = []
            quantity_per_order = total_quantity / grid_count
            price_interval_ticks = float(self.grid_interval_input.text()) * self.tick_size
            
            price_precision = self.symbol_info.get('pricePrecision')
            quantity_precision = self.symbol_info.get('quantityPrecision')
            
            start_offset = -(grid_count - 1) / 2.0
            for i in range(grid_count):
                price_offset = (start_offset + i) * price_interval_ticks
                price = center_price + price_offset
                adjusted_price = self.adjust_price_to_tick_size(price)
                
                # 수량 정밀도에 맞게 조정
                factor = 10 ** quantity_precision
                adjusted_quantity = math.floor(quantity_per_order * factor) / factor
                
                orders_to_place.append({
                    'price': f"{adjusted_price:.{price_precision}f}",
                    'quantity': f"{adjusted_quantity:.{quantity_precision}f}"
                })

            # 4. 사용자에게 최종 확인
            msg = f"## {title} 그리드 주문 확인 ({grid_count}개 분할) ##\n\n"
            for i, order in enumerate(orders_to_place):
                msg += f"  - 주문 {i+1}: 가격 ${order['price']}, 수량 {order['quantity']}\n"
            msg += f"\n총 수량: {total_quantity}\n\n위 내용으로 주문을 실행하시겠습니까?"
            
            reply = QMessageBox.question(self, f'{title} 확인', msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            # 5. 주문 실행
            if reply == QMessageBox.Yes:
                success_count = 0; failed_orders = []
                for order in orders_to_place:
                    try:
                        self.client.futures_create_order(
                            symbol=symbol, side=side, type=Client.ORDER_TYPE_LIMIT,
                            timeInForce=Client.TIME_IN_FORCE_GTC,
                            quantity=order['quantity'], price=order['price']
                        )
                        success_count += 1
                    except Exception as e:
                        failed_orders.append((order, e))
                
                QMessageBox.information(self, "주문 결과", f"총 {grid_count}개 중 {success_count}개 주문 성공.")
                if failed_orders:
                    print("실패한 주문:", failed_orders)
                self.update_asset_balance()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"주문 처리 중 오류가 발생했습니다: {e}")

    def place_entry_order(self):
        self.place_order_logic('entry')

    def place_target_order(self):
        self.place_order_logic('target')

    # --- (이하 나머지 함수들은 이전과 대부분 동일) ---
    def set_max_quantity(self):
        try:
            leverage = int(self.leverage_input.text())
            if self.position_type is None: QMessageBox.warning(self, "오류", "최대 수량을 계산하려면 먼저 포지션(롱/숏)을 선택해야 합니다."); return
            entry_price = self.best_ask_price if self.position_type == 'long' else self.best_bid_price
            if entry_price == 0: QMessageBox.warning(self, "오류", "호가 정보가 로드될 때까지 잠시 기다려주세요."); return
            max_usdt_value = self.available_balance * leverage; max_quantity = max_usdt_value / entry_price
            quantity_precision = self.symbol_info.get('quantityPrecision')
            if quantity_precision is not None: factor = 10 ** quantity_precision; max_quantity = math.floor(max_quantity * factor) / factor
            self.quantity_input.setText(f"{max_quantity:.{quantity_precision}f}")
        except ValueError: QMessageBox.warning(self, "오류", "레버리지 값이 올바르지 않습니다.")
        except Exception as e: QMessageBox.critical(self, "계산 오류", f"최대 수량 계산 중 오류 발생: {e}")

    def update_order_book_ui(self, data):
        asks = data.get('asks', []); bids = data.get('bids', [])
        if asks: self.best_ask_price = float(asks[0][0])
        for i, label in enumerate(self.ask_price_labels):
            if i < len(asks): label.setText(f"Sell {i+1}: {float(asks[i][0]):,.4f} ({float(asks[i][1]):.3f})")
        if bids: self.best_bid_price = float(bids[0][0])
        for i, label in enumerate(self.bid_price_labels):
            if i < len(bids): label.setText(f"Buy {i+1}: {float(bids[i][0]):,.4f} ({float(bids[i][1]):.3f})")

    def on_symbol_changed(self, symbol: str):
        self.current_selected_symbol = symbol; self.order_book_group_box.setTitle(f"{self.current_selected_symbol} 실시간 호가")
        self.stop_worker(); self.start_worker(); self.fetch_symbol_info()

    def start_worker(self):
        self.worker = BinanceWorker(self.current_selected_symbol); self.worker_thread = QThread(); self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run); self.worker.data_received.connect(self.update_order_book_ui)
        self.worker.connection_error.connect(self.handle_connection_error); self.worker_thread.start()

    def stop_worker(self):
        if self.worker_thread and self.worker_thread.isRunning(): self.worker.stop(); self.worker_thread.quit(); self.worker_thread.wait()

    def handle_connection_error(self, error_message): QMessageBox.critical(self, "연결 오류", f"실시간 데이터 연결에 실패했습니다.\n{error_message}")
    def on_order_book_price_clicked(self, label_text: str):
        try:
            price_str = label_text.split(': ')[1].split(' ')[0]
            self.entry_price_input.setText(f"{float(price_str.replace(',', '')):.8f}".rstrip('0').rstrip('.'))
        except (ValueError, IndexError): pass
    def closeEvent(self, event): self.stop_worker(); event.accept()
    def set_position_type(self, p_type: str): self.position_type = p_type; self.update_button_style(); self.calculate_and_display_target()
    def update_button_style(self):
        if self.position_type == 'long': self.long_button.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; border: 2px solid #0D47A1;"); self.short_button.setStyleSheet("background-color: #f44336; color: white; padding: 10px;")
        elif self.position_type == 'short': self.long_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;"); self.short_button.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; border: 2px solid #0D47A1;")
        else: self.long_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;"); self.short_button.setStyleSheet("background-color: #f44336; color: white; padding: 10px;")

    def calculate_and_display_target(self):
        try:
            entry_price = float(self.entry_price_input.text()); leverage = int(self.leverage_input.text()); target_roi_percent = float(self.roi_input.text())
            if self.position_type is None: self.target_price_label.setText("포지션 타입을 선택하세요 (롱/숏)"); return
            if entry_price <= 0 or leverage <= 0: self.target_price_label.setText("유효한 값을 입력하세요."); return
            target_price = calculate_target_price(entry_price, leverage, target_roi_percent, self.position_type)
            self.target_price_label.setText(f"목표 평균 가격: ${target_price:,.4f}")
        except (ValueError, TypeError): self.target_price_label.setText("입력값이 올바르지 않습니다.")
        except Exception as e: self.target_price_label.setText(f"계산 오류: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = BinanceCalculatorApp()
    ex.show()
    sys.exit(app.exec_())