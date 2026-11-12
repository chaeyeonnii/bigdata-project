"""
장마감 직후 하루 1회 실행되는 스크립트.
관심종목(watchlist.csv)의 그날 최종 종가를 네이버 API로 조회해 Turso DB의 price_history
테이블에 누적 저장한다 (종목별 최근 15거래일치만 유지, 오래된 행은 삭제).

여기서 쌓은 종가를 실제로 읽어 그래프에 그리는 것은 다음 주에 한다 — 이번 주는 "쌓기"까지다.

예전에는 price_history.json 파일을 저장소에 직접 커밋해 상태를 유지했지만, DB 자체가 영속
저장소이므로 이제 그럴 필요가 없다.

⚠️ read_watchlist()와 fetch_naver_current_price()는 notify_stock_price.py에도 **똑같은 것이
한 벌 더** 들어 있다. 두 스크립트가 같은 일(관심종목 읽기, 현재가 조회)을 해야 하는데 각자
자기 파일 안에 갖고 있어서 그렇다. 한쪽을 고치면 다른 쪽도 똑같이 고쳐야 한다.
"""
import os
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from stock_utils import (KST, read_watchlist, fetch_naver_current_price, get_turso_client, update_price_history)

WATCHLIST_FILE = "watchlist.csv"
NUM_HISTORY_DAYS = 15
# 시간대를 명시하지 않으면 실행 환경에 따라 날짜가 하루 어긋날 수 있다. 항상 이 KST를 기준으로 쓴다.
KST = ZoneInfo("Asia/Seoul")

load_dotenv()

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

watchlist_codes = read_watchlist()
if watchlist_codes is None:
    # 관심종목 목록을 못 읽었으면 더 할 수 있는 일이 없으므로 여기서 프로그램을 끝낸다.
    exit()

print(f"🚀 종가 수집 시작... (실행 시각 {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST)")

collected = 0  # 실제로 저장에 성공한 종목 수를 센다.
# get_turso_client()를 루프 밖에서 딱 한 번만 호출해 클라이언트 하나를 만들고, 종목마다
# update_price_history()에 그 client를 넘겨 재사용한다 — 관심종목이 몇 개 안 될 때는 차이가
# 작지만, 종목 수가 늘어날수록(예: 20개) 종목마다 새로 연결을 맺고 매번 테이블 존재 확인
# 쿼리까지 반복하는 비용을 줄여준다. with 문이라 루프가 끝나면(예외가 나도) client.close()가
# 자동으로 호출된다.
with get_turso_client() as client:
    for code in watchlist_codes:
        info = fetch_naver_current_price(code)
        if info is None:
            continue

        if info["is_open"]:
            # 장마감 후 실행되어야 하는 스크립트인데 아직 장중이면 종가가 확정되지 않은
            # 상태이므로 히스토리에 반영하지 않는다 (실행 시각 설정을 다시 확인해야 함).
            print(f"⚠️ [{code}] 아직 장중입니다. 확정되지 않은 가격이라 기록하지 않습니다.")
            continue

        # 저장할 날짜는 "지금 몇 시인가"가 아니라 "이 가격이 언제 체결된 것인가"로 정한다.
        # datetime.now()를 쓰면 실행이 늦어져 자정을 넘겼을 때 전날 종가가 다음날 날짜로
        # 저장된다. traded_at은 체결 시각이라 실행 시각과 무관하게 항상 옳은 거래일을 가리킨다.
        # "2026-07-29T16:10:20+09:00"에서 앞 10글자가 날짜("2026-07-29")이고, 하이픈을 빼면
        # DB의 date 컬럼 형식("20260729")이 된다.
        traded_at = info.get("traded_at") or ""
        if len(traded_at) >= 10:
            date_str = traded_at[:10].replace("-", "")
        else:
            # 네이버 응답에 이 필드가 없거나 형식이 바뀐 경우의 폴백 — 실행 시각을 쓴다.
            date_str = datetime.now(KST).strftime("%Y%m%d")
            print(f"⚠️ [{code}] 체결 시각을 읽지 못해 실행 시각 기준으로 날짜를 정합니다.")

        update_price_history(code, date_str, info["price"], client=client)
        collected += 1
        print(f"✅ [{code}] {info['name']} {date_str} 종가 {info['price']:,}원 기록")

if collected == 0:
    print("❌ 기록된 종가가 하나도 없습니다.")
    # 저장된 것이 하나도 없으므로, 아래 완료 메시지를 찍지 않고 여기서 끝낸다.
    exit()

print(f"🎉 종가 히스토리를 Turso DB에 저장했습니다 ({collected}/{len(watchlist_codes)}종목).")
