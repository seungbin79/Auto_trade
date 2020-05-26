# -*- coding: utf-8 -*-

import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5 import uic
from Kiwoom import *
import multiprocessing as mp
import pandas as pd
import datetime
import time
from collections import deque
import util

MAX_VOL_BUCKET = 8                      # volume 최대 deque 저장 갯수 (시점 duration 통해 속도 계산 사용)
MAX_ACCEL_COUNT = 10                    # volume accel history 저장 갯수
STD_MIN_BONG = 1                        # 기준 분봉
STD_BUYABLE_ACCEL_SCALE = 10            # 전봉 대비 매수 가능 거래량 배율
STD_MIN_ACCEL_LEVEL = 100               # 절대적 거래량 속도 기준 (항상 이 속도 이상이 되어야 한다.) 종목별로 설정해야 할듯
STD_CUT_MIN_ACCEL_RATIO = 0.5           # 절대적 매도를 위한 전봉 비교를 위한 현재 거래량 속도 대비 비율
STD_CUT_BUYING_TIME_ACCEL_RATIO = 0.4   # 매수 시점 대비 거래량 속도가 40% 수준인 경우 CUT
STD_CUT_BUYING_PRICE_RATIO = 0.2        # 매수가 아래 2% 까지 허용

def is_buyable(item_code, item_dict, kw):
    # false_cnt = 0 이면 매수 조건이 부합됨을 의미 아닌 경우 매수 조건 안됨
    false_cnt = 0

    # ===========================================================================
    # 잔고가 있으면 안된다. (일단 샀으면 전량 매도될때까지 추가로 중간에 사지 않는다.)
    # ===========================================================================
    chejango = item_dict["chejango"]
    if chejango > 0:
        false_cnt += 1

    # ===========================================================================
    # 현재 거래량 속도가 전분봉 속도 -> 전전 분봉속도 -> 전전전 분봉속도 대비 거래량 배율 조건이 맞아야 한다.
    # ===========================================================================
    cur_accel = item_dict["cur_vol_accel"]
    prev1_accel = item_dict["pre_min_vol_accel"]
    prev2_accel = item_dict["pre_before_min_vol_accel"]
    prev3_accel = item_dict["third_before_min_vol_accel"]
    if ((cur_accel < prev1_accel * STD_BUYABLE_ACCEL_SCALE) and
        (cur_accel < prev2_accel * STD_BUYABLE_ACCEL_SCALE) and
        (cur_accel < prev3_accel * STD_BUYABLE_ACCEL_SCALE)):
        false_cnt += 1

    # ===========================================================================
    # 거래량 배율 조건이 맞더라도 최소 거래량 속도를 만족해야 한다.
    # ===========================================================================
    cur_accel = item_dict["cur_vol_accel"]
    if cur_accel < STD_MIN_ACCEL_LEVEL:
        false_cnt += 1

    # ===========================================================================
    # 현재 분봉의 시가보다 높은 현재 가격이어야 한다.
    # ===========================================================================
    cur_real_price = item_dict["current_price"]
    cur_min_bong_open_price = item_dict["open_price"]
    if cur_min_bong_open_price > cur_real_price:
        false_cnt += 1

    false_idx = '매수불가'
    if false_cnt == 0:
        false_idx = '매수가능'

    print("02, %s, 잔고: %s, 현속도: %s, 전봉속도*배율: %s, 전전봉속도*배율: %s, 전전전봉속도*배율: %s, 절대최소속도: %s, 현가: %s, 현분봉시작가: %s "
          % (false_idx, chejango, round(cur_accel), round(prev1_accel * STD_BUYABLE_ACCEL_SCALE), round(prev2_accel * STD_BUYABLE_ACCEL_SCALE),
             round(prev3_accel * STD_BUYABLE_ACCEL_SCALE), STD_MIN_ACCEL_LEVEL, cur_real_price, cur_min_bong_open_price))

    if false_cnt == 0:
        return True

    return False


