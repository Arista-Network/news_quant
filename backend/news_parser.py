import feedparser
from bs4 import BeautifulSoup
import FinanceDataReader as fdr
import re

# 간이 감성 분석 사전
POSITIVE_WORDS = [
    "급등", "상승", "호재", "수주", "흑자", "수혜", "신고가", "돌파", "매수",
    "성장", "호전", "반등", "최고", "대박", "기대", "긍정", "낙폭과대", "저평가",
    "실적개선", "어닝서프라이즈", "목표가상향", "신규상장", "계약체결", "투자유치"
]
NEGATIVE_WORDS = [
    "급락", "하락", "악재", "적자", "매도", "폭락", "손실", "리스크", "우려",
    "하향", "감소", "부진", "위기", "경고", "규제", "제재", "소송", "횡령",
    "상폐", "실적쇼크", "어닝쇼크", "목표가하향", "공매도", "반도체한파"
]

class NewsParser:
    def __init__(self):
        # 다중 RSS 소스
        self.rss_sources = [
            {"name": "한국경제 증권", "url": "https://rss.hankyung.com/feed/hei.xml"},
            {"name": "매일경제 증권", "url": "https://www.mk.co.kr/rss/40300001/"},
            {"name": "연합뉴스 경제", "url": "https://www.yonhapnewstv.co.kr/category/news/economy/feed/"},
        ]
        self.stock_dict = {}
        self._load_stock_list()

    def _load_stock_list(self):
        try:
            df = fdr.StockListing('KRX')
            # 2글자 이상의 종목만 등록하여 오탐 방지
            skip_names = {"대상", "제일", "보해", "동방", "남양", "한화", "효성",
                          "현대", "삼성", "대한", "동아", "일진", "태영", "한일",
                          "신세계", "한국", "코리아", "세아", "대우"}
            for _, row in df.iterrows():
                name = row['Name']
                ticker = row['Code']
                if isinstance(name, str) and len(name) >= 2 and name not in skip_names:
                    self.stock_dict[name] = ticker
        except Exception as e:
            print(f"Error loading stock list: {e}")
            self.stock_dict = {
                "삼성전자": "005930", "SK하이닉스": "000660", "현대차": "005380",
                "NAVER": "035420", "카카오": "035720", "LG에너지솔루션": "373220"
            }

    def _analyze_sentiment(self, text):
        """간이 감성 분석 (키워드 기반)"""
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
        total = pos_count + neg_count
        if total == 0:
            return {"label": "NEUTRAL", "score": 0}
        score = round((pos_count - neg_count) / total * 100)
        if score > 20:
            return {"label": "POSITIVE", "score": score}
        elif score < -20:
            return {"label": "NEGATIVE", "score": score}
        return {"label": "NEUTRAL", "score": score}

    def fetch_latest_news(self, limit=20):
        """다중 RSS에서 뉴스를 수집하여 통합 반환"""
        all_items = []
        seen_titles = set()

        for source in self.rss_sources:
            try:
                feed = feedparser.parse(source["url"])
                for entry in feed.entries[:8]:
                    title_text = entry.title.strip()
                    # 중복 제거
                    if title_text in seen_titles:
                        continue
                    seen_titles.add(title_text)

                    summary_text = ""
                    if hasattr(entry, 'summary') and entry.summary:
                        summary_text = BeautifulSoup(entry.summary, 'html.parser').get_text(strip=True)

                    combined_text = title_text + " " + summary_text

                    # 종목 추출
                    extracted_stocks = []
                    for stock_name, stock_code in self.stock_dict.items():
                        if stock_name in combined_text:
                            extracted_stocks.append({"name": stock_name, "code": stock_code})
                    extracted_stocks = extracted_stocks[:3]

                    # 감성 분석
                    sentiment = self._analyze_sentiment(combined_text)

                    all_items.append({
                        "title": title_text,
                        "link": entry.link,
                        "source": source["name"],
                        "published": entry.published if hasattr(entry, 'published') else "",
                        "summary": summary_text[:200] + "..." if len(summary_text) > 200 else summary_text,
                        "extracted_stocks": extracted_stocks,
                        "sentiment": sentiment
                    })
            except Exception as e:
                print(f"Error parsing {source['name']}: {e}")

        # 종목이 있는 뉴스를 우선 정렬
        all_items.sort(key=lambda x: len(x['extracted_stocks']), reverse=True)
        return all_items[:limit]
