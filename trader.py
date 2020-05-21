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

MAX_VOL_BUCKET = 8           # volume 최대 deque 저장 갯수 (시점 duration 통해 속도 계산 사용)
MAX_ACCEL_COUNT = 10         # volume accel history 저장 갯수
STD_MIN_BONG = 1             # 기준 분봉
STD_BUYABLE_ACCEL_SCALE = 10 # 전봉 대비 매수 가능 거래량 배율
STD_MIN_ACCEL_LEVEL = 59     # 절대적 거래량 속도 기준 (항상 이 속도 이상이 되어야 한다.)

def is_buyable(item_code, item_dict, kw):
    # 잔고가 있으면 안된다. (일단 샀으면 전량 매도될때까지 추가로 중간에 사지 않는다.)
    if kw.dict_holding.get(item_code) is None:
        return False
    else:
        if kw.dict_holding[item_code]["보유수량"] <= 0:
            return False

    # 현재 거래량 속도가 전분봉 속도 -> 전전 분봉속도 -> 전전전 분봉속도 대비 거래량 배율 조건이 맞아야 한다.
    cur_accel = item_dict["cur_vol_accel"]
    prev1_accel = item_dict["pre_min_vol_accel"]
    prev2_accel = item_dict["pre_before_min_vol_accel"]
    prev3_accel = item_dict["third_before_min_vol_accel"]
    if ((cur_accel < prev1_accel * STD_BUYABLE_ACCEL_SCALE) and
        (cur_accel < prev2_accel * STD_BUYABLE_ACCEL_SCALE) and
        (cur_accel < prev3_accel * STD_BUYABLE_ACCEL_SCALE)):
        return False

    # 거래량 배율 조건이 맞더라도 최소 거래량 속도를 만족해야 한다.
    cur_accel = item_dict["cur_vol_accel"]
    if cur_accel < STD_MIN_ACCEL_LEVEL:
        return False

    # 현재 분봉의 시가보다 높은 현재 가격이어야 한다.
    cur_real_price = 0
    if kw.dict_real_price.get(item_code) is not None:
        cur_real_price = kw.dict_real_price[item_code]["현재가"]

    cur_min_bong_open_price = item_code["open_price"]
    if cur_min_bong_open_price > cur_real_price:
        return False

    print("매수조건 확인 완료 --> 매수가능")
    return True


def is_sellable():
    pass

def auto_buy_sell(item_code, item_dict, kw):
    start_sec = time.time()
    # 실시간 현재 시세 정보 - 현재 가격, 현 분봉 시가, 거래량
    kw.one_min_price = {'date': [], 'open': [], 'high': [], 'low': [], 'cur': [], 'volume': []}

    kw.set_input_value("종목코드", item_code)
    kw.set_input_value("틱범위", STD_MIN_BONG)
    kw.set_input_value("수정주가구분", 1)
    kw.comm_rq_data("opt10080_req", "opt10080", 0, "0101")
    time.sleep(0.6)

    df_min = pd.DataFrame(kw.one_min_price, columns=['open', 'high', 'low', 'cur', 'volume'],
                          index=kw.one_min_price['date'])

    #print(df_min)

    # kw.ohlcv = {'date': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
    #
    # today = datetime.datetime.today().strftime("%Y%m%d")
    # kw.set_input_value("종목코드", item_code)
    # kw.set_input_value("기준일자", today)
    # kw.set_input_value("수정주가구분", 1)
    # kw.comm_rq_data("opt10081_req", "opt10081", 0, "0101")
    # time.sleep(0.6)
    #
    # df_day = pd.DataFrame(kw.ohlcv, columns=['open', 'high', 'low', 'close', 'volume'],
    #                       index=kw.ohlcv['date'])

    #print(df_day)

    # 실시간 시세 데이터 가져오기
    if kw.dict_real_price.get(item_code):
        print("실시간 데이터 없음")
        return
    real_price = kw.dict_real_price[item_code]["현재가"]
    real_volume = kw.dict_real_price[item_code]["누적거래량"]

    # 현재 시점 기준 8초간 거래량 및 거래량 속도 (큐 사용)
    # 전 분봉 정보 - 가격, 거래량, 전 분봉 거래량 속도
    '''
        current_price = 0  # 현재 가격
        open_price = 0  # 현재 분봉의 시가
        pre_min_vol_accel = 0  # 전 분봉의 거래량 속도
        pre_before_min_vol_accel = 0  # 전전 분봉의 거래량 속도
        third_before_min_vol_accel = 0 # 전전전 분봉의 거래량 속도
        deque_vol_cum = deque 당일 기준 누적 거래량 snapshot
        deque_vol_time = deque time.time() -- 끝 정수가 (초) snapshot 시간 
        cur_vol_accel = 0  # 현재 거래량 속도 (10초 기준)
        accel_history = 0  # 거래량 속도 저장 (히스토리)
    '''

    # item_dict['current_price'] = abs(df_min['cur'][0])
    item_dict['current_price'] = real_price
    item_dict['open_price'] = abs(df_min['open'][0])
    item_dict['pre_min_vol_accel'] = abs(df_min['volume'][1])/60
    item_dict['pre_before_min_vol_accel'] = abs(df_min['volume'][2]) / (STD_MIN_BONG * 60)
    item_dict['third_before_min_vol_accel'] = abs(df_min['volume'][3]) / (STD_MIN_BONG * 60)

    if len(item_dict['deque_vol_cum']) >= MAX_VOL_BUCKET: # 거래량 버겟을 어느정도 볼 것인가
        item_dict['deque_vol_cum'].pop()
        # item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'][0]))
        item_dict['deque_vol_cum'].appendleft(real_volume)
        item_dict['deque_vol_time'].pop()
        item_dict['deque_vol_time'].appendleft(time.time())
    else:
        # item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'][0]))
        item_dict['deque_vol_cum'].appendleft(real_volume)
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

    # 매수 가능여부 확인
    # 거래량 속도가 X배 이상 증가하고 현재 가격이 현재 분봉의 시가보다 높은 경우 매수 단계로 진입한다. (시장가 or 최우선호가)
    if is_buyable(item_code, item_dict, kw):
        accouns_num = int(kw.get_login_info("ACCOUNT_CNT"))
        accounts = kw.get_login_info("ACCNO")
        account = accounts.split(';')[0]

        kw.send_order('send_order_req', '0101', account, 1, item_code, item_dict["buy_target_num"], real_price,
                      '03', '')

    end_sec = time.time()
    print(item_code, item_dict['name'], accel, round(end_sec - start_sec, 2))






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
                               'buy_target_price': buy_price, 'buy_type': buy_type,
                               'min_vol_accel': min_vol_accel, 'name': name}

        auto_buy_sell(code, item_dict[code], kw)



    app.quit()