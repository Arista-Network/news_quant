import requests
import json

print("=" * 60)
print("NewsQuant API 테스트")
print("=" * 60)

# 1. 뉴스 API 테스트
try:
    r = requests.get("http://localhost:8000/api/news", timeout=30)
    d = r.json()
    print(f"\n[뉴스 API] Status: {d['status']}")
    print(f"[뉴스 API] 총 기사 수: {len(d['data'])}")
    
    for i, item in enumerate(d["data"][:5]):
        print(f"\n  --- 기사 {i+1} ---")
        print(f"  출처: {item.get('source', 'N/A')}")
        print(f"  제목: {item['title'][:60]}...")
        print(f"  감성: {item.get('sentiment', {}).get('label', 'N/A')} (점수: {item.get('sentiment', {}).get('score', 0)})")
        stocks = [s["name"] for s in item.get("extracted_stocks", [])]
        print(f"  감지 종목: {stocks if stocks else '없음'}")
        qcount = len(item.get("quant_data", []))
        print(f"  퀀트 카드: {qcount}개")
        if qcount > 0:
            q = item["quant_data"][0]
            print(f"    -> {q['name']} | 가격: {q['current_price']:,}원 | RSI: {q['rsi']} | 시그널: {q['signal']} (Score: {q['score']})")
            print(f"    -> 외국인: {q['foreigner_net']:+,}주 | 기관: {q['institution_net']:+,}주")
            print(f"    -> 이유: {', '.join(q['reason'])}")
    
    print("\n" + "=" * 60)
    print("뉴스 API 테스트 성공!")
except Exception as e:
    print(f"뉴스 API 오류: {e}")

# 2. 프론트엔드 서빙 테스트
try:
    r2 = requests.get("http://localhost:8000/")
    if "NewsQuant" in r2.text:
        print("프론트엔드 서빙 정상!")
    else:
        print("프론트엔드 로딩 실패")
except Exception as e:
    print(f"프론트엔드 오류: {e}")

print("=" * 60)
