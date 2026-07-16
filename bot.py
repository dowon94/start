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
alert_threshold = 2.0   # 변동률 기준 (%)
check_interval = 5      # 체크 간격 (초)

# ==================== 데이터 ====================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"stocks": {"삼성전자": "005930", "SK하이닉스": "000660", "파세코": "037070"}, "targets": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
stocks = data.get("stocks", {})
targets = data.get("targets", {})

# ==================== 함수 ====================
def get_access_token():
    url = f"{URL}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    res = requests.post(url, data=json.dumps(body))
    return res.json().get('access_token')

def get_valid_token():
    if 'current_token' not in globals() or globals().get('token_issue_date') != datetime.date.today():
        globals()['current_token'] = get_access_token()
        globals()['token_issue_date'] = datetime.date.today()
    return globals()['current_token']

def get_market_data(token, ticker):
    url = f"{URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    try:
        res = requests.get(url, headers=headers, params=params).json()['output']
        return int(res.get('stck_prpr', 0)), int(res.get('stck_oprc', 0))
    except:
        return 0, 0

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML'})

def find_ticker_by_name(name):
    matches = get_close_matches(name, stocks.keys(), n=3, cutoff=0.6)
    if matches:
        return matches[0], stocks[matches[0]]
    return None, None

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
                    if str(update['message']['chat']['id']) != CHAT_ID: continue
                    
                    text = update['message']['text'].strip()

                    if text == '/help':
                        send_telegram("📌 <b>명령어 목록</b>\n"
                                      "/add 이름\n"
                                      "/remove 이름\n"
                                      "/target 이름 가격\n"
                                      "/threshold 숫자 (예: 1.5)\n"
                                      "/interval 초 (예: 10)\n"
                                      "/status\n"
                                      "/list")

                    elif text.startswith('/add '):
                        name = text[5:].strip()
                        matched, code = find_ticker_by_name(name)
                        if code:
                            stocks[matched] = code
                            save_data({"stocks": stocks, "targets": targets})
                            send_telegram(f"✅ {matched} 추가 완료!")
                        else:
                            send_telegram(f"❌ '{name}' 종목을 찾을 수 없습니다.")

                    elif text.startswith(('/remove ', '/del ')):
                        name = text.split(maxsplit=1)[1].strip()
                        if name in stocks:
                            del stocks[name]
                            targets.pop(name, None)
                            save_data({"stocks": stocks, "targets": targets})
                            send_telegram(f"🗑 {name} 삭제 완료")
                        else:
                            send_telegram("❌ 목록에 없습니다.")

                    elif text.startswith('/target '):
                        parts = text[8:].strip().split()
                        if len(parts) >= 2 and parts[0] in stocks:
                            try:
                                price = int(parts[1].replace(',', ''))
                                targets[parts[0]] = price
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"🎯 {parts[0]} 목표가 {price:,}원 설정")
                            except:
                                send_telegram("❌ 가격을 숫자로 입력하세요.")

                    elif text.startswith('/threshold '):
                        try:
                            global alert_threshold
                            alert_threshold = float(text.split()[1])
                            send_telegram(f"📊 변동률 기준을 {alert_threshold}%로 변경했습니다.")
                        except:
                            send_telegram("❌ /threshold 1.5 처럼 숫자로 입력")

                    elif text.startswith('/interval '):
                        try:
                            global check_interval
                            check_interval = int(text.split()[1])
                            send_telegram(f"⏱ 체크 간격을 {check_interval}초로 변경했습니다.")
                        except:
                            send_telegram("❌ /interval 10 처럼 숫자로 입력")

                    elif text == '/status':
                        send_telegram(f"📈 <b>현재 설정</b>\n"
                                      f"변동률 기준: {alert_threshold}%\n"
                                      f"체크 간격: {check_interval}초\n"
                                      f"감시 종목: {len(stocks)}개")

                    elif text == '/list':
                        msg = "📋 감시 종목:\n" + "\n".join([f"• {n} ({c})" for n, c in stocks.items()])
                        send_telegram(msg)

        except Exception as e:
            time.sleep(5)

# ==================== 감시 루프 ====================
def monitoring_loop():
    global alert_threshold, check_interval
    print(f"🚀 감시 시작 (기준 {alert_threshold}%, {check_interval}초 간격)")
    last_alert = {}

    while True:
        try:
            token = get_valid_token()
            for name, ticker in list(stocks.items()):
                current_p, open_p = get_market_data(token, ticker)
                if open_p == 0: continue

                change = (current_p - open_p) / open_p * 100

                if abs(change) >= alert_threshold:
                    key = f"{name}_{int(change)}"
                    now = time.time()
                    if key not in last_alert or now - last_alert[key] > 300:
                        dir_str = "🔺 상승" if change > 0 else "🔻 하락"
                        send_telegram(f"{dir_str} 알림!\n<b>{name}</b>\n현재가: {current_p:,}원\n변동률: {change:+.2f}%")
                        last_alert[key] = now

                if name in targets and current_p >= targets[name]:
                    t_key = f"target_{name}"
                    if t_key not in last_alert or time.time() - last_alert[t_key] > 300:
                        send_telegram(f"🎯 목표가 도달!\n{name} {current_p:,}원")
                        last_alert[t_key] = time.time()

            time.sleep(check_interval)

        except Exception as e:
            print(f"오류: {e}")
            time.sleep(10)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    monitoring_loop()
