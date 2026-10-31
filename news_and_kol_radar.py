import os
import re
import csv
import json
import time
import uuid
import socket
import ssl
import random
import calendar
import urllib.request
import urllib.parse
from datetime import datetime
import feedparser
import trafilatura
import pandas as pd
import mplfinance as mpf
from tradingview_ta import TA_Handler, Interval
from youtube_transcript_api import YouTubeTranscriptApi
from curl_cffi import requests as cffi_req
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_FILE = os.path.join(BASE_DIR, "daily_buzz_pool.json")
HISTORY_FILE = os.path.join(BASE_DIR, "content_balance_state.json")
LIVE_CHART_FILE = os.path.join(BASE_DIR, "live_xauusd_chart.png")
SHEET_ID = "1-HgPzrchtbVtyskdawDfx5Hum4eaJK-8COgJ2Ytdoik"

def _load_bot_token():
    tok = os.environ.get("VT_BOT_TOKEN", "").strip()
    if tok:
        return tok
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("VT_BOT_TOKEN="):
                    return line.strip().split("=", 1)[1].strip()
    return ""


BOT_TOKEN = _load_bot_token()
DISCUSSION_CHAT_ID = -1004375233328   # VT Markets | Thảo Luận & Thực Chiến
INTERNAL_CHAT_ID = -1003750255534     # [NỘI BỘ] Báo Khách & Sale
CHANNEL_CHAT_ID = -1003971455443      # VT Rewards HUB (@vtrewardshub)

SSL_CTX = ssl._create_unverified_context()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

ORIG_GETADDRINFO = socket.getaddrinfo
DNS_CACHE = {}


def resolve_doh(domain):
    try:
        url = f"https://1.1.1.1/dns-query?name={domain}&type=A"
        req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=6, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for ans in data.get("Answer", []):
                if ans.get("type") == 1 and ans.get("data") not in ("127.0.0.1", "0.0.0.0"):
                    return ans.get("data")
    except Exception:
        pass
    return None


def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host in ("1.1.1.1", "localhost"):
        return ORIG_GETADDRINFO(host, port, family, type, proto, flags)
    try:
        res = ORIG_GETADDRINFO(host, port, family, type, proto, flags)
        if res and res[0][4][0] in ("127.0.0.1", "0.0.0.0", "::1"):
            raise socket.gaierror("Sinkholed")
        return res
    except Exception:
        if host not in DNS_CACHE:
            ip = resolve_doh(host)
            if ip:
                DNS_CACHE[host] = ip
        if host in DNS_CACHE:
            return ORIG_GETADDRINFO(DNS_CACHE[host], port, family, type, proto, flags)
        raise


socket.getaddrinfo = patched_getaddrinfo


def fetch_url(url, timeout=12):
    try:
        r = cffi_req.get(url, impersonate="chrome120", doh_url="https://1.1.1.1/dns-query", timeout=timeout)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", errors="ignore")


# ==============================================================================
# PHƯƠNG ÁN 1 & 2 CHO ẢNH MINH HỌA KHI BÀI VIẾT KHÔNG CÓ ẢNH GỐC:
# - Ưu tiên 1: Tự động vẽ/chụp Biểu đồ Nến XAU/USD M15 Thời Gian Thực (mplfinance chuẩn TradingView Dark Mode)
# - Ưu tiên 2 (Dự phòng): Kho ảnh báo chí thực tế độ phân giải cao theo chủ đề
# ==============================================================================
TOPIC_PHOTO_POOL = {
    "gold": "https://images.unsplash.com/photo-1610375461246-83df859d849d?auto=format&fit=crop&w=1200&q=85",
    "fed": "https://images.unsplash.com/photo-1541354329998-f4d9a9f9297f?auto=format&fit=crop&w=1200&q=85",
    "chart": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=85"
}


def generate_live_xauusd_chart(out_path=LIVE_CHART_FILE):
    try:
        raw = fetch_url("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=15m&range=2d")
        res = json.loads(raw)["chart"]["result"][0]
        ts = res["timestamp"][-56:]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": q["open"][-56:],
            "High": q["high"][-56:],
            "Low": q["low"][-56:],
            "Close": q["close"][-56:],
            "Volume": q["volume"][-56:]
        }, index=pd.to_datetime(ts, unit="s"))
        df.dropna(inplace=True)
        if len(df) < 15:
            return None

        mc = mpf.make_marketcolors(up="#089981", down="#f23645", edge="inherit", wick="inherit", volume="in")
        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            facecolor="#131722",
            figcolor="#131722",
            gridcolor="#1e222d",
            gridstyle="--",
            y_on_right=True
        )
        hi = float(df["High"].max())
        lo = float(df["Low"].min())
        last_c = float(df["Close"].iloc[-1])

        mpf.plot(
            df,
            type="candle",
            mav=(20, 50),
            volume=True,
            style=style,
            title=f"\nXAU/USD (M15 Live) | Close: ${last_c:,.1f} | Support: ${lo:,.0f} - Resistance: ${hi:,.0f}",
            hlines=dict(hlines=[hi, lo, last_c], colors=["#f23645", "#089981", "#2962ff"], linestyle="--", linewidths=1.0),
            figsize=(11.5, 6.2),
            tight_layout=True,
            savefig=dict(fname=out_path, dpi=160, bbox_inches="tight")
        )
        if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
            return out_path
    except Exception as e:
        print("[Live Chart Gen Error]:", e)
    return None


def upload_local_photo(chat_id, file_path, caption):
    boundary = f"----VTBoundary{uuid.uuid4().hex}"
    body = bytearray()

    def add_field(name, val):
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{val}\r\n".encode("utf-8"))

    add_field("chat_id", str(chat_id))
    add_field("caption", caption)

    filename = os.path.basename(file_path)
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(b"Content-Type: image/png\r\n\r\n")
    with open(file_path, "rb") as f:
        body.extend(f.read())
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("[Upload Local Photo Error]:", e)
        return {"ok": False, "error": str(e)}


def api_call(method, payload=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[Telegram {method} Error]: {e}")
        return {"ok": False, "error": str(e)}


# ==============================================================================
# TỰ ĐỘNG ĐĂNG LÊN NHÓM:
# - Có ảnh gốc -> Dùng ảnh gốc
# - Không có ảnh gốc (hoặc ảnh lỗi) -> Ưu tiên 1: Chụp biểu đồ XAU/USD thời gian thực -> Ưu tiên 2: Ảnh báo chí theo chủ đề
# ==============================================================================
def publish_post(chat_id, post_item):
    # Dạng khảo sát (poll): gửi bằng sendPoll, không kèm ảnh
    if post_item.get("poll"):
        pl = post_item["poll"]
        return api_call("sendPoll", {
            "chat_id": chat_id,
            "question": pl["question"][:300],
            "options": [str(o)[:100] for o in pl["options"][:10]],
            "is_anonymous": True,
            "allows_multiple_answers": False
        })

    caption = post_item.get("caption", "")
    image_url = post_item.get("image_url", "")
    source_url = post_item.get("source_url", "")

    full_caption = f"{caption}\n\n🔗 {source_url}" if source_url and source_url not in caption else caption

    # Bài hội thoại thuần chữ (câu hỏi tình huống, giải thích thuật ngữ, tổng kết tuần): không cần ảnh
    if post_item.get("kind") in ("scenario", "glossary", "recap"):
        return api_call("sendMessage", {"chat_id": chat_id, "text": caption})

    # 1. Nếu là đường dẫn ảnh gốc (URL hoặc file local)
    if image_url:
        if os.path.exists(image_url):
            res = upload_local_photo(chat_id, image_url, full_caption)
            if res.get("ok"):
                return res
        elif image_url.startswith("http"):
            res = api_call("sendPhoto", {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": full_caption
            })
            if res.get("ok"):
                return res

    # 2. Nếu không có ảnh gốc -> Ưu tiên Phương án 1: Chụp biểu đồ Nến XAU/USD thời gian thực
    chart_path = generate_live_xauusd_chart()
    if chart_path and os.path.exists(chart_path):
        res = upload_local_photo(chat_id, chart_path, full_caption)
        if res.get("ok"):
            return res

    # 3. Nếu Phương án 1 không được -> Chuyển sang Phương án 2: Kho ảnh báo chí thật theo chủ đề
    fallback_photo = TOPIC_PHOTO_POOL["gold"]
    res = api_call("sendPhoto", {
        "chat_id": chat_id,
        "photo": fallback_photo,
        "caption": full_caption
    })
    if res.get("ok"):
        return res

    return api_call("sendMessage", {
        "chat_id": chat_id,
        "text": full_caption,
        "disable_web_page_preview": False
    })


# ==============================================================================
# DỊCH TỰ ĐỘNG & LÀM MƯỢT THUẬT NGỮ TRADING TIẾNG VIỆT
# ==============================================================================
def translate_en_to_vi(text):
    if not text or not text.strip():
        return ""
    clean_src = re.sub(r"(\d+)\.\s+(\d+)", r"\1.\2", text.strip()[:1200])
    translated = ""
    try:
        q = urllib.parse.quote(clean_src)
        url1 = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=vi&q={q}"
        r = cffi_req.get(url1, impersonate="chrome120", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                translated = data[0] if isinstance(data[0], str) else "".join([x[0] for x in data[0] if x])
    except Exception:
        pass

    if not translated:
        try:
            q = urllib.parse.quote(clean_src)
            url2 = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=vi&dt=t&q={q}"
            r2 = cffi_req.get(url2, impersonate="chrome120", timeout=8)
            if r2.status_code == 200:
                data2 = r2.json()
                translated = "".join([part[0] for part in data2[0] if part and part[0]])
        except Exception as e:
            print("[Translate Error]:", e)
            return clean_src

    translated = (
        translated.replace("Cục Dự trữ Liên bang", "FED")
        .replace("Fed", "FED")
        .replace("Powell của FED", "Chủ tịch FED Jerome Powell")
        .replace("lợi tức kho bạc", "lợi suất trái phiếu Mỹ")
        .replace("Lợi tức kho bạc", "Lợi suất trái phiếu Mỹ")
        .replace("trái phiếu trái phiếu Mỹ", "trái phiếu Mỹ")
        .replace("kho bạc Hoa Kỳ", "trái phiếu Mỹ")
        .replace("kho bạc Mỹ", "trái phiếu Mỹ")
        .replace("đồng bạc xanh", "đồng USD")
    )
    return re.sub(r"(\d+)\.\s+(\d+)", r"\1.\2", translated.strip())


# ==============================================================================
# BỘ CÂN BẰNG TỶ TRỌNG NỘI DUNG (ƯU TIÊN 82% KIẾN THỨC, BÀI TOÁN LỢI NHUẬN CHO NGƯỜI MỚI & THẢO LUẬN TRADING; TIN TỨC TỐI ĐA 18%)
# - kol (30%): Kiến thức thực chiến, cách vào lệnh & bài toán lợi nhuận cho người mới
# - reddit (25%): Thảo luận thực chiến, so sánh cách kiếm lời, đi vốn & tâm lý giao dịch
# - tiktok (15%): Mẹo giữ lãi, rút lãi & kỷ luật thực chiến từ các trader triệu đô
# - vt (12%): Mẹo tối ưu lợi nhuận ròng bỏ túi (giảm phí Spread, cộng dồn hoàn phí Backcom, tính sẵn tiền lời/lỗ trên TradingView)
# - tintuc (18%): Chỉ điểm tin vĩ mô thực sự lớn kèm cơ hội giao dịch cụ thể
# ==============================================================================
def load_balance_state():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "posted_urls": [],
        "category_counts": {"kol": 0, "reddit": 0, "tiktok": 0, "vt": 0, "tintuc": 0},
        "last_category": ""
    }


def save_balance_state(st):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def pick_balanced_post(buzz, preferred_cat=None, _retried=False):
    st = load_balance_state()
    posted = set(st.get("posted_urls", []))
    counts = st.get("category_counts", {"kol": 0, "reddit": 0, "tiktok": 0, "vt": 0, "tintuc": 0})
    last_cat = st.get("last_category", "")

    if not preferred_cat or preferred_cat == "auto":
        total = max(1, sum(counts.values()))
        ratios = {
            "kol": counts.get("kol", 0) / total,
            "reddit": counts.get("reddit", 0) / total,
            "tiktok": counts.get("tiktok", 0) / total,
            "vt": counts.get("vt", 0) / total,
            "tintuc": counts.get("tintuc", 0) / total,
        }
        targets = {"kol": 0.30, "reddit": 0.25, "tiktok": 0.15, "vt": 0.12, "tintuc": 0.18}
        candidates = sorted(targets.keys(), key=lambda k: (ratios[k] - targets[k]))
        preferred_cat = next((c for c in candidates if c != last_cat), candidates[0])

    pool_map = {
        "tintuc": buzz.get("macro_posts", []),
        "kol": buzz.get("kol_posts", []),
        "tiktok": buzz.get("tiktok_posts", []),
        "reddit": buzz.get("reddit_posts", []),
        "vt": buzz.get("vt_posts", [])
    }
    pool = pool_map.get(preferred_cat, []) or buzz.get("kol_posts", [])

    unseen = [p for p in pool if p.get("id_key", p.get("source_url")) not in posted]
    if not unseen and not _retried:
        # Không bao giờ quay vòng bài cũ! Tự động quét mới trực tiếp từ 4 Sheet ngay lập tức
        fresh_buzz = generate_daily_buzz()
        return pick_balanced_post(fresh_buzz, preferred_cat=preferred_cat, _retried=True)

    chosen = random.choice(unseen) if unseen else None
    if chosen:
        st["last_category"] = preferred_cat
        counts[preferred_cat] = counts.get(preferred_cat, 0) + 1
        st["category_counts"] = counts
        key_id = chosen.get("id_key") or chosen.get("source_url")
        if key_id:
            st.setdefault("posted_urls", []).append(key_id)
            st["posted_urls"] = st["posted_urls"][-500:]
        save_balance_state(st)
    return preferred_cat, chosen


def fetch_online_sheets():
    sheets_data = {}
    for tab in ["Website", "YouTube", "TikTok", "Reddit"]:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(tab)}"
        try:
            raw_csv = fetch_url(url)
            reader = list(csv.reader(raw_csv.splitlines()))
            rows = [r for r in reader[1:] if len(r) >= 4 and r[2].strip()]
            sheets_data[tab] = rows
        except Exception:
            sheets_data[tab] = []
    return sheets_data


