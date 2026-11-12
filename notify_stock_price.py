"""
하루 3회(장이 열리는 날 오전 10시/12시/2시) 실행되는 알림 스크립트.
관심종목(watchlist.csv)의 현재가를 네이버 API로 조회해 텔레그램 텍스트 메시지로 보내고,
오늘 분봉(네이버 API로 즉시 조회, 저장하지 않음)으로 추이 그래프를 종목별로 그려 sendPhoto로
전송한다.

이번 주에 collect_daily_close.py가 생겨 종가가 DB에 쌓이기 시작하지만, 이 스크립트는 아직
그 DB를 읽지 않는다 — 그래서 그래프에는 오늘 하루치만 그려진다. DB에 쌓인 종가를 읽어와
그래프 왼쪽을 채우는 것은 다음 주에 한다.

send_price_notification()으로 알림 로직 전체를 함수 하나에 감싸 두었다.
`python notify_stock_price.py`로 직접 실행하면 그 함수가 그대로 실행된다.
"""
import os
import io
import re
import time
import html
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from stock_utils import (read_watchlist, fetch_naver_current_price, fetch_naver_intraday_minutes, send_telegram_message,
                         send_telegram_photo,describe_price_trend,format_rate_badge,dedupe_daily_closes, 
                         _evenly_spaced,build_price_chart,resolve_today_price,load_price_history)


# pandas/matplotlib은 read_watchlist()/build_price_chart() 안에서 그때그때 import한다.
# 파일을 열자마자 무거운 패키지를 읽어들이지 않으려는 것이다.

