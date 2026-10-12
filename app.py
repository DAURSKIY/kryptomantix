import streamlit as st
import requests
import hashlib
import time
from datetime import datetime

st.set_page_config(
    page_title="KRYPTOMANTIX — AI-оракул",
    page_icon="favicon.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------- СЕКРЕТЫ ----------
try:
    YANDEX_API_KEY = st.secrets["YANDEX_API_KEY"]
    YANDEX_FOLDER_ID = st.secrets["YANDEX_FOLDER_ID"]
except Exception:
    YANDEX_API_KEY = ""
    YANDEX_FOLDER_ID = ""

try:
    GOPLUS_APP_KEY = st.secrets["GOPLUS_APP_KEY"]
    GOPLUS_APP_SECRET = st.secrets["GOPLUS_APP_SECRET"]
except Exception:
    GOPLUS_APP_KEY = ""
    GOPLUS_APP_SECRET = ""


# ---------- YANDEXGPT ----------
def get_ai_verdict(metrics: dict, flags: list, contract: dict = None) -> str:
    """Отправляет метрики, флаги и данные контракта в YandexGPT."""
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return "⚠️ AI-анализ не настроен. Добавь ключи YandexGPT в Secrets."

    verdict_map = {
        "gem": "ГЕМ (молодой, недооценённый, с потенциалом)",
        "young": "МОЛОДОЙ (свежий токен, высокий риск)",
        "established": "УСТОЯВШИЙСЯ (известный, безопасный, без потенциала иксов)",
        "risk": "РИСК (есть тревожные сигналы)",
        "scam": "СКАМ (красные флаги, не входить)",
    }
    verdict_ru = verdict_map.get(metrics.get("Вердикт", ""), "не определён")

    flags_text = "\n".join([f"— {text}" for level, text in flags])

    contract_text = ""
    if contract and "error" not in contract:
        c_v = contract.get("verdict", "")
        c_map = {"safe": "безопасный", "warning": "есть риски", "danger": "ОПАСНЫЙ"}
        contract_text = f"""
ПРОВЕРКА КОНТРАКТА (GoPlus):
Вердикт: {c_map.get(c_v, c_v)}
Honeypot: {"Да" if contract.get("is_honeypot") else "Нет"}
Mint: {"Есть — можно печатать токены" if contract.get("is_mintable") else "Отключён"}
Blacklist: {"Есть" if contract.get("is_blacklisted") else "Нет"}
Open source: {"Да" if contract.get("is_open_source") else "Нет"}
Proxy: {"Да" if contract.get("is_proxy") else "Нет"}
Скрытый владелец: {"Да" if contract.get("hidden_owner") else "Нет"}
Может вернуть ownership: {"Да" if contract.get("can_take_back") else "Нет"}
Налоги: покупка {contract.get("buy_tax", 0)*100:.1f}%, продажа {contract.get("sell_tax", 0)*100:.1f}%
"""

    prompt_text = f"""Ты — AI-аналитик мемкоинов. Проанализируй готовый отчёт сканера и напиши краткий вердикт на русском языке.

ОТЧЁТ СКАНЕРА:
Вердикт: {verdict_ru}
Сеть: {metrics.get('Сеть', 'N/A')}
Пара: {metrics.get('Пара', 'N/A')}
Ликвидность: {metrics.get('Ликвидность', 'N/A')}
Объём 24ч: {metrics.get('Объём 24ч', 'N/A')}
FDV: {metrics.get('FDV', 'N/A')}
Изменение 24ч: {metrics.get('Δ 24ч', 'N/A')}
Покупки: {metrics.get('Покупки', 'N/A')} / Продажи: {metrics.get('Продажи', 'N/A')}

АНАЛИЗ СКАНЕРА (что именно обнаружено):
{flags_text}
{contract_text}

ПРАВИЛА:
1. Пиши ТОЛЬКО на русском языке.
2. Опирайся ТОЛЬКО на строки из «Анализ сканера» и «Проверка контракта» выше. Не выдумывай.
3. Если в анализе написано «Достаточная ликвидность» — НЕ пиши про низкую ликвидность.
4. Если в анализе написано «Здоровый объём» — НЕ пиши про низкий объём.
5. Обязательно упомяни главные КРАСНЫЕ флаги. Если их нет — упомяни ЖЁЛТЫЕ.
6. Если проверка контракта показала «ОПАСНЫЙ» — упомяни это прямо.
7. Если вердикт «СКАМ» или «РИСК» — прямо предупреди: «не входи», «высокий риск рага».
8. Если вердикт «ГЕМ» — укажи потенциал и напомни о рисках.
9. Если вердикт «УСТОЯВШИЙСЯ» — скажи, что безопасный, но без роста.
10. Никаких общих фраз про волатильность криптовалют.
11. Пиши 2-3 предложения. Без вступлений вроде «Данный токен представляет собой».

Твой вердикт:"""

    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {YANDEX_API_KEY}"
    }
    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.2,
            "maxTokens": "400"
        },
        "messages": [
            {"role": "system", "text": "Ты — опытный криптоаналитик. Читай готовый отчёт сканера и пиши краткий вердикт. Только русский язык."},
            {"role": "user", "text": prompt_text}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result["result"]["alternatives"][0]["message"]["text"]
    except Exception as e:
        return f"⚠️ Ошибка AI-анализа: {str(e)[:200]}"


# ---------- GOPLUS ----------
CHAIN_MAP = {
    "SOLANA": "solana",
    "ETHEREUM": "1",
    "BSC": "56",
    "BASE": "8453",
    "POLYGON": "137",
    "ARBITRUM": "42161",
    "OPTIMISM": "10",
    "AVALANCHE": "43114",
}


@st.cache_data(ttl=3300)
def get_goplus_access_token(app_key: str, app_secret: str) -> str:
    """Получает access_token для GoPlus API."""
    if not app_key or not app_secret:
        return ""

    timestamp = str(int(time.time()))
    sign_str = app_key + timestamp + app_secret
    signature = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()

    payload = {
        "app_key": app_key,
        "sign": signature,
        "timestamp": int(timestamp)
    }

    url = "https://api.gopluslabs.io/api/v1/token"
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 1:
            return data.get("result", {}).get("access_token", "")
        else:
            return ""
    except Exception:
        return ""


def check_contract(address: str, chain: str) -> dict:
    """Проверяет контракт через GoPlus API."""
    chain_id = CHAIN_MAP.get(chain.upper(), "1")
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"

    headers = {"Accept": "application/json"}

    access_token = get_goplus_access_token(GOPLUS_APP_KEY, GOPLUS_APP_SECRET)
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        if data.get("code") != 1 or not data.get("result"):
            return {"error": f"GoPlus: {data.get('message', 'no data')}"}

        result = data["result"]
        token_data = None
        for key in result:
            token_data = result[key]
            break

        if not token_data:
            return {"error": "Контракт не найден в базе GoPlus"}

        is_honeypot = token_data.get("is_honeypot") == "1"
        is_mintable = token_data.get("is_mintable") == "1"
        is_open_source = token_data.get("is_open_source") == "1"
        is_proxy = token_data.get("is_proxy") == "1"
        is_blacklisted = token_data.get("is_blacklisted") == "1"
        hidden_owner = token_data.get("hidden_owner") == "1"
        can_take_back = token_data.get("can_take_back_ownership") == "1"
        owner_address = token_data.get("owner_address", "")
        buy_tax = float(token_data.get("buy_tax", "0") or "0")
        sell_tax = float(token_data.get("sell_tax", "0") or "0")
        holder_count = token_data.get("holder_count", "0")

        # ОПАСНЫЕ: honeypot, hidden_owner, can_take_back
        dangers = []
        if is_honeypot:
            dangers.append("honeypot")
        if hidden_owner:
            dangers.append("hidden_owner")
        if can_take_back:
            dangers.append("take_back_ownership")

        # ПРЕДУПРЕЖДЕНИЯ: mint, proxy, blacklist, налоги
        warnings = []
        if is_mintable:
            warnings.append("mint")
        if is_proxy:
            warnings.append("proxy")
        if is_blacklisted:
            warnings.append("blacklist")
        if buy_tax > 0.1 or sell_tax > 0.1:
            warnings.append("high_tax")

        if dangers:
            verdict = "danger"
        elif warnings:
            verdict = "warning"
        else:
            verdict = "safe"

        return {
            "verdict": verdict,
            "is_honeypot": is_honeypot,
            "is_mintable": is_mintable,
            "is_open_source": is_open_source,
            "is_proxy": is_proxy,
            "is_blacklisted": is_blacklisted,
            "hidden_owner": hidden_owner,
            "can_take_back": can_take_back,
            "owner_address": owner_address,
            "buy_tax": buy_tax,
            "sell_tax": sell_tax,
            "holder_count": holder_count,
            "dangers": dangers,
            "warnings": warnings,
        }
    except Exception as e:
        return {"error": f"Ошибка проверки: {str(e)[:200]}"}


# ---------- CSS ----------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background: radial-gradient(circle at 20% 10%, #1a0b2e 0%, #0a0a12 50%, #000000 100%);
    }

    .hero {
        text-align: center;
        padding: 40px 20px 20px 20px;
    }
    .hero-title {
        font-size: 64px;
        font-weight: 800;
        background: linear-gradient(90deg, #a855f7, #ec4899, #f59e0b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -2px;
        margin: 0;
    }
    .hero-sub {
        color: #9ca3af;
        font-size: 18px;
        margin-top: 8px;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(168, 85, 247, 0.15);
        border: 1px solid rgba(168, 85, 247, 0.4);
        color: #d8b4fe;
        padding: 4px 14px;
        border-radius: 100px;
        font-size: 12px;
        margin-top: 12px;
        letter-spacing: 1px;
    }

    .verdict-card {
        padding: 40px;
        border-radius: 20px;
        text-align: center;
        margin: 20px 0;
        border: 2px solid;
        animation: fadeIn 0.6s ease-in;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .verdict-gem {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(6, 78, 59, 0.4));
        border-color: #10b981;
        box-shadow: 0 0 60px rgba(16, 185, 129, 0.3);
    }
    .verdict-young {
        background: linear-gradient(135deg, rgba(236, 72, 153, 0.15), rgba(131, 24, 67, 0.4));
        border-color: #ec4899;
        box-shadow: 0 0 60px rgba(236, 72, 153, 0.3);
    }
    .verdict-established {
        background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(30, 58, 138, 0.4));
        border-color: #3b82f6;
        box-shadow: 0 0 60px rgba(59, 130, 246, 0.3);
    }
    .verdict-risk {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(120, 53, 15, 0.4));
        border-color: #f59e0b;
        box-shadow: 0 0 60px rgba(245, 158, 11, 0.3);
    }
    .verdict-scam {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(127, 29, 29, 0.4));
        border-color: #ef4444;
        box-shadow: 0 0 60px rgba(239, 68, 68, 0.3);
    }
    .verdict-emoji { font-size: 72px; }
    .verdict-title { font-size: 42px; font-weight: 800; margin: 10px 0; letter-spacing: 2px; }
    .verdict-gem .verdict-title { color: #6ee7b7; }
    .verdict-young .verdict-title { color: #f9a8d4; }
    .verdict-established .verdict-title { color: #93c5fd; }
    .verdict-risk .verdict-title { color: #fcd34d; }
    .verdict-scam .verdict-title { color: #fca5a5; }
    .verdict-desc { color: #e5e7eb; font-size: 16px; opacity: 0.9; }

    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 18px;
        text-align: center;
        transition: all 0.2s;
        margin-bottom: 10px;
    }
    .metric-card:hover {
        border-color: rgba(168, 85, 247, 0.5);
        background: rgba(168, 85, 247, 0.05);
    }
    .metric-label { color: #9ca3af; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { color: #ffffff; font-size: 20px; font-weight: 700; margin-top: 6px; word-break: break-word; }

    .flag-item {
        background: rgba(255, 255, 255, 0.03);
        border-left: 3px solid #6b7280;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 8px;
        color: #e5e7eb;
        font-size: 15px;
    }
    .flag-red { border-left-color: #ef4444; background: rgba(239, 68, 68, 0.08); }
    .flag-yellow { border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.08); }
    .flag-green { border-left-color: #10b981; background: rgba(16, 185, 129, 0.08); }

    .ai-block {
        background: linear-gradient(135deg, rgba(168, 85, 247, 0.1), rgba(236, 72, 153, 0.1));
        border: 1px solid rgba(168, 85, 247, 0.4);
        border-radius: 16px;
        padding: 24px;
        margin: 20px 0;
        color: #e5e7eb;
        font-size: 16px;
        line-height: 1.6;
    }
    .ai-header {
        color: #d8b4fe;
        font-size: 18px;
        font-weight: 700;
        margin-bottom: 12px;
        letter-spacing: 1px;
    }

    .disclaimer {
        text-align: center;
        color: #6b7280;
        font-size: 12px;
        margin-top: 40px;
        padding: 20px;
        border-top: 1px solid rgba(255, 255, 255, 0.05);
    }

    .stButton > button {
        background: linear-gradient(90deg, #a855f7, #ec4899);
        color: white;
        border: none;
        font-weight: 700;
        font-size: 16px;
        padding: 14px 0;
        border-radius: 12px;
        transition: all 0.3s;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 30px rgba(168, 85, 247, 0.4);
    }

    .stTextInput > div > div > input {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: white;
        padding: 14px 18px;
        border-radius: 12px;
        font-size: 15px;
    }
    .stTextInput > div > div > input:focus {
        border-color: #a855f7;
        box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.2);
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
    <div class="hero-title">🔮 KRYPTOMANTIX</div>
    <div class="hero-sub">AI-оракул для крипты. Вставь адрес токена — получи вердикт.</div>
    <div class="hero-badge">SOLANA · BASE · ETHEREUM · BSC</div>
</div>
""", unsafe_allow_html=True)


# ---------- DEXSCREENER ----------
@st.cache_data(ttl=60)
def fetch_token_data(address: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def analyze(pair: dict):
    flags = []
    score = 0
    gem_points = 0

    liq = pair.get("liquidity", {}).get("usd", 0) or 0
    vol24 = pair.get("volume", {}).get("h24", 0) or 0
    fdv = pair.get("fdv", 0) or 0
    created = pair.get("pairCreatedAt", 0) or 0
    txns = pair.get("txns", {}).get("h24", {})
    buys = txns.get("buys", 0)
    sells = txns.get("sells", 0)
    price_change = pair.get("priceChange", {}).get("h24", 0) or 0

    age_days = 0
    if created:
        age_days = (datetime.now().timestamp() * 1000 - created) / 1000 / 3600 / 24

    if liq < 5000:
        flags.append(("red", f"🔴 Критически низкая ликвидность: ${liq:,.0f}"))
        score -= 3
    elif liq < 30000:
        flags.append(("yellow", f"🟡 Низкая ликвидность: ${liq:,.0f}"))
        score -= 1
    else:
        flags.append(("green", f"🟢 Достаточная ликвидность: ${liq:,.0f}"))
        score += 2

    if created:
        if age_days < 0.25:
            flags.append(("red", "🔴 Токену меньше 6 часов. Высокий риск рага."))
            score -= 3
        elif age_days < 1:
            flags.append(("yellow", f"🟡 Токену меньше суток ({age_days*24:.1f} ч)."))
            score -= 1
        else:
            flags.append(("green", f"🟢 Возраст: {age_days:.1f} дней"))
            score += 1
    else:
        flags.append(("yellow", "🟡 Нет данных о дате создания пары"))
        score -= 1

    if liq > 0:
        ratio = vol24 / liq
        if ratio > 50:
            flags.append(("red", f"🔴 Аномальный объём: vol/liq = {ratio:.1f}x. Накрутка."))
            score -= 2
        elif ratio < 0.05:
            flags.append(("yellow", f"🟡 Очень низкий объём: vol/liq = {ratio:.2f}x. Мёртвый токен."))
            score -= 1
        else:
            flags.append(("green", f"🟢 Здоровый объём: vol/liq = {ratio:.2f}x"))
            score += 1

    if liq > 0 and fdv > 0:
        fdv_liq = fdv / liq
        red_threshold = 5000 if age_days > 30 else 2000
        yellow_threshold = 1000 if age_days > 30 else 500

        if fdv_liq > red_threshold:
            flags.append(("red", f"🔴 FDV в {fdv_liq:.0f}x больше ликвидности. Критично."))
            score -= 2
        elif fdv_liq > yellow_threshold:
            flags.append(("yellow", f"🟡 FDV в {fdv_liq:.0f}x больше ликвидности."))
        else:
            flags.append(("green", f"🟢 FDV/ликвидность в норме: {fdv_liq:.0f}x"))
            score += 1

    total_tx = buys + sells
    if total_tx > 0:
        buy_ratio = buys / total_tx
        if buy_ratio < 0.3:
            flags.append(("red", f"🔴 Давление продаж: {sells} продаж vs {buys} покупок"))
            score -= 2
        elif buy_ratio > 0.7:
            flags.append(("green", f"🟢 Активные покупки: {buys} vs {sells}"))
            score += 1

    if price_change < -70:
        flags.append(("red", f"🔴 Обвал за 24ч: {price_change:.1f}%"))
        score -= 3
    elif price_change < -40:
        flags.append(("yellow", f"🟡 Сильное падение: {price_change:.1f}%"))
        score -= 1

    if 7 <= age_days <= 90:
        gem_points += 2
        flags.append(("green", f"💎 Молодой токен ({age_days:.0f} дней) — потенциал роста"))
    elif 3 <= age_days < 7:
        gem_points += 1
    elif age_days > 180:
        gem_points -= 2
        flags.append(("yellow", "🏛️ Токен старше 6 месяцев — уже не гем"))

    if 50000 <= liq <= 5000000:
        gem_points += 2
        flags.append(("green", "💎 Ликвидность в оптимальной зоне"))
    elif liq > 5000000:
        gem_points -= 1
        flags.append(("yellow", "🏛️ Очень крупная ликвидность — токен устоявшийся"))

    if liq > 0:
        ratio = vol24 / liq
        if 0.3 <= ratio <= 5:
            gem_points += 2
            flags.append(("green", "💎 Активная здоровая торговля"))

    if 5 <= price_change <= 200:
        gem_points += 1
    elif price_change > 500:
        gem_points -= 1
        flags.append(("yellow", f"🟡 Уже памп +{price_change:.0f}% — поздно входить"))

    if total_tx > 0 and buys > sells * 1.2:
        gem_points += 1

    if score < 0:
        verdict = "scam"
    elif score < 3:
        verdict = "risk"
    elif age_days < 7:
        if gem_points >= 5:
            verdict = "gem"
        else:
            verdict = "young"
    elif gem_points >= 5:
        verdict = "gem"
    else:
        verdict = "established"

    metrics = {
        "Ликвидность": f"${liq:,.0f}",
        "Объём 24ч": f"${vol24:,.0f}",
        "FDV": f"${fdv:,.0f}",
        "Цена": f"${pair.get('priceUsd', '—')}",
        "Δ 24ч": f"{price_change:.1f}%",
        "Покупки": f"{buys}",
        "Продажи": f"{sells}",
        "DEX": str(pair.get("dexId", "—")).upper(),
        "Пара": f"{pair.get('baseToken', {}).get('symbol', '?')}/{pair.get('quoteToken', {}).get('symbol', '?')}",
        "Сеть": str(pair.get("chainId", "—")).upper(),
        "Вердикт": verdict,
    }

    return verdict, flags, gem_points, metrics


# ---------- UI ----------
address = st.text_input("", placeholder="📍 Вставь адрес контракта (Solana, Base, Ethereum, BSC...)", label_visibility="collapsed")

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    scan = st.button("🔮 СКАНИРОВАТЬ", use_container_width=True)

if scan and address.strip():
    with st.spinner("🔮 Криптомантикс смотрит в бездну..."):
        data = fetch_token_data(address.strip())

    if "error" in data:
        st.error(f"Ошибка запроса: {data['error']}")
    elif not data.get("pairs"):
        st.warning("Токен не найден на DexScreener. Проверь адрес или сеть.")
    else:
        pairs = sorted(
            data["pairs"],
            key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0,
            reverse=True
        )
        pair = pairs[0]
        verdict, flags, gem_points, metrics = analyze(pair)

        # 1. КАРТОЧКА ВЕРДИКТА
        if verdict == "gem":
            st.markdown("""
            <div class="verdict-card verdict-gem">
                <div class="verdict-emoji">💎</div>
                <div class="verdict-title">ГЕМ</div>
                <div class="verdict-desc">Молодой, недооценённый, с потенциалом. Но помни: это не гарантия.</div>
            </div>
            """, unsafe_allow_html=True)
        elif verdict == "young":
            st.markdown("""
            <div class="verdict-card verdict-young">
                <div class="verdict-emoji">🌱</div>
                <div class="verdict-title">МОЛОДОЙ</div>
                <div class="verdict-desc">Токену меньше 7 дней. Потенциал есть, но и риск высокий.</div>
            </div>
            """, unsafe_allow_html=True)
        elif verdict == "established":
            st.markdown("""
            <div class="verdict-card verdict-established">
                <div class="verdict-emoji">🏛️</div>
                <div class="verdict-title">УСТОЯВШИЙСЯ</div>
                <div class="verdict-desc">Известный токен. Безопасен, но уже не гем — потенциал роста ниже.</div>
            </div>
            """, unsafe_allow_html=True)
        elif verdict == "risk":
            st.markdown("""
            <div class="verdict-card verdict-risk">
                <div class="verdict-emoji">⚠️</div>
                <div class="verdict-title">РИСК</div>
                <div class="verdict-desc">Есть тревожные сигналы. Будь осторожен.</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="verdict-card verdict-scam">
                <div class="verdict-emoji">☠️</div>
                <div class="verdict-title">СКАМ / ВЫСОКИЙ РИСК</div>
                <div class="verdict-desc">Красные флаги. Не входи.</div>
            </div>
            """, unsafe_allow_html=True)

        # 2. МЕТРИКИ
        st.markdown("### 📊 Метрики")
        cols = st.columns(5)
        items = list(metrics.items())[:10]
        for i, (k, v) in enumerate(items):
            with cols[i % 5]:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">{k}</div>
                    <div class="metric-value">{v}</div>
                </div>
                """, unsafe_allow_html=True)

        # 3. ФЛАГИ СКАНЕРА
        st.markdown("### 🚩 Анализ Криптомантикса")
        for level, text in flags:
            st.markdown(f'<div class="flag-item flag-{level}">{text}</div>', unsafe_allow_html=True)

        # 4. ПРОВЕРКА КОНТРАКТА (до AI, чтобы AI учёл результат)
        st.markdown("### 🛡️ Проверка контракта")
        with st.spinner("🛡️ GoPlus проверяет контракт..."):
            contract = check_contract(address.strip(), metrics.get("Сеть", ""))

        if "error" in contract:
            st.warning(contract["error"])
        else:
            v = contract["verdict"]
            if v == "safe":
                st.markdown("""
                <div class="flag-item flag-green" style="font-size:17px; padding:18px;">
                    ✅ <b>Контракт безопасный</b> — опасных функций не найдено
                </div>
                """, unsafe_allow_html=True)
            elif v == "warning":
                st.markdown("""
                <div class="flag-item flag-yellow" style="font-size:17px; padding:18px;">
                    ⚠️ <b>Есть риски</b> — проверь детали ниже
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="flag-item flag-red" style="font-size:17px; padding:18px;">
                    ☠️ <b>Опасный контракт</b> — не входи
                </div>
                """, unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f'<div class="flag-item flag-{"red" if contract["is_honeypot"] else "green"}">{"🔴" if contract["is_honeypot"] else "🟢"} Honeypot: {"Да" if contract["is_honeypot"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_mintable"] else "green"}">{"🟡" if contract["is_mintable"] else "🟢"} Mint: {"Есть — можно печатать токены" if contract["is_mintable"] else "Отключён"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_blacklisted"] else "green"}">{"🟡" if contract["is_blacklisted"] else "🟢"} Blacklist: {"Есть" if contract["is_blacklisted"] else "Нет"}</div>', unsafe_allow_html=True)
            with col2:
                st.markdown(f'<div class="flag-item flag-{"green" if contract["is_open_source"] else "yellow"}">{"🟢" if contract["is_open_source"] else "🟡"} Open source: {"Да" if contract["is_open_source"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_proxy"] else "green"}">{"🟡" if contract["is_proxy"] else "🟢"} Proxy: {"Да" if contract["is_proxy"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["buy_tax"] > 0.1 or contract["sell_tax"] > 0.1 else "green"}">{"🟡" if contract["buy_tax"] > 0.1 or contract["sell_tax"] > 0.1 else "🟢"} Налоги: {contract["buy_tax"]*100:.1f}% / {contract["sell_tax"]*100:.1f}%</div>', unsafe_allow_html=True)

        # 5. AI-АНАЛИЗ (с учётом контракта)
        st.markdown("### 🤖 AI-анализ")
        with st.spinner("🤖 YandexGPT изучает данные..."):
            ai_verdict = get_ai_verdict(metrics, flags, contract)
        st.markdown(f"""
        <div class="ai-block">
            <div class="ai-header">🔮 ВЕРДИКТ AI-ОРАКУЛА</div>
            {ai_verdict}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="disclaimer">
            ⚠️ Это не инвестиционная рекомендация. DYOR. KRYPTOMANTIX даёт аналитику, а не совет покупать.
        </div>
        """, unsafe_allow_html=True)

elif scan and not address.strip():
    st.warning("Вставь адрес токена.")
else:
    st.markdown("""
    <div style="text-align:center; color:#4b5563; margin-top:60px; font-size:14px;">
        Попробуй: <code style="color:#a855f7;">DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263</code> (BONK)
    </div>
    """, unsafe_allow_html=True)
