from pykrx import stock
import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta
import json
import os

MAJOR_ETFS = [
    {"ticker": "069500", "name": "KODEX 200",           "category": "시장지수"},
    {"ticker": "102110", "name": "TIGER 200",            "category": "시장지수"},
    {"ticker": "229720", "name": "KBSTAR 200",           "category": "시장지수"},
    {"ticker": "278530", "name": "KODEX KOSDAQ150",      "category": "시장지수"},
    {"ticker": "122630", "name": "KODEX 레버리지",        "category": "레버리지"},
    {"ticker": "114800", "name": "KODEX 인버스",          "category": "인버스"},
    {"ticker": "251340", "name": "KODEX 코스닥150레버리지","category": "레버리지"},
    {"ticker": "091160", "name": "KODEX 반도체",          "category": "섹터"},
    {"ticker": "091170", "name": "KODEX 은행",            "category": "섹터"},
    {"ticker": "091180", "name": "KODEX 자동차",          "category": "섹터"},
    {"ticker": "305720", "name": "KODEX 2차전지산업",     "category": "테마"},
    {"ticker": "139220", "name": "TIGER 200 IT",         "category": "섹터"},
    {"ticker": "266390", "name": "KODEX 에너지화학",      "category": "섹터"},
    {"ticker": "152100", "name": "ARIRANG 200",          "category": "시장지수"},
    {"ticker": "360750", "name": "TIGER 미국S&P500",     "category": "해외지수"},
]

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "etf_composition_cache.json")


