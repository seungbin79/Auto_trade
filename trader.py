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

MAX_VOL_BUCKET = 4                      # volume 최대 deque 저장 갯수 (시점 duration 통해 속도 계산 사용)
MAX_PRICE_BUCKET = 3                    # Price 최대 deque 저장
MAX_ACCEL_COUNT = 10                    # volume accel history 저장 갯수
MAX_GRADI_COUNT = 5                     # Gradient history 최대 저장 갯수
MA_SHORT_TERM = 11                      # 단기구간 이평 범위
MA_MID_TERM = 54                        # 중기구간 이평 범위
MA_LONG_TERM = 105                      # 장기구간 이평 범위
STD_MIN_BONG = 1                        # 기준 분봉
STD_BUYABLE_ACCEL_SCALE = 7             # 전봉 대비 매수 가능 거래속도 배율. (종목별로 설정되어야 한다.)
STD_CUT_MIN_ACCEL_RATIO = 0.5           # 절대적 매도를 위한 전봉 비교를 위한 현재 거래량 속도 대비 비율
STD_CUT_BUYING_TIME_ACCEL_RATIO = 0.4   # 매수 시점 대비 거래량 속도가 40% 수준인 경우 CUT
STD_CUT_BUYING_PRICE_RATIO = 0.02       # 매수가 아래 2% 까지 허용

def cal_accel_multiple(accel, item_dict):
    accel_scale = 0
    if accel < item_dict['std_accel_1']:
        accel_scale = accel * item_dict['std_accel_1_multiple']
    elif item_dict['std_accel_1'] <= accel < item_dict['std_accel_2']:
        accel_scale = accel * item_dict['std_accel_2_multiple']
    elif item_dict['std_accel_2'] <= accel < item_dict['std_accel_3']:
        accel_scale = accel * item_dict['std_accel_3_multiple']
    elif item_dict['std_accel_3'] <= accel < item_dict['std_accel_4']:
        accel_scale = accel * item_dict['std_accel_4_multiple']
    else:
        accel_scale = 0

    return accel_scale

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
    # 거래량 속도 구간에 따라 곱해지는 배율이 달라진다.
    # ===========================================================================
    cur_accel = item_dict["cur_vol_accel"]
    prev1_accel = item_dict["pre_min_vol_accel"]
    prev2_accel = item_dict["pre_before_min_vol_accel"]
    prev3_accel = item_dict["third_before_min_vol_accel"]

    prev1_accel_scale = cal_accel_multiple(prev1_accel, item_dict)
    prev2_accel_scale = cal_accel_multiple(prev2_accel, item_dict)
    prev3_accel_scale = cal_accel_multiple(prev3_accel, item_dict)

    if ((cur_accel < prev1_accel_scale) and
        (cur_accel < prev2_accel_scale) and
        (cur_accel < prev3_accel_scale)):
        false_cnt += 1

    # ===========================================================================
    # 거래량 배율 조건이 맞더라도 최소 거래량 속도를 만족해야 한다.
    # ===========================================================================
    cur_accel = item_dict["cur_vol_accel"]
    min_vol_accel = item_dict["min_vol_accel"]
    if cur_accel < min_vol_accel:
        false_cnt += 1

    # ===========================================================================
    # 현재 가격이 단기이평 보다 높은 지 않은 경우 매수 금지
    # ===========================================================================
    ma_short = item_dict['ma_short_term']
    current_price = item_dict['current_price']
    if ma_short >= current_price:
        false_cnt += 1

    # ===========================================================================
    # 현재 분봉의 시가보다 높은 현재 가격이어야 한다.
    # ===========================================================================
    cur_real_price = item_dict["current_price"]
    cur_min_bong_open_price = item_dict["open_price"]
    if cur_min_bong_open_price > cur_real_price:
        false_cnt += 1

    # ===========================================================================
    # 가격 기울기 현황 합이 양수 이어야 한다.
    # ===========================================================================
    sum_gradient = sum(item_dict['price_gradient_history'])
    if sum_gradient < 0:
        false_cnt += 1

    false_idx = '매수불가'
    if false_cnt == 0:
        false_idx = '매수가능'

    print("02, %s, 종목: %s, 잔고: %s, 현속도: %s, 전전전봉속도*배율: %s, 전전봉속도*배율: %s, 전봉속도*배율: %s, 절대최소속도: %s, 현가: %s, 현분봉시작가: %s, 단기이평: %s, 기울기합: %s "
          % (false_idx, item_dict['name'], chejango, round(cur_accel), round(prev3_accel_scale), round(prev2_accel_scale),
             round(prev1_accel_scale), min_vol_accel, cur_real_price, cur_min_bong_open_price, round(ma_short), sum_gradient))

    if false_cnt == 0:
        return True

    return False