def is_sellable(item_code, item_dict, kw):
    false_cnt = 0
    # ===========================================================================
    # 잔고가 있어야 한다.
    # ===========================================================================
    chejango = item_dict["chejango"]
    if chejango > 0:
        false_cnt += 1

    # 매수시 거래량 속도보다 현재 속도가 현저히 줄어드는 경우
    buying_time_accel = item_dict['buying_time_accel']
    current_accel = item_dict['cur_vol_accel']
    if buying_time_accel * STD_CUT_BUYING_TIME_ACCEL_RATIO >= current_accel:
        false_cnt += 1

    # 거래량 속도가 줄어드는 경우 accel_history 4 단계 연속으로 빠지는 경우
    accel_hist = item_dict['accel_history']
    hist_1 = 0
    hist_2 = 0
    hist_3 = 0
    if len(accel_hist) >= 4:
        hist_1 = accel_hist[1]
        hist_2 = accel_hist[2]
        hist_3 = accel_hist[3]
        if (accel_hist[0] <= hist_1) and (hist_1 <= hist_2) and (hist_2 <= hist_3):
           false_cnt += 1

    # 전 분봉 속도 대비 accel이 현저희 낮을 때
    pre_min_vol_accel = item_dict['pre_min_vol_accel']
    current_accel = item_dict['cur_vol_accel']
    if pre_min_vol_accel * STD_CUT_MIN_ACCEL_RATIO >= current_accel:
        false_cnt += 1

    # 가격이 매입가 보다 절대수치% 만큼 빠진 경우
    buying_price = item_dict["buying_time_price"]
    current_price = item_dict['current_price']
    if buying_price * (1 - STD_CUT_BUYING_PRICE_RATIO) >= current_price:
        false_cnt += 1

    false_idx = "매도불가"
    if false_cnt > 0:
        false_idx = "매도가능"

    print("03, %s, 잔고: %s, 매수시속도: %s, 현재속도: %s, 현속도-1: %s, 현속도-2: %s, 현속도-3: %s, 전분봉속도: %s, 매수가격: %s, 현재가격: %s "
          % (false_idx, chejango, buying_time_accel, current_accel, hist_1, hist_2, hist_3, pre_min_vol_accel, buying_price, current_price))

    if false_cnt > 0:
        return True

    return False

