import sys
import asyncio
import websockets
import json
import math
import os
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox, QGroupBox, QTextEdit,
    QRadioButton, QSlider, QGridLayout, QSplashScreen, 
    QDesktopWidget  
)
from PyQt5.QtGui import QFont, QDoubleValidator, QCursor, QPixmap 
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, QThread, QTimer, QEvent, QCoreApplication,
    QPropertyAnimation, QEasingCurve 
)

from binance.client import Client
from binance.exceptions import BinanceAPIException
import config
import configparser
import logging
from logging.handlers import RotatingFileHandler


# --- 로깅 시스템 설정 ---
def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    log_handler = RotatingFileHandler('trading_app.log', maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    log_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)


# --- 설정 파일 관리 ---
def create_default_config():
    config = configparser.ConfigParser()
    config['API'] = {
        'api_url': 'https://fapi.binance.com/fapi',
        'websocket_base_uri': 'wss://fstream.binance.com/ws'
    }
    config['TRADING'] = {
        'default_symbol': 'BTCUSDT',
        'symbols': 'BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT',
        'maker_fee_rate': '0.0002',
        'taker_fee_rate': '0.0004'
    }
    config['APP_SETTINGS'] = {
        'position_update_interval_ms': '2000',
        'ui_update_interval_ms': '100'
    }
    with open('config.ini', 'w', encoding='utf-8') as configfile:
        config.write(configfile)
    logging.info("기본 'config.ini' 파일이 생성되었습니다.")


# --- 스플래시 스크린 관리 클래스 (Fade-In 적용) ---
class SplashManager(QObject):
    def __init__(self, parent=None, image_path="splash_boot.png"):
        super().__init__(parent)
        
        base_dir = os.path.dirname(sys.argv[0]) 
        self.full_image_path = os.path.join(base_dir, image_path)
        
        self.splash = None
        self.is_ready = False
        self.pixmap = None
        self.animation = None
        
        try:
            self.pixmap = QPixmap(self.full_image_path)
            
            if self.pixmap.isNull():
                logging.error(f"스플래시 이미지 로드 실패: 절대 경로({self.full_image_path})를 확인하세요.")
            else:
                self.is_ready = True
        except Exception as e:
            logging.error(f"스플래시 초기화 중 오류: {e}")

    def show_splash(self):
        if not self.is_ready:
            return
        
        self.splash = QSplashScreen(self.pixmap)
        screen_geometry = QApplication.desktop().screenGeometry()
        x = (screen_geometry.width() - self.pixmap.width()) // 2
        y = (screen_geometry.height() - self.pixmap.height()) // 2
        self.splash.move(x, y)
        
        # Fade-In 애니메이션 설정
        self.animation = QPropertyAnimation(self.splash, b"windowOpacity")
        self.animation.setDuration(400) 
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.InQuad)
        
        self.splash.setWindowOpacity(0.0)
        self.splash.show()
        self.animation.start() 
        
    def hide_splash(self, main_window=None, duration_ms=0):
        if not self.is_ready or not self.splash:
            return
            
        if self.animation and self.animation.state() == QPropertyAnimation.Running:
            self.animation.stop() 
        
        if duration_ms > 0:
            QTimer.singleShot(duration_ms, lambda: self._finalize_hide(main_window))
        else:
            self._finalize_hide(main_window)
            
    def _finalize_hide(self, main_window):
        if self.splash:
            # 메인 창이 있다면, finish를 호출하여 스플래시를 닫음
            if main_window:
                self.splash.finish(main_window)
            else:
                self.splash.close()
                self.splash.deleteLater()


# --- 앱 종료 시 호출될 로직 (사용 안 함) ---
# def _handle_app_quit(splash_manager: SplashManager):
#     pass


# --- 커스텀 라벨 클래스 ---
class ClickablePriceLabel(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, text, color, parent=None):
        super().__init__(text, parent)
        self.color = color
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont("Arial", 11, QFont.Bold))
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setStyleSheet(f"""
            QLabel {{
                background-color: #FFFFFF; color: {self.color}; border: 1px solid #DCDCDC;
                border-radius: 4px; padding: 6px;
            }}
            QLabel:hover {{ background-color: #F0F0F0; }}
        """)

    def mousePressEvent(self, event):
        self.clicked.emit(self.text())


# --- WebSocket 워커 ---
class BinanceWorker(QObject):
    data_received = pyqtSignal(dict)
    connection_error = pyqtSignal(str)

    def __init__(self, symbol, websocket_uri):
        super().__init__()
        self.symbol = symbol.lower()
        self.running = False
        self.websocket_uri = f"{websocket_uri}/{self.symbol}@depth5@100ms"

    def run(self):
        self.running = True
        asyncio.run(self.connect_and_listen())

    async def connect_and_listen(self):
        try:
            async with websockets.connect(self.websocket_uri) as websocket:
                logging.info(f"{self.symbol} WebSocket에 연결되었습니다.")
                while self.running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        self.data_received.emit(json.loads(message))
                    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                        logging.warning(f"{self.symbol} WebSocket 연결 문제 발생, 재연결 시도...")
                        break
        except Exception as e:
            self.connection_error.emit(f"WebSocket 연결 실패: {e}")
            logging.error(f"WebSocket 연결 실패: {e}", exc_info=True)

    def stop(self):
        self.running = False


# --- 핵심 계산 로직 ---
def calculate_target_price(
        entry_price: Decimal, leverage: Decimal, target_roi_percent: Decimal, position_type: str, fee_rate: Decimal
) -> Decimal:
    target_roi = target_roi_percent / Decimal('100.0')
    if position_type.lower() == 'long':
        return entry_price * (Decimal('1') + (target_roi / leverage) + fee_rate) / (Decimal('1') - fee_rate)
    elif position_type.lower() == 'short':
        return entry_price * (Decimal('1') - (target_roi / leverage) - fee_rate) / (Decimal('1') + fee_rate)
    raise ValueError("Position type must be 'long' or 'short'")