def is_sellable(item_code, item_dict, kw):
    false_cnt = 0

    # ===========================================================================
    # 매수시 거래량 속도보다 현재 속도가 현저히 줄어드는 경우
    # ===========================================================================
    buying_time_accel = item_dict['buying_time_accel']
    current_accel = item_dict['cur_vol_accel']
    if buying_time_accel * STD_CUT_BUYING_TIME_ACCEL_RATIO >= current_accel:
        false_cnt += 1

    # ===========================================================================
    # 거래량 속도가 줄어드는 경우 accel_history 4 단계 연속으로 빠지는 경우
    # ===========================================================================
    accel_hist = item_dict['accel_history']
    hist_1 = -999
    hist_2 = -999
    hist_3 = -999
    if len(accel_hist) >= 4:
        hist_1 = accel_hist[1]
        hist_2 = accel_hist[2]
        hist_3 = accel_hist[3]
        if (accel_hist[0] <= hist_1) and (hist_1 <= hist_2) and (hist_2 <= hist_3):
           false_cnt += 1

    # ===========================================================================
    # 전 분봉 속도 대비 accel이 현저희 낮을 때
    # ===========================================================================
    pre_min_vol_accel = item_dict['pre_min_vol_accel']
    current_accel = item_dict['cur_vol_accel']
    if pre_min_vol_accel * STD_CUT_MIN_ACCEL_RATIO >= current_accel:
        false_cnt += 1

    # ===========================================================================
    # 가격이 매입가 보다 절대수치% 만큼 빠진 경우
    # ===========================================================================
    buying_price = item_dict["buying_time_price"]
    current_price = item_dict['current_price']
    if buying_price * (1 - STD_CUT_BUYING_PRICE_RATIO) >= current_price:
        false_cnt += 1

    # ===========================================================================
    # 가격 기울기 합이 음수인 경우
    # ===========================================================================
    sum_gradient = sum(item_dict['price_gradient_history'])
    if sum_gradient < 0:
        false_cnt += 1

    false_idx = "매도불가"
    if false_cnt > 0:
        false_idx = "매도가능"

    print("03, %s, 종목: %s, 잔고: %s, 매수시속도: %s, 현재속도: %s, 현속도-1: %s, 현속도-2: %s, 현속도-3: %s, 전분봉속도: %s, 매수가격: %s, 현재가격: %s, 기울기합: %s"
          % (false_idx, item_dict['name'], item_dict["chejango"], round(buying_time_accel), round(current_accel), round(hist_1), round(hist_2), round(hist_3),
             round(pre_min_vol_accel), buying_price, current_price, sum_gradient))

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

    while df_min.index.size == 0:
        print('not found min. data...try again...')
        time.sleep(0.2)
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

    while df_day.index.size == 0:
        print('not found day. data...try again...')
        time.sleep(0.2)
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
    kw.reset_opw00018_output()
    kw.set_input_value("계좌번호", account_number)
    kw.comm_rq_data("opw00018_req", "opw00018", 0, "2000")
    while kw.remained_data:
        time.sleep(1)
        kw.set_input_value("계좌번호", account_number)
        kw.comm_rq_data("opw00018_req", "opw00018", 0, "2000")

    if kw.opw00018_output['multi'].get(item_code) is not None:
        item_dict["chejango"] =kw.opw00018_output['multi'][item_code]["quantity"]
        item_dict["buying_time_price"] = kw.opw00018_output['multi'][item_code]["purchase_price"]
    else:
        item_dict["chejango"] = 0
        item_dict["buying_time_price"] = 0



    # ===========================================================================
    # 현재 시점 기준 MAX_VOL_BUCKET 초간 거래량 및 거래량 속도 (큐 사용)
    # 전 분봉 정보 - 가격, 거래량, 전 분봉 거래량 속도
    # ===========================================================================

    # 분봉 pandas에 이동평균 정보 추가
    df_min['ma_short_term'] = abs(df_min['cur']).rolling(window=MA_SHORT_TERM).mean()
    df_min['ma_mid_term'] = abs(df_min['cur']).rolling(window=MA_MID_TERM).mean()
    df_min['ma_long_term'] = abs(df_min['cur']).rolling(window=MA_LONG_TERM).mean()

    item_dict['current_price'] = abs(df_min['cur'].iloc[0])
    item_dict['open_price'] = abs(df_min['open'].iloc[0])
    item_dict['pre_min_vol_accel'] = abs(df_min['volume'].iloc[1])/60
    item_dict['pre_before_min_vol_accel'] = abs(df_min['volume'].iloc[2]) / (STD_MIN_BONG * 60)
    item_dict['third_before_min_vol_accel'] = abs(df_min['volume'].iloc[3]) / (STD_MIN_BONG * 60)

    item_dict['ma_short_term'] = df_min['ma_short_term'].iloc[MA_SHORT_TERM-1]
    item_dict['ma_mid_term'] = df_min['ma_mid_term'].iloc[MA_MID_TERM-1]
    item_dict['ma_long_term'] = df_min['ma_long_term'].iloc[MA_LONG_TERM-1]

    if len(item_dict['deque_vol_cum']) >= MAX_VOL_BUCKET: # 거래량 버겟을 어느정도 볼 것인가
        item_dict['deque_vol_cum'].pop()
        item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'].iloc[0]))
        item_dict['deque_vol_time'].pop()
        item_dict['deque_vol_time'].appendleft(time.time())
    else:
        item_dict['deque_vol_cum'].appendleft(abs(df_day['volume'].iloc[0]))
        item_dict['deque_vol_time'].appendleft(time.time())

    if len(item_dict['deque_price']) >= MAX_PRICE_BUCKET: # price 버겟을 어느정도 볼 것인가
        item_dict['deque_price'].pop()
        item_dict['deque_price'].appendleft(abs(df_min['cur'].iloc[0]))
        item_dict['deque_price_time'].pop()
        item_dict['deque_price_time'].appendleft(time.time())
    else:
        item_dict['deque_price'].appendleft(abs(df_min['cur'].iloc[0]))
        item_dict['deque_price_time'].appendleft(time.time())

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
    else:
        item_dict['accel_history'].appendleft(accel)

    # 가격 기울기 계산
    deque_price_size = len(item_dict['deque_price'])
    gradi = 0
    if (item_dict['deque_price'][0] - item_dict['deque_price'][deque_price_size-1]) != 0:
        gradi = (item_dict['deque_price'][0] - item_dict['deque_price'][deque_price_size-1]) / ((item_dict['deque_price_time'][0] - item_dict['deque_price_time'][deque_price_size-1]))
    gradi = round(gradi, 3)
    item_dict['price_gradient'] = gradi

    #가격 기울기 히스토리 저장
    if len(item_dict['price_gradient_history']) >= MAX_GRADI_COUNT:
        item_dict['price_gradient_history'].pop()
        item_dict['price_gradient_history'].appendleft(gradi)
    else:
        item_dict['price_gradient_history'].appendleft(gradi)

    # 콘솔 출력
    print("01, %s, 종목: %s, 현재가: %s, 전분봉거래량: %s, 현분봉거래량: %s, 누적거래량: %s, 전전전분봉속도: %s, 전전분봉속도: %s, 전분봉속도: %s, 현분봉속도: %s, 단기이평: %s, 중기이평: %s, 장기이평: %s " %
          (util.get_str_now(), item_dict['name'], item_dict['current_price'], round(abs(df_min['volume'].iloc[1])), round(abs(df_min['volume'].iloc[0])), round(abs(df_day['volume'].iloc[0])),
           round(item_dict['third_before_min_vol_accel']), round(item_dict['pre_before_min_vol_accel']), round(item_dict['pre_min_vol_accel']), item_dict['cur_vol_accel'],
           round(item_dict['ma_short_term']), round(item_dict['ma_mid_term']), round(item_dict['ma_long_term'])))
    print('01, 종목: %s, 현기울기: %s, 가격현황: %s, 기울기현황: %s'
          % (item_dict['name'], item_dict['price_gradient'], list(item_dict['deque_price']), list(item_dict['price_gradient_history'])))

    # ===========================================================================
    # 매수 가능여부 확인 및 매수 진행
    # 거래량 속도가 X배 이상 증가하고 현재 가격이 현재 분봉의 시가보다 높은 경우 매수 단계로 진입한다. (시장가 or 최우선호가)
    # ===========================================================================
    if is_buyable(item_code, item_dict, kw):
        hoga_lookup = {'지정가': "00", '시장가': "03", '조건부지정가': '05', '최유리지정가': '06', '최우선지정가': '07'}
        kw.send_order('send_order_req', '0101', account_number, 1, item_code, item_dict["buy_target_num"], item_dict['current_price'],
                      hoga_lookup[item_dict["buy_type"]], '')

        time.sleep(1.7)

        # 매수시 거래량 속도 저장
        item_dict['buying_time_accel'] = item_dict['cur_vol_accel']

        # 매수 후 잠시 후 주문취소 (미체결에 대한 주문취소) - 일단 시장가로 대응할거라서..미체결은 없다.
        # time.sleep(0.5)
        # to do


    # ===========================================================================
    # 매도 가능여부 확인 및 매도 진행
    # ===========================================================================
    if item_dict["chejango"] > 0 and is_sellable(item_code, item_dict, kw):
        hoga_lookup = {'지정가': "00", '시장가': "03", '조건부지정가': '05', '최유리지정가': '06', '최우선지정가': '07'}
        kw.send_order('send_order_req', '0101', account_number, 2, item_code, item_dict["chejango"],
                      item_dict['current_price'],
                      hoga_lookup[item_dict["sell_type"]], '')

        time.sleep(1.7)

        # 시장가 매도가 아닌경우 매도 루프 만들어야 한다.

    print('')
    time.sleep(4.5)




