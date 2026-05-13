import os as _os
# pykrx 1.2.x reads KRX_ID/KRX_PW from env at import time and auto-authenticates.
# On cloud servers (Render), KRX auth returns non-JSON → crash before server starts.
# Temporarily hide credentials so pykrx imports with anonymous session (no network call).
# _init_krx_auth() in main.py startup will re-auth explicitly after import completes.
_krx_id = _os.environ.pop('KRX_ID', None)
_krx_pw = _os.environ.pop('KRX_PW', None)
try:
    from pykrx import stock
except Exception as _pykrx_err:
    print(f"[pykrx] 임포트 실패: {_pykrx_err}")
    stock = None
finally:
    if _krx_id is not None:
        _os.environ['KRX_ID'] = _krx_id
    if _krx_pw is not None:
        _os.environ['KRX_PW'] = _krx_pw
import FinanceDataReader as fdr
import pandas_ta as ta
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTE


class QuantEngine:
    def __init__(self):
        self._cache = {}
        self._cache_date = None
        self._market_flow_snapshot: dict = {}  # {ticker: {foreigner, institution}} — bulk cache for screener

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
        """외국인/기관 순매수 금액(원) 조회 — 금액 기반 API 우선, 수량 기반 폴백"""
        inv_start = (datetime.strptime(end_str, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")

        api_list = [
            ("금액", lambda: stock.get_market_trading_value_by_date(inv_start, end_str, ticker)),
            ("수량", lambda: stock.get_market_trading_volume_by_date(inv_start, end_str, ticker)),
        ]

        for label, api_fn in api_list:
            try:
                inv_df = api_fn()
                if inv_df is None or inv_df.empty:
                    continue

                cols = inv_df.columns.tolist()
                print(f"[투자자/{label}] {ticker} 컬럼: {cols[:6]}")

                f_net = 0
                i_net = 0

                # MultiIndex 처리
                if isinstance(inv_df.columns, pd.MultiIndex):
                    f_col = next((c for c in ['외국인합계', '외국인']
                                  if (c, '순매수') in inv_df.columns), None)
                    i_col = next((c for c in ['기관합계', '기관']
                                  if (c, '순매수') in inv_df.columns), None)
                    if f_col:
                        f_net = int(inv_df[(f_col, '순매수')].sum())
                    if i_col:
                        i_net = int(inv_df[(i_col, '순매수')].sum())
                else:
                    for col in ['외국인합계', '외국인']:
                        if col in inv_df.columns:
                            f_net = int(inv_df[col].sum())
                            break
                    for col in ['기관합계', '기관']:
                        if col in inv_df.columns:
                            i_net = int(inv_df[col].sum())
                            break

                if f_net != 0 or i_net != 0:
                    print(f"[투자자/{label}] {ticker}: 외={f_net:+,} 기={i_net:+,}")
                    return f_net, i_net

            except Exception as e:
                print(f"[투자자/{label}] {ticker} 오류: {e}")

        print(f"[투자자] {ticker}: 데이터 없음 (0 반환)")
        return 0, 0

    def analyze_stock(self, ticker):
        """종합 퀀트 분석 (기술적 지표 + 수급 + 시그널)"""
        self._check_cache()
        if ticker in self._cache:
            return self._cache[ticker]

        end_date = datetime.now()
        start_date = end_date - timedelta(days=200)
        end_str = end_date.strftime("%Y%m%d")
        start_str = start_date.strftime("%Y%m%d")

        try:
            # pykrx OHLCV 우선 (Render 등 FDR 차단 환경에서도 동작)
            df = None
            try:
                _df = stock.get_market_ohlcv_by_date(start_str, end_str, ticker)
                if _df is not None and not _df.empty and len(_df) >= 30:
                    _df.columns = ['open', 'high', 'low', 'close', 'volume', 'change']
                    _df['change'] = _df['change'] / 100  # % → 소수
                    df = _df
            except Exception:
                pass

            if df is None:
                df = fdr.DataReader(ticker, start_date, end_date)
                if df is None or df.empty or len(df) < 30:
                    return None
                df.columns = [c.lower() for c in df.columns]

            try:
                df.ta.rsi(length=14, append=True)
                df.ta.sma(length=5, append=True)
                df.ta.sma(length=20, append=True)
                df.ta.sma(length=60, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.bbands(length=20, std=2, append=True)
                df.ta.stoch(append=True)
            except Exception as ta_err:
                print(f"[TA 오류] {ticker}: {ta_err}")

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
            if not (0.0 <= stoch_k <= 100.0):
                stoch_k = 50.0
            current_price = safe('close')
            change_rate = safe('change', 0)

            # MACD 전일 값 (prev row 사용)
            prev_macd = self._safe_val(prev, 'MACD_12_26_9')
            prev_sig = self._safe_val(prev, 'MACDs_12_26_9')

            # 외국인/기관 수급 — 스냅샷 우선 사용 (thread-safe, 빠름)
            if ticker in self._market_flow_snapshot:
                snap = self._market_flow_snapshot[ticker]
                foreigner_net = snap.get('foreigner', 0)
                institution_net = snap.get('institution', 0)
            else:
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

    def _trading_days_for_period(self, period_days):
        """기간(일) → 수집할 거래일 수 매핑"""
        if period_days <= 1:
            return 1
        elif period_days <= 7:
            return 5
        elif period_days <= 30:
            return 20
        else:
            return 60  # 1년 필터도 최대 60거래일(약 3개월)로 제한

    def _parse_flow_df(self, day_df):
        """DataFrame에서 외국인·기관 순매수 컬럼 탐색"""
        is_multi = isinstance(day_df.columns, pd.MultiIndex)
        if is_multi:
            f_col = next((c for c in ['외국인합계', '외국인'] if (c, '순매수') in day_df.columns), None)
            i_col = next((c for c in ['기관합계', '기관'] if (c, '순매수') in day_df.columns), None)
        else:
            f_col = next((c for c in ['외국인합계', '외국인'] if c in day_df.columns), None)
            i_col = next((c for c in ['기관합계', '기관'] if c in day_df.columns), None)
        return is_multi, f_col, i_col

    def get_market_flow(self, market="KOSPI", top_n=20, period_days=7):
        """시장 전체 외국인/기관 수급 히트맵 데이터 (기간 합계)"""
        max_trading_days = self._trading_days_for_period(period_days)
        try:
            today = datetime.now()
            end = today - timedelta(days=1)
            while end.weekday() >= 5:
                end -= timedelta(days=1)
            end_str = end.strftime("%Y%m%d")
            start_str = (end - timedelta(days=max_trading_days * 3 + 10)).strftime("%Y%m%d")

            f_df = stock.get_market_net_purchases_of_equities_by_ticker(start_str, end_str, market, "외국인")
            i_df = stock.get_market_net_purchases_of_equities_by_ticker(start_str, end_str, market, "기관합계")

            if f_df is not None and not f_df.empty:
                try:
                    dl = fdr.StockListing(market)
                    name_map = dict(zip(dl['Code'], dl['Name']))
                except Exception:
                    name_map = {}

                f_val = next((c for c in ['순매수거래대금', '순매수거래량'] if c in f_df.columns), None)
                i_val = next((c for c in ['순매수거래대금', '순매수거래량']
                              if i_df is not None and not i_df.empty and c in i_df.columns), None)

                all_tkrs = set(f_df.index) | (set(i_df.index) if i_df is not None and not i_df.empty else set())
                results = []
                for tkr in all_tkrs:
                    f_net = int(f_df.loc[tkr, f_val]) if (f_val and tkr in f_df.index) else 0
                    i_net = int(i_df.loc[tkr, i_val]) if (i_val and i_df is not None and not i_df.empty and tkr in i_df.index) else 0
                    results.append({
                        "name": name_map.get(tkr, tkr),
                        "code": tkr,
                        "foreigner": f_net,
                        "institution": i_net,
                        "total": f_net + i_net,
                    })

                self._market_flow_snapshot = {
                    r['code']: {'foreigner': r['foreigner'], 'institution': r['institution']}
                    for r in results
                }
                results.sort(key=lambda x: abs(x['total']), reverse=True)
                print(f"[수급맵] 집계 완료: {len(results)}종목")
                return results[:top_n]

        except Exception as e:
            print(f"[수급맵 오류] {e}")

        print("[수급맵] 폴백: 개별 종목 조회")
        return self._get_market_flow_fallback(market, top_n)

    def _get_market_flow_fallback(self, market="KOSPI", top_n=20):
        """수급맵 폴백: 상위 80종목 병렬 개별 조회 (스냅샷 커버리지 확보)"""
        try:
            today = datetime.now()
            end_str   = today.strftime("%Y%m%d")
            start_str = (today - timedelta(days=14)).strftime("%Y%m%d")

            df_list = fdr.StockListing(market)
            if df_list is None or df_list.empty:
                return self._get_market_flow_fdr(market, top_n)

            # 스냅샷 커버리지를 위해 80종목 조회 (screener top_n과 맞춤)
            rows = list(df_list.head(80).iterrows())

            def fetch_one(idx_row):
                _, row = idx_row
                tkr  = row.get('Code') or row.get('code', '')
                name = row.get('Name') or row.get('name', tkr)
                if not tkr:
                    return None
                try:
                    inv_df = stock.get_market_trading_volume_by_date(start_str, end_str, tkr)
                    if inv_df is None or inv_df.empty:
                        return None
                    f_net = 0
                    i_net = 0
                    if isinstance(inv_df.columns, pd.MultiIndex):
                        for investor in ['외국인합계', '외국인']:
                            if (investor, '순매수') in inv_df.columns:
                                f_net = int(inv_df[(investor, '순매수')].sum())
                                break
                        for investor in ['기관합계', '기관']:
                            if (investor, '순매수') in inv_df.columns:
                                i_net = int(inv_df[(investor, '순매수')].sum())
                                break
                    else:
                        for col in ['외국인합계', '외국인']:
                            if col in inv_df.columns:
                                f_net = int(inv_df[col].sum())
                                break
                        for col in ['기관합계', '기관']:
                            if col in inv_df.columns:
                                i_net = int(inv_df[col].sum())
                                break
                    return {"name": name, "code": tkr,
                            "foreigner": f_net, "institution": i_net,
                            "total": f_net + i_net}
                except Exception:
                    return None

            results = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                futs = {executor.submit(fetch_one, r): r for r in rows}
                try:
                    for fut in as_completed(futs, timeout=60):
                        try:
                            res = fut.result(timeout=5)
                            if res is not None:
                                results.append(res)
                        except Exception:
                            pass
                except FTE:
                    print("[수급맵 폴백] 시간 초과, 수집된 데이터 사용")

            results.sort(key=lambda x: abs(x['total']), reverse=True)
            print(f"[수급맵 폴백] {len(results)}종목 수집")
            if results:
                self._market_flow_snapshot = {
                    r['code']: {'foreigner': r['foreigner'], 'institution': r['institution']}
                    for r in results
                }
                return results[:top_n]
            # pykrx 개별 조회도 실패 → FDR 기반 최후 폴백
            return self._get_market_flow_fdr(market, top_n)
        except Exception as e:
            print(f"[수급맵 폴백 오류] {e}")
            return self._get_market_flow_fdr(market, top_n)

    def get_market_daily_flow(self, market="KOSPI", period_days=7):
        """일별 시장 전체 외국인/기관 순매수 합계 반환 (추이 차트용)
        get_market_trading_value_by_date("KOSPI") 로 전체 시장 일별 수급을 단일 호출로 조회한다.
        period_days=365 의 경우 60거래일을 주간 집계로 반환한다.
        """
        max_td = self._trading_days_for_period(period_days)
        today = datetime.now()

        # 마지막 거래일 기준 날짜 범위 계산
        end = today - timedelta(days=1)
        while end.weekday() >= 5:
            end -= timedelta(days=1)
        end_str = end.strftime("%Y%m%d")
        start_str = (end - timedelta(days=max_td * 3 + 10)).strftime("%Y%m%d")

        results = []
        try:
            # 시장 전체 일별 투자자 수급 — 단일 호출
            df = stock.get_market_trading_value_by_date(start_str, end_str, market)
            if df is not None and not df.empty:
                for idx, row in df.iterrows():
                    ds = idx.strftime("%Y%m%d") if hasattr(idx, 'strftime') else str(idx).replace('-', '')[:8]
                    f_total = int(row['외국인합계']) if '외국인합계' in row.index else 0
                    i_total = int(row['기관합계']) if '기관합계' in row.index else 0
                    results.append({"date": ds, "foreigner": f_total, "institution": i_total,
                                    "total": f_total + i_total})
                    print(f"[일별수급] {ds}: 외={f_total:+,} 기={i_total:+,}")

                results.sort(key=lambda x: x['date'])
                results = results[-max_td:]  # 최근 max_td 거래일만 유지
        except Exception as e:
            print(f"[일별수급] 오류: {e}")

        if not results:
            print("[일별수급] 폴백: 종목별 수급 집계")
            target_dates = []
            for days_back in range(1, max_td * 3 + 30):
                d = today - timedelta(days=days_back)
                if d.weekday() < 5:
                    target_dates.append((d, d.strftime("%Y%m%d")))
                if len(target_dates) >= max_td:
                    break
            target_date_strs = {ds for _, ds in target_dates}
            results = self._get_daily_flow_per_stock(market, target_date_strs)
            results.sort(key=lambda x: x['date'])

        if period_days >= 365 and len(results) > 10:
            return self._resample_weekly(results)
        return results

    def _resample_weekly(self, daily_data):
        """일별 데이터를 주간 합계로 집계"""
        weekly = {}
        for item in daily_data:
            d = datetime.strptime(item['date'], "%Y%m%d")
            week_start = (d - timedelta(days=d.weekday())).strftime("%Y%m%d")
            if week_start not in weekly:
                weekly[week_start] = {"date": week_start, "foreigner": 0, "institution": 0, "total": 0}
            weekly[week_start]["foreigner"] += item["foreigner"]
            weekly[week_start]["institution"] += item["institution"]
            weekly[week_start]["total"] += item["total"]
        return sorted(weekly.values(), key=lambda x: x['date'])

    def get_top_stocks(self, market="KOSPI", top_n=80):
        """시가총액 상위 N종목 (ticker, name) 반환"""
        try:
            df = fdr.StockListing(market)
            if df is None or df.empty:
                return []
            if 'Marcap' in df.columns:
                df = df.nlargest(top_n, 'Marcap')
            else:
                df = df.head(top_n)
            col_code = 'Code' if 'Code' in df.columns else df.columns[0]
            col_name = 'Name' if 'Name' in df.columns else df.columns[1]
            return [(row[col_code], row[col_name]) for _, row in df.iterrows()]
        except Exception as e:
            print(f"[종목목록 오류] {e}")
            return []

    def _matches_conditions(self, data, conditions):
        """스크리너 조건 AND 매칭"""
        if not conditions:
            return True
        checks = []
        if conditions.get('rsi_low'):     checks.append(data['rsi'] < 40)
        if conditions.get('rsi_high'):    checks.append(data['rsi'] > 60)
        if conditions.get('macd_golden'): checks.append(data['macd'] > data['macd_signal'])
        if conditions.get('macd_dead'):   checks.append(data['macd'] < data['macd_signal'])
        if conditions.get('ma_up'):
            checks.append(data['ma5'] > data['ma20'] > 0 and data['ma20'] > data['ma60'] > 0)
        if conditions.get('ma_down'):
            checks.append(0 < data['ma5'] < data['ma20'] < data['ma60'])
        if conditions.get('foreigner_buy'):   checks.append(data['foreigner_net'] > 0)
        if conditions.get('institution_buy'): checks.append(data['institution_net'] > 0)
        if conditions.get('smart_money'):
            checks.append(data['foreigner_net'] > 0 and data['institution_net'] > 0)
        if conditions.get('signal_buy'):  checks.append(data['signal'] in ['BUY', 'STRONG_BUY'])
        if conditions.get('signal_sell'): checks.append(data['signal'] in ['SELL', 'STRONG_SELL'])
        if conditions.get('bb_lower'):
            checks.append(data['current_price'] > 0 and data['bb_lower'] > 0 and
                          data['current_price'] <= data['bb_lower'] * 1.03)
        return all(checks) if checks else True

    def run_screener(self, market="KOSPI", conditions=None, top_n=80):
        """퀀트 스크리너: 조건 기반 종목 필터링"""
        if conditions is None:
            conditions = {}

        # investor 조건 선택 시 스냅샷이 없으면 먼저 수급 데이터 수집
        investor_conds = {'foreigner_buy', 'institution_buy', 'smart_money'}
        if any(conditions.get(c) for c in investor_conds) and not self._market_flow_snapshot:
            print("[스크리너] 스냅샷 없음 → 수급 데이터 직접 조회 시작")
            self._get_market_flow_fallback(market, top_n=top_n)

        stocks = self.get_top_stocks(market, top_n)
        if not stocks:
            return []
        results = []

        def analyze_one(tkr_name):
            ticker, name = tkr_name
            try:
                data = self.analyze_stock(ticker)
                if data is None:
                    return None
                data = dict(data)
                data['name'] = name
                return data
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futs = {executor.submit(analyze_one, s): s for s in stocks}
            try:
                for fut in as_completed(futs, timeout=180):
                    try:
                        r = fut.result(timeout=5)
                        if r is not None:
                            results.append(r)
                    except Exception:
                        pass
            except FTE:
                print("[스크리너] 타임아웃, 수집된 데이터 사용")

        # bulk 수급 스냅샷 적용: 스냅샷 값이 0이 아닌 경우 항상 우선 적용
        if self._market_flow_snapshot:
            for r in results:
                snap = self._market_flow_snapshot.get(r.get('ticker', ''))
                if snap:
                    snap_f = snap.get('foreigner', 0)
                    snap_i = snap.get('institution', 0)
                    # 스냅샷에 유효한 값이 있거나 per-stock이 0이면 스냅샷 사용
                    if snap_f != 0 or r.get('foreigner_net', 0) == 0:
                        r['foreigner_net'] = snap_f
                    if snap_i != 0 or r.get('institution_net', 0) == 0:
                        r['institution_net'] = snap_i

        filtered = [r for r in results if self._matches_conditions(r, conditions)]
        filtered.sort(key=lambda x: x['score'], reverse=True)
        print(f"[스크리너] {market}: {len(filtered)}/{len(results)}종목 매칭")
        return filtered[:50]

    def get_stock_detail(self, ticker):
        """종목 상세: 60일 가격 히스토리 + 퀀트 분석"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=100)
            end_str = end_date.strftime("%Y%m%d")
            start_str = start_date.strftime("%Y%m%d")

            df = None
            try:
                _df = stock.get_market_ohlcv_by_date(start_str, end_str, ticker)
                if _df is not None and not _df.empty:
                    _df.columns = ['open', 'high', 'low', 'close', 'volume', 'change']
                    df = _df
            except Exception:
                pass

            if df is None:
                df = fdr.DataReader(ticker, start_date, end_date)
                if df is None or df.empty:
                    return None
                df.columns = [c.lower() for c in df.columns]
            quant = self.analyze_stock(ticker)
            price_history = []
            for date, row in df.tail(60).iterrows():
                price_history.append({
                    'date': date.strftime('%Y%m%d'),
                    'close': int(row['close']),
                    'volume': int(row.get('volume', 0)),
                })
            return {'ticker': ticker, 'price_history': price_history, 'quant': quant}
        except Exception as e:
            print(f"[종목상세 오류] {ticker}: {e}")
            return None

    def _get_daily_flow_per_stock(self, market: str, target_date_strs: set) -> list:
        """일별 수급 폴백: 상위 30종목 date-range 조회 → 일별 합산"""
        try:
            df_list = fdr.StockListing(market)
            if df_list is None or df_list.empty:
                return []
            col_code = 'Code' if 'Code' in df_list.columns else df_list.columns[0]
            tickers = list(df_list.head(30)[col_code])
            min_date = min(target_date_strs)
            max_date = datetime.now().strftime("%Y%m%d")
            daily_accum: dict = {}

            def fetch_ticker(tkr):
                try:
                    df = stock.get_market_trading_volume_by_date(min_date, max_date, tkr)
                    if df is None or df.empty:
                        return {}
                    result = {}
                    is_multi = isinstance(df.columns, pd.MultiIndex)
                    for idx, row in df.iterrows():
                        ds = idx.strftime("%Y%m%d") if hasattr(idx, 'strftime') else str(idx)[:8]
                        if ds not in target_date_strs:
                            continue
                        f_net, i_net = 0, 0
                        if is_multi:
                            for investor in ['외국인합계', '외국인']:
                                if (investor, '순매수') in df.columns:
                                    f_net = int(row[(investor, '순매수')]); break
                            for investor in ['기관합계', '기관']:
                                if (investor, '순매수') in df.columns:
                                    i_net = int(row[(investor, '순매수')]); break
                        else:
                            for col in ['외국인합계', '외국인']:
                                if col in row.index:
                                    f_net = int(row[col]); break
                            for col in ['기관합계', '기관']:
                                if col in row.index:
                                    i_net = int(row[col]); break
                        result[ds] = {'foreigner': f_net, 'institution': i_net}
                    return result
                except Exception:
                    return {}

            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {ex.submit(fetch_ticker, t): t for t in tickers}
                try:
                    for fut in as_completed(futs, timeout=60):
                        try:
                            day_data = fut.result(timeout=5)
                            for ds, vals in day_data.items():
                                if ds not in daily_accum:
                                    daily_accum[ds] = {'foreigner': 0, 'institution': 0}
                                daily_accum[ds]['foreigner'] += vals['foreigner']
                                daily_accum[ds]['institution'] += vals['institution']
                        except Exception:
                            pass
                except FTE:
                    print("[일별수급 폴백] 타임아웃")

            return [{'date': d, 'foreigner': v['foreigner'], 'institution': v['institution'],
                     'total': v['foreigner'] + v['institution']}
                    for d, v in daily_accum.items()]
        except Exception as e:
            print(f"[일별수급 폴백 오류] {e}")
            return []

    def _get_market_flow_fdr(self, market="KOSPI", top_n=20):
        """FDR 기반 최후 폴백: 가격×거래량으로 수급 추정 (pykrx 전면 차단 시 사용)"""
        try:
            df_list = fdr.StockListing(market)
            if df_list is None or df_list.empty:
                return []

            end   = datetime.now()
            start = end - timedelta(days=15)
            results = []

            def fetch_fdr(row_data):
                tkr, name = row_data
                try:
                    df = fdr.DataReader(tkr, start, end)
                    if df is None or df.empty or len(df) < 3:
                        return None
                    df.columns = [c.lower() for c in df.columns]
                    n = min(5, len(df) - 1)
                    close_now  = float(df['close'].iloc[-1])
                    close_prev = float(df['close'].iloc[-(n + 1)])
                    avg_vol    = float(df['volume'].tail(n).mean())
                    if close_prev == 0 or avg_vol == 0:
                        return None
                    chg = (close_now - close_prev) / close_prev
                    # 가격변화 × 거래량 × 주가 → 억원 단위 추정
                    est = int(chg * avg_vol * close_now / 1e8)
                    return {
                        "name": name, "code": tkr,
                        "foreigner":    int(est * 0.55),
                        "institution":  int(est * 0.45),
                        "total":        est,
                    }
                except Exception:
                    return None

            col_code = 'Code' if 'Code' in df_list.columns else df_list.columns[0]
            col_name = 'Name' if 'Name' in df_list.columns else df_list.columns[1]
            rows = [(r[col_code], r[col_name]) for _, r in df_list.head(40).iterrows()]

            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = {ex.submit(fetch_fdr, r): r for r in rows}
                try:
                    for fut in as_completed(futs, timeout=25):
                        try:
                            r = fut.result(timeout=2)
                            if r and r['total'] != 0:
                                results.append(r)
                        except Exception:
                            pass
                except FTE:
                    print("[FDR 폴백] 타임아웃, 수집 데이터 사용")

            results.sort(key=lambda x: abs(x['total']), reverse=True)
            print(f"[FDR 폴백] {len(results)}종목")
            return results[:top_n]
        except Exception as e:
            print(f"[FDR 폴백 오류] {e}")
            return []
