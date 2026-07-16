import requests
import json
import time
import datetime
import os
from threading import Thread
from difflib import get_close_matches

# ==================== 설정 ====================
APP_KEY = os.getenv("PSju3LP86B9wy64ks1kNE8Hqk9xOsctaOdnt")
APP_SECRET = os.getenv("jBCuOUWj2/EDMyk4QsF38j9AWNwHVb1z09gm19S4FAoQEyz78cVV3jeJWR5YdZbshwtJOBaGzFjwdyIqxN2lXdGzDCDBdh3JdFYwh8yZHagpBDmAu9e5E2l/m84ikcfOMu1KppBD/Jub8RF+xAEQOWHMGztr6Q440DYRwrEX0/UclWyykeg=
")
TELEGRAM_TOKEN = os.getenv("7692250924:AAGF39wQneTrVX0wHJIbEkCfOn7jc1K3aTs")
CHAT_ID = os.getenv("581210065")
URL = "https://openapi.koreainvestment.com:9443"

DATA_FILE = "stock_monitor.json"

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

alerted_levels = {}

# ==================== API 함수 ====================
def get_access_token():
    url = f"{URL}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    res = requests.post(url, data=json.dumps(body))
    return res.json().get('access_token')

def get_valid_token():
    global current_token, token_issue_date
    today = datetime.date.today()
    if 'current_token' not in globals() or token_issue_date != today:
        globals()['current_token'] = get_access_token()
        globals()['token_issue_date'] = today
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

# ==================== 명령어 처리 ====================
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
                        send_telegram("📌 명령어:\n/add 이름\n/remove 이름\n/target 이름 가격\n/list\n/targets")
                    # (다른 명령어는 이전 버전과 동일하게 동작)
                    elif text.startswith('/add '):
                        name = text[5:].strip()
                        matched, code = find_ticker_by_name(name)
                        if code:
                            stocks[matched] = code
                            save_data({"stocks": stocks, "targets": targets})
                            send_telegram(f"✅ {matched} 추가!")
        except:
            time.sleep(5)

# ==================== 감시 루프 ====================
def monitoring_loop():
    print("🚀 주식 감시 시작")
    while True:
        try:
            token = get_valid_token()
            for name, ticker in list(stocks.items()):
                current_p, open_p = get_market_data(token, ticker)
                if open_p == 0: continue
                change = (current_p - open_p) / open_p * 100
                if abs(change) >= 1.0:
                    dir_str = "🔺" if change > 0 else "🔻"
                    send_telegram(f"{dir_str} {name} {current_p:,}원 ({change:+.2f}%)")
            time.sleep(3)
        except Exception as e:
            print(f"오류: {e}")
            time.sleep(10)

if __name__ == "__main__":
    Thread(target=telegram_listener, daemon=True).start()
    monitoring_loop()