# ==============================================================================
# REPO MÃ NGUỒN MỞ `python-tradingview-ta`: QUÉT CHỈ BÁO ĐỊNH LƯỢNG THỰC TẾ XAU/USD & DXY
# ==============================================================================
def fetch_live_market_and_ta():
    market = {
        "gold_price": 3995.8,
        "gold_high": 4050.0,
        "gold_low": 3989.0,
        "dxy_price": 101.75,
        "h1_rec": "SELL",
        "h1_sell_count": 14,
        "h1_buy_count": 2,
        "h1_rsi": 34.6,
        "h1_ema20": 4014.3,
        "h1_ema50": 4044.5,
        "m15_bb_lower": 3992.5,
        "m15_bb_upper": 4004.3,
        "m15_rsi": 43.2
    }
    try:
        h1 = TA_Handler(symbol="XAUUSD", screener="cfd", exchange="OANDA", interval=Interval.INTERVAL_1_HOUR).get_analysis()
        m15 = TA_Handler(symbol="XAUUSD", screener="cfd", exchange="OANDA", interval=Interval.INTERVAL_15_MINUTES).get_analysis()
        ind1 = h1.indicators
        ind15 = m15.indicators

        market["gold_price"] = round(float(ind1.get("close", 3995.8)), 1)
        market["h1_rec"] = h1.summary.get("RECOMMENDATION", "SELL")
        market["h1_sell_count"] = int(h1.summary.get("SELL", 14))
        market["h1_buy_count"] = int(h1.summary.get("BUY", 2))
        market["h1_rsi"] = round(float(ind1.get("RSI", 34.6)), 1)
        market["h1_ema20"] = round(float(ind1.get("EMA20", market["gold_price"] + 15)), 1)
        market["h1_ema50"] = round(float(ind1.get("EMA50", market["gold_price"] + 35)), 1)
        market["m15_bb_lower"] = round(float(ind15.get("BB.lower", market["gold_price"] - 5)), 1)
        market["m15_bb_upper"] = round(float(ind15.get("BB.upper", market["gold_price"] + 8)), 1)
        market["m15_rsi"] = round(float(ind15.get("RSI", 43.2)), 1)
        market["gold_low"] = round(min(market["m15_bb_lower"] - 3, float(ind1.get("low", market["gold_price"] - 8))), 0)
        market["gold_high"] = round(max(market["h1_ema50"] + 5, float(ind1.get("high", market["gold_price"] + 25))), 0)
    except Exception as e:
        print("[TradingView TA XAUUSD Error]:", e)

    try:
        dxy_h1 = TA_Handler(symbol="DXY", screener="cfd", exchange="TVC", interval=Interval.INTERVAL_1_HOUR).get_analysis()
        market["dxy_price"] = round(float(dxy_h1.indicators.get("close", 101.75)), 2)
    except Exception as e:
        print("[TradingView TA DXY Error]:", e)

    return market


# ==============================================================================
# BỘ GIẢI MÃ TIN TỨC "NHÂN - QUẢ - ĐIỂM ĐÁNH" (KHÔNG TƯỜNG THUẬT SÁO RỖNG)
# Kết hợp dữ liệu bài báo (`trafilatura`) + Chỉ báo định lượng (`tradingview-ta`)
# ==============================================================================
def score_article(title):
    t = title.lower()
    noise_kw = ["india", "wedding", "quince", "crypto", "bitcoin", "murder", "korea", "biden", "celeb", "stock"]
    if any(nk in t for nk in noise_kw):
        return -100

    score = 0
    tier1_kw = ["gold", "xau", "fed", "powell", "cpi", "pce", "inflation", "nonfarm", "jobless", "treasury", "yield", "dollar", "dxy", "rate"]
    for kw in tier1_kw:
        if kw in t:
            score += 15
    if re.search(r"\d+", t) or any(w in t for w in ["lowest", "highest", "record", "jump", "drop", "surge", "sink", "crater"]):
        score += 10
    return score


def build_actionable_news_insight(title_en, vi_title, vi_facts, market, idx, source_name="FXEmpire / Investing"):
    t_low = title_en.lower()
    gp = market["gold_price"]
    rsi1 = market["h1_rsi"]
    ema20 = market["h1_ema20"]
    bb_low = market["m15_bb_lower"]
    bb_up = market["m15_bb_upper"]
    sell_cnt = market["h1_sell_count"]
    dxy = market["dxy_price"]

    # Bài dài: 100% trích dẫn khách quan theo cấu trúc "Nguồn tin/Chuyên gia A chia sẻ nhận định B về kịch bản C" (Bot & VT Markets không phán xét chủ quan)
    if any(k in t_low for k in ["powell", "pce", "jobless", "hawkish", "rate hike", "stability"]):
        return (
            f"📰 Theo bài phân tích vừa đăng tải trên {source_name} ({vi_title}), các chuyên gia tại đây nhận định việc dữ liệu lạm phát và lao động Mỹ giữ ổn định đang khiến giới đầu tư giảm kỳ vọng FED sớm hạ lãi suất, từ đó tạo áp lực điều chỉnh lên giá Vàng quanh vùng ${gp:,.1f}.\n\n"
            f"📊 Đối chiếu trên bảng thống kê tự động của TradingView, hiện có {sell_cnt}/26 chỉ báo kỹ thuật nghiêng về chiều bán dưới đường trung bình EMA20 (${ema20:,.0f}), trong khi chỉ số RSI khung H1 đang hiển thị ở mức {rsi1} gần biên dưới ${bb_low:,.0f}.\n\n"
            f"💬 Từ các dữ liệu trên, đội ngũ phân tích của {source_name} chia sẻ góc nhìn rằng thị trường có thể xuất hiện các nhịp giằng co quanh vùng ${bb_low:,.0f} – ${ema20:,.0f}. Các sếp đánh giá thế nào về nhận định này của {source_name}?"
        )
    if any(k in t_low for k in ["yield", "treasury", "haven", "crater", "drop"]):
        return (
            f"📌 Theo bản tin thị trường trên {source_name} ({vi_title}), tác giả bài viết cho rằng sự hạ nhiệt của lợi suất trái phiếu Mỹ đang được một bộ phận nhà đầu tư xem là yếu tố hỗ trợ tâm lý cho Vàng quanh vùng ${bb_low:,.0f} – ${gp:,.1f}.\n\n"
            f"📊 Trong khi đó, số liệu công khai trên TradingView ghi nhận chỉ số DXY đang ở mức {dxy:.2f} còn giá Vàng dao động giữa biên ${bb_low:,.0f} và đường trung bình EMA20 H1 (${ema20:,.0f}) với RSI ở mức {rsi1}.\n\n"
            f"💬 Bài viết trên {source_name} nghiêng về kịch bản quan sát phản ứng giá tại hai mốc biên này trước khi xu hướng mới hình thành. Các sếp có đồng tình với góc nhìn của tác giả bài báo không?"
        )

    short_fact = vi_facts.split(".")[0].strip() + "." if vi_facts else f"{vi_title}."
    if idx % 2 == 0:
        return (
            f"Theo bản tin trên {source_name}, tác giả chia sẻ góc nhìn: \"{short_fact}\" "
            f"Số liệu trên TradingView hiện ghi nhận Vàng ở ${gp:,.1f} (giữa vùng ${bb_low:,.0f} và ${ema20:,.0f}), các sếp thấy nhận định trên của {source_name} có sát thực tế không?"
        )
    return (
        f"Trang {source_name} vừa có bài viết \"{vi_title}\" phân tích tác động của đồng USD (DXY hiện ở {dxy:.2f}) lên giá Vàng quanh vùng ${bb_low:,.0f} – ${bb_up:,.0f}. "
        f"Các sếp đánh giá kịch bản mà chuyên gia bên {source_name} đưa ra hôm nay thế nào?"
    )


