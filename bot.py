import requests
import json
import time
import datetime
import os
from threading import Thread
from difflib import get_close_matches
from zoneinfo import ZoneInfo

# ==================== 설정 ====================
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URL = "https://openapi.koreainvestment.com:9443"
DATA_FILE = "stock_monitor.json"

# ==================== 설정 변수 ====================
alert_threshold = 2.0          # 변동률 기준 (%)
check_interval = 5             # 체크 간격 (초)

# ==================== 데이터 ====================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "stocks": {
            "삼성전자": "005930",
            "SK하이닉스": "000660",
            "파세코": "037070"
        },
        "targets": {}
    }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
stocks = data.get("stocks", {})
targets = data.get("targets", {})

# ==================== 유틸 함수 ====================
def is_market_open():
    """정규장 시간 체크 (평일 09:00 ~ 15:30)"""
    now = datetime.datetime.now()
    if now.weekday() >= 5:  # 토, 일
        return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def get_access_token():
    url = f"{URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, data=json.dumps(body))
    return res.json().get('access_token')

def get_valid_token():
    if 'current_token' not in globals() or globals().get('token_issue_date') != datetime.date.today():
        globals()['current_token'] = get_access_token()
        globals()['token_issue_date'] = datetime.date.today()
    return globals()['current_token']

def get_market_data(token, ticker):
    """현재가 조회 (정규장 + 시간외 모두 가능)"""
    url = f"{URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker
    }
    try:
        res = requests.get(url, headers=headers, params=params).json()['output']
        current = int(res.get('stck_prpr', 0))
        open_p = int(res.get('stck_oprc', 0))
        high = int(res.get('stck_hgpr', 0))
        low = int(res.get('stck_lwpr', 0))
        return current, open_p, high, low
    except Exception as e:
        print(f"시세 조회 오류 ({ticker}): {e}")
        return 0, 0, 0, 0

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    })

def find_ticker_by_name(name):
    matches = get_close_matches(name, stocks.keys(), n=3, cutoff=0.6)
    if matches:
        return matches[0], stocks[matches[0]]
    return None, None

# ==================== 텔레그램 리스너 ====================
def telegram_listener():
    offset = 0
    print("텔레그램 리스너 시작...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=30"
            res = requests.get(url).json()
            if res.get('ok') and res.get('result'):
                for update in res['result']:
                    offset = update['update_id'] + 1
                    if 'message' not in update:
                        continue
                    if str(update['message']['chat']['id']) != str(CHAT_ID):
                        continue

                    text = update['message']['text'].strip()

                    if text in ['/help', '/도움말']:
                        send_telegram(
                            "📌 <b>명령어 목록</b>\n\n"
                            "• /add 이름 코드 → 신규 종목 추가\n"
                            "• /remove 이름 → 종목 삭제\n"
                            "• /target 이름 가격 → 목표가 설정\n"
                            "• /시세 이름  or  /가격 이름 → 현재가 조회 (시간외 포함)\n"
                            "• /변동률 숫자 → 알림 기준 변경\n"
                            "• /간격 초 → 체크 간격 변경\n"
                            "• /상태 → 현재 설정 확인\n"
                            "• /list → 감시 종목 목록"
                        )

                    elif text.startswith(('/add ', '/추가 ')):
                        parts = text.split(maxsplit=2)
                        if len(parts) >= 3:
                            name = parts[1].strip()
                            code = parts[2].strip()
                            if code.isdigit() and len(code) == 6:
                                stocks[name] = code
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"✅ {name} ({code}) 추가 완료!")
                            else:
                                send_telegram("❌ 종목코드는 6자리 숫자여야 합니다.\n예: /add 모나미 005360")
                        else:
                            name = parts[1].strip()
                            matched, code = find_ticker_by_name(name)
                            if code:
                                stocks[matched] = code
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"✅ {matched} 추가 완료!")
                            else:
                                send_telegram(f"❌ '{name}'을(를) 찾을 수 없습니다.")

                    elif text.startswith(('/remove ', '/del ', '/삭제 ')):
                        name = text.split(maxsplit=1)[1].strip()
                        if name in stocks:
                            del stocks[name]
                            targets.pop(name, None)
                            save_data({"stocks": stocks, "targets": targets})
                            send_telegram(f"🗑 {name} 삭제 완료")
                        else:
                            send_telegram("❌ 목록에 없는 종목입니다.")

                    elif text.startswith(('/target ', '/목표가 ')):
                        parts = text.split()
                        if len(parts) >= 3 and parts[1] in stocks:
                            try:
                                price = int(parts[2].replace(',', ''))
                                targets[parts[1]] = price
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"🎯 {parts[1]} 목표가 {price:,}원 설정 완료")
                            except:
                                send_telegram("❌ /target 이름 가격 형식으로 입력")
                        else:
                            send_telegram("❌ 종목이 없거나 형식이 틀렸습니다.")

                    # ========== 시세 조회 (시간외 포함) ==========
                    elif text.startswith(('/시세 ', '/가격 ', '/현재가 ')):
                        name = text.split(maxsplit=1)[1].strip()
                        matched, code = find_ticker_by_name(name)
                        if not code and name in stocks:
                            matched, code = name, stocks[name]
                        
                        if not code:
                            send_telegram(f"❌ '{name}' 종목을 찾을 수 없습니다.")
                            continue
                        
                        token = get_valid_token()
                        current, open_p, high, low = get_market_data(token, code)
                        
                        if current == 0:
                            send_telegram(f"❌ {matched} 시세 조회 실패")
                            continue
                        
                        change = (current - open_p) / open_p * 100 if open_p else 0
                        status = "🟢 정규장" if is_market_open() else "🌙 시간외"
                        
                        send_telegram(
                            f"{status} <b>{matched}</b>\n\n"
                            f"현재가: <b>{current:,}원</b>\n"
                            f"시가: {open_p:,}원\n"
                            f"고가: {high:,}원\n"
                            f"저가: {low:,}원\n"
                            f"등락률: {change:+.2f}%"
                        )

                    elif text.startswith(('/변동률 ', '/threshold ')):
                        try:
                            global alert_threshold
                            alert_threshold = float(text.split()[1])
                            send_telegram(f"📊 변동률 알림 기준을 <b>{alert_threshold}%</b>로 변경했습니다.")
                        except:
                            send_telegram("❌ /변동률 1.5 형식으로 입력")

                    elif text.startswith(('/간격 ', '/interval ')):
                        try:
                            global check_interval
                            check_interval = int(text.split()[1])
                            send_telegram(f"⏱ 체크 간격을 <b>{check_interval}초</b>로 변경했습니다.")
                        except:
                            send_telegram("❌ /간격 10 형식으로 입력")

                    elif text in ['/상태', '/status']:
                        market_status = "🟢 정규장 중" if is_market_open() else "🔴 장 마감 (알림 중단)"
                        send_telegram(
                            f"📈 <b>현재 설정</b>\n\n"
                            f"• 장 상태: {market_status}\n"
                            f"• 변동률 기준: {alert_threshold}%\n"
                            f"• 체크 간격: {check_interval}초\n"
                            f"• 감시 종목 수: {len(stocks)}개"
                        )

                    elif text == '/list':
                        if stocks:
                            msg = "📋 <b>감시 종목</b>\n" + "\n".join([f"• {n} ({c})" for n, c in stocks.items()])
                        else:
                            msg = "📋 감시 중인 종목이 없습니다."
                        send_telegram(msg)

        except Exception as e:
            print(f"텔레그램 오류: {e}")
            time.sleep(5)

