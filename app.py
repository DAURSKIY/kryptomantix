import streamlit as st
import requests
import hashlib
import time
import urllib.parse
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
    GOPLUS_APP_KEY = st.secrets["GOPLUS_APP_KEY"]
    GOPLUS_APP_SECRET = st.secrets["GOPLUS_APP_SECRET"]
except Exception:
    YANDEX_API_KEY = ""
    YANDEX_FOLDER_ID = ""
    GOPLUS_APP_KEY = ""
    GOPLUS_APP_SECRET = ""

# ---------- СЧЕТЧИК ПРОВЕРОК (ЧЕРЕЗ URL) ----------
if "scan_count" not in st.query_params:
    st.query_params["scan_count"] = "0"
scan_count = int(st.query_params["scan_count"])

# ---------- YANDEXGPT ----------
def get_ai_verdict(metrics: dict, flags: list, contract: dict = None) -> str:
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return "⚠️ AI-анализ не настроен."
    
    verdict_map = {"gem": "ГЕМ", "young": "МОЛОДОЙ", "established": "УСТОЯВШИЙСЯ", "risk": "РИСК", "scam": "СКАМ"}
    verdict_ru = verdict_map.get(metrics.get("Вердикт", ""), "не определён")
    flags_text = "\n".join([f"— {text}" for level, text in flags])
    
    contract_text = ""
    if contract and "error" not in contract:
        contract_text = f"Контракт: {contract.get('verdict')}. Honeypot: {contract.get('is_honeypot')}, Mint: {contract.get('is_mintable')}"

    prompt_text = f"""Ты — AI-аналитик. Напиши краткий вердикт (2-3 предложения).
    Вердикт: {verdict_ru}
    Сеть: {metrics.get('Сеть')}, Пара: {metrics.get('Пара')}
    Ликвидность: {metrics.get('Ликвидность')}, Объём 24ч: {metrics.get('Объём 24ч')}
    Флаги: {flags_text}
    {contract_text}
    Пиши только на русском, без воды."""

    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {YANDEX_API_KEY}"}
    body = {"modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite", "completionOptions": {"stream": False, "temperature": 0.2, "maxTokens": "300"}, "messages": [{"role": "user", "text": prompt_text}]}
    
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"]
    except Exception:
        return "AI-анализ временно недоступен."

# ---------- GOPLUS ----------
CHAIN_MAP = {"SOLANA": "solana", "ETHEREUM": "1", "BSC": "56", "BASE": "8453"}

@st.cache_data(ttl=3300)
def get_goplus_token(key, secret):
    if not key: return ""
    ts = str(int(time.time()))
    sig = hashlib.sha1((key + ts + secret).encode()).hexdigest()
    try:
        r = requests.post("https://api.gopluslabs.io/api/v1/token", json={"app_key": key, "sign": sig, "timestamp": int(ts)}, timeout=10)
        return r.json().get("result", {}).get("access_token", "")
    except: return ""

def check_contract(address: str, chain: str) -> dict:
    chain_upper = chain.upper()
    if chain_upper == "SOLANA":
        url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={address}"
    else:
        chain_id = CHAIN_MAP.get(chain_upper, "1")
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
    
    headers = {"Accept": "application/json"}
    token = get_goplus_token(GOPLUS_APP_KEY, GOPLUS_APP_SECRET)
    if token: headers["Authorization"] = f"Bearer {token}"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get("code") != 1 or not data.get("result"): return {"error": "Данные недоступны"}
        
        res = next(iter(data["result"].values()), None)
        if not res: return {"error": "Контракт не найден"}

        is_honeypot = res.get("is_honeypot") == "1"
        is_mintable = res.get("is_mintable") == "1"
        is_blacklisted = res.get("is_blacklisted") == "1"
        hidden_owner = res.get("hidden_owner") == "1"
        is_open_source = res.get("is_open_source") == "1"
        is_proxy = res.get("is_proxy") == "1"
        buy_tax = float(res.get("buy_tax", 0) or 0)
        sell_tax = float(res.get("sell_tax", 0) or 0)

        dangers = ["honeypot"] if is_honeypot else []
        if hidden_owner: dangers.append("hidden_owner")
        
        warnings = ["mint"] if is_mintable else []
        if is_blacklisted: warnings.append("blacklist")
        if is_proxy: warnings.append("proxy")
        if buy_tax > 0.1 or sell_tax > 0.1: warnings.append("tax")

        verdict = "danger" if dangers else ("warning" if warnings else "safe")
        
        return {"verdict": verdict, "is_honeypot": is_honeypot, "is_mintable": is_mintable, "is_open_source": is_open_source, "is_proxy": is_proxy, "is_blacklisted": is_blacklisted, "hidden_owner": hidden_owner, "buy_tax": buy_tax, "sell_tax": sell_tax}
    except: return {"error": "Ошибка проверки"}