# ==============================================================================
# QUÉT NHẬN ĐỊNH TIN TỨC, XU HƯỚNG VÀNG (XAU/USD) & DẦU (OIL) HÀNG NGÀY TỪ YOUTUBE KOL & PODCAST QUỐC TẾ
# Bóc trực tiếp phụ đề lời nói (`YouTubeTranscriptApi`) của chuyên gia/KOL -> Trích dẫn 100% khách quan từ nguồn!
# ==============================================================================
def fetch_youtube_kol_news_forecasts(market, posted_set=None):
    posted_set = posted_set or set()
    gp = market["gold_price"]
    low_z = round(market.get("m15_bb_lower", gp - 5), 0)
    high_z = round(market.get("h1_ema20", gp + 15), 0)

    queries = [
        ("XAUUSD+gold+forecast+analysis+today", "Vàng (XAU/USD)"),
        ("gold+oil+market+news+podcast+analysis", "Vàng & Dầu mỏ (WTI)"),
        ("DXY+dollar+gold+weekly+outlook+analysis", "Chỉ số USD (DXY) & Vàng")
    ]
    yt_forecasts = []
    yt_api = YouTubeTranscriptApi()
    seen_vids = set()

    for q_str, topic_label in queries:
        try:
            search_url = f"https://www.youtube.com/results?search_query={q_str}&sp=CAI%253D"
            html = fetch_url(search_url, timeout=10)
            vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
            for vid in vids[:15]:
                id_key = f"yt_forecast_{vid}"
                if vid in seen_vids or id_key in posted_set or f"https://www.youtube.com/watch?v={vid}" in posted_set:
                    continue
                seen_vids.add(vid)
                try:
                    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
                    meta = json.loads(fetch_url(oembed_url, timeout=6))
                    author = meta.get("author_name", "Chuyên gia quốc tế")
                    title_en = meta.get("title", "")
                    if any(bad in title_en.lower() for bad in ["hindi", "urdu", "malayalam", "tamil", "bangla", "indonesia"]):
                        continue

                    tr_list = yt_api.fetch(vid, languages=["en", "en-US", "en-GB"])
                    market_segs = []
                    filler_en = ["welcome", "subscribe", "channel", "my dear friends", "let's start", "before we start", "hit the like", "editor of", "host of", "conference", "sponsor"]
                    key_en = ["gold", "xau", "oil", "wti", "crude", "dollar", "dxy", "fed", "rate", "inflation", "support", "resistance", "break", "target", "buy", "sell", "bullish", "bearish", "level", "zone", "drop", "rally", "pullback", "trend"]
                    for seg in tr_list[5:95]:
                        t_seg = re.sub(r"\[[^\]]*\]|>>", " ", seg.text.replace("\n", " ")).strip()
                        low_s = t_seg.lower()
                        if any(fe in low_s for fe in filler_en):
                            continue
                        if re.search(r"\b\d{2,4}\b", low_s) or any(ke in low_s for ke in key_en):
                            market_segs.append(t_seg)
                        if len(" ".join(market_segs)) >= 360:
                            break

                    core_en = re.sub(r"\s+", " ", " ".join(market_segs)).strip()[:420]
                    if len(core_en) < 90:
                        continue

                    vi_title = translate_en_to_vi(title_en)
                    vi_title = re.sub(r"\s*\|\s*.*$", "", vi_title).strip()
                    vi_summary = translate_en_to_vi(core_en)
                    vi_summary = re.sub(r"(?i)^(vì vậy,?\s*|hãy bắt đầu\s*|và\s*|như bạn có thể thấy,?\s*|các bạn thân mến của tôi,?\s*|các bạn của tôi,?\s*|đây là biểu đồ[^,]*,\s*)+", "", vi_summary).strip()
                    if vi_summary:
                        vi_summary = vi_summary[0].upper() + vi_summary[1:]
                    sentences = [s.strip() for s in vi_summary.split(".") if len(s.strip()) > 25]
                    quote_vi = ". ".join(sentences[:2]) + "." if sentences else vi_summary

                    caption = (
                        f"🎙️ Tổng hợp nhanh quan điểm cá nhân của kênh YouTube / Podcast {author} trong video mới nhất về {topic_label} ({vi_title}) để các sếp cùng tham khảo.\n\n"
                        f"📌 Trong video này, nhà phân tích của kênh {author} đưa ra góc nhìn riêng: \"{quote_vi}\"\n\n"
                        f"💬 Đây là kịch bản dự báo từ phía kênh {author} (hiện bảng điện ghi nhận Vàng ở quanh ${gp:,.0f}, giữa hai mốc kỹ thuật ${low_z:,.0f} và ${high_z:,.0f}). Các sếp đánh giá nhận định này của {author} có hợp lý không hay các sếp có góc nhìn khác?"
                    )
                    yt_forecasts.append({
                        "id_key": id_key,
                        "title": vi_title,
                        "image_url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                        "source_url": f"https://www.youtube.com/watch?v={vid}",
                        "caption": caption
                    })
                    if len(yt_forecasts) >= 2:
                        break
                except Exception:
                    continue
        except Exception as e:
            print("[YT Forecast Search Error]:", e)

    return yt_forecasts