class ETFTracker:
    def __init__(self):
        self._comp_cache: dict = {}
        self._rebal_cache: list = []
        self._rebal_date: str = ""
        self._perf_cache: list = []
        self._perf_date: str = ""
        self._load_disk_cache()

    # ── 캐시 ─────────────────────────────────────────────────────────────────
    def _load_disk_cache(self):
        if os.path.exists(_CACHE_FILE):
            try:
                with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                    self._comp_cache = json.load(f)
            except Exception:
                self._comp_cache = {}

    def _save_disk_cache(self):
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._comp_cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"[ETF 캐시 저장 오류] {e}")

    # ── 거래일 유틸 ───────────────────────────────────────────────────────────
    @staticmethod
    def _last_trading_day(offset_days: int = 0) -> str:
        d = datetime.now() - timedelta(days=offset_days)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d.strftime("%Y%m%d")

    # ── 구성종목 조회 ──────────────────────────────────────────────────────────
    def _get_composition(self, ticker: str, date_str: str) -> dict | None:
        key = f"{ticker}_{date_str}"
        if key in self._comp_cache:
            return self._comp_cache[key]

        try:
            df = stock.get_etf_portfolio_deposit_file(date_str, ticker)
            if df is None or df.empty:
                return None

            cols = {c.strip(): c for c in df.columns}
            comp = {}
            for _, row in df.iterrows():
                code = None
                for c in ['종목코드', 'Code', '코드', 'Ticker']:
                    if c in cols:
                        code = str(row[cols[c]]).strip().zfill(6)
                        break

                name = ""
                for c in ['종목명', 'Name', '명칭']:
                    if c in cols:
                        name = str(row[cols[c]]).strip()
                        break

                weight = 0.0
                for c in ['비중', 'Weight', '구성비율', '편입비율']:
                    if c in cols:
                        try:
                            weight = float(row[cols[c]])
                        except Exception:
                            pass
                        break

                if code and code != '000000':
                    comp[code] = {"name": name, "weight": weight}

            if comp:
                self._comp_cache[key] = comp
                self._save_disk_cache()
            return comp if comp else None

        except Exception as e:
            print(f"[ETF 구성종목 오류] {ticker} / {date_str}: {e}")
            return None

    # ── 리밸런싱 감지 ─────────────────────────────────────────────────────────
    def detect_rebalancing(self) -> list:
        today_str = self._last_trading_day(0)
        if self._rebal_date == today_str and self._rebal_cache is not None:
            return self._rebal_cache

        prev_str = self._last_trading_day(7)   # 7 거래일 전
        events = []

        for etf_info in MAJOR_ETFS:
            ticker = etf_info["ticker"]
            name = etf_info["name"]

            today_comp = self._get_composition(ticker, today_str)
            prev_comp = self._get_composition(ticker, prev_str)

            if not today_comp or not prev_comp:
                continue

            today_set = set(today_comp.keys())
            prev_set = set(prev_comp.keys())

            added = today_set - prev_set
            removed = prev_set - today_set

            reweighted = []
            for code in today_set & prev_set:
                tw = today_comp[code].get("weight", 0)
                pw = prev_comp[code].get("weight", 0)
                delta = tw - pw
                if abs(delta) >= 0.5:
                    reweighted.append({
                        "code": code,
                        "name": today_comp[code].get("name", code),
                        "prev_weight": round(pw, 2),
                        "curr_weight": round(tw, 2),
                        "change": round(delta, 2)
                    })

            reweighted.sort(key=lambda x: abs(x["change"]), reverse=True)

            if added or removed or len(reweighted) >= 3:
                events.append({
                    "etf_ticker": ticker,
                    "etf_name": name,
                    "category": etf_info["category"],
                    "date": today_str,
                    "prev_date": prev_str,
                    "added": [
                        {"code": c, "name": today_comp[c].get("name", c),
                         "weight": round(today_comp[c].get("weight", 0), 2)}
                        for c in sorted(added)
                    ],
                    "removed": [
                        {"code": c, "name": prev_comp[c].get("name", c)}
                        for c in sorted(removed)
                    ],
                    "reweighted": reweighted[:10],
                    "summary": self._make_summary(added, removed, reweighted, today_comp, prev_comp)
                })

        self._rebal_cache = events
        self._rebal_date = today_str
        return events

    @staticmethod
    def _make_summary(added, removed, reweighted, today_comp, prev_comp) -> str:
        parts = []
        if added:
            names = [today_comp[c].get("name", c) for c in list(added)[:3]]
            parts.append(f"신규편입: {', '.join(names)}")
        if removed:
            names = [prev_comp[c].get("name", c) for c in list(removed)[:3]]
            parts.append(f"편출: {', '.join(names)}")
        if reweighted:
            parts.append(f"{len(reweighted)}개 종목 비중 변경")
        return " / ".join(parts) if parts else "구성종목 소폭 변경"

    # ── ETF 성과 데이터 ───────────────────────────────────────────────────────
    def get_etf_performance(self) -> list:
        today_str = datetime.now().strftime("%Y%m%d")
        if self._perf_date == today_str and self._perf_cache:
            return self._perf_cache

        results = []
        end = datetime.now()
        start_30d = (end - timedelta(days=40)).strftime("%Y%m%d")

        for etf_info in MAJOR_ETFS:
            try:
                df = fdr.DataReader(etf_info["ticker"], start_30d, end)
                if df is None or df.empty or len(df) < 2:
                    continue

                df.columns = [c.lower() for c in df.columns]
                current = float(df['close'].iloc[-1])
                prev_month = float(df['close'].iloc[0])
                change_1m = round((current - prev_month) / prev_month * 100, 2)

                raw_change = float(df['change'].iloc[-1]) if 'change' in df.columns else 0
                change_1d = round(raw_change * 100, 2) if abs(raw_change) < 1 else round(raw_change, 2)

                volume = int(df['volume'].iloc[-1]) if 'volume' in df.columns else 0

                results.append({
                    "ticker": etf_info["ticker"],
                    "name": etf_info["name"],
                    "category": etf_info["category"],
                    "price": int(current),
                    "change_1d": change_1d,
                    "change_1m": change_1m,
                    "volume": volume,
                })
            except Exception as e:
                print(f"[ETF 성과 오류] {etf_info['name']}: {e}")
                continue

        self._perf_cache = results
        self._perf_date = today_str
        return results