# ---------- DEXSCREENER ----------
@st.cache_data(ttl=60)
def fetch_token_data(query: str):
    query = query.strip()
    try:
        if len(query) < 30 and not query.startswith("0x"):
            search_res = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={query}", timeout=10).json()
            if search_res.get("pairs"):
                best_pair = sorted(search_res["pairs"], key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0, reverse=True)[0]
                query = best_pair.get("baseToken", {}).get("address")
        return requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{query}", timeout=15).json()
    except Exception as e:
        return {"error": str(e)}

# ---------- АНАЛИЗ ----------
def analyze(pair: dict):
    flags, score, gem_points = [], 0, 0
    liq = pair.get("liquidity", {}).get("usd", 0) or 0
    vol24 = pair.get("volume", {}).get("h24", 0) or 0
    fdv = pair.get("fdv", 0) or 0
    created = pair.get("pairCreatedAt", 0) or 0
    txns = pair.get("txns", {}).get("h24", {})
    buys, sells = txns.get("buys", 0), txns.get("sells", 0)
    price_change = pair.get("priceChange", {}).get("h24", 0) or 0

    age_days = 0
    if created: age_days = (datetime.now().timestamp() * 1000 - created) / 1000 / 3600 / 24

    if liq < 5000: flags.append(("red", f"🔴 Критически низкая ликвидность: ${liq:,.0f}")); score -= 3
    elif liq < 30000: flags.append(("yellow", f"🟡 Низкая ликвидность: ${liq:,.0f}")); score -= 1
    else: flags.append(("green", f"🟢 Достаточная ликвидность: ${liq:,.0f}")); score += 2

    if created:
        if age_days < 0.25: flags.append(("red", "🔴 Токену меньше 6 часов.")); score -= 3
        elif age_days < 1: flags.append(("yellow", f"🟡 Токену меньше суток ({age_days*24:.1f} ч).")); score -= 1
        else: flags.append(("green", f"🟢 Возраст: {age_days:.1f} дней")); score += 1

    if liq > 0:
        ratio = vol24 / liq
        if ratio > 50: flags.append(("red", f"🔴 Аномальный объём: vol/liq = {ratio:.1f}x.")); score -= 2
        elif ratio < 0.05: flags.append(("yellow", f"🟡 Очень низкий объём.")); score -= 1
        else: flags.append(("green", f"🟢 Здоровый объём: vol/liq = {ratio:.2f}x")); score += 1

    if price_change < -70: flags.append(("red", f"🔴 Обвал за 24ч: {price_change:.1f}%")); score -= 3
    elif price_change < -40: flags.append(("yellow", f"🟡 Сильное падение: {price_change:.1f}%")); score -= 1

    if 7 <= age_days <= 90: gem_points += 2
    if 50000 <= liq <= 5000000: gem_points += 2
    if liq > 0 and 0.3 <= (vol24/liq) <= 5: gem_points += 2

    if score < 0: verdict = "scam"
    elif score < 3: verdict = "risk"
    elif age_days < 7: verdict = "gem" if gem_points >= 5 else "young"
    elif gem_points >= 5: verdict = "gem"
    else: verdict = "established"

    metrics = {
        "Ликвидность": f"${liq:,.0f}", "Объём 24ч": f"${vol24:,.0f}", "FDV": f"${fdv:,.0f}",
        "Цена": f"${pair.get('priceUsd', '—')}", "Δ 24ч": f"{price_change:.1f}%",
        "Покупки": f"{buys}", "Продажи": f"{sells}", "DEX": str(pair.get("dexId", "—")).upper(),
        "Пара": f"{pair.get('baseToken', {}).get('symbol', '?')}/{pair.get('quoteToken', {}).get('symbol', '?')}",
        "Сеть": str(pair.get("chainId", "—")).upper(), "Вердикт": verdict,
    }
    return verdict, flags, gem_points, metrics

# ---------- СТАТИЧНЫЕ ТРЕНДОВЫЕ ТОКЕНЫ (ВИТРИНА) ----------
def fetch_trending():
    # Жестко задаем 4 красивых токена, чтобы витрина всегда выглядела отлично
    return [
        {"name": "BONK", "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"}, # Solana
        {"name": "WIF", "address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"}, # Solana
        {"name": "PEPE", "address": "0x6982508145454Ce325dDbE47a25d4ec3d2311933"}, # Ethereum
        {"name": "CAKE", "address": "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82"} # BSC
    ]

