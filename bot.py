import requests
import json
import time
import datetime
import os
from threading import Thread
from difflib import get_close_matches

# ==================== 설정 ====================
APP_KEY = os.getenv("APP_KEY")
APP_SECRET = os.getenv("APP_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = "https://openapi.koreainvestment.com:9443"

DATA_FILE = "stock_monitor.json"

# ==================== 설정 변수 ====================
alert_threshold = 2.0      # 변동률 기준 (%)
check_interval = 5         # 체크 간격 (초)
after_hours_interval = 300 # 시외/프리 알림 간격 (초)

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
            # 국내 예시
            "삼성전자": {"code": "005930", "market": "KR"},
            "SK하이닉스": {"code": "000660", "market": "KR"},
            # 해외 예시 (나중에 /add로 추가)
            # "SOXS": {"code": "SOXS", "market": "NASD"},
            # "SOXL": {"code": "SOXL", "market": "NASD"},
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

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        })
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")

# ==================== 시세 조회 ====================
def get_kr_price(token, code):
    """국내주식 현재가"""
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
        "fid_input_iscd": code
    }
    try:
        res = requests.get(url, headers=headers, params=params).json()
        output = res.get('output', {})
        current = int(output.get('stck_prpr', 0))
        open_p = int(output.get('stck_oprc', 0))
        return current, open_p
    except Exception as e:
        print(f"국내시세 오류 ({code}): {e}")
        return 0, 0

def get_overseas_price(token, exchange, symbol):
    """해외주식 현재가 (프리/정규/애프터 포함)"""
    url = f"{URL}/uapi/overseas-price/v1/quotations/price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "HHDFS00000300"
    }
    params = {
        "AUTH": "",
        "EXCD": exchange,   # NASD, NYSE, AMEX 등
        "SYMB": symbol
    }
    try:
        res = requests.get(url, headers=headers, params=params).json()
        output = res.get('output', {})
        current = float(output.get('last', 0))
        open_p = float(output.get('open', 0))
        return current, open_p
    except Exception as e:
        print(f"해외시세 오류 ({symbol}): {e}")
        return 0, 0

def get_price(token, name, info):
    """시장에 따라 시세 조회"""
    if info.get("market") == "KR":
        return get_kr_price(token, info["code"])
    else:
        return get_overseas_price(token, info.get("market", "NASD"), info["code"])

# ==================== 텔레그램 명령어 ====================
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
                    if 'message' not in update: continue
                    if str(update['message']['chat']['id']) != str(CHAT_ID): continue

                    text = update['message']['text'].strip()

                    if text in ['/help', '/도움말']:
                        send_telegram(
                            "📌 <b>명령어 목록</b>\n\n"
                            "• /add 이름 코드 [거래소] → 종목 추가\n"
                            "  예: /add 모나미 005360\n"
                            "  예: /add SOXS SOXS\n"
                            "  예: /add SOXL SOXL NASD\n"
                            "• /remove 이름 → 삭제\n"
                            "• /target 이름 가격 → 목표가\n"
                            "• /변동률 숫자 → 알림 기준\n"
                            "• /간격 초 → 체크 간격\n"
                            "• /상태 → 현재 설정\n"
                            "• /list → 감시 목록"
                        )

                    elif text.startswith(('/add ', '/추가 ')):
                        parts = text.split()
                        if len(parts) < 3:
                            send_telegram("❌ 사용법:\n/add 이름 코드\n/add 이름 코드 거래소")
                            continue

                        name = parts[1]
                        code = parts[2]
                        market = parts[3].upper() if len(parts) >= 4 else None

                        # 국내/해외 자동 판단
                        if code.isdigit() and len(code) == 6:
                            market = "KR"
                        else:
                            market = market or "NASD"  # 기본 NASD

                        stocks[name] = {"code": code, "market": market}
                        save_data({"stocks": stocks, "targets": targets})
                        send_telegram(f"✅ {name} ({code} / {market}) 추가 완료!")

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
                                price = float(parts[2].replace(',', ''))
                                targets[parts[1]] = price
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"🎯 {parts[1]} 목표가 {price} 설정 완료")
                            except:
                                send_telegram("❌ /target 이름 가격 형식으로 입력")
                        else:
                            send_telegram("❌ 종목이 없거나 형식이 틀렸습니다.")

                    elif text.startswith(('/변동률 ', '/threshold ')):
                        try:
                            global alert_threshold
                            alert_threshold = float(text.split()[1])
                            send_telegram(f"📊 변동률 기준을 <b>{alert_threshold}%</b>로 변경")
                        except:
                            send_telegram("❌ /변동률 1.5 형식으로 입력")

                    elif text.startswith(('/간격 ', '/interval ')):
                        try:
                            global check_interval
                            check_interval = int(text.split()[1])
                            send_telegram(f"⏱ 체크 간격을 <b>{check_interval}초</b>로 변경")
                        except:
                            send_telegram("❌ /간격 10 형식으로 입력")

                    elif text in ['/상태', '/status']:
                        send_telegram(
                            f"📈 <b>현재 설정</b>\n\n"
                            f"• 변동률 기준: {alert_threshold}%\n"
                            f"• 체크 간격: {check_interval}초\n"
                            f"• 감시 종목 수: {len(stocks)}개"
                        )

                    elif text == '/list':
                        if stocks:
                            lines = []
                            for n, info in stocks.items():
                                lines.append(f"• {n} ({info['code']} / {info['market']})")
                            send_telegram("📋 <b>감시 종목</b>\n" + "\n".join(lines))
                        else:
                            send_telegram("📋 감시 중인 종목이 없습니다.")

        except Exception as e:
            print(f"텔레그램 오류: {e}")
            time.sleep(5)

# ==================== 감시 루프 ====================
def monitoring_loop():
    global alert_threshold, check_interval
    print(f"🚀 감시 시작 (변동률 {alert_threshold}%, {check_interval}초 간격)")
    last_alert = {}

    while True:
        try:
            print("🔍 감시 루프 실행 중...")
            token = get_valid_token()

            for name, info in list(stocks.items()):
                current, open_p = get_price(token, name, info)

                if current == 0:
                    continue

                print(f"📈 {name}: 현재가={current}, 시가={open_p}")

                # 변동률 계산
                change = 0
                if open_p > 0:
                    change = (current - open_p) / open_p * 100

                # 알림 조건
                if abs(change) >= alert_threshold:
                    key = f"{name}_{int(change)}"
                    now_ts = time.time()
                    if key not in last_alert or now_ts - last_alert[key] > 300:
                        dir_str = "🔺 상승" if change > 0 else "🔻 하락"
                        market_str = "국내" if info["market"] == "KR" else "해외"
                        send_telegram(
                            f"{dir_str} [{market_str}]\n"
                            f"<b>{name}</b>\n"
                            f"현재가: {current}\n"
                            f"변동률: {change:+.2f}%"
                        )
                        last_alert[key] = now_ts

                # 목표가 알림
                if name in targets and current >= targets[name]:
                    t_key = f"target_{name}"
                    if t_key not in last_alert or time.time() - last_alert[t_key] > 300:
                        send_telegram(
                            f"🎯 목표가 도달!\n"
                            f"<b>{name}</b>\n"
                            f"현재가: {current}"
                        )
                        last_alert[t_key] = time.time()

            time.sleep(check_interval)

        except Exception as e:
            print(f"감시 루프 오류: {e}")
            time.sleep(10)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    monitoring_loop()
