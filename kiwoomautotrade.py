
import sys
import math
import time
from collections import defaultdict

from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, QTimer

# 화면번호(중복 사용 금지)
SCREEN_LOGIN = "0000"
SCREEN_CONDITION = "0001"
SCREEN_TR_PRICE = "1001"      # opt10001
SCREEN_TR_BALANCE = "1002"    # opw00018
SCREEN_ORDER = "2001"

TARGET_BUY_AMOUNT = 1000000  # 100만원
TARGET_SELL_AMOUNT = 1000000 # 100만원

BUY_CONDITIONS = {"n1"}  # 편입 시 매수
SELL_CONDITION = "n1"               # 이탈 시 매도

class Kiwoom(QAxWidget):
    def __init__(self):
        super().__init__()
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")

        # 이벤트 연결
        self.OnEventConnect.connect(self._on_event_connect)
        self.OnReceiveConditionVer.connect(self._on_receive_condition_ver)
        self.OnReceiveRealCondition.connect(self._on_receive_real_condition)
        self.OnReceiveTrData.connect(self._on_receive_tr_data)
        self.OnReceiveChejanData.connect(self._on_receive_chejan_data)

        # 동기 대기를 위한 루프
        self.login_loop = QEventLoop()
        self.tr_loop = QEventLoop()

        # 상태
        self.account = None
        self.conditions = {}           # {idx: name}
        self.holdings = {}             # {code: qty}
        self.pending_orders = set()    # 중복 주문 방지 {code}
        self.last_prices = {}          # {code: price}
        self.server_gubun = None       # 모의/실서버 확인용

        # 초기 로그인 및 준비
        print("[INIT] 프로그램 초기화 완료")


    # -----------------------------
    # 로그인 및 초기 준비
    # -----------------------------
    def login(self):
        print("[LOGIN] 로그인 요청")
        self.dynamicCall("CommConnect()")
        self.login_loop.exec_()  # OnEventConnect에서 종료

    def _on_event_connect(self, err_code):
        if err_code == 0:
            print("[LOGIN] 로그인 성공")
            # 계좌 정보
            acc_list = self.dynamicCall('GetLoginInfo(QString)', "ACCNO")
            self.account = acc_list.split(';')[0]
            print(f"[LOGIN] 계좌번호: {self.account}")
            self.server_gubun = self.dynamicCall('GetLoginInfo(QString)', "GetServerGubun")
            print(f"[LOGIN] 서버구분(1=모의, 0=실): {self.server_gubun}")
            # 잔고 먼저 조회해서 보유 종목 캐시
            self.request_balance()

            # 조건식 로드
            self.dynamicCall("GetConditionLoad()")
        else:
            print(f"[LOGIN] 로그인 실패 코드: {err_code}")
        self.login_loop.quit()

    # -----------------------------
    # 잔고 조회(opw00018)
    # -----------------------------
    def request_balance(self):
        print("[BALANCE] 잔고 조회 요청")
        # TR 입력값 설정
        self.dynamicCall("SetInputValue(QString, QString)", "계좌번호", self.account)
        self.dynamicCall("SetInputValue(QString, QString)", "비밀번호", "0000")  # 보안설정에 저장되어 있으면 공란
        self.dynamicCall("SetInputValue(QString, QString)", "비밀번호입력매체구분", "00")
        self.dynamicCall("SetInputValue(QString, QString)", "조회구분", "2")  # 2: 종목별
        ret = self.dynamicCall("CommRqData(QString, QString, int, QString)", "opw00018_req", "opw00018", 0, SCREEN_TR_BALANCE)
        if ret != 0:
            print(f"[BALANCE] TR 요청 실패 ret={ret}")
            return
        self.tr_loop.exec_()  # _on_receive_tr_data에서 종료

    def _parse_balance(self, trcode, rqname):
        # 잔고 TR 파싱: opw00018의 '계좌평가잔고내역' 반복
        cnt = int(self.dynamicCall("GetRepeatCnt(QString, QString)", trcode, "계좌평가잔고내역"))
        holdings = {}
        for i in range(cnt):
            code = self.dynamicCall("CommGetData(QString, QString, QString, int, QString)",
                                    trcode, "", rqname, i, "종목코드").strip()
            qty_str = self.dynamicCall("CommGetData(QString, QString, QString, int, QString)",
                                       trcode, "", rqname, i, "보유수량").strip()
            try:
                qty = int(qty_str)
            except:
                qty = 0
            # 종목코드 앞에 'A'가 붙는 경우 제거
            code = code.replace("A", "")
            if code and qty > 0:
                holdings[code] = qty
        self.holdings = holdings
        print(f"[BALANCE] 보유종목: {self.holdings}")

    # -----------------------------
    # 조건식 로드 및 실시간 구독
    # -----------------------------
    def _on_receive_condition_ver(self, bRet, msg):
        if bRet == 1:
            raw = self.dynamicCall("GetConditionNameList()")  # '0^조건명;1^조건명;...'
            print(f"[COND] 조건 목록: {raw}")
            conds = {}
            for item in raw.split(';'):
                if not item: continue
                idx, name = item.split('^')
                conds[int(idx)] = name
            self.conditions = conds

            # 원하는 조건 이름(n1, n2, n3, n10)을 인덱스로 매핑
            wanted = {"n1"}
            to_subscribe = []
            for idx, name in conds.items():
                if name in wanted:
                    to_subscribe.append((idx, name))

            if not to_subscribe:
                print("[COND] 대상 조건을 찾지 못했습니다. (n1, n2, n3, n10)")
                return

            # 각 조건 실시간 구독 시작(type=1)
            for idx, name in to_subscribe:
                self.dynamicCall("SendCondition(QString, QString, int, int)", SCREEN_CONDITION, name, idx, 1)
                print(f"[COND] 실시간 구독 시작: {name} (idx={idx})")
        else:
            print(f"[COND] 조건 로드 실패: {msg}")

    def _on_receive_real_condition(self, code, type, cond_name, cond_index):
        # type: 'I' 편입, 'D' 이탈
        code = code.strip()
        event = "편입(I)" if type == 'I' else "이탈(D)"
        print(f"[COND] {cond_name} {event}: {code}")

        # 매수 트리거: n1/n2/n3 편입
        if type == 'I' and cond_name in BUY_CONDITIONS:
            if code in self.holdings:
                print(f"[BUY] 이미 보유 중이라 매수 스킵: {code}")
                return
            if code in self.pending_orders:
                print(f"[BUY] 진행 중 주문 있어 스킵: {code}")
                return
            self.buy_market_amount(code, TARGET_BUY_AMOUNT)

        # 매도 트리거: n10 이탈
        if type == 'D' and cond_name == SELL_CONDITION:
            if code not in self.holdings:
                print(f"[SELL] 보유 없음으로 스킵: {code}")
                return
            if code in self.pending_orders:
                print(f"[SELL] 진행 중 주문 있어 스킵: {code}")
                return
            self.sell_market_amount(code, TARGET_SELL_AMOUNT)

    # -----------------------------
    # 현재가 조회(opt10001)로 수량 산출
    # -----------------------------
    def request_price(self, code):
        # opt10001: 주식 기본정보, 현재가 FID
        self.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        ret = self.dynamicCall("CommRqData(QString, QString, int, QString)", "opt10001_req", "opt10001", 0, SCREEN_TR_PRICE)
        if ret != 0:
            print(f"[PRICE] TR 요청 실패 ret={ret} code={code}")
            return None
        self.tr_loop.exec_()  # _on_receive_tr_data에서 종료
        price = self.last_prices.get(code)
        return price

    def _parse_price(self, trcode, rqname):
        if rqname != "opt10001_req":
            return
        code = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, 0, "종목코드").strip()
        curr_str = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, 0, "현재가").strip()
        code = code.replace("A", "")
        try:
            # 현재가는 -부호 포함 문자열일 수 있음 -> 절대값
            price = abs(int(curr_str))
        except:
            price = None
        if code and price:
            self.last_prices[code] = price
            print(f"[PRICE] {code} 현재가: {price}")

    # -----------------------------
    # 주문 로직(시장가 100만원)
    # -----------------------------
    def buy_market_amount(self, code, amount):
        price = self.request_price(code)
        if not price or price <= 0:
            print(f"[BUY] 현재가 조회 실패로 매수 불가: {code}")
            return
        qty = amount // price
        if qty <= 0:
            print(f"[BUY] 100만원으로 매수 가능한 수량이 0: price={price}")
            return

        rqname = "buy_by_condition"
        order_type = 1           # 신규매수
        hoga = "03"              # 시장가
        self.pending_orders.add(code)
        print(f"[BUY] 주문 전송: {code} 수량={qty} 시장가")

        ret = self.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            rqname, SCREEN_ORDER, self.account, order_type, code, int(qty), 0, hoga, ""
        )
        if ret != 0:
            print(f"[BUY] 주문 실패 ret={ret} code={code}")
            self.pending_orders.discard(code)

    def sell_market_amount(self, code, amount):
        price = self.request_price(code)
        if not price or price <= 0:
            print(f"[SELL] 현재가 조회 실패로 매도 불가: {code}")
            return
        hold_qty = self.holdings.get(code, 0)
        target_qty = amount // price
        qty = min(hold_qty, target_qty)
        if qty <= 0:
            print(f"[SELL] 매도 가능한 수량이 0: hold={hold_qty}, price={price}")
            return

        rqname = "sell_by_condition"
        order_type = 2           # 신규매도
        hoga = "03"              # 시장가
        self.pending_orders.add(code)
        print(f"[SELL] 주문 전송: {code} 수량={qty} 시장가")

        ret = self.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            rqname, SCREEN_ORDER, self.account, order_type, code, int(qty), 0, hoga, ""
        )
        if ret != 0:
            print(f"[SELL] 주문 실패 ret={ret} code={code}")
            self.pending_orders.discard(code)

    # -----------------------------
    # TR 수신
    # -----------------------------
    def _on_receive_tr_data(self, screenNo, rqname, trcode, recordName, prevNext, dataLen, errCode, msg1, msg2):
        try:
            if rqname == "opw00018_req":
                self._parse_balance(trcode, rqname)
            elif rqname == "opt10001_req":
                self._parse_price(trcode, rqname)
            else:
                print(f"[TR] 수신: {rqname}")
        finally:
            # 다음 페이지(prevNext) 처리 필요 시 확장 가능. 여기선 단건만.
            self.tr_loop.quit()

    # -----------------------------
    # 체잔 수신(주문/체결/잔고 반영)
    # -----------------------------
    def _on_receive_chejan_data(self, gubun, item_cnt, fid_list):
        # gubun: '0' 주문체결, '1' 잔고변경
        # 잔고 변경 시 보유 종목 갱신(간단히 재조회)
        print(f"[CHEJAN] gubun={gubun} item_cnt={item_cnt}")
        # 주문 진행 중인 코드 정리: 체결/취소 이벤트에서 원주문/종목코드 FID를 읽어 처리하는 게 베스트.
        # 여기서는 안전하게 잔고를 재조회하여 pending 해제.
        QTimer.singleShot(300, self._refresh_after_chejan)

    def _refresh_after_chejan(self):
        self.request_balance()
        # pending 해제는 잔고 기반으로 간단 처리(실전은 주문번호 상태 테이블 권장)
        self.pending_orders.clear()

def main():
    app = QApplication(sys.argv)
    kiwoom = Kiwoom()
    kiwoom.login()
    # 이벤트 루프 실행
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