# ==================== 감시 루프 ====================
# ==================== 감시 루프 (휴장일 완벽 처리) ====================
# ==================== 감시 루프 (datetime 오류 수정 버전) ====================
def monitoring_loop():
    global alert_threshold, check_interval
    print(f"🚀 감시 시작 (변동률 {alert_threshold}%, {check_interval}초 간격)")
    last_alert = {}
    last_afterhours = {}

    while True:
        try:
            print("🔍 감시 루프 실행 중...")
            
            # 올바른 datetime 사용
            now = datetime.datetime.now()
            weekday = now.weekday()
            hour = now.hour
            minute = now.minute

            is_weekend = weekday >= 5
            is_afterhours = (hour == 15 and minute >= 40) or (hour == 16 and minute < 5)

            if is_weekend:
                print("📅 주말이라 스킵")
                time.sleep(60)
                continue

            token = get_valid_token()
            print(f"🔑 토큰 발급 성공")

            for name, ticker in list(stocks.items()):
                current_p, open_p = get_market_data(token, ticker)
                print(f"📈 {name}: 현재가={current_p}, 시가={open_p}")

                if open_p == 0 and not is_afterhours:
                    print(f"⚠️ {name} 시가 0 → 스킵")
                    continue

                # 정규장
                if not is_afterhours and open_p > 0:
                    change = (current_p - open_p) / open_p * 100

                    if abs(change) >= alert_threshold:
                        key = f"regular_{name}_{int(change)}"
                        now_ts = time.time()
                        if key not in last_alert or now_ts - last_alert[key] > 300:
                            dir_str = "🔺 상승" if change > 0 else "🔻 하락"
                            send_telegram(
                                f"{dir_str} [정규장]\n"
                                f"<b>{name}</b>\n"
                                f"현재가: {current_p:,}원\n"
                                f"변동률: {change:+.2f}%"
                            )
                            last_alert[key] = now_ts

                # 시외장
                elif is_afterhours:
                    key = f"after_{name}"
                    now_ts = time.time()
                    if key not in last_afterhours or now_ts - last_afterhours[key] > 300:
                        send_telegram(
                            f"🕒 [시외장]\n"
                            f"<b>{name}</b>\n"
                            f"현재가: {current_p:,}원"
                        )
                        last_afterhours[key] = now_ts

                # 목표가
                if name in targets and current_p >= targets[name]:
                    t_key = f"target_{name}"
                    if t_key not in last_alert or time.time() - last_alert[t_key] > 300:
                        send_telegram(
                            f"🎯 목표가 도달!\n"
                            f"<b>{name}</b>\n"
                            f"현재가: {current_p:,}원"
                        )
                        last_alert[t_key] = time.time()

            time.sleep(check_interval)

        except Exception as e:
            print(f"감시 루프 오류: {e}")
            time.sleep(10)
            
if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    monitoring_loop()