WATCHLIST_FILE = "watchlist.csv"
# 시간대를 명시하지 않으면 실행 환경에 따라 날짜가 하루 어긋날 수 있다. 항상 이 KST를 기준으로 쓴다.
KST = ZoneInfo("Asia/Seoul")

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_price_notification() -> bool:
    """관심종목 현재가 텍스트 메시지와 종목별 추이 그래프를 텔레그램으로 전송합니다.

    관심종목을 하나라도 처리했으면 True, 아무것도 하지 못했으면 False를 반환합니다.
    여기서 "아무것도 하지 못했다"에는 조회에 전부 실패한 경우뿐 아니라 조회는 됐는데
    텔레그램 전송이 전부 실패한 경우도 포함됩니다.
    """
    watchlist_codes = read_watchlist()
    if watchlist_codes is None:
        return False

    # 1. 네이버 API로 현재가 조회 후 텔레그램 텍스트 메시지 전송
    print("🚀 관심종목 현재가 조회 시작...")

    current_prices = {}  # code -> fetch_naver_current_price() 결과
    # 종목별 상세 정보(가격·등락 등)는 사진 캡션에 담기므로, 헤더 문구만 먼저 만들어둔다
    # (추이 설명은 아래에서 대표 종목 데이터로 한 번만 덧붙인다). 아래 for문은 그래프 전송(2번)
    # 단계에서 쓸 current_prices만 채운다.
    telegram_message = "📊 <b>내 관심종목 현재가</b>"

    for code in watchlist_codes:
        info = fetch_naver_current_price(code)
        if info is None:
            # 이 종목만 조회 실패해도 프로그램을 멈추지 않고 다음 종목으로 넘어간다.
            continue

        current_prices[code] = info

    if not current_prices:
        print("❌ 관심종목의 현재가를 하나도 가져오지 못했습니다. 네이버 API 상태를 확인해 주세요.")
        return False

    # 2. 오늘 분봉으로 그래프 생성 및 전송
    # 종목별 오늘 분봉을 미리 한 번씩만 조회해 딕셔너리에 담아둔다. 아래 헤더 문구(대표 종목)와
    # 그래프 루프가 같은 종목의 분봉을 각각 조회하면 같은 API를 두 번 부르게 되고, 조회 시각이
    # 달라 헤더와 그래프가 서로 다른 데이터를 보게 될 수 있다.
    price_history = load_price_history()    

    intraday_by_code = {code: fetch_naver_intraday_minutes(code) for code in current_prices}

    # 추이 설명(describe_price_trend())은 종목마다 거의 같은 문구가 반복되므로, 대표로 첫
    # 종목의 데이터만 써서 헤더 문구 아래 한 번만 붙인다 (종목별 사진 캡션에는 넣지 않는다).
    # next(iter(current_prices)): current_prices는 {종목코드: 조회결과} 딕셔너리인데, 딕셔너리
    # 자체를 순회(iter)하면 키(종목코드)들이 나온다 — 그중 맨 처음 것 하나만 next()로 꺼낸다.
    first_code = next(iter(current_prices))
    first_info = current_prices[first_code]
    first_daily_closes = price_history.get(first_code, [])
    first_intraday_minutes = intraday_by_code[first_code]
    first_today_price = resolve_today_price(first_info["price"], first_info["is_open"], first_intraday_minutes, first_daily_closes)
    first_daily_closes = dedupe_daily_closes(first_daily_closes, first_today_price, first_intraday_minutes)
    # 첫 번째 인자(과거 종가 목록)에 빈 리스트를 넘긴다 — 이 스크립트는 아직 DB를 읽지 않으므로
    # 그릴 수 있는 것이 오늘 하루치뿐이기 때문이다. 그래서 문구도 "종가 히스토리 누적 전"이 된다.
    # 다음 주에 DB를 읽어 여기에 실제 종가 목록을 넘기면 문구가 "최근 N일 종가 + 현재가 추이"로 바뀐다.
    telegram_message += f"\n\n{describe_price_trend(first_daily_closes, first_intraday_minutes)}"

    sent = 0  # 텔레그램으로 실제 전송에 성공한 건수(텍스트 1건 + 종목별 사진)를 센다.

    if send_telegram_message(telegram_message):
        sent += 1
        print("✅ 현재가 메시지를 텔레그램으로 전송했습니다!")
    else:
        print("❌ 현재가 메시지 전송에 실패했습니다.")

    # current_prices.items(): {종목코드: 조회결과} 딕셔너리를 (code, info) 쌍으로 순회한다.
    for code, info in current_prices.items():
        daily_closes = price_history.get(code, []) #종목마다daily_closes를꺼내고, 없으면⚠️를찍습니다
        if not daily_closes:
            print(f"⚠️[{code}] 저장된종가히스토리가없어현재가만으로그래프를그립니다. "
                  f"collect_daily_close.py가아직한번도실행되지않았을수있습니다.")
            
        intraday_minutes = intraday_by_code[code]
        today_price = resolve_today_price(info["price"], info["is_open"], intraday_minutes, daily_closes)
        chart_buffer = build_price_chart(daily_closes, today_price, intraday_minutes)
        # send_telegram_photo()가 parse_mode="HTML"로 보내므로, 종목명을 <b> 태그로 감싸면
        # 굵게 표시된다. html.escape()로 종목명에 HTML 특수문자가 섞여 있어도 태그 구조가
        # 깨지지 않게 한다. 텔레그램 캡션은 일반 텍스트라 HTML과 달리 공백이 줄어들지 않으므로,
        # "    "(공백 4칸)를 그대로 써도 들여쓰기가 유지된다.
        caption = (
            f"📈 <b>{html.escape(info['name'])}</b> ({code})\n"
            f"    {format_rate_badge(info['price'], info['rate'])}"
        )

        if send_telegram_photo(chart_buffer, caption):
            sent += 1
            print(f"🎉 [{code}] 추이 그래프를 텔레그램으로 전송했습니다!")
        else:
            print(f"❌ [{code}] 추이 그래프 전송에 실패했습니다.")

    # "하나도 못 보냈을 때만" 실패로 본다 — 일부 종목의 사진만 실패한 경우는 나머지가 정상적으로
    # 도착했으므로 실패가 아니다.
    if sent == 0:
        print("❌ 텔레그램으로 아무것도 전송하지 못했습니다. 봇 토큰과 텔레그램 API 상태를 확인해 주세요.")
        return False

    return True


# if __name__ == "__main__": 은 "이 파일을 직접 실행했을 때만" 아래 코드를 돌리라는 뜻이다.
# 다른 스크립트가 `from notify_stock_price import send_price_notification`처럼 함수만
# 가져다 쓰는 경우에는 이 블록이 자동으로 실행되지 않는다.
if __name__ == "__main__":
    send_price_notification()