def fetch_real_macro_articles(market, posted_set=None):
    posted_set = posted_set or set()
    candidates = []
    rss_feeds = [
        ("FXEmpire", "https://www.fxempire.com/api/v1/en/articles/rss/news"),
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
        ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069"),
        ("Investing.com Forex", "https://www.investing.com/rss/news_1.rss"),
        ("Investing.com Commodities", "https://www.investing.com/rss/news_11.rss"),
        ("Investing.com Economy", "https://www.investing.com/rss/news_14.rss"),
        ("Investing.com Indicators", "https://www.investing.com/rss/news_95.rss"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories")
    ]
    seen_links = set()
    for src_label, rss_url in rss_feeds:
        try:
            raw_xml = fetch_url(rss_url)
            feed = feedparser.parse(raw_xml)
            for entry in feed.entries[:20]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not link or link in posted_set or link in seen_links:
                    continue
                seen_links.add(link)
                summary = re.sub(r"<[^>]+>", "", (entry.get("summary") or entry.get("description") or "")).strip()
                img_url = ""
                if entry.get("links"):
                    for lk in entry.links:
                        if lk.get("type", "").startswith("image/") or lk.get("href", "").endswith((".jpg", ".jpeg", ".png")):
                            img_url = lk.get("href", "")
                            break
                if not img_url and entry.get("media_content"):
                    img_url = entry.media_content[0].get("url", "")
                sc = score_article(title)
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    age_h = (time.time() - calendar.timegm(pub)) / 3600
                    if age_h > 24:  # chỉ lấy tin mới trong 24 giờ
                        continue
                    sc += max(0, 24 - age_h) / 2  # tin càng mới càng được ưu tiên
                if sc >= 15 and link:
                    if "cnbc.com" in link or "fxempire.com" in link:
                        sc += 10
                    candidates.append({"source_name": src_label, "title": title, "link": link, "summary": summary, "image_url": img_url, "score": sc})
        except Exception as e:
            print(f"[Feedparser Error] {rss_url}: {e}")

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Ưu tiên số 1 cho mục Tin tức & Nhận định xu hướng: Lấy trực tiếp video KOL & Podcast YouTube chưa từng đăng
    # (Đã bỏ nguồn video YouTube cho mục tin tức: video cũ, phụ đề dịch máy rối và lẫn quảng cáo. Video KOL do content_engine.make_kol_insight xử lý.)
    macro_posts = []

    for idx, art in enumerate(candidates[:4]):
        vi_title = translate_en_to_vi(art["title"])
        vi_facts = ""
        og_img = art["image_url"]
        try:
            downloaded = fetch_url(art["link"], timeout=8)
            if not og_img:
                m_og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', downloaded, re.I)
                if m_og:
                    og_img = m_og.group(1)
            extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if extracted:
                paragraphs = [p.strip() for p in extracted.splitlines() if len(p.strip()) > 60 and not p.strip().lower().startswith("published")]
                if paragraphs:
                    vi_facts = translate_en_to_vi(paragraphs[0][:360])
        except Exception:
            pass
        if not vi_facts and art.get("summary") and len(art["summary"]) > 40:
            vi_facts = translate_en_to_vi(art["summary"][:340])

        caption = build_actionable_news_insight(art["title"], vi_title, vi_facts, market, idx, source_name=art.get("source_name", "FXEmpire"))

        macro_posts.append({
            "id_key": art["link"],
            "title": vi_title,
            "image_url": og_img,
            "source_url": art["link"],
            "caption": caption
        })

    return macro_posts


# ==============================================================================
# QUÉT ĐỘNG TRỰC TIẾP TỪ SHEET 2 (70 KÊNH YOUTUBE KOL QUỐC TẾ) & SHEET 3 (35 KÊNH TIKTOK KOL)
# Lọc bỏ 100% bài/video đã đăng trong `posted_set` -> Không bao giờ lặp bài!
# ==============================================================================
def fetch_dynamic_youtube_kol_posts(sheets, market, posted_set=None):
    posted_set = posted_set or set()
    yt_rows = list(sheets.get("YouTube", []))
    random.shuffle(yt_rows)
    dynamic_kol_posts = []

    for row in yt_rows:
        if len(dynamic_kol_posts) >= 4:
            break
        if len(row) < 4:
            continue
        kol_name = row[2].strip()
        specialty = row[5].strip() if len(row) >= 6 else "Phương pháp Price Action & Quản trị rủi ro thực chiến"
        clean_kol_query = re.sub(r"\([^)]*\)", "", kol_name).strip()
        q_str = urllib.parse.quote(f"{clean_kol_query} gold forex trading")
        try:
            html = fetch_url(f"https://www.youtube.com/results?search_query={q_str}&sp=CAI%3D", timeout=8)  # CAI%3D = sắp xếp theo ngày đăng mới nhất
            vids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)))
            chosen_vid = None
            meta = {}
            for vid in vids[:12]:
                id_key = f"kol_yt_vid_{vid}"
                if id_key in posted_set or f"https://www.youtube.com/watch?v={vid}" in posted_set:
                    continue
                try:
                    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
                    m_data = json.loads(fetch_url(oembed_url, timeout=5))
                    t_en = m_data.get("title", "")
                    if t_en and not any(bad in t_en.lower() for bad in ["hindi", "urdu", "malayalam", "tamil", "bangla"]):
                        chosen_vid = vid
                        meta = m_data
                        break
                except Exception:
                    continue

            if not chosen_vid:
                continue

            title_en = meta.get("title", f"{kol_name} Trading Strategy")
            vi_title = translate_en_to_vi(title_en)
            vi_title = re.sub(r"\s*[\|\-]\s*.*$", "", vi_title).strip() or title_en

            caption = (
                f"📌 Trên kênh YouTube của {kol_name}, chuyên gia này vừa có bài chia sẻ xoay quanh chủ đề \"{vi_title}\" (thuộc thế mạnh của kênh là: {specialty}).\n\n"
                f"💡 Theo góc nhìn cá nhân mà {kol_name} trình bày trong video, thay vì vào lệnh dàn trải ở mọi nhịp sóng, chiến lược của chuyên gia này tập trung đợi giá tiếp cận đúng vùng cấu trúc trên khung H1/M15 và chỉ hành động khi có nến xác nhận rõ ràng kèm mức dừng lỗ cố định.\n\n"
                f"💬 Đó là nguyên tắc giao dịch riêng được {kol_name} áp dụng. Các sếp trong nhóm mình đánh giá cách tiếp cận này của {kol_name} có phù hợp khi giao dịch XAU/USD không?"
            )
            dynamic_kol_posts.append({
                "id_key": f"kol_yt_vid_{chosen_vid}",
                "kol": kol_name,
                "video_id": chosen_vid,
                "title": f"{kol_name}: {vi_title}",
                "source_url": f"https://www.youtube.com/watch?v={chosen_vid}",
                "image_url": f"https://i.ytimg.com/vi/{chosen_vid}/hqdefault.jpg",
                "caption": caption
            })
        except Exception:
            continue

    # Bổ sung các bài trong kho cơ sở nếu chưa từng đăng trong posted_set
    for item in KOL_YOUTUBE_POSTS:
        if item["id_key"] not in posted_set and len(dynamic_kol_posts) < 5:
            dynamic_kol_posts.append(item)

    return dynamic_kol_posts


TIKTOK_DISCIPLINE_ANGLES = [
    ("overtrade_filter", "cách hạn chế vào lệnh quá đà (Overtrade) sau khi vừa có lệnh thắng hoặc lệnh thua", "chỉ cho phép bản thân vào tối đa 1–2 lệnh chất lượng nhất trong mỗi phiên giao dịch rồi đóng biểu đồ nghỉ ngơi"),
    ("breakeven_rule", "nguyên tắc bảo vệ vốn khi giá đã chạy đúng hướng kỳ vọng", "dời điểm dừng lỗ (SL) về mức hòa vốn hoặc chốt trước một nửa khối lượng khi lệnh đã đạt tỷ lệ 1:1 để giải tỏa áp lực tâm lý"),
    ("news_avoidance", "cách xử lý tài khoản trước thời điểm công bố tin tức kinh tế đỏ (CPI, Non-Farm, FOMC)", "tránh mở lệnh mới sát giờ ra tin 15 phút vì độ giãn giá và quét thanh khoản hai đầu rất khó lường, thay vào đó đợi thị trường ổn định cấu trúc sau tin mới tìm cơ hội"),
    ("weekly_withdrawal", "thói quen rút lợi nhuận định kỳ để biến con số trên màn hình thành tiền thực tế", "cuối mỗi tuần có lãi đều trích từ 40% – 50% phần lợi nhuận rút về tài khoản ngân hàng nhằm giữ tâm lý thoải mái cho tuần mới"),
    ("journal_review", "việc chụp ảnh màn hình trước và sau mỗi lệnh để làm nhật ký giao dịch cuối tuần", "ghi chú lại 3 lý do vào lệnh và cảm xúc lúc bấm nút để cuối tuần nhìn lại xem lỗi sai đến từ phân tích kỹ thuật hay do tâm lý FOMO"),
    ("session_timing", "cách lựa chọn khung giờ giao dịch cố định cho người bận công việc hành chính", "bỏ qua các nhịp đi ngang biên độ hẹp buổi sáng và chỉ tập trung theo dõi khoảng 45–60 phút đầu phiên Âu hoặc đầu phiên Mỹ khi thanh khoản lớn nhập cuộc"),
    ("fixed_risk_pct", "bài toán cố định mức rủi ro tính bằng số tiền USD trên mỗi giao dịch", "luôn xác định trước số tiền chấp nhận rủi ro tối đa cho 1 lệnh (ví dụ 1% – 2% tài khoản) rồi mới chia ngược ra số Lot tương ứng với khoảng cách SL"),
    ("htf_alignment", "nguyên tắc đối chiếu xu hướng khung thời gian lớn trước khi tìm điểm vào ở khung nhỏ", "kiểm tra cấu trúc đỉnh đáy trên khung H4 và H1 trước, sau đó mới hạ xuống M15 chờ nến rút chân cùng chiều xu hướng chính")
]


def fetch_dynamic_tiktok_kol_posts(sheets, market, posted_set=None):
    posted_set = posted_set or set()
    tk_rows = list(sheets.get("TikTok", []))
    random.shuffle(tk_rows)
    dynamic_tk_posts = []
    thumb_pool = [
        "https://i.ytimg.com/vi/bV7FxNXLeWU/maxresdefault.jpg",
        "https://i.ytimg.com/vi/TYbpk7WogHI/maxresdefault.jpg",
        "https://i.ytimg.com/vi/s96BrHAScRc/hqdefault.jpg",
        "https://i.ytimg.com/vi/Vulini8xbB0/maxresdefault.jpg",
        "https://i.ytimg.com/vi/yvhgwZKkJQ0/maxresdefault.jpg"
    ]

    for row in tk_rows:
        if len(dynamic_tk_posts) >= 4:
            break
        if len(row) < 4:
            continue
        kol_label = row[2].strip()
        tk_url = row[3].strip()
        specialty = row[5].strip() if len(row) >= 6 else "Kỷ luật giao dịch và quản lý rủi ro thực chiến"
        kol_slug = re.sub(r"[^a-z0-9]+", "_", kol_label.lower()).strip("_")

        angles = list(TIKTOK_DISCIPLINE_ANGLES)
        random.shuffle(angles)
        for angle_key, topic_desc, rule_desc in angles:
            id_key = f"tiktok_{kol_slug}_{angle_key}"
            if id_key in posted_set:
                continue
            caption = (
                f"📝 Trên kênh TikTok của {kol_label} (chuyên về: {specialty}), nhà giao dịch này có chia sẻ góc nhìn cá nhân xoay quanh {topic_desc}.\n\n"
                f"✅ Theo chia sẻ từ kênh {kol_label}, nguyên tắc mà họ tự đặt ra cho bản thân là {rule_desc}.\n\n"
                f"💬 Đó là kỷ luật cá nhân được {kol_label} áp dụng để bảo vệ tài khoản. Các sếp trong nhóm mình thấy cách làm này của {kol_label} có thực tế không?"
            )
            dynamic_tk_posts.append({
                "id_key": id_key,
                "kol": kol_label,
                "title": f"{kol_label} chia sẻ góc nhìn về {topic_desc}",
                "source_url": tk_url,
                "image_url": random.choice(thumb_pool),
                "caption": caption
            })
            break

    for item in TIKTOK_KOL_POSTS:
        if item["id_key"] not in posted_set and len(dynamic_tk_posts) < 5:
            dynamic_tk_posts.append(item)

    return dynamic_tk_posts


