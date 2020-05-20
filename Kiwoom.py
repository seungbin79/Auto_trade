import sys
from PyQt5.QtWidgets import *
from PyQt5.QAxContainer import *
from PyQt5.QtCore import *
import time
import pandas as pd
import sqlite3
import util

TR_REQ_TIME_INTERVAL = 0.2

class SingletonInstane:
  __instance = None

  @classmethod
  def __getInstance(cls):
    return cls.__instance

  @classmethod
  def instance(cls, *args, **kargs):
    cls.__instance = cls(*args, **kargs)
    cls.instance = cls.__getInstance
    return cls.__instance

class Kiwoom(QAxWidget, SingletonInstane):
    def __init__(self):
        super().__init__()
        self._create_kiwoom_instance()
        self._set_signal_slots()

    def _create_kiwoom_instance(self):
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")

    def _set_signal_slots(self):
        self.OnEventConnect.connect(self._event_connect)
        self.OnReceiveTrData.connect(self._receive_tr_data)
        self.OnReceiveChejanData.connect(self._receive_chejan_data)
        self.OnReceiveRealData.connect(self._receive_real_data)

    def comm_connect(self):
        self.dynamicCall("CommConnect()")
        self.login_event_loop = QEventLoop()
        self.login_event_loop.exec_()

    def _event_connect(self, err_code):
        if err_code == 0:
            print("connected")
        else:
            print("disconnected")

        self.login_event_loop.exit()

    def get_code_list_by_market(self, market):
        code_list = self.dynamicCall("GetCodeListByMarket(QString)", market)
        code_list = code_list.split(';')
        return code_list[:-1]

    def get_master_code_name(self, code):
        code_name = self.dynamicCall("GetMasterCodeName(QString)", code)
        return code_name

    def get_connect_state(self):
        ret = self.dynamicCall("GetConnectState()")
        return ret

    def get_login_info(self, tag):
        ret = self.dynamicCall("GetLoginInfo(QString)", tag)
        return ret

    def set_input_value(self, id, value):
        self.dynamicCall("SetInputValue(QString, QString)", id, value)

    def comm_rq_data(self, rqname, trcode, next, screen_no):
        self.dynamicCall("CommRqData(QString, QString, int, QString)", rqname, trcode, next, screen_no)
        self.tr_event_loop = QEventLoop()
        self.tr_event_loop.exec_()

    def _comm_get_data(self, code, real_type, field_name, index, item_name):
        ret = self.dynamicCall("CommGetData(QString, QString, QString, int, QString)", code,
                               real_type, field_name, index, item_name)
        return ret.strip()

    def _get_repeat_cnt(self, trcode, rqname):
        ret = self.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname)
        return ret

    def send_order(self, rqname, screen_no, acc_no, order_type, code, quantity, price, hoga, order_no):
        self.dynamicCall("SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                         [rqname, screen_no, acc_no, order_type, code, quantity, price, hoga, order_no])

    def _get_chejan_data(self, fid):
        ret = self.dynamicCall("GetChejanData(int)", fid)
        return ret

    def _get_comm_real_data(self, strCode, nFid):
        ret = self.dynamicCall("GetCommRealData(QString, int)", [strCode, nFid])
        return ret

    def get_server_gubun(self):
        ret = self.dynamicCall("KOA_Functions(QString, QString)", "GetServerGubun", "")
        return ret

    def _receive_real_data(self, sCode, sRealType, sRealData, **kwargs):
        """
        실시간 데이터 수신
          OnReceiveRealData(
          BSTR sCode,        // 종목코드
          BSTR sRealType,    // 리얼타입
          BSTR sRealData    // 실시간 데이터 전문
          )
        :param sCode: 종목코드
        :param sRealType: 리얼타입
        :param sRealData: 실시간 데이터 전문
        :param kwargs:
        :return:
        """
        # 종목코드에서 'A' 제거
        if 'A' <= sCode <= 'Z' or 'a' <= sCode <= 'z':
            sCode = sCode[1:]

        if sRealType == "주식시세":
            list_item_name = ["현재가", "(최우선)매도호가", "(최우선)매수호가", "누적거래량", "누적거래대금",
                              "시가", "고가", "저가"]
            list_item_id = [10, 27, 28, 13, 14, 16, 17, 18]
            dict_real_price = {item_name: self._get_comm_real_data(sCode, item_id)
                               for item_name, item_id in zip(list_item_name, list_item_id)}

            dict_real_price["현재가"] = util.safe_cast(dict_real_price["현재가"], int, 0)
            dict_real_price["(최우선)매도호가"] = util.safe_cast(dict_real_price["(최우선)매도호가"], int, 0)
            dict_real_price["(최우선)매수호가"] = util.safe_cast(dict_real_price["(최우선)매수호가"], int, 0)
            dict_real_price["누적거래량"] = util.safe_cast(dict_real_price["누적거래량"], int, 0)
            dict_real_price["누적거래대금"] = util.safe_cast(dict_real_price["누적거래대금"], int, 0)
            dict_real_price["시가"] = util.safe_cast(dict_real_price["시가"], int, 0)
            dict_real_price["고가"] = util.safe_cast(dict_real_price["고가"], int, 0)
            dict_real_price["저가"] = util.safe_cast(dict_real_price["저가"], int, 0)

            self.dict_real_price[sCode] = dict_real_price

            print("실시간 시세: %s %s" % (sCode, dict_real_price,))


    def _receive_chejan_data(self, sGubun, nItemCnt, sFIdList, **kwargs):
        print("체결/잔고: %s %s %s" % (sGubun, nItemCnt, sFIdList))
        # if sGubun == '0':
        #     list_item_name = ["계좌번호", "주문번호", "관리자사번", "종목코드", "주문업무분류",
        #                       "주문상태", "종목명", "주문수량", "주문가격", "미체결수량",
        #                       "체결누계금액", "원주문번호", "주문구분", "매매구분", "매도수구분",
        #                       "주문체결시간", "체결번호", "체결가", "체결량", "현재가",
        #                       "매도호가", "매수호가", "단위체결가", "단위체결량", "당일매매수수료",
        #                       "당일매매세금", "거부사유", "화면번호", "터미널번호", "신용구분",
        #                       "대출일"]
        #     list_item_id = [9201, 9203, 9205, 9001, 912,
        #                     913, 302, 900, 901, 902,
        #                     903, 904, 905, 906, 907,
        #                     908, 909, 910, 911, 10,
        #                     27, 28, 914, 915, 938,
        #                     939, 919, 920, 921, 922,
        #                     923]
        #
        # dict_contract = {item_name: self._get_chejan_data(item_id).strip() for item_name, item_id in zip(list_item_name, list_item_id)}
        #
        # # 종목코드에서 'A' 제거
        # item_code = dict_contract["종목코드"]
        # if 'A' <= item_code[0] <= 'Z' or 'a' <= item_code[0] <= 'z':
        #     item_code = item_code[1:]
        #     dict_contract["종목코드"] = item_code

        # 종목을 대기 리스트에서 제거
        # if 종목코드 in self.set_stock_ordered:
        #    self.set_stock_ordered.remove(종목코드)

        # 매수 체결일 경우 보유종목에 빈 dict 추가 (키만 추가하기 위해)
        # if "매수" in dict_contract["주문구분"]:
        #     self.dict_holding[item_code] = {}
        # # 매도 체결일 경우 보유종목에서 제거
        # else:
        #     self.dict_holding.pop(item_code, None)
        #
        # print("체결: %s" % (dict_contract,))

        if sGubun == '1':
            list_item_name = ["계좌번호", "종목코드", "신용구분", "대출일", "종목명",
                              "현재가", "보유수량", "매입단가", "총매입가", "주문가능수량",
                              "당일순매수량", "매도매수구분", "당일총매도손일", "예수금", "매도호가",
                              "매수호가", "기준가", "손익율", "신용금액", "신용이자",
                              "만기일", "당일실현손익", "당일실현손익률", "당일실현손익_신용", "당일실현손익률_신용",
                              "담보대출수량", "기타"]
            list_item_id = [9201, 9001, 917, 916, 302,
                            10, 930, 931, 932, 933,
                            945, 946, 950, 951, 27,
                            28, 307, 8019, 957, 958,
                            918, 990, 991, 992, 993,
                            959, 924]
            dict_holding = {item_name: self._get_chejan_data(item_id).strip() for item_name, item_id in
                            zip(list_item_name, list_item_id)}
            dict_holding["현재가"] = util.safe_cast(dict_holding["현재가"], int, 0)
            dict_holding["보유수량"] = util.safe_cast(dict_holding["보유수량"], int, 0)
            dict_holding["매입단가"] = util.safe_cast(dict_holding["매입단가"], int, 0)
            dict_holding["총매입가"] = util.safe_cast(dict_holding["총매입가"], int, 0)
            dict_holding["주문가능수량"] = util.safe_cast(dict_holding["주문가능수량"], int, 0)

            # 종목코드에서 'A' 제거
            item_code = dict_holding["종목코드"]
            if 'A' <= item_code[0] <= 'Z' or 'a' <= item_code[0] <= 'z':
                item_code = item_code[1:]
                dict_holding["종목코드"] = item_code

            # 보유종목 리스트에 추가
            self.dict_holding[item_code] = dict_holding

            print("잔고: %s" % (dict_holding,))

    def _receive_tr_data(self, screen_no, rqname, trcode, record_name, next, unused1, unused2, unused3, unused4):
        if next == '2':
            self.remained_data = True
        else:
            self.remained_data = False

        if rqname == "opt10081_req":
            self._opt10081(rqname, trcode)
        elif rqname == "opw00001_req":
            self._opw00001(rqname, trcode)
        elif rqname == "opw00018_req":
            self._opw00018(rqname, trcode)
        elif rqname == "opt10080_req":
            self._opt10080(rqname, trcode)

        try:
            self.tr_event_loop.exit()
        except AttributeError:
            pass

    def set_real_reg(self, strScreenNo, strCodeList, strFidList, strOptType):
        """
        SetRealReg(
          BSTR strScreenNo,   // 화면번호
          BSTR strCodeList,   // 종목코드 리스트
          BSTR strFidList,  // 실시간 FID리스트
          BSTR strOptType   // 실시간 등록 타입, 0또는 1 (0은 교체 등록, 1은 추가 등록)
          )
        :param str:
        :return:
        """
        lRet = self.dynamicCall("SetRealReg(QString, QString, QString, QString)",
                                [strScreenNo, strCodeList, strFidList, strOptType])
        return lRet



    def reset_opw00018_output(self):
        self.opw00018_output = {'single': [], 'multi': []}

    def _opt10081(self, rqname, trcode):
        data_cnt = self._get_repeat_cnt(trcode, rqname)

        for i in range(data_cnt):
            date = self._comm_get_data(trcode, "", rqname, i, "일자")
            open = self._comm_get_data(trcode, "", rqname, i, "시가")
            high = self._comm_get_data(trcode, "", rqname, i, "고가")
            low = self._comm_get_data(trcode, "", rqname, i, "저가")
            close = self._comm_get_data(trcode, "", rqname, i, "현재가")
            volume = self._comm_get_data(trcode, "", rqname, i, "거래량")

            self.ohlcv['date'].append(date)
            self.ohlcv['open'].append(int(open))
            self.ohlcv['high'].append(int(high))
            self.ohlcv['low'].append(int(low))
            self.ohlcv['close'].append(int(close))
            self.ohlcv['volume'].append(int(volume))

    def _opw00001(self, rqname, trcode):
        d2_deposit = self._comm_get_data(trcode, "", rqname, 0, "d+2추정예수금")
        self.d2_deposit = Kiwoom.change_format(d2_deposit)

    def _opw00018(self, rqname, trcode):
        # single data
        total_purchase_price = self._comm_get_data(trcode, "", rqname, 0, "총매입금액")
        total_eval_price = self._comm_get_data(trcode, "", rqname, 0, "총평가금액")
        total_eval_profit_loss_price = self._comm_get_data(trcode, "", rqname, 0, "총평가손익금액")

        total_earning_rate = self._comm_get_data(trcode, "", rqname, 0, "총수익률(%)")
        if self.get_server_gubun():
            total_earning_rate = float(total_earning_rate) / 100
            total_earning_rate = str(total_earning_rate)

        estimated_deposit = self._comm_get_data(trcode, "", rqname, 0, "추정예탁자산")

        self.opw00018_output['single'].append(Kiwoom.change_format(total_purchase_price))
        self.opw00018_output['single'].append(Kiwoom.change_format(total_eval_price))
        self.opw00018_output['single'].append(Kiwoom.change_format(total_eval_profit_loss_price))
        self.opw00018_output['single'].append(Kiwoom.change_format(total_earning_rate))
        self.opw00018_output['single'].append(Kiwoom.change_format(estimated_deposit))

        # multi data
        rows = self._get_repeat_cnt(trcode, rqname)
        for i in range(rows):
            code = self._comm_get_data((trcode, "", rqname, i, "종목번호"))
            name = self._comm_get_data(trcode, "", rqname, i, "종목명")
            quantity = self._comm_get_data(trcode, "", rqname, i, "보유수량")
            purchase_price = self._comm_get_data(trcode, "", rqname, i, "매입가")
            current_price = self._comm_get_data(trcode, "", rqname, i, "현재가")
            eval_profit_loss_price = self._comm_get_data(trcode, "", rqname, i, "평가손익")
            earning_rate = self._comm_get_data(trcode, "", rqname, i, "수익률(%)")

            quantity = Kiwoom.change_format(quantity)
            purchase_price = Kiwoom.change_format(purchase_price)
            current_price = Kiwoom.change_format(current_price)
            eval_profit_loss_price = Kiwoom.change_format(eval_profit_loss_price)
            earning_rate = Kiwoom.change_format2(earning_rate)

            self.opw00018_output['multi'].append([code, name, quantity, purchase_price, current_price, eval_profit_loss_price, earning_rate])

    def _opt10080(self, rqname, trcode):
        data_cnt = self._get_repeat_cnt(trcode, rqname)

        try:
            # self.one_min_price = {}

            for i in range(data_cnt):
                cur = self._comm_get_data(trcode, "", rqname, i, "현재가")
                volume = self._comm_get_data(trcode, "", rqname, i, "거래량")
                date = self._comm_get_data(trcode, "", rqname, i, "체결시간")
                open = self._comm_get_data(trcode, "", rqname, i, "시가")
                high = self._comm_get_data(trcode, "", rqname, i, "고가")
                low = self._comm_get_data(trcode, "", rqname, i, "저가")

                self.one_min_price['date'].append(date)
                self.one_min_price['open'].append(int(open))
                self.one_min_price['high'].append(int(high))
                self.one_min_price['low'].append(int(low))
                self.one_min_price['cur'].append(int(cur))
                self.one_min_price['volume'].append(int(volume))
        except Exception as e:
            print(e)


    # @staticmethod
    def change_format(data):
        strip_data = data.lstrip('-0')
        if strip_data == '':
            strip_data = '0'

        try:
            format_data = format(int(strip_data), ',d')
        except:
            format_data = format(float(strip_data))

        if data.startswith('-'):
            format_data = '-' + format_data

        return format_data

    # @staticmethod
    def change_format2(data):
        strip_data = data.lstrip('-0')

        if strip_data == '':
            strip_data = '0'

        if strip_data.startswith('.'):
            strip_data = '0' + strip_data

        if data.startswith('-'):
            strip_data = '-' + strip_data

        return strip_data


if __name__ == "__main__":
    app = QApplication(sys.argv)
    kiwoom = Kiwoom.instance()
    kiwoom.comm_connect()

    account_number = kiwoom.get_login_info("ACCNO")
    account_number = account_number.split(';')[0]

    kiwoom.set_input_value("계좌번호", account_number)
    kiwoom.comm_rq_data("opw00018_req", "opw00018", 0, "2000")

