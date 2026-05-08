from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
import os, sys, asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from news_parser import NewsParser
from quant_engine import QuantEngine
from etf_tracker import ETFTracker

app = FastAPI(title="NewsQuant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

news_parser = NewsParser()
quant_engine = QuantEngine()
etf_tracker = ETFTracker()

VALID_PERIODS = {1, 7, 30, 365}

# ── 수급맵 백그라운드 캐시 (키: f"{market}_{period}") ───────────────────────
_flow_cache: dict = {}   # {"data": [], "loading": False}
_trend_cache: dict = {}  # {"data": [], "loading": False}


def _flow_key(market: str, period: int) -> str:
    return f"{market}_{period}"


async def _refresh_flow(market: str, period: int = 7):
    key = _flow_key(market, period)
    entry = _flow_cache.setdefault(key, {"data": [], "loading": False})
    if entry["loading"]:
        return
    entry["loading"] = True
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: quant_engine.get_market_flow(market, period_days=period)
            ),
            timeout=120.0,
        )
        entry["data"] = data or []
        print(f"[수급맵 캐시] {key} 업데이트: {len(entry['data'])}종목")
    except asyncio.TimeoutError:
        print(f"[수급맵 캐시] {key} 타임아웃")
    except Exception as e:
        print(f"[수급맵 캐시 오류] {key}: {e}")
    finally:
        entry["loading"] = False


async def _refresh_trend(market: str, period: int = 7):
    key = _flow_key(market, period)
    entry = _trend_cache.setdefault(key, {"data": [], "loading": False})
    if entry["loading"]:
        return
    entry["loading"] = True
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(
                None, lambda: quant_engine.get_market_daily_flow(market, period_days=period)
            ),
            timeout=120.0,
        )
        entry["data"] = data or []
        print(f"[추이 캐시] {key} 업데이트: {len(entry['data'])}건")
    except asyncio.TimeoutError:
        print(f"[추이 캐시] {key} 타임아웃")
    except Exception as e:
        print(f"[추이 캐시 오류] {key}: {e}")
    finally:
        entry["loading"] = False


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_refresh_flow("KOSPI", 7))
    asyncio.create_task(_refresh_trend("KOSPI", 7))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/news")
async def get_news_with_quant():
    """최신 뉴스 + 퀀트 인사이트 통합 API"""
    news_items = news_parser.fetch_latest_news(limit=15)
    for item in news_items:
        quant_data_list = []
        for stock_info in item["extracted_stocks"]:
            q_data = quant_engine.analyze_stock(stock_info["code"])
            if q_data:
                q_data["name"] = stock_info["name"]
                quant_data_list.append(q_data)
        item["quant_data"] = quant_data_list
    return {"status": "success", "data": news_items}


@app.get("/api/market-flow")
async def get_market_flow(
    market: str = Query("KOSPI"),
    period: int = Query(7),
):
    """시장 전체 외국인/기관 수급 히트맵 데이터 (백그라운드 캐시)"""
    if period not in VALID_PERIODS:
        period = 7
    key = _flow_key(market, period)
    entry = _flow_cache.setdefault(key, {"data": [], "loading": False})

    if not entry["data"] and not entry["loading"]:
        asyncio.create_task(_refresh_flow(market, period))

    if entry["loading"] and not entry["data"]:
        return {"status": "loading", "data": []}

    return {"status": "success", "data": entry["data"]}


@app.get("/api/market-flow/refresh")
async def force_refresh_flow(
    market: str = Query("KOSPI"),
    period: int = Query(7),
):
    """수급맵 강제 갱신 트리거"""
    if period not in VALID_PERIODS:
        period = 7
    key = _flow_key(market, period)
    _flow_cache[key] = {"data": [], "loading": False}
    _trend_cache[key] = {"data": [], "loading": False}
    asyncio.create_task(_refresh_flow(market, period))
    asyncio.create_task(_refresh_trend(market, period))
    return {"status": "refreshing", "market": market, "period": period}