# ---------- СТИЛИ (CSS) ----------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: radial-gradient(circle at 20% 10%, #1a0b2e 0%, #0a0a12 50%, #000000 100%); }
    .hero { text-align: center; padding: 20px 20px 10px 20px; }
    .hero-title { font-size: 64px; font-weight: 800; background: linear-gradient(90deg, #a855f7, #ec4899, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
    .hero-sub { color: #9ca3af; font-size: 18px; margin-top: 8px; }
    .verdict-card { padding: 30px; border-radius: 20px; text-align: center; margin: 20px 0; border: 2px solid; }
    .verdict-gem { background: rgba(16,185,129,0.1); border-color: #10b981; }
    .verdict-young { background: rgba(236,72,153,0.1); border-color: #ec4899; }
    .verdict-established { background: rgba(59,130,246,0.1); border-color: #3b82f6; }
    .verdict-risk { background: rgba(245,158,11,0.1); border-color: #f59e0b; }
    .verdict-scam { background: rgba(239,68,68,0.1); border-color: #ef4444; }
    .verdict-title { font-size: 42px; font-weight: 800; margin: 10px 0; }
    .metric-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 15px; text-align: center; margin-bottom: 10px; }
    .flag-item { background: rgba(255,255,255,0.03); border-left: 3px solid #6b7280; padding: 12px; border-radius: 8px; margin-bottom: 8px; color: #e5e7eb; }
    .flag-red { border-left-color: #ef4444; background: rgba(239,68,68,0.08); } .flag-yellow { border-left-color: #f59e0b; background: rgba(245,158,11,0.08); } .flag-green { border-left-color: #10b981; background: rgba(16,185,129,0.08); }
    .ai-block { background: rgba(168,85,247,0.1); border: 1px solid rgba(168,85,247,0.4); border-radius: 16px; padding: 20px; margin: 20px 0; }
        .hero-sub-badge {
        display: inline-block;
        background: linear-gradient(90deg, rgba(168, 85, 247, 0.1), rgba(236, 72, 153, 0.1));
        border: 1px solid rgba(168, 85, 247, 0.3);
        border-radius: 50px;
        padding: 10px 24px;
        margin-top: 15px;
        font-size: 16px;
        font-weight: 600;
        color: #e5e7eb;
        letter-spacing: 0.5px;
        box-shadow: 0 0 20px rgba(168, 85, 247, 0.15);
    }
    .hero-sub-badge span {
        color: #d8b4fe;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
    <div class="hero-title">🔮 KRYPTOMANTIX</div>
    <div class="hero-sub-badge">
        <span>AI-инструменты</span> для анализа и поиска криптовалют
    </div>
</div>
""", unsafe_allow_html=True)

# ---------- UI: ВЫБОР ТРЕНДОВЫХ ТОКЕНОВ ----------
trending = fetch_trending()
if trending:
    st.markdown("#### 🔥 Популярные токены")
    cols = st.columns(len(trending))
    for i, t in enumerate(trending):
        with cols[i]:
            if st.button(f"{t['name']}", key=f"trend_btn_{i}", use_container_width=True):
                st.session_state.scan_address = t['address']
                st.rerun()

default_addr = st.session_state.get('scan_address', '')
address = st.text_input("", value=default_addr, placeholder="📍 Вставь адрес (0x...) или тикер (BONK, PEPE)...", label_visibility="collapsed")

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    scan = st.button("🔮 СКАНИРОВАТЬ", use_container_width=True)
    if st.button("🪙 Попробовать на BONK (пример)", use_container_width=True):
        st.session_state.scan_address = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        st.rerun()

# ---------- ЛОГИКА СКАНИРОВАНИЯ И ЛИМИТА ----------
if scan and address.strip():
    if scan_count >= 3:
        st.error("🛑 Вы исчерпали лимит бесплатных проверок (3/3).")
        st.info("Оформите подписку VK Donut за 100₽/мес для безлимитного доступа.")
        st.link_button("💎 Оформить подписку за 100₽", "https://vk.com/donut/club224917928")
        st.stop()
    
    with st.spinner("🔮 Ищу токен и анализирую..."):
        data = fetch_token_data(address.strip())

    if "error" in data:
        st.error(f"Ошибка: {data['error']}")
    elif not data.get("pairs"):
        st.warning("Токен не найден. Проверь тикер или адрес.")
    else:
        new_count = scan_count + 1
        st.query_params["scan_count"] = str(new_count)
        
        pairs = sorted(data["pairs"], key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0, reverse=True)
        pair = pairs[0]
        
        image_url = pair.get("info", {}).get("imageUrl")
        token_symbol = pair.get("baseToken", {}).get("symbol", "Токен")
        
        c1, c2 = st.columns([1, 4])
        with c1:
            if image_url: st.image(image_url, width=100)
            else: st.markdown("### 🪙")
        with c2:
            st.markdown(f"## {token_symbol}")

        verdict, flags, gem_points, metrics = analyze(pair)

        if verdict == "gem": st.markdown('<div class="verdict-card verdict-gem"><div class="verdict-title" style="color:#6ee7b7">💎 ГЕМ</div></div>', unsafe_allow_html=True)
        elif verdict == "young": st.markdown('<div class="verdict-card verdict-young"><div class="verdict-title" style="color:#f9a8d4">🌱 МОЛОДОЙ</div></div>', unsafe_allow_html=True)
        elif verdict == "established": st.markdown('<div class="verdict-card verdict-established"><div class="verdict-title" style="color:#93c5fd">🏛️ УСТОЯВШИЙСЯ</div></div>', unsafe_allow_html=True)
        elif verdict == "risk": st.markdown('<div class="verdict-card verdict-risk"><div class="verdict-title" style="color:#fcd34d">⚠️ РИСК</div></div>', unsafe_allow_html=True)
        else: st.markdown('<div class="verdict-card verdict-scam"><div class="verdict-title" style="color:#fca5a5">☠️ СКАМ</div></div>', unsafe_allow_html=True)

        share_txt = urllib.parse.quote(f"Проверил {token_symbol} в KRYPTOMANTIX. Вердикт: {verdict.upper()}!")
        st.markdown(f'<a href="https://vk.com/share.php?url=https://kryptomantix.streamlit.app&title={share_txt}" target="_blank" style="display:block; text-align:center; padding:10px; background:rgba(255,255,255,0.1); border-radius:8px; color:white; text-decoration:none; margin-bottom:20px;">🚀 Поделиться в ВК</a>', unsafe_allow_html=True)

        st.markdown("### 📊 Метрики")
        cols = st.columns(5)
        for i, (k, v) in enumerate(list(metrics.items())[:10]):
            with cols[i % 5]: st.markdown(f'<div class="metric-card"><div style="color:#9ca3af; font-size:12px;">{k}</div><div style="font-size:18px; font-weight:bold;">{v}</div></div>', unsafe_allow_html=True)

        st.markdown("### 🚩 Анализ")
        for level, text in flags: st.markdown(f'<div class="flag-item flag-{level}">{text}</div>', unsafe_allow_html=True)

        st.markdown("### 🛡️ Проверка контракта")
        contract = check_contract(pair.get("baseToken", {}).get("address", address), metrics["Сеть"])
        
        if "error" in contract: 
            st.warning(contract["error"])
        else:
            v = contract["verdict"]
            if v == "safe": st.markdown('<div class="flag-item flag-green" style="font-size:17px; padding:18px;">✅ <b>Контракт безопасный</b></div>', unsafe_allow_html=True)
            elif v == "warning": st.markdown('<div class="flag-item flag-yellow" style="font-size:17px; padding:18px;">⚠️ <b>Есть риски</b></div>', unsafe_allow_html=True)
            else: st.markdown('<div class="flag-item flag-red" style="font-size:17px; padding:18px;">☠️ <b>Опасный контракт</b></div>', unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f'<div class="flag-item flag-{"red" if contract["is_honeypot"] else "green"}">{"🔴" if contract["is_honeypot"] else "🟢"} Honeypot: {"Да" if contract["is_honeypot"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_mintable"] else "green"}">{"🟡" if contract["is_mintable"] else "🟢"} Mint: {"Есть" if contract["is_mintable"] else "Отключён"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_blacklisted"] else "green"}">{"🟡" if contract["is_blacklisted"] else "🟢"} Blacklist: {"Есть" if contract["is_blacklisted"] else "Нет"}</div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="flag-item flag-{"green" if contract["is_open_source"] else "yellow"}">{"🟢" if contract["is_open_source"] else "🟡"} Open source: {"Да" if contract["is_open_source"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["is_proxy"] else "green"}">{"🟡" if contract["is_proxy"] else "🟢"} Proxy: {"Да" if contract["is_proxy"] else "Нет"}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="flag-item flag-{"yellow" if contract["buy_tax"] > 0.1 or contract["sell_tax"] > 0.1 else "green"}">{"🟡" if contract["buy_tax"] > 0.1 or contract["sell_tax"] > 0.1 else "🟢"} Налоги: {contract["buy_tax"]*100:.1f}% / {contract["sell_tax"]*100:.1f}%</div>', unsafe_allow_html=True)

        st.markdown("### 🤖 AI-анализ")
        with st.spinner("AI думает..."):
            ai_text = get_ai_verdict(metrics, flags, contract)
        st.markdown(f'<div class="ai-block">{ai_text}</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.link_button("🚀 Купить на BingX", "https://bingxdao.com/invite/IHWT6L/", use_container_width=True)
        st.caption(f"Осталось бесплатных проверок: {3 - new_count}")

elif scan and not address.strip():
    st.warning("Введи тикер или адрес токена.")