def auto_buy_sell(item_code, item_dict, kw):
    accounts = kw.get_login_info("ACCNO")
    account_number = accounts.split(';')[0]

    #===========================================================================
    # 현재 분봉 시세 정보 - 현재 가격, 현 분봉 시가, 거래량
    # ===========================================================================
    kw.one_min_price = {'date': [], 'open': [], 'high': [], 'low': [], 'cur': [], 'volume': []}

    kw.set_input_value("종목코드", item_code)
    kw.set_input_value("틱범위", STD_MIN_BONG)
    kw.set_input_value("수정주가구분", 1)
    kw.comm_rq_data("opt10080_req", "opt10080", 0, "0101")

    df_min = pd.DataFrame(kw.one_min_price, columns=['open', 'high', 'low', 'cur', 'volume'],
                          index=kw.one_min_price['date'])

    #print(df_min)

    # ===========================================================================
    # 현재 일 시세 정보 - 현재 가격, 현 분봉 시가, 거래량
    # ===========================================================================
    kw.ohlcv = {'date': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}

    today = datetime.datetime.today().strftime("%Y%m%d")
    kw.set_input_value("종목코드", item_code)
    kw.set_input_value("기준일자", today)
    kw.set_input_value("수정주가구분", 1)
    kw.comm_rq_data("opt10081_req", "opt10081", 0, "0101")

    df_day = pd.DataFrame(kw.ohlcv, columns=['open', 'high', 'low', 'close', 'volume'],
                          index=kw.ohlcv['date'])

    #print(df_day)

    # ===========================================================================
    # 잔고 정보
    # ===========================================================================
    kw.profit_dict = {}
    kw.set_input_value("계좌번호", account_number)
    kw.comm_rq_data("opt10085_req", "opt10085", 0, "2000")

    if kw.profit_dict.get(item_code) is not None:
        item_dict["chejango"] = kw.profit_dict[item_code]["chejan"]

    # ===========================================================================
    # 현재 시점 기준 MAX_VOL_BUCKET 초간 거래량 및 거래량 속도 (큐 사용)
    # 전 분봉 정보 - 가격, 거래량, 전 분봉 거래량 속도
    # ===========================================================================

    '''
    current_price = 0  # 현재 가격
    open_price = 0  # 현재 분봉의 시가
    pre_min_vol_accel = 0  # 전 분봉의 거래량 속도
    pre_before_min_vol_accel = 0  # 전전 분봉의 거래량 속도
    third_before_min_vol_accel = 0 # 전전전 분봉의 거래량 속도
    deque_vol_cum = deque 당일 기준 누적 거래량 snapshot
    deque_vol_time = deque time.time() -- 끝 정수가 (초) snapshot 시간 
    cur_vol_accel = 0  # 현재 거래량 속도 (10초 기준)
    accel_history = 0  # 거래량 속도 저장 
    buying_time_accel = 0 # 매수시 거래량 속도
    buing_time_price = 0 # 매수가
    chejango = 0 # 잔고정보
    '''

    item_dict['current_price'] = abs(df_min['cur'][0])
    item_dict['open_price'] = abs(df_min['open'][0])
    item_dict['pre_min_vol_accel'] = abs(df_min['volume'][1])/60
    item_dict['pre_before_min_vol_accel'] = abs(df_min['volume'][2]) / (STD_MIN_BONG * 60)
    item_dict['third_before_min_vol_accel'] = abs(df_min['volume'][3]) / (STD_MIN_BONG * 60)

    if len(item_dict['deque_vol_cum']) >= MAX_VOL_BUCKET: # 거래량 버겟을 어느정도 볼 것인가
        item_dict['deque_vol_cum'].pop()
        item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'][0]))
        item_dict['deque_vol_time'].pop()
        item_dict['deque_vol_time'].appendleft(time.time())
    else:
        item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'][0]))
        item_dict['deque_vol_time'].appendleft(time.time())

    # 거래량 속도 계산
    accel = 0
    if max(item_dict['deque_vol_time']) - min(item_dict['deque_vol_time']) == 0: # 분모가 0 이면 안된다.
        accel = 0
    else:
        accel = int((max(item_dict['deque_vol_cum']) - min(item_dict['deque_vol_cum'])) / (max(item_dict['deque_vol_time']) - min(item_dict['deque_vol_time'])))
    item_dict['cur_vol_accel'] = accel

    # 거래량 속도 history 저장
    if len(item_dict['accel_history']) >= MAX_ACCEL_COUNT:
        item_dict['accel_history'].pop()
        item_dict['accel_history'].appendleft(accel)

    # 콘솔 출력
    print("01, %s, 종목: %s, 현재가: %s, 전분봉거래량: %s, 현분봉거래량: %s, 누적거래량: %s, 전분봉속도: %s, 현분봉속도: %s " %
          (util.get_str_now(), item_dict['name'], item_dict['current_price'], round(abs(df_min['volume'][1])), round(abs(df_min['volume'][0])), round(abs(df_day['volume'][0])),
           item_dict['pre_min_vol_accel'], item_dict['cur_vol_accel']))

    # ===========================================================================
    # 매수 가능여부 확인 및 매수 진행
    # 거래량 속도가 X배 이상 증가하고 현재 가격이 현재 분봉의 시가보다 높은 경우 매수 단계로 진입한다. (시장가 or 최우선호가)
    # ===========================================================================
    if is_buyable(item_code, item_dict, kw):
        hoga_lookup = {'지정가': "00", '시장가': "03", '조건부지정가': '05', '최유리지정가': '06', '최우선지정가': '07'}
        kw.send_order('send_order_req', '0101', account_number, 1, item_code, item_dict["buy_target_num"], item_dict['current_price'],
                      hoga_lookup[item_dict["buy_type"]], '')

        time.sleep(0.5)

        # 매수 후 잠시 후 주문취소 (미체결에 대한 주문취소) - 일단 시장가로 대응할거라서..미체결은 없다.
        # time.sleep(0.5)
        # to do

        # 매수시 거래량 속도 저장
        item_dict['buying_time_accel'] = item_dict['cur_vol_accel']

        # 체결이 되면 체결된 수량 및 매수가 item_dict 에 업데이트
        kw.profit_dict = {}
        kw.set_input_value("계좌번호", account_number)
        kw.comm_rq_data("opt10085_req", "opt10085", 0, "2000")

        if kw.profit_dict.get(item_code) is not None:
            item_dict["chejango"] = kw.profit_dict[item_code]["chejan"]
            item_dict["buying_time_price"] = kw.profit_dict[item_code]["buying_price"]



    # ===========================================================================
    # 매도 가능여부 확인 및 매도 진행
    # ===========================================================================
    if is_sellable(item_code, item_dict, kw) and item_dict["chejango"] > 0:
        hoga_lookup = {'지정가': "00", '시장가': "03", '조건부지정가': '05', '최유리지정가': '06', '최우선지정가': '07'}
        kw.send_order('send_order_req', '0101', account_number, 1, item_code, item_dict["chejango"],
                      item_dict['current_price'],
                      hoga_lookup[item_dict["sell_type"]], '')

        time.sleep(0.5)

        # 시장가 매도가 아닌경우 매도 루프 만들어야 한다.

        # 체결이 되면 체결된 수량 및 매수가 item_dict 에 업데이트
        kw.profit_dict = {}
        kw.set_input_value("계좌번호", account_number)
        kw.comm_rq_data("opt10085_req", "opt10085", 0, "2000")

        if kw.profit_dict.get(item_code) is not None:
            item_dict["chejango"] = kw.profit_dict[item_code]["chejan"]
            item_dict["buying_time_price"] = 0

    time.sleep(1.5)