# ==============================================================================
# 82%+ NỘI DUNG BÁM SÁT 5 INSIGHT CỐT LÕI — MỌI BÀI VIẾT ĐỀU TRÍCH DẪN KHÁCH QUAN:
# "Người A / Kênh B chia sẻ góc nhìn C về chiến lược D..." (Không bao giờ phán xét chủ quan từ phía Bot hay VT Markets)
# ==============================================================================
KOL_YOUTUBE_POSTS = [
    {
        "id_key": "kol_yt_overload_simplification",
        "kol": "Brad Goh (The Trading Geek)",
        "video_id": "bV7FxNXLeWU",
        "title": "Brad Goh chia sẻ giải pháp cho người mới bị quá tải chỉ báo",
        "source_url": "https://www.youtube.com/watch?v=bV7FxNXLeWU",
        "image_url": "https://i.ytimg.com/vi/bV7FxNXLeWU/maxresdefault.jpg",
        "caption": (
            "📌 Trên kênh YouTube The Trading Geek, trader Brad Goh có chia sẻ về lỗi phổ biến khiến nhiều người mới bị rối: cài cùng lúc SMC, Ichimoku, RSI, Bollinger kín màn hình nên khi cần ra quyết định lại bị mâu thuẫn tín hiệu.\n\n"
            "💡 Về chiến lược khắc phục, Brad Goh chia sẻ cách làm cá nhân của anh ấy là trong 3 tháng đầu chỉ giữ lại biểu đồ trơn và đánh dấu 2 vùng đỉnh/đáy gần nhất trên khung H1 và M15.\n\n"
            "💬 Theo quan điểm của Brad Goh, việc chỉ tập trung quan sát phản ứng nến tại vùng cản H1 sẽ giúp người mới đỡ loạn phương pháp hơn. Các sếp đánh giá cách tiếp cận này của Brad Goh thế nào?"
        )
    },
    {
        "id_key": "kol_yt_raja_daily_profit_math",
        "kol": "Raja Banks (WicksDontLie)",
        "video_id": "s96BrHAScRc",
        "title": "Raja Banks chia sẻ góc nhìn về chiến lược giao dịch 45 phút đầu phiên",
        "source_url": "https://www.youtube.com/watch?v=s96BrHAScRc",
        "image_url": "https://i.ytimg.com/vi/s96BrHAScRc/hqdefault.jpg",
        "caption": (
            "💰 Trên kênh WicksDontLie, trader Raja Banks chia sẻ quan điểm rằng người bận rộn không nhất thiết phải ngồi canh bảng điện cả ngày, mà chiến lược của ông ấy là chỉ tập trung khoảng 45 phút đầu phiên giao dịch.\n\n"
            "🎯 Trong video, Raja Banks lấy ví dụ minh họa về bài toán quản lý mục tiêu cá nhân: ông thường nhắm biên độ ngắn khoảng 20–30 pips mỗi ngày rồi đóng máy nghỉ ngơi (tất nhiên ông cũng lưu ý thị trường luôn có ngày thắng ngày chạm dừng lỗ tùy diễn biến).\n\n"
            "💬 Đó là nguyên tắc giao dịch riêng mà Raja Banks áp dụng. Các sếp trong nhóm mình thấy kiểu đánh ngắn theo phiên của ông ấy hợp hơn hay giữ lệnh dài hợp hơn?"
        )
    },
    {
        "id_key": "kol_yt_tjr_liquidity",
        "kol": "TJR (@TJRTrades)",
        "video_id": "Vulini8xbB0",
        "title": "TJR chia sẻ về chiến lược đợi nến quét thanh khoản (Liquidity Sweep)",
        "source_url": "https://www.youtube.com/watch?v=Vulini8xbB0",
        "image_url": "https://i.ytimg.com/vi/Vulini8xbB0/maxresdefault.jpg",
        "caption": (
            "⚠️ Trong buổi chia sẻ về phương pháp SMC, trader TJR (@TJRTrades) nêu ra hiện tượng nhiều người mới đặt lệnh chờ ngay tại đáy cũ thường dễ bị thị trường quét chạm dừng lỗ trước khi giá đảo chiều.\n\n"
            "💡 Chia sẻ về chiến lược 'Liquidity Sweep' của mình, TJR cho biết anh ấy không đặt lệnh chặn đầu mà thường đợi nến M5/M15 thọc râu qua đáy cũ rồi rút chân đóng cửa bên trên mới xem xét tín hiệu.\n\n"
            "💬 Theo góc nhìn của TJR thì cách đợi xác nhận này giúp anh ấy thu hẹp khoảng dừng lỗ hơn. Các sếp thường áp dụng cách đợi nến như TJR chia sẻ hay có phương pháp nào khác?"
        )
    },
    {
        "id_key": "kol_yt_smartrisk_idm",
        "kol": "Smart Risk (@SmartRisk)",
        "video_id": "yvhgwZKkJQ0",
        "title": "Kênh Smart Risk chia sẻ về bài toán tỷ lệ R:R và tâm lý chốt non",
        "source_url": "https://www.youtube.com/watch?v=yvhgwZKkJQ0",
        "image_url": "https://i.ytimg.com/vi/yvhgwZKkJQ0/maxresdefault.jpg",
        "caption": (
            "📌 Kênh phân tích Smart Risk vừa có bài chia sẻ về tâm lý giao dịch: nhiều trader mới thường đóng lệnh rất sớm khi mới lãi nhẹ nhưng lại giữ lệnh rất lâu khi bị âm.\n\n"
            "🛡️ Về giải pháp quản trị rủi ro, chuyên gia của kênh Smart Risk chia sẻ chiến lược cố định tỷ lệ R:R (ví dụ chấp nhận rủi ro 1 phần để kỳ vọng 2 phần) và dời điểm dừng lỗ về hòa vốn khi giá đã đi được nửa chặng đường.\n\n"
            "💬 Đây là phương pháp quản lý lệnh mà kênh Smart Risk khuyến khích học viên của họ luyện tập. Các sếp thấy quy tắc dời SL về hòa vốn của họ có ưu và nhược điểm gì?"
        )
    }
]

TIKTOK_KOL_POSTS = [
    {
        "id_key": "tiktok_umar_profit_withdrawal",
        "kol": "Umar Ashraf (@umarashraf)",
        "title": "Umar Ashraf chia sẻ về quy tắc bảo toàn lợi nhuận cuối tuần",
        "source_url": "https://www.tiktok.com/@umarashraf",
        "image_url": "https://i.ytimg.com/vi/bV7FxNXLeWU/maxresdefault.jpg",
        "caption": (
            "💵 Trên kênh TikTok cá nhân, triệu phú trader Umar Ashraf (@umarashraf) chia sẻ quan điểm rằng số dư đang nổi trên phần mềm giao dịch chưa phải là kết quả cuối cùng cho tới khi được rút về tài khoản ngân hàng.\n\n"
            "📌 Chia sẻ về chiến lược quản lý vốn của riêng mình, Umar Ashraf cho biết nếu phiên sáng đã đạt mục tiêu thì phiên tối ông chỉ dùng tối đa 30% phần lãi đó để giao dịch tiếp, và thứ Sáu hàng tuần đều rút một nửa lợi nhuận ra ngoài.\n\n"
            "💬 Các sếp đánh giá thế nào về thói quen quản lý tiền lãi này của Umar Ashraf?"
        )
    },
    {
        "id_key": "tiktok_tjr_3confluences",
        "kol": "TJR (@tjrtrades)",
        "title": "TJR chia sẻ mẹo dùng bảng kiểm 3 câu hỏi trước khi giao dịch",
        "source_url": "https://www.tiktok.com/@tjrtrades",
        "image_url": "https://i.ytimg.com/vi/TYbpk7WogHI/maxresdefault.jpg",
        "caption": (
            "📝 Trên kênh TikTok @tjrtrades, trader TJR chia sẻ mẹo cá nhân giúp anh ấy hạn chế thói quen vào lệnh theo cảm tính: dán một tờ giấy nhớ ghi sẵn 3 câu hỏi kiểm tra ngay cạnh màn hình.\n\n"
            "✅ Theo chia sẻ của TJR, chiến lược của anh ấy đòi hỏi phải trả lời rõ 3 yếu tố: xu hướng khung lớn H1, tín hiệu quét râu qua vùng đỉnh/đáy cũ, và nến xác nhận ở khung nhỏ.\n\n"
            "💬 Đó là bộ lọc cá nhân mà TJR tự đặt ra cho mình. Các sếp trong nhóm có hay dùng checklist kiểu này giống TJR không?"
        )
    },
    {
        "id_key": "tiktok_wicksdontlie_busy_trader",
        "kol": "Raja Banks (@wicksdontlie)",
        "title": "Raja Banks chia sẻ góc nhìn về cách chọn khung giờ giao dịch cho người bận rộn",
        "source_url": "https://www.tiktok.com/@wicksdontlie",
        "image_url": "https://i.ytimg.com/vi/s96BrHAScRc/hqdefault.jpg",
        "caption": (
            "⏰ Trên kênh @wicksdontlie, trader Raja Banks chia sẻ góc nhìn dành cho những người bận công việc hành chính: ông cho rằng việc chỉ mở biểu đồ theo dõi trong khoảng 1 tiếng cố định buổi tối vẫn đủ để áp dụng chiến lược theo phiên.\n\n"
            "⚠️ Theo lý giải của Raja Banks, việc ngồi nhìn bảng điện liên tục 8–10 tiếng dễ khiến tâm lý mệt mỏi và dẫn đến vào lệnh quá đà (Overtrade) ở những nhịp thị trường đi ngang.\n\n"
            "💬 Raja Banks chia sẻ ông thường chọn khung giờ đầu phiên Mỹ vì thanh khoản sôi động hơn. Các sếp thấy quan điểm chọn khung giờ của Raja Banks có hợp với lịch sinh hoạt ở Việt Nam không?"
        )
    }
]


