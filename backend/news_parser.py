import feedparser
from bs4 import BeautifulSoup
import FinanceDataReader as fdr
import re
from datetime import datetime

POSITIVE_WORDS = [
    "급등", "상승", "호재", "수주", "흑자", "수혜", "신고가", "돌파", "매수",
    "성장", "호전", "반등", "최고", "기대", "긍정", "낙폭과대", "저평가",
    "실적개선", "어닝서프라이즈", "목표가상향", "신규상장", "계약체결", "투자유치",
    "사상최대", "흑자전환", "호실적", "강세", "상향", "성장동력", "인수합병",
    "협약체결", "기술이전", "신약허가", "수출증가", "영업이익증가", "배당확대",
]
NEGATIVE_WORDS = [
    "급락", "하락", "악재", "적자", "매도", "폭락", "손실", "리스크", "우려",
    "하향", "감소", "부진", "위기", "경고", "규제", "제재", "소송", "횡령",
    "상폐", "실적쇼크", "어닝쇼크", "목표가하향", "공매도", "반도체한파",
    "영업적자", "순손실", "경영위기", "부도", "워크아웃", "약세", "침체",
    "불안", "경계", "리콜", "불확실", "매출감소", "수익악화", "파산위기",
]

CATEGORY_KEYWORDS = {
    "실적":   ["실적", "매출", "영업이익", "순이익", "흑자", "적자", "분기", "반기", "어닝"],
    "M&A":    ["인수", "합병", "M&A", "지분", "협약", "파트너십", "전략적제휴", "기업결합"],
    "수급":   ["외국인", "기관", "순매수", "순매도", "대규모매수", "매집", "수급"],
    "ETF":    ["ETF", "리밸런싱", "편입", "편출", "인덱스", "펀드", "구성종목"],
    "거시경제": ["금리", "환율", "인플레이션", "경기", "연준", "한국은행", "기준금리", "물가", "CPI"],
    "규제":   ["규제", "제재", "소송", "조사", "공정위", "금융위", "금감원", "과징금"],
}

ETF_REBAL_KEYWORDS = ["리밸런싱", "편입", "편출", "구성종목", "ETF", "인덱스펀드", "지수변경", "편출입"]


class NewsParser:
    def __init__(self):
        self.rss_sources = [
            {"name": "한국경제 증권", "url": "https://rss.hankyung.com/feed/hei.xml"},
            {"name": "매일경제 증권", "url": "https://www.mk.co.kr/rss/40300001/"},
            {"name": "연합뉴스 경제", "url": "https://www.yonhapnewstv.co.kr/category/news/economy/feed/"},
            {"name": "이데일리 증권", "url": "https://rss.edaily.co.kr/edaily_stock.xml"},
            {"name": "머니투데이", "url": "https://www.mt.co.kr/rss/news/stock.xml"},
            {"name": "뉴스1 경제", "url": "https://feeds.news1.kr/articles/economy"},
        ]
        self.stock_dict = {}
        self._load_stock_list()

    def _load_stock_list(self):
        try:
            df = fdr.StockListing('KRX')
            skip_names = {
                "대상", "제일", "보해", "동방", "남양", "한화", "효성",
                "현대", "삼성", "대한", "동아", "일진", "태영", "한일",
                "신세계", "한국", "코리아", "세아", "대우", "금호", "두산",
            }
            for _, row in df.iterrows():
                name = row['Name']
                ticker = row['Code']
                if isinstance(name, str) and len(name) >= 2 and name not in skip_names:
                    self.stock_dict[name] = ticker
        except Exception as e:
            print(f"[주식목록 오류] {e}")
            self.stock_dict = {
                "삼성전자": "005930", "SK하이닉스": "000660", "현대차": "005380",
                "NAVER": "035420", "카카오": "035720", "LG에너지솔루션": "373220",
            }

    def _analyze_sentiment(self, text: str) -> dict:
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
        total = pos_count + neg_count
        if total == 0:
            return {"label": "NEUTRAL", "score": 0, "pos": 0, "neg": 0}
        score = round((pos_count - neg_count) / total * 100)
        if score > 20:
            label = "POSITIVE"
        elif score < -20:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"
        return {"label": label, "score": score, "pos": pos_count, "neg": neg_count}

    def _extract_category(self, text: str) -> str:
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return category
        return "일반"

    def _is_etf_rebal_news(self, text: str) -> bool:
        return any(kw in text for kw in ETF_REBAL_KEYWORDS)

    def _dedupe_title(self, title: str) -> str:
        """중복 비교용 정규화 제목"""
        return re.sub(r'[\s\[\]()「」]', '', title).lower()

    def fetch_latest_news(self, limit=20) -> list:
        all_items = []
        seen_titles = set()

        for source in self.rss_sources:
            try:
                feed = feedparser.parse(source["url"])
                for entry in feed.entries[:8]:
                    title_text = entry.title.strip() if hasattr(entry, 'title') else ""
                    if not title_text:
                        continue

                    norm_title = self._dedupe_title(title_text)
                    if norm_title in seen_titles:
                        continue
                    seen_titles.add(norm_title)

                    # 요약문 추출 (summary > description > content 순)
                    summary_text = ""
                    for attr in ['summary', 'description']:
                        if hasattr(entry, attr) and getattr(entry, attr):
                            summary_text = BeautifulSoup(getattr(entry, attr), 'html.parser').get_text(strip=True)
                            break
                    if not summary_text and hasattr(entry, 'content') and entry.content:
                        summary_text = BeautifulSoup(entry.content[0].get('value', ''), 'html.parser').get_text(strip=True)

                    combined_text = title_text + " " + summary_text

                    # 종목 추출
                    extracted_stocks = []
                    for stock_name, stock_code in self.stock_dict.items():
                        if stock_name in combined_text:
                            extracted_stocks.append({"name": stock_name, "code": stock_code})
                    extracted_stocks = extracted_stocks[:3]

                    sentiment = self._analyze_sentiment(combined_text)
                    category = self._extract_category(combined_text)
                    is_etf_news = self._is_etf_rebal_news(combined_text)

                    # 발행일 파싱 보완
                    published = ""
                    if hasattr(entry, 'published'):
                        published = entry.published
                    elif hasattr(entry, 'updated'):
                        published = entry.updated

                    all_items.append({
                        "title": title_text,
                        "link": entry.link if hasattr(entry, 'link') else "",
                        "source": source["name"],
                        "published": published,
                        "summary": summary_text[:200] + "..." if len(summary_text) > 200 else summary_text,
                        "extracted_stocks": extracted_stocks,
                        "sentiment": sentiment,
                        "category": category,
                        "is_etf_rebal": is_etf_news,
                    })
            except Exception as e:
                print(f"[RSS 오류] {source['name']}: {e}")

        # 정렬: ETF 리밸런싱 뉴스 → 종목 감지 → 일반
        all_items.sort(key=lambda x: (x['is_etf_rebal'], len(x['extracted_stocks'])), reverse=True)
        return all_items[:limit]