if __name__ == "__main__":
    app = QApplication(sys.argv)
    kw = Kiwoom.instance()
    kw.comm_connect()

    # 종목코드;매수타입;매수총수량;매수총가격(목표);최소기준거래속도
    f = open("buy_list.txt", 'rt', encoding='UTF8')
    buy_list = f.readlines()
    f.close()

    '''
    current_price = 0                       # 현재 가격
    open_price = 0                          # 현재 분봉의 시가
    pre_min_vol_accel = 0                   # 전 분봉의 거래량 속도
    pre_before_min_vol_accel = 0            # 전전 분봉의 거래량 속도
    third_before_min_vol_accel = 0          # 전전전 분봉의 거래량 속도
    deque_vol_cum = deque                   # 당일 기준 누적 거래량 snapshot
    deque_vol_time = deque time.time() --   # 끝 정수가 (초) snapshot 시간 
    cur_vol_accel = 0                       # 현재 거래량 속도 (10초 기준)
    accel_history = 0                       # 거래량 속도 저장 
    buying_time_accel = 0                   # 매수시 거래량
    buying_time_price = 0                   # 매수가
    chejango = 0                            # 잔고정보
    min_vol_accel = 0                       # 종목별 최소 매수 거래속도
    ma_short_term = 0                       # 단기구간 이동평균
    ma_mid_term = 0                         # 중기구간
    ma_long_term = 0                        # 장기구간
    'deque_price': dq_price,                # 햔제기격 저장 큐
    'deque_price_time': dq_date,            # 현재가격 저장 시간 큐
    'price_gradient': 0,                    # 현재가격에 대한 기울기 (MAX_PRICE_BUCKET 기준)
    'price_gradient_history': dq_gradi      # 가격 기울기 저장 history
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
        std_accel_1 = split_row_data[5]
        std_accel_1_multiple = split_row_data[6]
        std_accel_2 = split_row_data[7]
        std_accel_2_multiple = split_row_data[8]
        std_accel_3 = split_row_data[9]
        std_accel_3_multiple = split_row_data[10]
        std_accel_4 = split_row_data[11]
        std_accel_4_multiple = split_row_data[12]


        if item_dict.get(code) is None:
            dq_vol = deque()
            dq_time = deque()
            dq_accel = deque()
            dq_price = deque()
            dq_date = deque()
            dq_gradi = deque()

            item_dict[code] = {'current_price': 0,
                               'open_price': 0,
                               'pre_min_vol_accel': 0,
                               'pre_before_min_vol_accel': 0,
                               'third_before_min_vol_accel': 0,
                               'deque_vol_cum': dq_vol,
                               'accel_history': dq_accel,
                               'deque_vol_time': dq_time,
                               'buy_target_num': buy_num,
                               'buy_target_price': buy_price,
                               'buy_type': buy_type,
                               'sell_type': buy_type,
                               'min_vol_accel': int(min_vol_accel),
                               'name': name,
                               'buying_time_accel': 0,
                               'chejango': 0,
                               'buying_time_price': 0,
                               'ma_short_term': 0,
                               'ma_mid_term': 0,
                               'ma_long_term': 0,
                               'deque_price': dq_price,
                               'deque_price_time': dq_date,
                               'price_gradient': 0,
                               'price_gradient_history': dq_gradi,
                               'std_accel_1': int(std_accel_1),
                               'std_accel_1_multiple': int(std_accel_1_multiple),
                               'std_accel_2': int(std_accel_2),
                               'std_accel_2_multiple': int(std_accel_2_multiple),
                               'std_accel_3': int(std_accel_3),
                               'std_accel_3_multiple': int(std_accel_3_multiple),
                               'std_accel_4': int(std_accel_4),
                               'std_accel_4_multiple': int(std_accel_4_multiple),
                               }

        auto_buy_sell(code, item_dict[code], kw)

    app.quit()