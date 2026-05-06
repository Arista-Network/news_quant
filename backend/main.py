from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
import sys

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
async def get_market_flow(market: str = Query("KOSPI")):
    """시장 전체 외국인/기관 수급 히트맵 데이터"""
    data = quant_engine.get_market_flow(market=market)
    return {"status": "success", "data": data}


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
    return FileResponse(os.path.join(frontend_path, "style.css"))


@app.get("/app.js")
async def read_js():
    return FileResponse(os.path.join(frontend_path, "app.js"))


if __name__ == "__main__":
    import uvicorn
    print(f"Frontend: {frontend_path}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
