from pykrx import stock
import FinanceDataReader as fdr
import pandas_ta as ta
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class QuantEngine:
    def __init__(self):
        self._cache = {}  # 종목별 분석 결과 캐시 (당일 유효)
        self._cache_date = None

    def _check_cache(self):
        today = datetime.now().strftime("%Y%m%d")
        if self._cache_date != today:
            self._cache = {}
            self._cache_date = today

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

            # --- 기술적 지표 대규모 계산 ---
            df.ta.rsi(length=14, append=True)
            df.ta.sma(length=5, append=True)
            df.ta.sma(length=20, append=True)
            df.ta.sma(length=60, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.bbands(length=20, std=2, append=True)
            df.ta.stoch(append=True)

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last

            # 안전한 값 추출 헬퍼
            def safe(col, default=0):
                if col in last and not pd.isna(last[col]):
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

            # --- 스마트 머니 (외국인/기관 수급) ---
            foreigner_net = 0
            institution_net = 0
            try:
                inv_start = (end_date - timedelta(days=10)).strftime("%Y%m%d")
                inv_df = stock.get_market_trading_volume_by_date(inv_start, end_str, ticker)
                if inv_df is not None and not inv_df.empty:
                    if '외국인' in inv_df.columns:
                        foreigner_net = int(inv_df['외국인'].sum())
                    if '기관합계' in inv_df.columns:
                        institution_net = int(inv_df['기관합계'].sum())
            except:
                pass

            # --- 종합 시그널 판단 (다중 지표 스코어링) ---
            score = 0
            reasons = []

            # RSI
            if rsi <= 30:
                score += 2
                reasons.append(f"RSI 과매도 ({rsi:.0f})")
            elif rsi >= 70:
                score -= 2
                reasons.append(f"RSI 과매수 ({rsi:.0f})")

            # MACD 골든/데드크로스
            prev_macd = safe('MACD_12_26_9') if 'MACD_12_26_9' in prev else 0
            prev_sig = safe('MACDs_12_26_9') if 'MACDs_12_26_9' in prev else 0
            if macd_val > macd_sig and prev_macd <= prev_sig:
                score += 1
                reasons.append("MACD 골든크로스")
            elif macd_val < macd_sig and prev_macd >= prev_sig:
                score -= 1
                reasons.append("MACD 데드크로스")

            # 볼린저 밴드
            if current_price > 0 and bb_lower > 0 and current_price <= bb_lower:
                score += 1
                reasons.append("볼린저 밴드 하단 터치")
            elif current_price > 0 and bb_upper > 0 and current_price >= bb_upper:
                score -= 1
                reasons.append("볼린저 밴드 상단 돌파")

            # 이동평균선 정배열
            if ma5 > ma20 > ma60 and ma60 > 0:
                score += 1
                reasons.append("이동평균선 정배열 (5>20>60)")
            elif ma5 < ma20 < ma60 and ma5 > 0:
                score -= 1
                reasons.append("이동평균선 역배열")

            # 스마트 머니 수급
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

            # 시그널 판정
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
                "change_rate": round(change_rate, 2),
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
            print(f"Error analyzing {ticker}: {e}")
            return None

    def get_market_flow(self, market="KOSPI", top_n=20):
        """시장 전체 외국인/기관 수급 히트맵 데이터"""
        try:
            end_date = datetime.now()
            end_str = end_date.strftime("%Y%m%d")
            start_str = (end_date - timedelta(days=7)).strftime("%Y%m%d")

            if market == "KOSPI":
                df_list = fdr.StockListing('KOSPI')
            else:
                df_list = fdr.StockListing('KOSDAQ')

            results = []
            for _, row in df_list.head(50).iterrows():
                ticker = row['Code']
                name = row['Name']
                try:
                    inv_df = stock.get_market_trading_volume_by_date(start_str, end_str, ticker)
                    if inv_df is None or inv_df.empty:
                        continue
                    f_net = int(inv_df['외국인'].sum()) if '외국인' in inv_df.columns else 0
                    i_net = int(inv_df['기관합계'].sum()) if '기관합계' in inv_df.columns else 0
                    results.append({
                        "name": name,
                        "code": ticker,
                        "foreigner": f_net,
                        "institution": i_net,
                        "total": f_net + i_net
                    })
                except:
                    continue

            results.sort(key=lambda x: abs(x['total']), reverse=True)
            return results[:top_n]
        except Exception as e:
            print(f"Market flow error: {e}")
            return []