@app.get("/api/market-flow/trend")
async def get_market_flow_trend(
    market: str = Query("KOSPI"),
    period: int = Query(7),
):
    """일별(또는 주간) 시장 수급 추이 데이터 (차트용)"""
    if period not in VALID_PERIODS:
        period = 7
    key = _flow_key(market, period)
    entry = _trend_cache.setdefault(key, {"data": [], "loading": False})

    if not entry["data"] and not entry["loading"]:
        asyncio.create_task(_refresh_trend(market, period))

    if entry["loading"] and not entry["data"]:
        return {"status": "loading", "data": []}

    return {"status": "success", "data": entry["data"]}


_screener_cache: dict = {}


async def _run_screener_bg(market: str, conditions: dict, cache_key: str):
    entry = _screener_cache.setdefault(cache_key, {"data": [], "loading": False})
    if entry["loading"]:
        return
    entry["loading"] = True
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: quant_engine.run_screener(market, conditions)),
            timeout=200.0,
        )
        entry["data"] = data or []
        print(f"[스크리너 캐시] {cache_key}: {len(entry['data'])}종목")
    except asyncio.TimeoutError:
        print(f"[스크리너 캐시] {cache_key} 타임아웃")
    except Exception as e:
        print(f"[스크리너 캐시 오류] {cache_key}: {e}")
    finally:
        entry["loading"] = False


@app.get("/api/screener")
async def get_screener_results(
    market: str = Query("KOSPI"),
    conditions: str = Query(""),
    refresh: bool = Query(False),
):
    """퀀트 스크리너 (백그라운드 캐시)"""
    cond_list = [c.strip() for c in conditions.split(",") if c.strip()]
    cond_dict = {c: True for c in cond_list}
    cache_key = f"screener_{market}_{conditions}"
    entry = _screener_cache.setdefault(cache_key, {"data": [], "loading": False})
    if refresh:
        entry["data"] = []
        entry["loading"] = False
    if not entry["data"] and not entry["loading"]:
        asyncio.create_task(_run_screener_bg(market, cond_dict, cache_key))
    if entry["loading"] and not entry["data"]:
        return {"status": "loading", "data": [], "total": 0}
    return {"status": "success", "data": entry["data"], "total": len(entry["data"])}


@app.get("/api/stock/{ticker}")
async def get_stock_detail_api(ticker: str):
    """종목 상세 분석 (미니 차트 + 퀀트)"""
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: quant_engine.get_stock_detail(ticker)),
            timeout=30.0,
        )
        if data:
            return {"status": "success", "data": data}
        return {"status": "error", "message": "데이터 없음", "data": None}
    except asyncio.TimeoutError:
        return {"status": "error", "message": "타임아웃", "data": None}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}


@app.get("/api/etf-rebalancing")
async def get_etf_rebalancing():
    """ETF 리밸런싱 이벤트 감지 API"""
    try:
        events = etf_tracker.detect_rebalancing()
        return {"status": "success", "data": events, "count": len(events)}
    except Exception as e:
        print(f"[ETF 리밸런싱 API 오류] {e}")
        return {"status": "error", "message": str(e), "data": [], "count": 0}


@app.get("/api/etf-performance")
async def get_etf_performance():
    """주요 ETF 성과 데이터 API"""
    try:
        data = etf_tracker.get_etf_performance()
        return {"status": "success", "data": data}
    except Exception as e:
        print(f"[ETF 성과 API 오류] {e}")
        return {"status": "error", "message": str(e), "data": []}


# 프론트엔드 파일 서빙
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_path = os.path.join(BASE_DIR, "frontend")


@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))


@app.get("/style.css")
async def read_css():
    resp = FileResponse(os.path.join(frontend_path, "style.css"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/app.js")
async def read_js():
    resp = FileResponse(os.path.join(frontend_path, "app.js"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


if __name__ == "__main__":
    import uvicorn
    print(f"Frontend: {frontend_path}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