# --- GUI 애플리케이션 클래스 ---
class BinanceCalculatorApp(QWidget):
    def __init__(self):
        super().__init__()

        self.config = configparser.ConfigParser()
        if not self.config.read('config.ini', encoding='utf-8'):
            create_default_config()
            self.config.read('config.ini', encoding='utf-8')

        self.setWindowTitle("Binance Station Alpha V1.0 (Live Mode)")
        
        # 창 크기 설정: 902x1305
        self.resize(902, 1305) 
        
        # 창을 화면 정 중앙에 배치
        self.center()

        try:
            self.client = Client(config.API_KEY, config.SECRET_KEY)
            self.client.API_URL = self.config.get('API', 'api_url')
            self.client.futures_ping()
            logging.info("바이낸스 실제 서버 클라이언트 초기화 성공.")
        except Exception as e:
            logging.critical(f"API 연결 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "API 연결 실패", f"API 키 또는 연결을 확인해주세요.\n오류: {e}")
            QCoreApplication.quit()
            
        self.current_selected_symbol = self.config.get('TRADING', 'default_symbol')
        self.position_type = None
        self.worker_thread = None
        self.worker = None
        self.available_balance = Decimal('0')
        self.best_ask_price = Decimal('0')
        self.best_bid_price = Decimal('0')
        self.symbol_info = {}
        self.tick_size = Decimal('0')
        self.step_size = Decimal('0')
        self.latest_order_book_data = {}
        self.leverage_brackets = []
        self.is_retry_scheduled = False
        self.calculated_target_price_decimal = None  

        self.initUI()
        self.start_worker()
        self.update_asset_balance()
        self.fetch_symbol_info()

        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_position_status)
        self.position_timer.timeout.connect(self.update_open_orders_status)
        self.position_timer.start(self.config.getint('APP_SETTINGS', 'position_update_interval_ms'))

        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_ui_from_buffer)
        self.ui_update_timer.start(self.config.getint('APP_SETTINGS', 'ui_update_interval_ms'))
        
        
    def center(self):
        """창을 화면 중앙에 배치하는 메서드"""
        screen = QDesktopWidget().screenGeometry()
        size = self.geometry()
        
        new_x = (screen.width() - size.width()) // 2
        new_y = (screen.height() - size.height()) // 2
        
        self.move(new_x, new_y)


    def place_limit_close_order(self):
        """
        현재 포지션 상태를 확인하고, 입력된 가격과 수량으로 LIMIT 청산 주문을 제출합니다.
        SIDE는 포지션에 따라 자동으로 결정됩니다.
        """
        symbol = self.current_selected_symbol

        try:
            # 1. 현재 포지션 정보 확인
            positions = self.client.futures_position_information(symbol=symbol)
            open_position = next((p for p in positions if Decimal(p['positionAmt']) != Decimal('0')), None)

            if not open_position:
                QMessageBox.warning(self, "청산 오류", "현재 청산할 포지션이 없습니다.")
                return

            position_amt = Decimal(open_position['positionAmt'])
            position_side = "LONG" if position_amt > Decimal('0') else "SHORT"

            # 2. 주문 SIDE 결정 (포지션과 반대)
            side = Client.SIDE_SELL if position_side == "LONG" else Client.SIDE_BUY

            # 3. 가격 및 수량 유효성 검사
            limit_price_text = self.limit_price_input.text()
            quantity_text = self.limit_quantity_input.text().strip().upper()

            if not limit_price_text:
                QMessageBox.warning(self, "주문 오류", "청산 지정가를 입력해주세요.")
                return
            if not quantity_text:
                QMessageBox.warning(self, "주문 오류", "청산 수량을 입력해주세요.")
                return

            price = Decimal(limit_price_text)

            # 가격을 틱 사이즈에 맞게 조정 (ROUND_DOWN)
            adjusted_price = self.adjust_price(price) 

            # 4. 청산 수량 결정 (MAX 처리)
            if quantity_text == "MAX":
                quantity = position_amt.copy_abs()
            else:
                quantity = Decimal(quantity_text)

            if price <= Decimal('0') or quantity <= Decimal('0'):
                QMessageBox.warning(self, "주문 오류", "가격과 수량은 0보다 커야 합니다.")
                return
            
            # 수량도 Step Size에 맞춰 조정합니다. (adjust_quantity는 ROUND_DOWN 사용)
            adjusted_quantity = self.adjust_quantity(quantity) 
            
            if adjusted_quantity > position_amt.copy_abs():
                QMessageBox.warning(self, "청산 오류",
                                    f"청산하려는 수량({adjusted_quantity.normalize()})이 현재 포지션 수량({position_amt.copy_abs().normalize()})보다 많습니다.")
                return

            # 5. Binance API 호출
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=Client.ORDER_TYPE_LIMIT,
                timeInForce=Client.TIME_IN_FORCE_GTC,
                quantity=adjusted_quantity.normalize(), # 조정된 수량 사용
                price=str(adjusted_price.normalize()), # 조정된 가격 사용
                reduceOnly=True
            )

            logging.info(f"LIMIT 청산 주문 제출 성공 (SIDE: {side}, 수량: {adjusted_quantity}): {order}")
            QMessageBox.information(
                self,
                "주문 성공",
                f"{symbol} 포지션({position_side})에 대한 LIMIT 청산 주문이 제출되었습니다.\n"
                f"SIDE: {order['side']} | 수량: {order['origQty']} @ {order['price']}"
            )

            self.manual_refresh_data()

        except BinanceAPIException as e:
            logging.error(f"LIMIT 청산 주문 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "주문 실패", f"LIMIT 청산 주문 실패: {e.message}")
        except Exception as e:
            logging.error(f"LIMIT 청산 주문 중 일반 오류 발생: {e}", exc_info=True)
            QMessageBox.critical(self, "오류", f"LIMIT 청산 주문 중 오류 발생: {e}")

    def cancel_all_open_orders(self):
        """
        현재 선택된 종목의 모든 미체결 주문을 취소하고 상태를 새로고침합니다.
        """
        symbol = self.current_selected_symbol

        try:
            # Binance API 호출: 전체 미체결 주문 취소
            result = self.client.futures_cancel_all_open_orders(symbol=symbol)

            if result.get('code') == 200:
                QMessageBox.information(self, "성공", f"{symbol}의 모든 미체결 주문이 성공적으로 취소되었습니다.")
            else:
                logging.info(f"미체결 주문 취소 시도 결과: {result}")
                QMessageBox.information(self, "알림", f"{symbol}의 미체결 주문 취소 요청을 완료했습니다. 상세: {result.get('msg', '응답 확인')}")

            self.manual_refresh_data()

        except BinanceAPIException as e:
            if e.code == -4046:  # -4046: No orders present
                QMessageBox.information(self, "알림", f"취소할 {symbol}의 미체결 주문이 없습니다.")
            else:
                logging.error(f"{symbol} 주문 전체 취소 실패: {e}", exc_info=True)
                QMessageBox.critical(self, "오류", f"주문 전체 취소 실패: {e.message}")
        except Exception as e:
            logging.error(f"주문 전체 취소 중 일반 오류 발생: {e}", exc_info=True)
            QMessageBox.critical(self, "오류", f"주문 전체 취소 중 오류 발생: {e}")

    def initUI(self):
        grid = QGridLayout()
        self.setLayout(grid)
        label_font = QFont("Arial", 10)
        input_font = QFont("Arial", 10)
        result_font = QFont("Arial", 14, QFont.Bold)
        button_font = QFont("Arial", 10, QFont.Bold)

        # --- UI 구성 요소는 이전 코드와 동일하게 유지 ---

        # [0, 0] 자산 현황
        self.asset_group_box = QGroupBox("자산 현황 (USDT)")
        asset_main_layout = QVBoxLayout()
        asset_top_layout = QHBoxLayout()
        self.balance_label = QLabel("사용 가능: $0.00", self)
        self.balance_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.refresh_button = QPushButton("🔄 새로고침", self)
        self.refresh_button.setFont(button_font)
        self.refresh_button.clicked.connect(self.manual_refresh_data)
        asset_top_layout.addWidget(self.balance_label)
        asset_top_layout.addStretch(1)
        asset_top_layout.addWidget(self.refresh_button)
        asset_main_layout.addLayout(asset_top_layout)
        self.asset_group_box.setLayout(asset_main_layout)

        # [1, 0] 거래 종목 선택
        symbol_group_box = QGroupBox("거래 종목 선택")
        symbol_layout = QVBoxLayout()
        self.symbol_combo = QComboBox(self)
        self.symbol_combo.setFont(input_font)
        symbols = self.config.get('TRADING', 'symbols').split(',')
        self.symbol_combo.addItems(symbols)
        self.symbol_combo.setCurrentText(self.current_selected_symbol)
        self.symbol_combo.currentTextChanged.connect(self.on_symbol_changed)
        symbol_layout.addWidget(self.symbol_combo)
        symbol_group_box.setLayout(symbol_layout)

        # [2, 0] 거래 정보 입력 (계산기)
        input_group_box = QGroupBox("거래 정보 입력")
        input_form_layout = QVBoxLayout()
        entry_price_layout = QHBoxLayout()
        entry_price_label = QLabel("기준 가격:")
        self.entry_price_input = QLineEdit(self)
        self.entry_price_input.setValidator(QDoubleValidator(0.0, 1e9, 8))
        self.entry_price_input.setText("0.00")
        self.entry_price_input.textChanged.connect(self.calculate_and_display_target)
        self.entry_price_input.editingFinished.connect(self.format_entry_price)
        entry_price_layout.addWidget(entry_price_label)
        entry_price_layout.addWidget(self.entry_price_input)
        input_form_layout.addLayout(entry_price_layout)

        leverage_layout = QHBoxLayout()
        self.leverage_label = QLabel("레버리지 (x):")
        self.leverage_label.setToolTip("종목 변경 시 최대 레버리지가 자동으로 설정됩니다.")
        self.leverage_input = QLineEdit(self)
        self.leverage_input.setValidator(QDoubleValidator(1.0, 125.0, 0))
        self.leverage_input.setText("10")
        self.leverage_input.textChanged.connect(self.calculate_and_display_target)
        leverage_layout.addWidget(self.leverage_label)
        leverage_layout.addWidget(self.leverage_input)
        input_form_layout.addLayout(leverage_layout)

        roi_layout = QHBoxLayout()
        roi_label = QLabel("목표 수익률 (%):")
        self.roi_input = QLineEdit(self)
        self.roi_input.setValidator(QDoubleValidator(0.01, 1e6, 2))
        self.roi_input.setText("10")
        self.roi_input.textChanged.connect(self.calculate_and_display_target)
        roi_layout.addWidget(roi_label)
        roi_layout.addWidget(self.roi_input)
        input_form_layout.addLayout(roi_layout)

        quantity_layout = QHBoxLayout()
        quantity_label = QLabel("총 주문 수량:")
        self.quantity_input = QLineEdit(self)
        self.quantity_input.setValidator(QDoubleValidator(0.0, 1e6, 8))
        self.quantity_input.setText("0.001")
        quantity_layout.addWidget(quantity_label)
        quantity_layout.addWidget(self.quantity_input)
        self.max_button = QPushButton("Max", self)
        self.max_button.setFont(button_font)
        self.max_button.setFixedWidth(50)
        self.max_button.clicked.connect(self.set_max_quantity)
        quantity_layout.addWidget(self.max_button)
        input_form_layout.addLayout(quantity_layout)

        slider_layout = QHBoxLayout()
        self.quantity_slider = QSlider(Qt.Horizontal, self)
        self.quantity_slider.setRange(0, 100)
        self.quantity_slider.setValue(50)
        self.slider_label = QLabel("50%", self)
        self.quantity_slider.valueChanged.connect(self.update_quantity_from_slider)
        slider_layout.addWidget(self.quantity_slider)
        slider_layout.addWidget(self.slider_label)
        input_form_layout.addLayout(slider_layout)

        grid_layout = QHBoxLayout()
        grid_count_label = QLabel("분할 개수:")
        self.grid_count_input = QLineEdit(self)
        self.grid_count_input.setText("1")
        self.grid_count_input.setValidator(QDoubleValidator(1, 100, 0))
        grid_interval_label = QLabel("가격 간격(Tick):")
        self.grid_interval_input = QLineEdit(self)
        self.grid_interval_input.setText("10")
        self.grid_interval_input.setValidator(QDoubleValidator(0, 1e6, 8))
        grid_layout.addWidget(grid_count_label)
        grid_layout.addWidget(self.grid_count_input)
        grid_layout.addWidget(grid_interval_label)
        grid_layout.addWidget(self.grid_interval_input)
        input_form_layout.addLayout(grid_layout)

        fee_type_layout = QHBoxLayout()
        fee_type_label = QLabel("수수료 종류:")
        self.maker_radio = QRadioButton("Maker (지정가)", self)
        self.taker_radio = QRadioButton("Taker (시장가)", self)
        self.taker_radio.setChecked(True)
        self.maker_radio.toggled.connect(self.calculate_and_display_target)
        self.taker_radio.toggled.connect(self.calculate_and_display_target)
        fee_type_layout.addWidget(fee_type_label)
        fee_type_layout.addWidget(self.maker_radio)
        fee_type_layout.addWidget(self.taker_radio)
        input_form_layout.addLayout(fee_type_layout)
        input_group_box.setLayout(input_form_layout)

        # [3, 0] 포지션 선택
        position_type_group_box = QGroupBox("포지션 선택")
        position_type_layout = QHBoxLayout()
        self.long_button = QPushButton("롱 (Long)", self)
        self.long_button.clicked.connect(lambda: self.set_position_type('long'))
        self.short_button = QPushButton("숏 (Short)", self)
        self.short_button.clicked.connect(lambda: self.set_position_type('short'))
        position_type_layout.addWidget(self.long_button)
        position_type_layout.addWidget(self.short_button)
        position_type_group_box.setLayout(position_type_layout)

        # [4, 0] 계산 결과
        result_group_box = QGroupBox("계산 결과")
        result_layout = QVBoxLayout()
        self.target_price_label = QLabel("Target Price: N/A", self)
        self.target_price_label.setFont(result_font)
        self.target_price_label.setAlignment(Qt.AlignCenter)
        self.price_change_label = QLabel("NLV: N/A", self)
        self.price_change_label.setFont(QFont("Arial", 11))
        self.price_change_label.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self.target_price_label)
        result_layout.addWidget(self.price_change_label)
        result_group_box.setLayout(result_layout)

        # ----------------------------------------------------------------------
        # [5, 0] Limit Exit Order
        manual_limit_group_box = QGroupBox("Limit Exit Order")
        limit_layout = QGridLayout()

        # 1. 지정가 (Price) 입력
        limit_layout.addWidget(QLabel("Price:"), 0, 0)
        self.limit_price_input = QLineEdit(self)
        self.limit_price_input.setPlaceholderText("청산 희망 가격 입력")
        self.limit_price_input.setValidator(QDoubleValidator(0.00, 100000.00, 8))
        limit_layout.addWidget(self.limit_price_input, 0, 1)

        # 2. 수량 (Quantity) 입력
        limit_layout.addWidget(QLabel("Quantity:"), 1, 0)
        self.limit_quantity_input = QLineEdit(self)
        self.limit_quantity_input.setPlaceholderText("청산할 수량 입력 (전량은 'MAX')")
        self.limit_quantity_input.setValidator(QDoubleValidator(0.00, 1000000.00, 8))
        self.limit_quantity_input.setText("MAX")  # 초기값은 전량 청산
        limit_layout.addWidget(self.limit_quantity_input, 1, 1)

        # 3. LIMIT 버튼 (검은색 바탕, 흰 글씨)
        self.limit_close_button = QPushButton("LIMIT", self)
        self.limit_close_button.setFont(button_font)
        self.limit_close_button.setStyleSheet("background-color: #212529; color: white; padding: 6px; font-weight: bold;")
        self.limit_close_button.clicked.connect(self.place_limit_close_order)
        limit_layout.addWidget(self.limit_close_button, 2, 0, 1, 2)  # (2행 0열부터 2열까지 병합)

        manual_limit_group_box.setLayout(limit_layout)
        # ----------------------------------------------------------------------

        # [6, 0] 미체결 주문 현황
        open_orders_group_box = QGroupBox("미체결 주문 현황")
        open_orders_layout = QVBoxLayout()
        self.open_orders_display = QTextEdit(self)
        self.open_orders_display.setReadOnly(True)
        self.open_orders_display.setFont(QFont("Consolas", 10))
        self.open_orders_display.setText("미체결 주문 없음")
        open_orders_layout.addWidget(self.open_orders_display)

        # 주문 전체 취소 버튼
        self.cancel_all_orders_button = QPushButton(f"{self.current_selected_symbol} 미체결 전체 취소", self)
        self.cancel_all_orders_button.setFont(button_font)
        self.cancel_all_orders_button.setStyleSheet("background-color: #212529; color: white; padding: 6px; font-weight: bold;")
        self.cancel_all_orders_button.clicked.connect(self.cancel_all_open_orders)
        open_orders_layout.addWidget(self.cancel_all_orders_button)

        open_orders_group_box.setLayout(open_orders_layout)

        # [7, 0] 실시간 포지션 현황
        position_group_box = QGroupBox("실시간 포지션 현황")
        position_layout = QVBoxLayout()
        self.position_display = QTextEdit(self)
        self.position_display.setReadOnly(True)
        self.position_display.setFont(QFont("Consolas", 10))
        self.position_display.setText("포지션 정보 없음")
        position_layout.addWidget(self.position_display)
        self.market_close_button = QPushButton("전체 포지션 시장가 청산", self)
        self.market_close_button.setFont(button_font)
        self.market_close_button.setStyleSheet("background-color: #212529; color: white; padding: 8px;")
        self.market_close_button.clicked.connect(self.emergency_market_close)
        position_layout.addWidget(self.market_close_button)
        position_group_box.setLayout(position_layout)

        # [2, 1] ~ [7, 1] 실시간 호가 (오른쪽 패널)
        self.order_book_group_box = QGroupBox(f"{self.current_selected_symbol} 실시간 호가")
        order_book_layout = QVBoxLayout()
        self.ask_price_labels = [ClickablePriceLabel(f"Sell {i + 1}: N/A", "#dc3545") for i in range(5)]
        for label in self.ask_price_labels:
            order_book_layout.addWidget(label)
            label.clicked.connect(self.on_order_book_price_clicked)
        order_execution_widget = QWidget()
        order_layout = QHBoxLayout()
        order_layout.setContentsMargins(0, 5, 0, 5)
        self.place_entry_order_button = QPushButton("포지션 진입", self)
        self.place_entry_order_button.setStyleSheet("background-color: #28a745; color: white; padding: 12px; font-weight: bold;")
        self.place_entry_order_button.clicked.connect(self.place_entry_order)
        self.place_target_order_button = QPushButton("Target Price Limit", self)
        self.place_target_order_button.setStyleSheet("background-color: #ffc107; color: black; padding: 12px; font-weight: bold;")
        self.place_target_order_button.clicked.connect(self.place_target_order)
        order_layout.addWidget(self.place_entry_order_button)
        order_layout.addWidget(self.place_target_order_button)
        order_execution_widget.setLayout(order_layout)
        order_book_layout.addWidget(order_execution_widget)
        self.bid_price_labels = [ClickablePriceLabel(f"Buy {i + 1}: N/A", "#007BFF") for i in range(5)]
        for label in self.bid_price_labels:
            order_book_layout.addWidget(label)
            label.clicked.connect(self.on_order_book_price_clicked)
        self.order_book_group_box.setLayout(order_book_layout)

        # --- Grid Layout 배치 (이전 코드와 동일하게 유지) ---
        grid.addWidget(self.asset_group_box, 0, 0, 1, 2)
        grid.addWidget(symbol_group_box, 1, 0, 1, 2)
        grid.addWidget(input_group_box, 2, 0)
        grid.addWidget(position_type_group_box, 3, 0)
        grid.addWidget(result_group_box, 4, 0)
        grid.addWidget(manual_limit_group_box, 5, 0)
        grid.addWidget(open_orders_group_box, 6, 0)
        grid.addWidget(position_group_box, 7, 0)
        grid.addWidget(self.order_book_group_box, 2, 1, 6, 1)

        grid.setRowStretch(6, 1)  
        grid.setRowStretch(7, 2)  
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)

        self.update_button_style()
        self.calculate_and_display_target()

    def buffer_order_book_data(self, data):
        self.latest_order_book_data = data
        if data.get('asks'):
            self.best_ask_price = Decimal(data['asks'][0][0])
        if data.get('bids'):
            self.best_bid_price = Decimal(data['bids'][0][0])

    def update_ui_from_buffer(self):
        if self.latest_order_book_data:
            self.update_order_book_ui(self.latest_order_book_data)

    def update_order_book_ui(self, data):
        asks = data.get('a', [])
        bids = data.get('b', [])
        
        precision = 4 
        if self.tick_size > Decimal('0'):
            precision = max(0, -self.tick_size.as_tuple().exponent) 
            
        format_string = f"{{:,.{precision}f}} ({{:.3f}})"

        for i, label in enumerate(self.ask_price_labels):
            if i < len(asks):
                label.setText(format_string.format(Decimal(asks[i][0]), Decimal(asks[i][1])))
            else:
                label.setText("N/A")
        for i, label in enumerate(self.bid_price_labels):
            if i < len(bids):
                label.setText(format_string.format(Decimal(bids[i][0]), Decimal(bids[i][1])))
            else:
                label.setText("N/A")

    def start_worker(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.stop_worker()
        ws_uri = self.config.get('API', 'websocket_base_uri')
        self.worker = BinanceWorker(self.current_selected_symbol, ws_uri)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.data_received.connect(self.buffer_order_book_data)
        self.worker.connection_error.connect(self.handle_connection_error)
        self.worker_thread.start()

    def stop_worker(self):
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker:
                logging.info(f"{self.worker.symbol} WebSocket 연결을 종료합니다.")
                self.worker.stop()
            self.worker_thread.quit()
            # WebSocket 종료를 대기 (2초)
            self.worker_thread.wait(2000)

    def closeEvent(self, event):
        logging.info("애플리케이션을 종료합니다.")
        self.position_timer.stop()
        self.ui_update_timer.stop()
        # WebSocket 종료를 대기 (2초)
        self.stop_worker()
        event.accept()

    def retry_position_update(self):
        """2초 후 포지션 정보만 조용히 다시 가져옵니다."""
        logging.info("누락된 포지션 정보를 자동으로 다시 가져옵니다...")
        self.update_position_status()
        self.is_retry_scheduled = False

    def manual_refresh_data(self):
        logging.info("사용자가 수동으로 데이터 새로고침을 요청했습니다.")
        self.is_retry_scheduled = False
        self.update_asset_balance()
        self.update_position_status()
        self.update_open_orders_status()

    def update_open_orders_status(self):
        try:
            orders = self.client.futures_get_open_orders(symbol=self.current_selected_symbol)
            if not orders:
                self.open_orders_display.setText(f"현재 {self.current_selected_symbol} 미체결 주문 없음")
                return
            display_text = ""
            precision = 2 
            if self.tick_size > Decimal('0'):
                precision = max(0, -self.tick_size.as_tuple().exponent)
            price_format = f",.{precision}f"
            
            for o in orders:
                # BUY는 파란색, SELL은 빨간색
                side_color = "red" if o['side'] == 'SELL' else "blue" 
                display_text += (f"<b style='font-size:11pt;'>{o['symbol']} <span style='color:{side_color}';>{o['side']}</span></b><br>"
                                 f" - <b>가격:</b> ${Decimal(o['price']):{price_format}}<br>"
                                 f" - <b>수량:</b> {Decimal(o['origQty'])}<br>"
                                 "--------------------------<br>")
            self.open_orders_display.setHtml(display_text)
        except Exception as e:
            logging.error(f"미체결 주문 로드 실패: {e}", exc_info=True)
            self.open_orders_display.setText(f"미체결 주문 로드 실패:\n{e}")

    def update_position_status(self):
        try:
            positions = self.client.futures_position_information(symbol=self.current_selected_symbol)
            open_positions = [p for p in positions if Decimal(p['positionAmt']) != Decimal('0')]

            if not open_positions:
                self.position_display.setText(f"현재 {self.current_selected_symbol} 포지션이 없습니다.")
                return

            precision = 2 
            if self.tick_size > Decimal('0'):
                precision = max(0, -self.tick_size.as_tuple().exponent)
            price_format = f",.{precision}f"
            
            display_text = ""
            for p in open_positions:
                pnl = Decimal(p['unRealizedProfit'])
                entry_price = Decimal(p['entryPrice'])
                position_amt = Decimal(p['positionAmt'])
                mark_price = Decimal(p['markPrice'])
                position_side = "LONG" if position_amt > 0 else "SHORT"
                liq_price = Decimal(p['liquidationPrice'])
                
                # 포지션 타입 색상 (LONG=빨강, SHORT=파랑)
                position_color = "red" if position_side == "LONG" else "blue"

                taker_fee_rate = Decimal(self.config.get('TRADING', 'taker_fee_rate'))
                position_notional = mark_price * position_amt.copy_abs()
                closing_fee = position_notional * taker_fee_rate

                net_pnl = pnl - closing_fee
                # nPNL/nROE 색상 (양수: 초록, 음수: 검정)
                net_color = "green" if net_pnl >= Decimal('0') else "black" 

                leverage_str = p.get('leverage')
                leverage = Decimal('0')
                net_roe_text = "N/A"

                if leverage_str:
                    leverage = Decimal(leverage_str)
                elif self.leverage_input.text():
                    try:
                        leverage = Decimal(self.leverage_input.text())
                        logging.warning(f"포지션 leverage 키 누락! UI 입력값 {leverage}x로 nROE 계산 보완.")
                    except:
                        pass

                if leverage > Decimal('0'):
                    margin = entry_price * position_amt.copy_abs() / leverage
                    if margin != Decimal('0'):
                        net_roe = (net_pnl / margin) * Decimal('100')
                        net_roe_text = f"{net_roe:.2f}%"
                    else:
                        net_roe_text = "0.00%"
                
                # nPNL과 nROE 값 볼드 처리
                display_text += (f"<b style='font-size:11pt;'>{p['symbol']} <span style='color:{position_color};'>({position_side})</span></b><br>"
                                 f" - <b>수익(nPNL):</b> <span style='color:{net_color};'><b>${net_pnl:,.2f}</b></span><br>"
                                 f" - <b>수익률(nROE):</b> <span style='color:{net_color};'><b>{net_roe_text}</b></span><br>"
                                 f" - <b>진입가:</b> ${entry_price:{price_format}}<br>"
                                 f" - <b>시장가:</b> ${mark_price:{price_format}}<br>"
                                 f" - <b>청산가:</b> <span style='color:orange;'>${liq_price:{price_format}}</span><br>"
                                 f" - <b>수량:</b> {position_amt.copy_abs()}<br>"
                                 f"--------------------------<br>")
            self.position_display.setHtml(display_text)

        except Exception as e:
            logging.error(f"포지션 정보 로드 실패: {e}", exc_info=True)
            self.position_display.setText(f"포지션 정보 로드 실패:\n{e}")

    def format_entry_price(self):
        try:
            price_str = self.entry_price_input.text()
            if not price_str:
                return
            price = Decimal(price_str)
            
            # tick_size를 사용하여 반올림 처리
            if self.tick_size > Decimal('0'):
                adjusted_price = price.quantize(self.tick_size, rounding=ROUND_HALF_UP)
            else:
                adjusted_price = price
                
            self.entry_price_input.setText(str(adjusted_price.normalize()))

        except Exception:
            pass

    def adjust_price(self, price: Decimal) -> Decimal:
        if self.tick_size == Decimal('0'):
            return price
        # 가격 조정 시 내림하여 보수적으로 처리
        return price.quantize(self.tick_size, rounding=ROUND_DOWN)

    def adjust_quantity(self, quantity: Decimal) -> Decimal:
        if self.step_size == Decimal('0'):
            return quantity
        # 수량 조정 시 내림하여 보수적으로 처리
        return quantity.quantize(self.step_size, rounding=ROUND_DOWN)

    def fetch_symbol_info(self):
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == self.current_selected_symbol:
                    self.symbol_info = s
                    for f in s['filters']:
                        if f['filterType'] == 'PRICE_FILTER':
                            # tick_size 정밀도 문제 해결을 위해 normalize() 적용
                            self.tick_size = Decimal(f['tickSize']).normalize() 
                            logging.info(f"✅ {self.current_selected_symbol} Tick Size Fetched: {self.tick_size}")
                        if f['filterType'] == 'LOT_SIZE':
                            self.step_size = Decimal(f['stepSize'])

            leverage_brackets_data = self.client.futures_leverage_bracket(symbol=self.current_selected_symbol)
            if leverage_brackets_data:
                self.leverage_brackets = leverage_brackets_data[0]['brackets']
                max_leverage = int(self.leverage_brackets[0]['initialLeverage'])
                logging.info(
                    f"{self.current_selected_symbol} 정보 로드: Tick Size {self.tick_size}, Step Size {self.step_size}, Max Leverage {max_leverage}x")
                self.leverage_input.setValidator(QDoubleValidator(1.0, float(max_leverage), 0))
                self.leverage_label.setToolTip(f"이 종목의 최대 레버리지는 {max_leverage}배입니다.")
                if self.leverage_input.text() and int(self.leverage_input.text()) > max_leverage:
                    self.leverage_input.setText(str(max_leverage))
            return
        except Exception as e:
            logging.error(f"종목 정보 로드 실패: {e}", exc_info=True)
            self.tick_size = Decimal('0')
            self.step_size = Decimal('0')

    def get_adjusted_max_notional(self, desired_notional, selected_leverage):
        if not self.leverage_brackets:
            return (desired_notional, selected_leverage)
        for tier in self.leverage_brackets:
            if desired_notional > Decimal(str(tier['notionalFloor'])) and desired_notional <= Decimal(
                    str(tier['notionalCap'])):
                allowed_leverage = Decimal(str(tier['initialLeverage']))
                if selected_leverage > allowed_leverage:
                    logging.warning(
                        f"레버리지 조정: 포지션 규모 ${desired_notional:,.0f} USDT는 최대 {allowed_leverage}배 레버리지만 허용됩니다.")
                    return (self.available_balance * allowed_leverage, allowed_leverage)
                break
        return (desired_notional, selected_leverage)

    def update_asset_balance(self):
        try:
            account_info = self.client.futures_account()
            total_balance = Decimal(account_info['totalWalletBalance'])
            self.asset_group_box.setTitle(f"자산 현황 (총: ${total_balance:,.2f} USDT)")
            for asset in account_info['assets']:
                if asset['asset'] == 'USDT':
                    self.available_balance = Decimal(asset['availableBalance'])
                    self.balance_label.setText(f"사용 가능: ${self.available_balance:,.2f}")
                    return
        except Exception as e:
            logging.error(f"자산 정보 로드 실패: {e}", exc_info=True)
            self.balance_label.setText("자산 로드 실패")

    def place_order_logic(self, order_type):
        try:
            symbol = self.current_selected_symbol
            total_quantity_text = self.quantity_input.text()
            if not total_quantity_text:
                QMessageBox.warning(self, "주문 오류", "총 주문 수량을 입력해주세요.")
                return

            total_quantity = Decimal(total_quantity_text)
            grid_count_text = self.grid_count_input.text()
            if not grid_count_text:
                 QMessageBox.warning(self, "주문 오류", "분할 개수를 입력해주세요.")
                 return
                 
            grid_count = int(grid_count_text)

            if self.position_type is None:
                QMessageBox.warning(self, "주문 오류", "포지션 타입을 먼저 선택해주세요.")
                return
            if grid_count < 1:
                QMessageBox.warning(self, "주문 오류", "분할 개수는 1 이상이어야 합니다.")
                return

            if order_type == 'entry':
                title = "포지션 진입"
                entry_price_text = self.entry_price_input.text()
                if not entry_price_text:
                    QMessageBox.warning(self, "주문 오류", "기준 가격을 입력해주세요.")
                    return
                center_price = Decimal(entry_price_text)
                side = Client.SIDE_BUY if self.position_type == 'long' else Client.SIDE_SELL
            elif order_type == 'target':
                title = "Target Price Limit"
                if self.calculated_target_price_decimal is None:
                    QMessageBox.warning(self, "주문 오류", "목표 가격을 먼저 계산해주세요.")
                    return
                center_price = self.calculated_target_price_decimal 
                side = Client.SIDE_SELL if self.position_type == 'long' else Client.SIDE_BUY
            else:
                return
            
            if total_quantity <= Decimal('0'):
                QMessageBox.warning(self, "주문 오류", "총 주문 수량은 0보다 커야 합니다.")
                return

            orders_to_place = []
            quantity_per_order = total_quantity / Decimal(grid_count)
            
            grid_interval_text = self.grid_interval_input.text()
            if not grid_interval_text:
                QMessageBox.warning(self, "주문 오류", "가격 간격(Tick)을 입력해주세요.")
                return
            
            price_interval = Decimal(grid_interval_text) * self.tick_size

            start_offset = -(Decimal(grid_count) - Decimal('1')) / Decimal('2')
            for i in range(grid_count):
                price_offset = (start_offset + Decimal(i)) * price_interval
                price = center_price + price_offset

                if self.tick_size > Decimal('0'):
                    if order_type == 'entry':
                        if self.position_type == 'long':
                            adjusted_price = price.quantize(self.tick_size, rounding=ROUND_DOWN)
                        else:
                            adjusted_price = price.quantize(self.tick_size, rounding=ROUND_CEILING)
                    else:
                        adjusted_price = price.quantize(self.tick_size, rounding=ROUND_HALF_UP)
                else:
                    adjusted_price = price
                    
                adjusted_quantity = self.adjust_quantity(quantity_per_order)

                orders_to_place.append({'price': str(adjusted_price.normalize()), 'quantity': str(adjusted_quantity.normalize())})

            logging.info(f"'{title}' 확인 없이 즉시 실행: {grid_count}개 분할, 총 수량 {total_quantity}")
            success_count = 0
            failed_orders = []
            for order in orders_to_place:
                if Decimal(order['quantity']) <= Decimal('0'):
                    logging.warning(f"수량 0으로 주문 건너뜀: {order}")
                    continue
                    
                try:
                    reduce_only = True if order_type == 'target' else False
                    
                    logging.info(
                        f"🚀 Placing Order: SYMBOL={symbol}, SIDE={side}, QTY={order['quantity']}, PRICE={order['price']}, ReduceOnly={reduce_only}")
                    self.client.futures_create_order(symbol=symbol, side=side, type=Client.ORDER_TYPE_LIMIT,
                                                     timeInForce=Client.TIME_IN_FORCE_GTC, quantity=order['quantity'],
                                                     price=order['price'], reduceOnly=reduce_only)
                    success_count += 1
                except Exception as e:
                    failed_orders.append((order, e))
                    logging.error(f"주문 실패 (가격: {order['price']}, 수량: {order['quantity']}): {e}", exc_info=True)

            logging.info(f"주문 결과: {success_count}/{grid_count} 성공.")
            if failed_orders:
                error_msg = "\n".join([f"가격: {o[0]['price']}, 오류: {str(o[1])}" for o in failed_orders])
                QMessageBox.warning(self, "부분 주문 실패", f"총 {grid_count}개 중 {success_count}개 성공. 나머지 주문 실패:\n{error_msg}")
            
            if success_count > 0:
                self.manual_refresh_data()
            

        except Exception as e:
            logging.error(f"주문 처리 중 오류 발생: {e}", exc_info=True)
            QMessageBox.critical(self, "오류", f"주문 처리 중 오류가 발생했습니다: {e}")

    def emergency_market_close(self):
        try:
            positions = self.client.futures_position_information()
            open_positions = [p for p in positions if float(p['positionAmt']) != 0]
            if not open_positions:
                QMessageBox.information(self, "알림", "청산할 포지션이 없습니다.")
                return

            positions_summary = "\n".join([f"- {p['symbol']}: {p['positionAmt']}" for p in open_positions])
            msg = (
                f"## 경고 ##\n\n아래의 모든 포지션을 시장가로 즉시 청산합니다.\n관련된 모든 미체결 주문도 함께 취소됩니다.\n\n{positions_summary}\n\n정말로 실행하시겠습니까?")
            reply = QMessageBox.question(self, '비상 청산 확인', msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                logging.warning("비상 시장가 청산 기능 실행!")
                success_count = 0
                for p in open_positions:
                    symbol = p['symbol']
                    position_amt = float(p['positionAmt'])
                    side = Client.SIDE_SELL if position_amt > 0 else Client.SIDE_BUY
                    quantity = abs(position_amt)
                    try:
                        self.client.futures_create_order(symbol=symbol, side=side, type=Client.ORDER_TYPE_MARKET,
                                                         quantity=quantity, reduceOnly=True)
                        success_count += 1
                        logging.info(f"{symbol} 포지션 시장가 청산 주문 제출 완료.")
                    except Exception as e:
                        logging.error(f"{symbol} 포지션 청산 중 오류 발생: {e}", exc_info=True)
                        QMessageBox.critical(self, "청산 오류", f"{symbol} 포지션 청산 중 오류 발생:\n{e}")
                QMessageBox.information(self, "실행 완료",
                                        f"총 {len(open_positions)}개 중 {success_count}개 포지션에 대한 청산 주문을 제출했습니다.")
                self.manual_refresh_data()
        except Exception as e:
            logging.error(f"비상 청산 기능 실행 중 오류: {e}", exc_info=True)
            QMessageBox.critical(self, "오류", f"비상 청산 기능 실행 중 오류가 발생했습니다: {e}")

    def place_entry_order(self):
        self.place_order_logic('entry')

    def place_target_order(self):
        self.place_order_logic('target')

    def set_max_quantity(self):
        self.quantity_slider.setValue(100)
        self.update_quantity_from_slider()

    def update_quantity_from_slider(self):
        try:
            percentage = self.quantity_slider.value()
            self.slider_label.setText(f"{percentage}%")
            if not self.leverage_input.text() or self.available_balance <= 0:
                return
            leverage = Decimal(self.leverage_input.text())
            entry_price = self.best_ask_price if self.position_type != 'short' else self.best_bid_price
            if entry_price <= Decimal('0'):
                if self.entry_price_input.text() and Decimal(self.entry_price_input.text()) > 0:
                    entry_price = Decimal(self.entry_price_input.text())
                else:
                    return

            max_usdt_value = self.available_balance * leverage
            adjusted_max_usdt_value, effective_leverage = self.get_adjusted_max_notional(max_usdt_value, leverage)

            if int(leverage) != int(effective_leverage):
                self.leverage_input.setText(str(int(effective_leverage)))

            if entry_price > Decimal('0'):
                max_quantity = adjusted_max_usdt_value / entry_price
                target_quantity = max_quantity * (Decimal(percentage) / Decimal('100'))
                adjusted_quantity = self.adjust_quantity(target_quantity)

                if adjusted_quantity > 0:
                    self.quantity_input.setText(str(adjusted_quantity.normalize()))
                else:
                    self.quantity_input.setText("0")
            else:
                 self.quantity_input.setText("0")
                 
        except Exception as e:
            logging.error(f"수량 계산 슬라이더 오류: {e}", exc_info=True)
            pass

    def on_symbol_changed(self, symbol: str):
        logging.info(f"거래 종목 변경: {symbol}")
        self.current_selected_symbol = symbol
        self.order_book_group_box.setTitle(f"{self.current_selected_symbol} 실시간 호가")
        self.stop_worker()
        self.start_worker()
        self.fetch_symbol_info()
        self.update_position_status()
        self.update_open_orders_status()


    def handle_connection_error(self, error_message):
        QMessageBox.critical(self, "연결 오류", f"실시간 데이터 연결에 실패했습니다.\n{error_message}")

    def on_order_book_price_clicked(self, label_text: str):
        try:
            price_str = label_text.split(' ')[0].replace(',', '')
            price_str = price_str.split('(')[0].strip()
            self.entry_price_input.setText(price_str)
            self.format_entry_price() 

        except (ValueError, IndexError):
            pass

    def set_position_type(self, p_type: str):
        self.position_type = p_type
        self.update_button_style()
        self.calculate_and_display_target()

    def update_button_style(self):
        default_style = "background-color: #FFFFFF; color: black; padding: 10px; border: 1px solid #DCDCDC;"
        long_selected_style = "background-color: #dc3545; color: white; padding: 10px; border: 1px solid #dc3545;"
        short_selected_style = "background-color: #007BFF; color: white; padding: 10px; border: 1px solid #007BFF;"
        if self.position_type == 'long':
            self.long_button.setStyleSheet(long_selected_style)
            self.short_button.setStyleSheet(default_style)
        elif self.position_type == 'short':
            self.long_button.setStyleSheet(default_style)
            self.short_button.setStyleSheet(short_selected_style)
        else:
            self.long_button.setStyleSheet(default_style)
            self.short_button.setStyleSheet(default_style)

    def calculate_and_display_target(self):
        try:
            if not all([self.entry_price_input.text(), self.leverage_input.text(), self.roi_input.text()]):
                return
            entry_price = Decimal(self.entry_price_input.text())
            leverage = Decimal(self.leverage_input.text())
            target_roi_percent = Decimal(self.roi_input.text())
            if self.taker_radio.isChecked():
                fee_rate = Decimal(self.config.get('TRADING', 'taker_fee_rate'))
            else:
                fee_rate = Decimal(self.config.get('TRADING', 'maker_fee_rate'))

            if self.position_type is None:
                self.target_price_label.setText("Target Price: N/A")
                self.price_change_label.setText("NLV: N/A")
                return
            if entry_price <= Decimal('0') or leverage <= Decimal('0'):
                self.target_price_label.setText("유효한 값을 입력하세요.")
                self.price_change_label.setText("NLV: N/A")
                return

            target_price = calculate_target_price(entry_price, leverage, target_roi_percent, self.position_type,
                                                  fee_rate)

            if self.tick_size > Decimal('0'):
                if self.position_type == 'long':
                    rounding_mode = ROUND_CEILING
                else: 
                    rounding_mode = ROUND_FLOOR

                adjusted_target_price = target_price.quantize(self.tick_size, rounding=rounding_mode)
                
                precision = max(0, -self.tick_size.as_tuple().exponent) 
            else:
                adjusted_target_price = target_price
                precision = self.symbol_info.get('pricePrecision', 2)
                
            self.calculated_target_price_decimal = adjusted_target_price
            
            price_format_string = f"{{:,.{precision}f}}"
            
            self.target_price_label.setText(f"Target Price: ${price_format_string.format(adjusted_target_price)}")

            required_change_percent = (target_roi_percent / leverage) + (fee_rate * Decimal('100'))
            if self.position_type == 'long':
                color = "red"
                sign = "+"
            else:
                color = "blue"
                sign = "-"
            html_text = (f"NLV: <b style='color:{color};'>{sign}{required_change_percent:.2f}%</b>")
            self.price_change_label.setText(html_text)
        except Exception as e:
            logging.error(f"목표 가격 계산/표시 오류: {e}", exc_info=True)
            self.target_price_label.setText("Target Price: N/A")
            self.price_change_label.setText("NLV: N/A")


# --- 메인 앱 시작/표시 로직 ---

def _start_main_app(app, splash_manager):
    """타이머에 의해 호출되어 메인 앱을 초기화하고 스플래시를 닫습니다."""
    try:
        # 1. 메인 앱 초기화 및 설정 (아직 화면에 띄우지 않음)
        ex = BinanceCalculatorApp()
        
        # 2. 스플래시 화면 닫기 시작 (Fade-In 완료 및 닫는 시간 500ms 확보)
        # 스플래시가 완전히 사라질 시간(500ms)을 기다립니다.
        splash_manager.hide_splash(main_window=ex, duration_ms=500) 
        
        # 3. 📢 [핵심 수정] 스플래시가 닫힐 시간(500ms)이 지난 후에 메인 창을 띄우도록 QTimer를 사용
        QTimer.singleShot(500, lambda: _show_main_window(ex))
        
    except Exception as e:
        logging.critical("메인 앱 초기화 중 치명적인 오류 발생.", exc_info=True)
        QCoreApplication.quit()


def _show_main_window(main_window):
    """스플래시가 완전히 닫힌 후 메인 창을 띄웁니다."""
    main_window.show()
    logging.info("애플리케이션 시작.")


if __name__ == "__main__":
    setup_logging()
    
    try:
        # 1. QApplication을 가장 먼저 생성합니다. 
        app = QApplication(sys.argv)
        
        # 2. 스플래시 매니저 초기화 및 표시 (Fade-In 시작)
        splash_manager = SplashManager(image_path="splash_boot.png") 
        splash_manager.show_splash()
        
        # 3. 500ms 대기 후 메인 앱 초기화 시작 (Fade-In 애니메이션 시간을 벌어줌)
        QTimer.singleShot(500, lambda: _start_main_app(app, splash_manager)) 
        
        # 4. 메인 이벤트 루프 시작
        sys.exit(app.exec_()) 
        
    except Exception as e:
        logging.critical("애플리케이션 실행 중 치명적인 오류 발생.", exc_info=True)
        sys.exit(1)