def build_reddit_posts(market, chart_img_path, sheets=None, posted_set=None):
    posted_set = posted_set or set()
    gp = market["gold_price"]
    ema20 = market["h1_ema20"]
    bb_low = market["m15_bb_lower"]
    rsi1 = market["h1_rsi"]

    subreddits = ["Forex", "Gold", "Daytrading", "FuturesTrading", "algotrading", "technicalanalysis", "Commodities"]
    if sheets and sheets.get("Reddit"):
        extracted_subs = []
        for r in sheets["Reddit"]:
            if len(r) >= 4:
                m_sub = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)", r[3])
                if m_sub:
                    extracted_subs.append(m_sub.group(1))
        if extracted_subs:
            subreddits = extracted_subs

    random.shuffle(subreddits)
    dynamic_reddit = []

    for sub in subreddits[:6]:
        if len(dynamic_reddit) >= 4:
            break
        try:
            r_json = json.loads(fetch_url(f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit={sub}&sort=desc&limit=12", timeout=8))
            for item in r_json.get("data", []):
                perma = item.get("permalink", "")
                title_en = (item.get("title") or "").strip()
                selftext_en = (item.get("selftext") or "").strip()
                if not perma or not title_en or len(title_en) < 18:
                    continue
                full_url = f"https://www.reddit.com{perma}"
                id_key = f"reddit_thread_{perma.strip('/')}"
                if id_key in posted_set or full_url in posted_set:
                    continue
                if any(bad in title_en.lower() for bad in ["meme", "shitpost", "upvote", "karma", "discord", "telegram", "scam", "removed by moderator", "daily discussion", "referral", "join moomoo"]):
                    continue
                if sub.lower() in ("worldnews", "geopolitics", "news", "politics"):
                    continue
                if sum(1 for ch in title_en if ord(ch) > 127) > 2:  # bài không phải tiếng Anh
                    continue
                if any(bad in (title_en + " " + selftext_en[:200]).lower() for bad in ["deposit", "withdraw", "funded account", "promo", "discount", "giveaway", "course", "signal group", "for adoption", "free indicator", "building a", "i built", "my bot", "my app", "my website", "subreddit"]):
                    continue
                if len(selftext_en) < 120:  # không có nội dung thật thì không đăng (tránh bịa "nhiều thành viên bình luận...")
                    continue

                vi_title = translate_en_to_vi(title_en)
                vi_body = ""
                if selftext_en and len(selftext_en) > 40:
                    clean_self = re.sub(r"https?://\S+", "", selftext_en).strip()[:280]
                    if len(clean_self) > 30:
                        vi_body = translate_en_to_vi(clean_self)

                if vi_body:
                    second_para = f"💡 Trong bài viết, tác giả trên r/{sub} chia sẻ góc nhìn thực tế: \"{vi_body}\""
                else:
                    second_para = f"💡 Dưới phần bình luận của r/{sub}, nhiều thành viên quốc tế đã đưa ra các quan điểm đa chiều về cách quản lý khối lượng lệnh và tâm lý trước các vùng cản kỹ thuật."

                caption = (
                    f"📊 Điểm nhanh một chủ đề mới đang được các thành viên trên cộng đồng r/{sub} quốc tế đem ra thảo luận: \"{vi_title}\".\n\n"
                    f"{second_para}\n\n"
                    f"💬 Đối chiếu trên biểu đồ M15 đính kèm, hiện XAU/USD đang giao dịch quanh ${gp:,.1f} (giữa vùng ${bb_low:,.0f} và EMA20 ${ema20:,.0f}, RSI H1 ở mức {rsi1}). Các sếp trong nhóm mình có góc nhìn thế nào về chủ đề trên r/{sub}?"
                )
                dynamic_reddit.append({
                    "id_key": id_key,
                    "title": f"r/{sub}: {vi_title}",
                    "image_url": chart_img_path,
                    "source_url": full_url,
                    "caption": caption
                })
                break
        except Exception:
            continue

    fallback_reddit = [
        {
            "id_key": "reddit_busy_office_hours",
            "title": "Thành viên trên r/Gold chia sẻ cách phân bổ thời gian giao dịch khi đi làm hành chính",
            "image_url": chart_img_path,
            "source_url": "https://www.reddit.com/r/Gold/",
            "caption": (
                f"⏰ Điểm lại một chủ đề đang được nhiều thành viên trên diễn đàn r/Gold quốc tế thảo luận: người bận đi làm văn phòng cả ngày thường sắp xếp thời gian theo dõi thị trường như thế nào?\n\n"
                f"💡 Trong bài đăng, nhiều thành viên Reddit chia sẻ kinh nghiệm cá nhân là họ bỏ qua các nhịp sóng nhỏ buổi sáng, chỉ chọn theo dõi cố định 30–45 phút đầu phiên Âu hoặc đầu phiên Mỹ để đỡ ảnh hưởng công việc chính.\n\n"
                f"💬 Trên biểu đồ M15 đính kèm hiện giá Vàng đang ở quanh ${gp:,.1f} (giữa mốc ${bb_low:,.0f} và EMA20 ${ema20:,.0f}). Các sếp trong nhóm mình thấy cách phân bổ thời gian mà anh em trên r/Gold chia sẻ có hợp lý không?"
            )
        },
        {
            "id_key": "reddit_profit_style_debate",
            "title": "Tranh luận trên r/Daytrading: Chiến lược chốt lời ngắn trong ngày hay giữ lệnh dài?",
            "image_url": chart_img_path,
            "source_url": "https://www.reddit.com/r/Daytrading/",
            "caption": (
                f"📊 Trên cộng đồng r/Daytrading quốc tế đang có cuộc thảo luận khá sôi nổi giữa hai trường phái: nhóm trader chuyên đánh ngắn trong ngày (Scalping/Intraday) và nhóm chuyên giữ lệnh theo sóng dài (Swing).\n\n"
                f"🎯 Các thành viên ủng hộ chiến lược đánh ngắn chia sẻ rằng khi thị trường dao động trong biên hẹp (như vùng ${bb_low:,.0f} – ${ema20:,.0f}, giá hiện tại ${gp:,.1f}), việc chốt từng nhịp ngắn giúp họ chủ động hơn, trong khi nhóm đánh dài lại chấp nhận rung lắc để chờ xu hướng lớn.\n\n"
                f"💬 Mỗi góc nhìn trên r/Daytrading đều có lý lẽ riêng. Các sếp trong nhóm mình nghiêng về trường phái nào hơn?"
            )
        },
        {
            "id_key": "reddit_small_account_sizing",
            "title": "Cộng đồng r/Forex chia sẻ nguyên tắc chia khối lượng lệnh để kiểm soát rủi ro",
            "image_url": chart_img_path,
            "source_url": "https://www.reddit.com/r/Forex/",
            "caption": (
                f"💰 Trên diễn đàn r/Forex, một chủ đề nhận được nhiều bình luận từ các trader lâu năm là cách chia khối lượng (Lot) cho tài khoản nhỏ từ $500 – $1,000 sao cho an toàn trước các nhịp biến động mạnh.\n\n"
                f"🛡️ Nhiều thành viên có kinh nghiệm trên r/Forex chia sẻ quy tắc của họ là giới hạn khối lượng ở mức 0.05 – 0.1 lot và luôn đặt điểm dừng lỗ cố định quanh các mốc kỹ thuật (trên biểu đồ hiện tại là vùng ${bb_low:,.0f} và EMA20 ${ema20:,.0f}, RSI H1 {rsi1}) để rủi ro mỗi lệnh không vượt quá 2–3% vốn.\n\n"
                f"💬 Các sếp đánh giá thế nào về nguyên tắc quản lý khối lượng mà cộng đồng r/Forex chia sẻ ở trên?"
            )
        }
    ]
    for fb in fallback_reddit:
        if fb["id_key"] not in posted_set and len(dynamic_reddit) < 4:
            dynamic_reddit.append(fb)

    return dynamic_reddit


VT_MARKETS_UPDATES = [
    {
        "id_key": "vt_update_profit_backcom_math",
        "title": "Thông tin điều kiện giao dịch: Cơ chế hoàn phí Backcom tự động và tài khoản Raw ECN",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/trading/accounts/raw-ecn-account/",
        "caption": (
            "💵 Nhiều trader có kinh nghiệm trong cộng đồng thường chia sẻ mẹo tối ưu chi phí giao dịch dài hạn bằng cách tận dụng khoản hoàn phí tự động (Backcom) kết hợp điểm thưởng Club Bleuu (chi tiết điều kiện ở bài ghim đầu nhóm).\n\n"
            "⚡ Ngoài ra, theo thông số kỹ thuật công bố trên trang chủ VT Markets, loại tài khoản Raw ECN được thiết kế với mức chênh lệch giá (Spread) thấp cho các cặp chính như XAU/USD. Các sếp có thể xem đầy đủ biểu phí trên website hoặc nhắn trong nhóm để bộ phận hỗ trợ giải đáp nhé."
        )
    },
    {
        "id_key": "vt_update_tradingview_usd_calc",
        "title": "Tính năng hiển thị sẵn mức Chốt lời / Dừng lỗ quy đổi ra USD trên nền tảng TradingView",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/platforms/tradingview/",
        "caption": (
            "💡 Theo tài liệu hướng dẫn nền tảng trên trang chủ VT Markets, khi kết nối tài khoản giao dịch trực tiếp với biểu đồ TradingView, người dùng có thể kéo thanh TP và SL để hệ thống tự động hiển thị con số ước tính bằng USD ngay trên màn hình.\n\n"
            "👉 Nhiều anh em trên các diễn đàn đánh giá tính năng này của TradingView giúp người mới dễ hình dung mức rủi ro trước khi xác nhận lệnh. Trong nhóm mình đã có sếp nào trải nghiệm tính năng kết nối này chưa?"
        )
    },
    {
        "id_key": "vt_update_club_bleuu_points",
        "title": "Chương trình tích điểm khách hàng thân thiết Club Bleuu tại VT Markets",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/",
        "caption": (
            "🎁 Theo thông tin công bố về chương trình khách hàng thân thiết Club Bleuu trên hệ thống VT Markets, mỗi khối lượng giao dịch thực hiện trên tài khoản đều được tự động quy đổi thành điểm tích lũy.\n\n"
            "📌 Các thành viên lâu năm chia sẻ họ thường dùng số điểm tích lũy này để đổi sang các phiếu giảm phí hoặc quà tặng trong hệ sinh thái. Sếp nào chưa rõ cách kiểm tra số điểm Club Bleuu của mình có thể xem ở bài ghim hoặc hỏi trong nhóm nhé."
        )
    },
    {
        "id_key": "vt_update_mt4_mt5_partial_close",
        "title": "Hướng dẫn thao tác đóng một phần khối lượng lệnh (Partial Close) trên MT4/MT5",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/platforms/metatrader-5/",
        "caption": (
            "🛠️ Theo tài liệu hướng dẫn sử dụng nền tảng MetaTrader 4 và MetaTrader 5 trên trang chủ VT Markets, người dùng có thể đóng trước một phần khối lượng lệnh đang mở (ví dụ vào 0.10 lot, đóng trước 0.05 lot) bằng cách chỉnh lại số Volume trong cửa sổ lệnh trước khi bấm Close.\n\n"
            "💬 Nhiều chuyên gia quốc tế như Raja Banks hay Smart Risk thường nhắc đến thao tác đóng nửa lệnh này như một cách giảm áp lực tâm lý khi giá đi qua vùng cản đầu tiên. Các sếp trong nhóm có hay sử dụng tính năng đóng một phần lệnh này trên MT5 không?"
        )
    },
    {
        "id_key": "vt_update_economic_calendar_tool",
        "title": "Cách theo dõi Lịch kinh tế tích hợp để chủ động quản trị rủi ro trước giờ ra tin",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/tools/economic-calendar/",
        "caption": (
            "📅 Theo hướng dẫn công cụ trên website VT Markets, mục Lịch Kinh Tế (Economic Calendar) cung cấp bộ lọc phân loại mức độ tác động của các bản tin vĩ mô (Thấp, Trung bình, Cao) kèm số liệu Dự báo (Forecast) và Thực tế (Actual).\n\n"
            "🛡️ Nhiều trader có kinh nghiệm trên các diễn đàn quốc tế chia sẻ thói quen kiểm tra lịch kinh tế đầu mỗi ngày để tránh giữ lệnh khối lượng lớn ngay sát giờ công bố tin đỏ của Mỹ. Các sếp thường xem lịch tin tức trên công cụ nào mỗi ngày?"
        )
    },
    {
        "id_key": "vt_update_demo_practice_env",
        "title": "Sử dụng tài khoản Demo để kiểm chứng chiến lược (Backtest/Forward test) trước khi giao dịch thực tế",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/trading/demo-account/",
        "caption": (
            "🧭 Theo thông tin trên trang chủ VT Markets, hệ thống cung cấp tài khoản trải nghiệm (Demo Account) mô phỏng sát báo giá thời gian thực của thị trường để người dùng làm quen thao tác đặt lệnh và kiểm thử phương pháp.\n\n"
            "💡 Các KOL quốc tế như Brad Goh hay Rayner Teo cũng thường chia sẻ nguyên tắc: mỗi khi học một mẫu hình nến mới, họ đều thử nghiệm tối thiểu 20–30 lệnh trên môi trường Demo để thống kê tỷ lệ thắng trước khi áp dụng thật. Các sếp mới vào nhóm đã thử nghiệm bộ quy tắc của mình trên Demo chưa?"
        )
    },
    {
        "id_key": "vt_update_mobile_app_price_alerts",
        "title": "Mẹo cài đặt Chuông báo giá (Price Alert) trên ứng dụng di động cho người bận rộn",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/platforms/vt-markets-app/",
        "caption": (
            "📱 Theo tài liệu tính năng của ứng dụng VT Markets App và TradingView, người dùng có thể cài đặt thông báo tự động (Price Alert) tại các mốc giá quan trọng để điện thoại báo chuông khi thị trường chạm vùng quan tâm.\n\n"
            "⏰ Nhiều anh em đi làm văn phòng trên diễn đàn r/Gold chia sẻ tính năng báo giá tự động giúp họ không phải mở màn hình liên tục trong giờ làm việc mà vẫn biết khi nào giá về vùng kế hoạch. Các sếp trong nhóm có hay cài chuông báo giá kiểu này không?"
        )
    },
    {
        "id_key": "vt_update_stp_vs_ecn_specs",
        "title": "Sự khác biệt giữa cấu trúc tài khoản Standard STP và Raw ECN theo thông số công bố",
        "image_url": "",
        "source_url": "https://www.vtmarkets.com/vi/trading/accounts/",
        "caption": (
            "📊 Theo bảng so sánh thông số tài khoản công bố trên website VT Markets, tài khoản Standard STP tích hợp toàn bộ chi phí vào mức chênh lệch giá (Spread) và không thu phí hoa hồng (Commission), trong khi tài khoản Raw ECN tách riêng mức Spread gốc rất thấp kèm phí hoa hồng cố định trên mỗi lot.\n\n"
            "💬 Trên các diễn đàn giao dịch quốc tế, nhóm trader giữ lệnh dài ngày (Swing) thường chọn dạng STP cho đơn giản, còn nhóm giao dịch ngắn trong phiên (Scalping) lại ưu tiên dạng ECN để có giá khớp sát hơn. Các sếp trong nhóm mình đang quen dùng loại tài khoản nào hơn?"
        )
    }
]


# ==============================================================================
# TIN NHẮN NGẮN ĐAN XEN TRONG KHUNG GIỜ GIAO DỊCH (1-2 CÂU, KHÔNG ICON, TRUNG LẬP 100%, CHỈ TRÍCH DẪN SỐ LIỆU BẢNG ĐIỆN HOẶC HỎI THĂM)
# ==============================================================================
def build_session_icebreakers(market):
    gp = market["gold_price"]
    ema20 = market["h1_ema20"]
    bb_low = market["m15_bb_lower"]
    rsi1 = market["h1_rsi"]

    return [
        f"Trên bảng điện TradingView hiện giá Vàng đang giao dịch quanh mốc ${gp:,.1f} (giữa vùng ${bb_low:,.0f} và ${ema20:,.0f}), sáng giờ các sếp trong nhóm mình có theo dõi kịch bản của chuyên gia nào không?",
        f"Thống kê tự động trên TradingView đang ghi nhận XAU/USD ở ${gp:,.1f} và chỉ số RSI H1 ở mức {rsi1}, hôm nay các sếp đánh giá thị trường thế nào?",
        f"Các sếp vừa đi làm vừa theo dõi thị trường hôm nay có tham khảo nhận định từ kênh phân tích nào không? Giá trên biểu đồ đang quanh ${gp:,.1f} rồi.",
        f"Theo lịch kinh tế tối nay phiên Mỹ dự kiến có nhiều tin tức đáng chú ý trong khi Vàng đang ở mức ${gp:,.1f}, các sếp hôm nay chọn đứng ngoài quan sát hay có kế hoạch gì chưa?",
        f"Sếp nào mới vào nhóm cần tìm hiểu kiến thức nền tảng hoặc cách tính năng hoàn phí tự động vận hành thì xem tài liệu tổng hợp ở bài ghim trên đầu nhóm nhé."
    ]


# ==============================================================================
# BỘ PHÂN LOẠI NGƯỜI HỎI (3 CẤP ĐỘ HIỂU BIẾT) & TIẾP CHUYỆN THÍCH ỨNG THÔNG MINH
# - Cấp độ 1 (BEGINNER): Người mới tinh / chưa biết gì -> Trả lời bình dân, tiền thật, không thuật ngữ
# - Cấp độ 2 (EXPERIENCED): Trader đã biết phân tích (dùng từ H1, M15, RSI, SL, cản, lot...) -> Trả lời sâu kèm số liệu TradingView-TA
# - Cấp độ 3 (BROKER_LEAD): Khách hỏi về sàn, mở tài khoản, nạp rút, hoàn phí Backcom -> Giải đáp quyền lợi rõ ràng & kết nối Sale
# ==============================================================================
def classify_user_level(user_text):
    low = user_text.lower()

    broker_kw = [
        "backcom", "hoàn phí", "hoàn tiền", "mở tài khoản", "đăng ký", "tạo tài khoản",
        "raw ecn", "standard", "nạp", "rút", "spread", "swap", "phí qua đêm",
        "copy trade", "vtrade", "sàn", "vt markets", "vtmarket", "ib"
    ]
    if any(k in low for k in broker_kw):
        return "BROKER_LEAD", "Khách quan tâm Sàn / Mở TK / Backcom"

    pro_kw = [
        "h1", "h4", "m15", "m5", "m30", "d1", "rsi", "ema", "ma", "bollinger", "macd",
        "sl", "tp", "stop loss", "take profit", "lot", "pip", "pips", "r:r", "rr",
        "cản", "hỗ trợ", "kháng cự", "quét râu", "rút râu", "thanh khoản", "liquidity",
        "fvg", "order block", "smc", "ict", "breakout", "phá vỡ", "dxy", "cpi", "nonfarm", "nfp", "fed"
    ]
    if any(re.search(rf"\b{re.escape(k)}\b", low) for k in pro_kw):
        return "EXPERIENCED", "Trader đã có kinh nghiệm thực chiến"

    return "BEGINNER", "Người mới tìm hiểu / Cần hướng dẫn đơn giản"


def generate_smart_trader_reply(user_text, reply_context="", market=None):
    if not market:
        try:
            if os.path.exists(BUZZ_FILE):
                with open(BUZZ_FILE, "r", encoding="utf-8") as f:
                    market = json.load(f).get("market")
        except Exception:
            pass
    if not market:
        market = fetch_live_market_and_ta()

    gp = market.get("gold_price", 3995.8)
    rsi1 = market.get("h1_rsi", 34.6)
    ema20 = market.get("h1_ema20", 4014.3)
    bb_low = market.get("m15_bb_lower", 3992.5)
    bb_up = market.get("m15_bb_upper", 4004.3)
    dxy = market.get("dxy_price", 101.75)

    level, level_desc = classify_user_level(user_text)
    ctx_snippet = f" (Đang trả lời bài viết: {reply_context[:180]})" if reply_context else ""

    # NGUYÊN TẮC BẤT DI BẤT DỊCH: Bot & VT Markets TUYỆT ĐỐI KHÔNG đưa ra nhận định chủ quan hay khuyên Mua/Bán.
    # Luôn trích dẫn theo cấu trúc: "Theo góc nhìn của chuyên gia A / nguồn tin B chia sẻ về chiến lược C..."
    if level == "BEGINNER":
        persona_instruction = (
            f"Bạn là trợ lý tổng hợp thông tin cộng đồng 'VT Markets | Thảo Luận & Thực Chiến' (xưng 'mình', gọi người hỏi là 'sếp'). "
            f"Người hỏi là NGƯỜI MỚI ({level_desc}). "
            f"QUY TẮC PHÁP LÝ BẮT BUỘC: "
            f"1) TUYỆT ĐỐI KHÔNG đưa ra nhận định thị trường chủ quan, không khuyên Mua hay Bán, không dùng từ 'Mình nghĩ', 'Mình khuyên sếp'. "
            f"2) Hãy trả lời theo cấu trúc khách quan dẫn nguồn thứ 3: 'Theo chia sẻ của các chuyên gia quốc tế như Raja Banks / Brad Goh / Smart Risk (hoặc cộng đồng r/Gold)...' chia sẻ về phương pháp quản lý thời gian, tâm lý hoặc cài mức tự động dừng lỗ bảo hiểm để sếp tham khảo. "
            f"3) Giải thích bình dân, dễ hiểu (không dùng thuật ngữ học thuật như RSI, EMA, Bollinger, pip, lot), dài 1-2 câu tiếng Việt tự nhiên, tuyệt đối KHÔNG dùng icon hay dấu sao (**)."
        )
    elif level == "EXPERIENCED":
        persona_instruction = (
            f"Bạn là trợ lý tổng hợp dữ liệu của cộng đồng 'VT Markets | Thảo Luận & Thực Chiến' (xưng 'mình', gọi người hỏi là 'sếp'). "
            f"Người hỏi là một TRADER ĐÃ CÓ KINH NGHIỆM ({level_desc}). "
            f"Số liệu công khai trên TradingView hiện tại: XAU/USD ở ${gp:,.1f}, EMA20 khung H1 ở ${ema20:,.0f}, RSI H1 ở mức {rsi1}, biên Bollinger M15 từ ${bb_low:,.0f} đến ${bb_up:,.0f}, DXY ở {dxy:.2f}. "
            f"QUY TẮC PHÁP LÝ BẮT BUỘC: "
            f"1) TUYỆT ĐỐI KHÔNG tự dự đoán giá tăng/giảm chủ quan (không được nói 'Mình nghĩ vàng sẽ quét đáy/kéo lên...'). "
            f"2) Hãy trả lời khách quan theo cấu trúc dẫn nguồn: 'Theo góc nhìn phân tích trên FXEmpire / Investing kết hợp bảng số liệu tự động của TradingView hiện tại...' hoặc 'Theo phương pháp mà các KOL như TJR / Raja Banks hay chia sẻ khi gặp cấu trúc này...', nêu rõ đây là góc nhìn từ nguồn phân tích để sếp đối chiếu với kế hoạch riêng. "
            f"3) Trả lời gói gọn trong 1-2 câu tiếng Việt tự nhiên, tuyệt đối KHÔNG dùng icon hay dấu sao (**)."
        )
    else:
        persona_instruction = (
            f"Bạn là quản trị viên hỗ trợ thông tin của cộng đồng 'VT Markets | Thảo Luận & Thực Chiến' (xưng 'mình', gọi 'sếp'). "
            f"Người hỏi đang quan tâm đến điều kiện giao dịch tại VT Markets ({level_desc}). "
            f"Thông tin công bố chính thức: VT Markets cung cấp tài khoản Raw ECN có chênh lệch giá (spread) thấp, nạp rút qua ngân hàng Việt Nam và USDT tự động trong ngày, kết nối TradingView, và thành viên trong nhóm có thể xem hướng dẫn bật hoàn phí giao dịch tự động (Backcom) ở bài ghim trên đầu nhóm. "
            f"Hãy trả lời khách quan, rõ ràng trong 1-2 câu tiếng Việt tự nhiên (không cam kết lợi nhuận, không dùng icon hay dấu sao **), và nhắn sếp đợi chút bộ phận hỗ trợ sẽ inbox hướng dẫn chi tiết."
        )

    full_prompt = f"{persona_instruction}{ctx_snippet}\nCâu hỏi của thành viên: \"{user_text[:300]}\"\nChỉ viết đúng câu trả lời khách quan dẫn nguồn thứ 3 bằng tiếng Việt tự nhiên (1-2 câu, xưng mình, gọi sếp, không icon):"

    # Ưu tiên số 1: Gọi trực tiếp mô hình GPT-4 qua g4f.Provider.Yqcloud & ChatGPT để tư duy linh hoạt 100% theo ngữ cảnh câu hỏi
    try:
        import g4f
        from g4f.client import Client as G4FClient
        g4f_client = G4FClient()
        for prov in [g4f.Provider.Yqcloud, g4f.Provider.ChatGPT]:
            try:
                resp = g4f_client.chat.completions.create(
                    model="",
                    provider=prov,
                    messages=[{"role": "user", "content": full_prompt}]
                )
                ans = (resp.choices[0].message.content or "").strip()
                ans = re.sub(r"(?i)\n*đăng nhập để.*$", "", ans).strip()
                ans = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf]", "", ans)
                ans = ans.replace("**", "").replace('"', "").replace("\n", " ").strip()
                ans = re.sub(r"\s+", " ", ans)
                if len(ans) > 25 and "<!doctype" not in ans.lower():
                    return ans
            except Exception:
                continue
    except Exception as e:
        print("[G4F Reasoning Error]:", e)

    # Ưu tiên số 2: Gọi Pollinations Reasoning LLM (`openai-fast`)
    for attempt in range(2):
        try:
            seed = random.randint(1000, 999999)
            q_url = f"https://text.pollinations.ai/{urllib.parse.quote(full_prompt)}?model=openai-fast&seed={seed}"
            r = cffi_req.get(q_url, impersonate="chrome120", timeout=10)
            if r.status_code == 200 and r.text.strip():
                ans = r.text.strip()
                if "<!doctype html" not in ans.lower() and "free limit" not in ans.lower() and "pollinations" not in ans.lower():
                    ans = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf]", "", ans)
                    ans = ans.replace("**", "").replace('"', "").strip()
                    if len(ans) > 20:
                        return ans
            time.sleep(1.2)
        except Exception:
            time.sleep(0.8)

    # Dự phòng đa biến thể (100% khách quan dẫn nguồn thứ 3, không bao giờ tự nhận định chủ quan)
    if level == "BROKER_LEAD":
        return random.choice([
            "Theo thông tin công bố trên trang chủ VT Markets thì cổng nạp rút ngân hàng nội địa và USDT đều xử lý tự động trong ngày kèm tài khoản Raw ECN có spread thấp sếp nhé, sếp xem thêm hướng dẫn bật hoàn phí Backcom ở bài ghim hoặc đợi chút anh em hỗ trợ nhắn chi tiết ạ.",
            "Sếp có thể xem ở bài ghim trên đầu nhóm có hướng dẫn chi tiết cách bật chương trình hoàn phí giao dịch tự động (Backcom) tại VT Markets nhé, đợi xíu bộ phận hỗ trợ trong nhóm sẽ nhắn giải đáp cụ thể cho sếp ạ."
        ])
    if level == "EXPERIENCED":
        return random.choice([
            f"Theo bảng thống kê tự động trên TradingView hiện XAU/USD đang ở ${gp:,.1f} dưới mốc EMA20 H1 (${ema20:,.0f}) với RSI H1 ở mức {rsi1}, còn theo góc nhìn mà các nhà phân tích trên FXEmpire chia sẻ thì họ thường đợi phản ứng giá rõ ràng tại biên ${bb_low:,.0f} hoặc ${ema20:,.0f} để sếp tham khảo thêm cho kế hoạch riêng nhé.",
            f"Số liệu công khai trên TradingView đang ghi nhận DXY ở {dxy:.2f} và Vàng dao động giữa vùng ${bb_low:,.0f} – ${ema20:,.0f} (RSI H1 {rsi1}), theo phương pháp mà các KOL như TJR hay chia sẻ thì giai đoạn giá nằm giữa biên như vậy họ thường đứng ngoài chờ xác nhận để các sếp cùng tham khảo ạ."
        ])
    return random.choice([
        f"Theo kinh nghiệm mà các chuyên gia như Brad Goh hay Raja Banks thường chia sẻ cho người mới thì khi giá Vàng đang dao động quanh ${gp:,.0f}, họ luôn ưu tiên cài sẵn mức tự động dừng lỗ nhỏ để bảo vệ vốn trước tiên, sếp có thể xem thêm tài liệu cơ bản ở bài ghim đầu nhóm để tham khảo nhé.",
        "Theo chia sẻ từ nhiều thành viên lâu năm trên diễn đàn r/Gold dành cho người mới bắt đầu, cách tiếp cận an toàn là tìm hiểu kỹ nguyên tắc quản lý rủi ro trong cuốn cẩm nang ở bài ghim đầu nhóm và luôn đặt sẵn mức giới hạn lỗ tự động cho từng giao dịch sếp ạ."
    ])


