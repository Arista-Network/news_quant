from pykrx import stock
import FinanceDataReader as fdr
import pandas_ta as ta
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class QuantEngine:
    def __init__(self):
        self._cache = {}
        self._cache_date = None

    def _check_cache(self):
        today = datetime.now().strftime("%Y%m%d")
        if self._cache_date != today:
            self._cache = {}
            self._cache_date = today

    def _safe_val(self, row, col, default=0):
        if col in row.index and not pd.isna(row[col]):
            return float(row[col])
        return default

    def _get_investor_data(self, ticker, end_str, days=20):
        """외국인/기관 순매수 데이터 조회 (robust)"""
        foreigner_net = 0
        institution_net = 0
        inv_start = (datetime.strptime(end_str, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")

        try:
            inv_df = stock.get_market_trading_volume_by_date(inv_start, end_str, ticker)
            if inv_df is not None and not inv_df.empty:
                cols = inv_df.columns.tolist()
                print(f"[투자자] {ticker} 컬럼: {cols}")

                # 외국인 컬럼 탐색
                for col in ['외국인', '외국인합계']:
                    if col in inv_df.columns:
                        foreigner_net = int(inv_df[col].sum())
                        break

                # 기관 컬럼 탐색
                for col in ['기관합계', '기관']:
                    if col in inv_df.columns:
                        institution_net = int(inv_df[col].sum())
                        break

                if foreigner_net == 0 and institution_net == 0:
                    # 값 기반(금액) API 시도
                    inv_val = stock.get_market_trading_value_by_date(inv_start, end_str, ticker)
                    if inv_val is not None and not inv_val.empty:
                        for col in ['외국인', '외국인합계']:
                            if col in inv_val.columns:
                                foreigner_net = int(inv_val[col].sum())
                                break
                        for col in ['기관합계', '기관']:
                            if col in inv_val.columns:
                                institution_net = int(inv_val[col].sum())
                                break
            else:
                print(f"[투자자] {ticker}: 데이터 없음")
        except Exception as e:
            print(f"[투자자 오류] {ticker}: {e}")

        return foreigner_net, institution_net

    def analyze_stock(self, ticker):
        """종합 퀀트 분석 (기술적 지표 + 수급 + 시그널)"""
        self._check_cache()
        if ticker in self._cache:
            return self._cache[ticker]

        end_date = datetime.now()
        start_date = end_date - timedelta(days=200)
        end_str = end_date.strftime("%Y%m%d")

        try:
            df = fdr.DataReader(ticker, start_date, end_date)
            if df is None or df.empty or len(df) < 30:
                return None

            df.columns = [c.lower() for c in df.columns]

            df.ta.rsi(length=14, append=True)
            df.ta.sma(length=5, append=True)
            df.ta.sma(length=20, append=True)
            df.ta.sma(length=60, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.bbands(length=20, std=2, append=True)
            df.ta.stoch(append=True)

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last

            def safe(col, default=0):
                if col in last.index and not pd.isna(last[col]):
                    return float(last[col])
                return default

            rsi = safe('RSI_14', 50)
            ma5 = safe('SMA_5')
            ma20 = safe('SMA_20')
            ma60 = safe('SMA_60')
            macd_val = safe('MACD_12_26_9')
            macd_sig = safe('MACDs_12_26_9')
            bb_upper = safe('BBU_20_2.0')
            bb_lower = safe('BBL_20_2.0')
            stoch_k = safe('STOCHk_14_3_3', 50)
            current_price = safe('close')
            change_rate = safe('change', 0)

            # MACD 전일 값 (prev row 사용)
            prev_macd = self._safe_val(prev, 'MACD_12_26_9')
            prev_sig = self._safe_val(prev, 'MACDs_12_26_9')

            # 외국인/기관 수급
            foreigner_net, institution_net = self._get_investor_data(ticker, end_str)

            # 다중 지표 스코어링
            score = 0
            reasons = []

            if rsi <= 30:
                score += 2
                reasons.append(f"RSI 과매도 ({rsi:.0f})")
            elif rsi >= 70:
                score -= 2
                reasons.append(f"RSI 과매수 ({rsi:.0f})")

            if macd_val > macd_sig and prev_macd <= prev_sig:
                score += 1
                reasons.append("MACD 골든크로스")
            elif macd_val < macd_sig and prev_macd >= prev_sig:
                score -= 1
                reasons.append("MACD 데드크로스")

            if current_price > 0 and bb_lower > 0 and current_price <= bb_lower:
                score += 1
                reasons.append("볼린저 밴드 하단 터치")
            elif current_price > 0 and bb_upper > 0 and current_price >= bb_upper:
                score -= 1
                reasons.append("볼린저 밴드 상단 돌파")

            if ma5 > ma20 > ma60 and ma60 > 0:
                score += 1
                reasons.append("이동평균선 정배열 (5>20>60)")
            elif ma5 < ma20 < ma60 and ma5 > 0:
                score -= 1
                reasons.append("이동평균선 역배열")

            if foreigner_net > 0 and institution_net > 0:
                score += 2
                reasons.append("외국인+기관 동시 순매수")
            elif foreigner_net > 0:
                score += 1
                reasons.append("외국인 순매수 유입")
            elif institution_net > 0:
                score += 1
                reasons.append("기관 순매수 유입")
            elif foreigner_net < 0 and institution_net < 0:
                score -= 1
                reasons.append("외국인+기관 동시 순매도")

            if score >= 3:
                signal = "STRONG_BUY"
            elif score >= 1:
                signal = "BUY"
            elif score <= -3:
                signal = "STRONG_SELL"
            elif score <= -1:
                signal = "SELL"
            else:
                signal = "NEUTRAL"

            if not reasons:
                reasons.append("특이사항 없음")

            result = {
                "ticker": ticker,
                "current_price": int(current_price),
                "change_rate": round(change_rate * 100, 2) if abs(change_rate) < 1 else round(change_rate, 2),
                "rsi": round(rsi, 1),
                "ma5": int(ma5),
                "ma20": int(ma20),
                "ma60": int(ma60),
                "macd": round(macd_val, 2),
                "macd_signal": round(macd_sig, 2),
                "bb_upper": int(bb_upper),
                "bb_lower": int(bb_lower),
                "stoch_k": round(stoch_k, 1),
                "foreigner_net": foreigner_net,
                "institution_net": institution_net,
                "signal": signal,
                "score": score,
                "reason": reasons
            }

            self._cache[ticker] = result
            return result

        except Exception as e:
            print(f"[분석 오류] {ticker}: {e}")
            return None

    def get_market_flow(self, market="KOSPI", top_n=20):
        """시장 전체 외국인/기관 수급 히트맵 데이터 (일별 집계)"""
        try:
            today = datetime.now()
            flow_accum = {}
            found_days = 0

            # 최근 5 거래일 합산 (weekday 필터링으로 캘린더 14일 범위)
            for days_back in range(1, 20):
                d = today - timedelta(days=days_back)
                if d.weekday() >= 5:
                    continue
                date_str = d.strftime("%Y%m%d")

                try:
                    day_df = stock.get_market_trading_volume_by_ticker(date_str, market)
                    if day_df is None or day_df.empty:
                        continue

                    is_multiindex = isinstance(day_df.columns, pd.MultiIndex)
                    if found_days == 0:
                        print(f"[수급맵] 컬럼 구조: {list(day_df.columns[:8])}")

                    # 컬럼명 한 번만 탐색
                    if is_multiindex:
                        f_col = next((c for c in ['외국인합계', '외국인'] if (c, '순매수') in day_df.columns), None)
                        i_col = next((c for c in ['기관합계', '기관'] if (c, '순매수') in day_df.columns), None)
                    else:
                        f_col = next((c for c in ['외국인합계', '외국인'] if c in day_df.columns), None)
                        i_col = next((c for c in ['기관합계', '기관'] if c in day_df.columns), None)

                    if found_days == 0:
                        print(f"[수급맵] f_col={f_col}, i_col={i_col}, is_multi={is_multiindex}")

                    for ticker in day_df.index:
                        if ticker not in flow_accum:
                            flow_accum[ticker] = {"foreigner": 0, "institution": 0}

                        try:
                            if is_multiindex:
                                f_net = int(day_df.loc[ticker, (f_col, '순매수')]) if f_col else 0
                                i_net = int(day_df.loc[ticker, (i_col, '순매수')]) if i_col else 0
                            else:
                                row = day_df.loc[ticker]
                                f_net = int(row[f_col]) if f_col else 0
                                i_net = int(row[i_col]) if i_col else 0

                            flow_accum[ticker]["foreigner"] += f_net
                            flow_accum[ticker]["institution"] += i_net
                        except Exception:
                            pass

                    found_days += 1
                    if found_days >= 5:
                        break
                except Exception as e:
                    print(f"[수급맵] {date_str} 오류: {e}")
                    continue

            if not flow_accum:
                return self._get_market_flow_fallback(market, top_n)

            # 종목명 매핑
            try:
                df_list = fdr.StockListing(market)
                name_map = dict(zip(df_list['Code'], df_list['Name']))
            except Exception:
                name_map = {}

            results = []
            for ticker, data in flow_accum.items():
                f_net = data["foreigner"]
                i_net = data["institution"]
                results.append({
                    "name": name_map.get(ticker, ticker),
                    "code": ticker,
                    "foreigner": f_net,
                    "institution": i_net,
                    "total": f_net + i_net
                })

            results.sort(key=lambda x: abs(x['total']), reverse=True)
            return results[:top_n]

        except Exception as e:
            print(f"[수급맵 오류] {e}")
            return self._get_market_flow_fallback(market, top_n)

    def _get_market_flow_fallback(self, market="KOSPI", top_n=20):
        """수급맵 폴백: 종목별 개별 조회"""
        try:
            end_date = datetime.now()
            end_str = end_date.strftime("%Y%m%d")
            start_str = (end_date - timedelta(days=14)).strftime("%Y%m%d")

            if market == "KOSPI":
                df_list = fdr.StockListing('KOSPI')
            else:
                df_list = fdr.StockListing('KOSDAQ')

            results = []
            for _, row in df_list.head(30).iterrows():
                ticker = row['Code']
                name = row['Name']
                try:
                    inv_df = stock.get_market_trading_volume_by_date(start_str, end_str, ticker)
                    if inv_df is None or inv_df.empty:
                        continue
                    f_net = 0
                    i_net = 0
                    for col in ['외국인', '외국인합계']:
                        if col in inv_df.columns:
                            f_net = int(inv_df[col].sum())
                            break
                    for col in ['기관합계', '기관']:
                        if col in inv_df.columns:
                            i_net = int(inv_df[col].sum())
                            break
                    results.append({
                        "name": name, "code": ticker,
                        "foreigner": f_net, "institution": i_net,
                        "total": f_net + i_net
                    })
                except Exception:
                    continue

            results.sort(key=lambda x: abs(x['total']), reverse=True)
            return results[:top_n]
        except Exception as e:
            print(f"[폴백 오류] {e}")
            return []