if __name__ == "__main__":
    app = QApplication(sys.argv)
    kw = Kiwoom.instance()
    kw.comm_connect()

    # 종목코드;매수타입;매수총수량;매수총가격(목표);최소기준거래속도
    f = open("buy_list.txt", 'rt', encoding='UTF8')
    buy_list = f.readlines()
    f.close()


    '''
    current_price = 0  # 현재 가격
    open_price = 0  # 현재 분봉의 시가
    pre_min_vol_accel = 0  # 전 분봉의 거래량 속도
    pre_before_min_vol_accel = 0  # 전전 분봉의 거래량 속도
    third_before_min_vol_accel = 0 # 전전전 분봉의 거래량 속도
    deque_vol_cum = deque 당일 기준 누적 거래량 snapshot
    deque_vol_time = deque time.time() -- 끝 정수가 (초) snapshot 시간 
    cur_vol_accel = 0  # 현재 거래량 속도 (10초 기준)
    accel_history = 0  # 거래량 속도 저장 
    buying_time_accel = 0 # 매수시 거래량
    buying_time_price = 0 # 매수가
    chejango = 0 # 잔고정보
    '''
    item_dict = {}

    loop_item = deque(buy_list)

    while True:
        buy_item = loop_item.popleft()
        loop_item.append(buy_item)

        split_row_data = buy_item.split(';')
        code = split_row_data[0]
        name = kw.get_master_code_name(code)
        buy_type = split_row_data[1]
        buy_num = split_row_data[2]
        buy_price = split_row_data[3]
        min_vol_accel = split_row_data[4]

        if item_dict.get(code) is None:
            dq_vol = deque()
            dq_time = deque()
            dq_accel = deque()
            item_dict[code] = {'current_price': 0, 'open_price': 0, 'pre_min_vol_accel': 0,
                               'pre_before_min_vol_accel': 0, 'third_before_min_vol_accel': 0,
                               'deque_vol_cum': dq_vol, 'accel_history': dq_accel,
                               'deque_vol_time': dq_time, 'buy_target_num': buy_num,
                               'buy_target_price': buy_price, 'buy_type': buy_type, 'sell_type': buy_type,
                               'min_vol_accel': min_vol_accel, 'name': name,
                               'buying_time_accel': 0, 'chejango': 0, 'buying_time_price': 0}

        auto_buy_sell(code, item_dict[code], kw)



    app.quit()