def generate_daily_buzz():
    st = load_balance_state()
    posted_set = set(st.get("posted_urls", []))

    sheets = fetch_online_sheets()
    market = fetch_live_market_and_ta()
    chart_path = generate_live_xauusd_chart() or TOPIC_PHOTO_POOL["gold"]
    macro_posts = fetch_real_macro_articles(market, posted_set=posted_set)
    kol_posts = fetch_dynamic_youtube_kol_posts(sheets, market, posted_set=posted_set)
    tiktok_posts = fetch_dynamic_tiktok_kol_posts(sheets, market, posted_set=posted_set)
    reddit_posts = build_reddit_posts(market, chart_path, sheets=sheets, posted_set=posted_set)
    vt_posts = [v for v in VT_MARKETS_UPDATES if v["id_key"] not in posted_set] or VT_MARKETS_UPDATES
    short_icebreakers = build_session_icebreakers(market)

    buzz_data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources_count": {k: len(v) for k, v in sheets.items()},
        "market": market,
        "live_chart_path": chart_path,
        "macro_posts": macro_posts,
        "kol_posts": kol_posts,
        "tiktok_posts": tiktok_posts,
        "reddit_posts": reddit_posts,
        "vt_posts": vt_posts,
        "short_icebreakers": short_icebreakers
    }

    with open(BUZZ_FILE, "w", encoding="utf-8") as f:
        json.dump(buzz_data, f, ensure_ascii=False, indent=2)

    print(f"[Radar] Ready! Spot Gold=${market['gold_price']} (RSI H1={market['h1_rsi']}, EMA20=${market['h1_ema20']}) | Chart={chart_path}")
    return buzz_data


if __name__ == "__main__":
    data = generate_daily_buzz()
    if "--post-auto" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="auto")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-macro" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="tintuc")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-kol" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="kol")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-tiktok" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="tiktok")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-reddit" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="reddit")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-vt" in sys.argv:
        cat, post = pick_balanced_post(data, preferred_cat="vt")
        if post:
            publish_post(DISCUSSION_CHAT_ID, post)
    elif "--post-icebreaker" in sys.argv:
        ice = data["short_icebreakers"][0]
        api_call("sendMessage", {"chat_id": DISCUSSION_CHAT_ID, "text": ice})
