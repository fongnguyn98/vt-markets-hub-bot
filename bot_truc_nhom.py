import urllib.request
import urllib.parse
import json
import time
import os
import re
import sys
import random
from datetime import datetime
import news_and_kol_radar
import content_engine

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


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
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

OWNER_ID = 8598343729
DISCUSSION_CHAT_ID = -1004375233328   # VT Markets | Thảo Luận & Thực Chiến
INTERNAL_CHAT_ID = -1003750255534     # [NỘI BỘ] Báo Khách & Sale
CHANNEL_CHAT_ID = -1003971455443      # VT Rewards HUB (@vtrewardshub)

WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.json")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")
BUZZ_FILE = os.path.join(BASE_DIR, "daily_buzz_pool.json")
LOG_FILE = os.path.join(BASE_DIR, "bot_runtime.log")
PID_FILE = os.path.join(BASE_DIR, "bot.pid")

os.makedirs(BASE_DIR, exist_ok=True)


def log_info(msg_str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg_str}"
    print(line, flush=True)


# 1B: Tin nhắn ngắn đan xen trong phiên (1-2 câu tự nhiên, tuyệt đối không icon, trung lập 100%, không nhận định chủ quan)
SESSION_ICEBREAKERS = {
    "morning": [
        "Sáng giờ phiên Á các sếp đã theo dõi bài phân tích của chuyên gia nào chưa hay vẫn đang đợi vào phiên Âu?",
        "Mấy nay các sếp giao dịch kết quả ổn chứ, sáng nay các sếp đang quan sát mốc giá nào trên biểu đồ XAU/USD thế?",
        "Hôm nay trên các kênh phân tích quốc tế có nhiều góc nhìn trái chiều về Vàng, các sếp trong nhóm mình nghiêng về kịch bản nào hơn?"
    ],
    "afternoon": [
        "Bắt đầu bước vào khung giờ phiên Âu rồi các sếp, chiều nay có sếp nào đang theo dõi biểu đồ Vàng không?",
        "Theo chia sẻ của nhiều trader trên diễn đàn r/Gold thì giờ giao phiên chiều họ thường ưu tiên kiểm tra kỹ mức dừng lỗ, chiều nay các sếp có kế hoạch gì chưa?",
        "Chiều nay thị trường bắt đầu có thanh khoản hơn rồi, các sếp đánh giá các mốc kỹ thuật trên TradingView hôm nay thế nào?"
    ],
    "evening": [
        "Chuẩn bị bước vào khung giờ phiên Mỹ theo lịch kinh tế, tối nay các sếp đang theo dõi vùng giá nào của XAU/USD thế?",
        "Tối nay phiên Mỹ có nhiều tin tức đáng chú ý, các sếp chọn đứng ngoài quan sát hay đã hoàn thành mục tiêu trong ngày rồi?",
        "Sếp nào mới vào nhóm cần xem tài liệu cơ bản hoặc cách bật chương trình hoàn phí tự động Backcom thì xem ở bài ghim trên đầu nhóm nhé."
    ]
}

QUIET_THRESHOLD_SECONDS = 5 * 3600  # 5 giờ nhóm im ắng mới thả câu hỏi gợi chuyện


def load_whitelist():
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "user_ids": set(data.get("user_ids", [OWNER_ID])),
                    "usernames": set(u.lower().lstrip("@") for u in data.get("usernames", ["fonguyn"]))
                }
        except Exception:
            pass
    return {"user_ids": {OWNER_ID}, "usernames": {"fonguyn"}}


def save_whitelist(wl):
    with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "user_ids": sorted(list(wl["user_ids"])),
            "usernames": sorted(list(wl["usernames"]))
        }, f, ensure_ascii=False, indent=2)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "offset": 0,
        "last_group_activity": time.time(),
        "last_icebreaker_time": 0,
        "last_icebreaker_slot": ""
    }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def api_call(method, payload=None):
    url = f"{BASE_URL}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[API Error] {method}: {e.code} {err_body}")
        return {"ok": False, "error": err_body}
    except Exception as e:
        print(f"[Network Error] {method}: {e}")
        return {"ok": False, "error": str(e)}


ADMIN_CACHE = {"ids": {OWNER_ID}, "updated_at": 0}


def get_discussion_admins():
    now = time.time()
    if now - ADMIN_CACHE["updated_at"] > 300:
        res = api_call("getChatAdministrators", {"chat_id": DISCUSSION_CHAT_ID})
        if res.get("ok"):
            ids = {OWNER_ID}
            for member in res.get("result", []):
                u = member.get("user", {})
                if u.get("id"):
                    ids.add(u["id"])
            ADMIN_CACHE["ids"] = ids
            ADMIN_CACHE["updated_at"] = now
    return ADMIN_CACHE["ids"]


def is_exempt_user(msg, wl):
    sender_chat = msg.get("sender_chat", {})
    if sender_chat.get("id") in (CHANNEL_CHAT_ID, DISCUSSION_CHAT_ID):
        return True
    if msg.get("is_automatic_forward"):
        return True

    user = msg.get("from", {})
    uid = user.get("id")
    uname = (user.get("username") or "").lower().lstrip("@")

    if not uid:
        return False
    if uid in wl["user_ids"] or (uname and uname in wl["usernames"]):
        return True
    if uid in get_discussion_admins():
        return True
    return False


ALLOWED_DOMAINS = (
    "vtmarkets.com",
    "t.me/vtrewardshub",
    "1dxcfv2spjkebxu27qfb079qs8mdtyqlw",
)

ALLOWED_MENTIONS = {
    "@vtmarkets8386_bot",
    "@vtrewardshub",
    "@fonguyn",
}

COMPETITOR_AND_SCAM_PATTERNS = [
    r"\bexness\b",
    r"\bic\s*markets?\b",
    r"\btickmill\b",
    r"\bvantage\b",
    r"\blitefinance\b",
    r"\bmitrade\b",
    r"\bxm\.com\b",
    r"\bsàn\s+xm\b",
    r"\bsàn\s+fbs\b",
    r"\bxtb\b",
    r"\bfxpro\b",
    r"\bpepperstone\b",
    r"\boctafx\b",
    r"kéo\s+tài\s+khoản",
    r"ủy\s+thác",
    r"cam\s+kết\s+lợi\s+nhuận",
    r"cam\s+kết\s+lãi",
    r"bán\s+bot",
    r"ib\s+mình\s+kéo",
    r"nhóm\s+vip",
    r"nhóm\s+tín\s+hiệu",
    r"cứu\s+cháy",
]


def detect_violation(msg):
    if any(k in msg for k in ("forward_origin", "forward_from", "forward_from_chat", "forward_sender_name")):
        fwd_chat = msg.get("forward_from_chat", {})
        fwd_origin = msg.get("forward_origin", {})
        origin_chat_id = fwd_chat.get("id") or fwd_origin.get("chat", {}).get("id") or fwd_origin.get("sender_chat", {}).get("id")
        if origin_chat_id not in (CHANNEL_CHAT_ID, DISCUSSION_CHAT_ID):
            return True, "Chuyển tiếp (Forward) tin nhắn từ kênh/nhóm ngoài"

    text = (msg.get("text") or msg.get("caption") or "").strip()
    lower_text = text.lower()

    entities = (msg.get("entities") or []) + (msg.get("caption_entities") or [])
    for ent in entities:
        etype = ent.get("type")
        if etype == "text_link":
            url = (ent.get("url") or "").lower()
            if not any(allow in url for allow in ALLOWED_DOMAINS):
                return True, f"Chèn link ẩn lạ ({url})"
        elif etype == "url":
            offset = ent.get("offset", 0)
            length = ent.get("length", 0)
            extracted = text[offset:offset + length].lower()
            if not any(allow in extracted for allow in ALLOWED_DOMAINS):
                return True, f"Gửi đường link lạ ({extracted})"
        elif etype == "mention":
            offset = ent.get("offset", 0)
            length = ent.get("length", 0)
            mention = text[offset:offset + length].lower()
            if mention not in ALLOWED_MENTIONS:
                return True, f"Tag tài khoản/kênh lạ ({mention})"

    url_matches = re.findall(r"(?:https?://|www\.|t\.me/|zalo\.me/|[a-z0-9\-]+\.(?:com|net|org|vn|io|me|gg|xyz))\S*", lower_text)
    for m in url_matches:
        if not any(allow in m for allow in ALLOWED_DOMAINS):
            return True, f"Gửi link không nằm trong danh sách cho phép ({m})"

    for pat in COMPETITOR_AND_SCAM_PATTERNS:
        m = re.search(pat, lower_text)
        if m:
            return True, f"Từ khóa Seeding / Sàn đối thủ ('{m.group(0)}')"

    return False, ""


HOT_LEAD_KEYWORDS = [
    "backcom", "hoàn phí", "hoàn tiền", "mở tài khoản", "tài khoản",
    "nạp", "rút", "vt markets", "vtmarket", "vt", "sàn", "copy trade",
    "vtrade", "ib", "tư vấn", "hỗ trợ", "tài liệu", "ebook", "spread",
    "raw ecn", "standard", "mt4", "mt5", "đòn bẩy", "lot", "cháy"
]


def format_user_html(user):
    uid = user.get("id", "")
    first = user.get("first_name") or ""
    last = user.get("last_name") or ""
    full_name = f"{first} {last}".strip() or "Thành viên"
    full_name_esc = (
        full_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    uname = user.get("username")
    if uname:
        return f'<a href="tg://user?id={uid}">{full_name_esc}</a> (@{uname} | ID: <code>{uid}</code>)'
    return f'<a href="tg://user?id={uid}">{full_name_esc}</a> (ID: <code>{uid}</code>)'


def handle_violation(msg, reason):
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    user = msg.get("from", {})
    uid = user.get("id")
    uname = user.get("username") or ""
    text = (msg.get("text") or msg.get("caption") or "[Đính kèm Media/Forward]").strip()
    text_esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 1. Silent delete in Discussion Group
    api_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    # 2. Mute user immediately (Phương án A)
    if uid:
        api_call("restrictChatMember", {
            "chat_id": chat_id,
            "user_id": uid,
            "permissions": {
                "can_send_messages": False,
                "can_send_audios": False,
                "can_send_documents": False,
                "can_send_photos": False,
                "can_send_videos": False,
                "can_send_video_notes": False,
                "can_send_voice_notes": False,
                "can_send_polls": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False
            }
        })

    # 3. Alert Internal Group
    alert_text = (
        f"🛡️ <b>ĐÃ CHẶN SEEDING / XÓA RÁC &amp; KHÓA CHAT</b>\n\n"
        f"👤 <b>Đối tượng:</b> {format_user_html(user)}\n"
        f"⚠️ <b>Lý do:</b> {reason}\n"
        f"🗑 <b>Nội dung đã xóa âm thầm:</b>\n<code>{text_esc[:500]}</code>\n\n"
        f"<i>(Nhóm thảo luận vẫn sạch tuyệt đối. Nếu đây là khách thật vô tình gửi nhầm, bấm nút bên dưới để mở khóa chat).</i>"
    )
    buttons = []
    if uid:
        buttons.append([
            {"text": "🔓 Mở khóa chat cho khách này", "callback_data": f"unmute:{uid}"},
            {"text": "➕ Thêm vào Quân mình", "callback_data": f"wl_add:{uid}:{uname}"}
        ])
    api_call("sendMessage", {
        "chat_id": INTERNAL_CHAT_ID,
        "text": alert_text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons} if buttons else {}
    })


def welcome_new_members(members):
    """Chào thành viên mới ngay trong nhóm (1 tin duy nhất kể cả khi nhiều người vào cùng lúc)."""
    if not members:
        return
    names = ", ".join(format_user_html(m) for m in members[:5])
    text = (
        f"Chào mừng {names} đã vào nhóm VT Markets | Thảo Luận & Thực Chiến.\n\n"
        "Nhóm mình chia sẻ kiến thức, tin tức và kinh nghiệm giao dịch để anh em cùng tham khảo, "
        "tài liệu cơ bản có ở bài ghim đầu nhóm. Các sếp đang theo dõi sản phẩm nào, Vàng, Dầu hay ngoại tệ, "
        "và mới bắt đầu hay đã giao dịch một thời gian? Giới thiệu nhanh một câu để anh em làm quen nhé.\n\n"
        "Lưu ý: mọi nội dung trong nhóm chỉ mang tính tham khảo, không phải lời khuyên đầu tư."
    )
    api_call("sendMessage", {"chat_id": DISCUSSION_CHAT_ID, "text": text, "parse_mode": "HTML"})


def handle_new_members(msg, wl):
    welcome_new_members([m for m in msg.get("new_chat_members", []) if not m.get("is_bot") and m.get("id") not in wl["user_ids"]])
    for m in msg.get("new_chat_members", []):
        if m.get("is_bot"):
            continue
        uid = m.get("id")
        if uid in wl["user_ids"]:
            continue
        uname = m.get("username")
        alert_text = (
            f"👋 <b>THÀNH VIÊN MỚI VÀO NHÓM THẢO LUẬN</b>\n\n"
            f"👤 <b>Khách hàng:</b> {format_user_html(m)}\n"
            f"📍 <b>Nhóm:</b> VT Markets | Thảo Luận &amp; Thực Chiến\n\n"
            f"💡 <i>Đội Sale có thể bấm vào tên khách để chủ động chào hỏi và gửi tặng Ebook / tư vấn Backcom 100%!</i>"
        )
        kb = []
        if uname:
            kb.append([{"text": "💬 Nhắn tin riêng cho khách", "url": f"https://t.me/{uname}"}])
        api_call("sendMessage", {
            "chat_id": INTERNAL_CHAT_ID,
            "text": alert_text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": kb} if kb else {}
        })


def handle_member_message_lead(msg):
    user = msg.get("from", {})
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        return

    lower_text = text.lower()
    level_code, level_label = news_and_kol_radar.classify_user_level(text)
    is_hot = (level_code == "BROKER_LEAD") or any(k in lower_text for k in HOT_LEAD_KEYWORDS) or ("?" in text)
    header = (
        "🔥 <b>PHÁT HIỆN KHÁCH HỎI / CẦN TƯ VẤN TRONG NHÓM</b>"
        if is_hot else
        "💬 <b>KHÁCH HÀNG TƯƠNG TÁC TRONG NHÓM THẢO LUẬN</b>"
    )

    text_esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    msg_id = msg["message_id"]
    msg_link = f"https://t.me/c/4375233328/{msg_id}"
    uname = user.get("username")

    alert_text = (
        f"{header}\n\n"
        f"👤 <b>Khách hàng:</b> {format_user_html(user)}\n"
        f"🎯 <b>Phân loại trình độ/nhu cầu:</b> <code>{level_label}</code>\n"
        f"📝 <b>Nội dung vừa nhắn:</b>\n<blockquote>{text_esc[:600]}</blockquote>\n\n"
        f"👉 <i>Sale vào nhóm trả lời trực tiếp hoặc nhắn riêng chăm sóc đúng tâm lý khách ngay nhé!</i>"
    )

    row = [{"text": "👉 Nhảy tới tin nhắn trong nhóm", "url": msg_link}]
    if uname:
        row.append({"text": "💬 Nhắn riêng", "url": f"https://t.me/{uname}"})

    api_call("sendMessage", {
        "chat_id": INTERNAL_CHAT_ID,
        "text": alert_text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [row]}
    })


def sync_git_state():
    """Commit + push state an toàn: autostash (state bị ghi liên tục nên working tree luôn 'bẩn'), retry khi push bị từ chối."""
    try:
        import subprocess
        git_dir = os.path.join(BASE_DIR, ".git")
        if not os.path.exists(git_dir):
            return
        kw = {"cwd": BASE_DIR, "capture_output": True, "text": True}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW

        def git(*args, timeout=30):
            return subprocess.run(["git", *args], timeout=timeout, **kw)

        git("config", "user.name", "VT-Markets-Bot-Cloud", timeout=8)
        git("config", "user.email", "bot@vtmarketshub.local", timeout=8)
        git("add", "bot_state.json", "content_balance_state.json", "daily_buzz_pool.json", "whitelist.json", timeout=15)
        if git("diff", "--staged", "--quiet", timeout=8).returncode == 0:
            return
        git("commit", "-m", "chore: auto-sync posted history [skip ci]", timeout=15)
        for attempt in range(3):
            git("pull", "--rebase", "--autostash", "origin", "main", timeout=60)
            res = git("push", "origin", "main", timeout=60)
            if res.returncode == 0:
                return
            time.sleep(2 + attempt * 3)
        log_info(f"[Git Sync Warning]: push failed: {(res.stderr or '')[:200]}")
    except Exception as e:
        log_info(f"[Git Sync Warning]: {e}")

def load_or_refresh_buzz(force_refresh=False):
    now = time.time()
    if not force_refresh and os.path.exists(BUZZ_FILE):
        try:
            mtime = os.path.getmtime(BUZZ_FILE)
            if now - mtime < 900:  # Refresh every 15 minutes max
                with open(BUZZ_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
    try:
        return news_and_kol_radar.generate_daily_buzz()
    except Exception as e:
        print("[Buzz Refresh Error]:", e)
        if os.path.exists(BUZZ_FILE):
            with open(BUZZ_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}


_SLOT_FAIL_AT = {}
SLOT_RETRY_COOLDOWN = 600  # ??ng l?i -> ??i 10 ph?t m?i th? l?i (tr?nh qu?t l?i to?n b? ngu?n li?n t?c v? ??t h?t b?i trong kho)


def _slot_cooling(slot_id):
    return time.time() - _SLOT_FAIL_AT.get(slot_id, 0) < SLOT_RETRY_COOLDOWN


# Lịch đăng (phút trong ngày). Tối đa ~5 bài/ngày: 3 bài chất lượng + 2 bài ngắn/tương tác. Cuối tuần chỉ 1 bài/ngày.
# (tag, bắt đầu, kết thúc [cửa sổ bù], loại nội dung, các thứ trong tuần: 0=T2 ... 6=CN)
WEEKDAYS = {0, 1, 2, 3, 4}
SCHEDULE = [
    ("morning_slot", 510, 690, "news", WEEKDAYS),          # 08:30 tin vĩ mô thật (<=24h) kèm câu hỏi
    ("short_1015", 615, 695, "poll", WEEKDAYS),            # 10:15 khảo sát nhanh
    ("afternoon_kol", 870, 950, "kol_insight", WEEKDAYS),  # 14:30 tóm tắt video KOL từ phụ đề thật
    ("short_1600", 960, 1125, "scenario", WEEKDAYS),       # 16:00 câu hỏi tình huống
    ("evening_us", 1155, 1235, "discussion", WEEKDAYS),    # 19:15 xoay vòng Reddit / giải thích thuật ngữ / VT Markets
    ("weekend_recap", 540, 810, "recap", {5}),             # T7 09:00-13:30 tổng kết tuần
    ("sat_kol", 870, 1020, "kol_insight", {5}),            # T7 14:30-17:00 video KOL mới
    ("sat_scenario", 1170, 1290, "scenario", {5}),         # T7 19:30-21:30 tình huống cuối tuần
    ("sun_glossary", 570, 750, "glossary", {6}),           # CN 09:30-12:30 giải thích thuật ngữ
    ("sun_kol", 900, 1050, "kol_insight", {6}),            # CN 15:00-17:30 video KOL mới
    ("weekend_ahead", 1140, 1290, "weekahead", {6}),       # CN 19:00-21:30 khảo sát đầu tuần
]


def run_live_v2_showcase(state):
    """Chạy thử 1 lần duy nhất khi lên bản v2 trên GitHub Cloud: đăng ngay 1 bài Tin mới 24h + 1 Poll lên nhóm."""
    if state.get("engine_v2_2_direct_verified"):
        return False
    log_info("[Live Test v2] Triggering one-time live test post to Telegram...")
    now = time.time()
    results = []
    try:
        buzz = load_or_refresh_buzz(force_refresh=True)
        news_post = content_engine.make_post("news", buzz)
        if news_post:
            r1 = news_and_kol_radar.publish_post(DISCUSSION_CHAT_ID, news_post)
            if r1.get("ok"):
                content_engine.record(news_post.get("kind", "news"), news_post.get("id_key", "live_news"), news_post.get("title", ""))
                results.append({
                    "kind": news_post.get("kind", "news"),
                    "msg_id": r1.get("result", {}).get("message_id"),
                    "source_url": news_post.get("source_url", ""),
                    "caption": (news_post.get("caption") or "")[:500]
                })
        time.sleep(3)
        poll_post = content_engine.make_post("scenario", buzz)
        if poll_post:
            r2 = news_and_kol_radar.publish_post(DISCUSSION_CHAT_ID, poll_post)
            if r2.get("ok"):
                content_engine.record("poll", poll_post.get("id_key", "live_poll"), poll_post.get("title", ""))
                results.append({
                    "kind": poll_post.get("kind", "scenario"),
                    "msg_id": r2.get("result", {}).get("message_id"),
                    "caption": (poll_post.get("caption") or "")[:500]
                })
    except Exception as e:
        log_info(f"[Live Test v2 Error]: {e}")

    if results:
        state["engine_v2_2_direct_verified"] = True
        state["last_live_test_result"] = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "posts": results
        }
        state["last_scheduled_time"] = now
        state["last_group_activity"] = now
        save_state(state)
        sync_git_state()
        try:
            api_call("sendMessage", {
                "chat_id": INTERNAL_CHAT_ID,
                "text": (
                    "✅ <b>ĐÃ CHẠY THỬ SKILL V2 TRÊN GITHUB CLOUD LÊN NHÓM THẢO LUẬN</b>\n\n"
                    f"• Số bài vừa đăng test: <b>{len(results)} bài</b> (Tin mới 24h + Khảo sát Poll tương tác)\n"
                    "• Toàn bộ lịch tự động & chăm sóc cộng đồng đã hoạt động 100% trên GitHub Actions."
                ),
                "parse_mode": "HTML"
            })
        except Exception:
            pass
        return True
    return False


def check_scheduled_daily_posts(state):
    now = time.time()
    dt = datetime.now()
    date_str = dt.strftime("%Y-%m-%d")
    cur_mins = dt.hour * 60 + dt.minute

    executed = state.setdefault("executed_slots", [])
    if len(executed) > 60:
        state["executed_slots"] = executed[-60:]
        executed = state["executed_slots"]

    # Giãn cách tối thiểu 20 phút giữa 2 bài tự động liên tiếp
    if now - state.get("last_scheduled_time", 0) < 1200:
        return False

    for tag, w_start, w_end, kind, days in SCHEDULE:
        slot_id = f"{date_str}_{tag}"
        if dt.weekday() not in days or not (w_start <= cur_mins <= w_end):
            continue
        if slot_id in executed or _slot_cooling(slot_id):
            continue
        log_info(f"Triggering scheduled slot: {slot_id} ({kind})")
        post = None
        try:
            buzz = load_or_refresh_buzz(force_refresh=True) if kind in content_engine.NEEDS_BUZZ else None
            post = content_engine.make_post(kind, buzz, dt)
            res = news_and_kol_radar.publish_post(DISCUSSION_CHAT_ID, post) if post else {"ok": False}
        except Exception as e:
            log_info(f"[Slot {slot_id} error]: {e}")
            res = {"ok": False}
        if res.get("ok"):
            content_engine.record(post.get("kind", kind), post.get("id_key", slot_id), post.get("title", ""))
            executed.append(slot_id)
            state["last_scheduled_post"] = slot_id
            state["last_scheduled_time"] = now
            state["last_group_activity"] = now
            save_state(state)
            sync_git_state()
            log_info(f"Published {slot_id} OK (msg_id={res.get('result', {}).get('message_id')})")
            return True
        _SLOT_FAIL_AT[slot_id] = now
    return False


def send_session_icebreaker(state, force=False, mode="auto"):
    now = time.time()
    dt = datetime.now()
    hour = dt.hour

    if 8 <= hour < 14:
        slot_key = "morning"
    elif 14 <= hour < 18:
        slot_key = "afternoon"
    elif 18 <= hour <= 22:
        slot_key = "evening"
    else:
        if not force:
            return False
        slot_key = "evening"

    today_slot_id = f"{dt.strftime('%Y-%m-%d')}_{slot_key}"

    if not force:
        if (now - state.get("last_group_activity", 0)) < QUIET_THRESHOLD_SECONDS:
            return False
        if state.get("last_icebreaker_slot") == today_slot_id:
            return False

    buzz = load_or_refresh_buzz()
    kinds = {"tintuc": "news", "kol": "kol_insight", "tiktok": "scenario", "reddit": "reddit", "vt": "vt"}
    if mode in kinds:
        post = content_engine.make_post(kinds[mode], buzz)
        res = news_and_kol_radar.publish_post(DISCUSSION_CHAT_ID, post) if post else {"ok": False}
        if res.get("ok"):
            content_engine.record(post.get("kind", mode), post.get("id_key", mode), post.get("title", ""))
    elif mode == "icebreaker" or not force:
        short_pool = buzz.get("short_icebreakers", []) or SESSION_ICEBREAKERS[slot_key]
        res = api_call("sendMessage", {
            "chat_id": DISCUSSION_CHAT_ID,
            "text": random.choice(short_pool)
        })
    else:
        _, post = news_and_kol_radar.pick_balanced_post(buzz, preferred_cat="auto")
        if post:
            res = news_and_kol_radar.publish_post(DISCUSSION_CHAT_ID, post)
        else:
            short_pool = buzz.get("short_icebreakers", []) or SESSION_ICEBREAKERS[slot_key]
            res = api_call("sendMessage", {
                "chat_id": DISCUSSION_CHAT_ID,
                "text": random.choice(short_pool)
            })

    if res.get("ok"):
        state["last_group_activity"] = now
        state["last_icebreaker_time"] = now
        state["last_icebreaker_slot"] = today_slot_id
        save_state(state)
        return True
    return False


def handle_admin_command(msg, wl, state):
    text = (msg.get("text") or "").strip()
    chat_id = msg["chat"]["id"]
    if not text.startswith("/"):
        return False

    parts = text.split()
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/them" and len(parts) >= 2:
        target = parts[1].strip()
        if target.lstrip("-").isdigit():
            wl["user_ids"].add(int(target))
        else:
            wl["usernames"].add(target.lower().lstrip("@"))
        save_whitelist(wl)
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ Đã thêm <b>{target}</b> vào danh sách Quân mình (Miễn trừ xóa link &amp; không báo khách).",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/xoa" and len(parts) >= 2:
        target = parts[1].strip()
        if target.lstrip("-").isdigit():
            wl["user_ids"].discard(int(target))
        else:
            wl["usernames"].discard(target.lower().lstrip("@"))
        save_whitelist(wl)
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"🗑 Đã xóa <b>{target}</b> khỏi danh sách Quân mình.",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/danhsach":
        ulist = ", ".join(f"@{u}" for u in sorted(wl["usernames"])) or "(Trống)"
        idlist = ", ".join(str(i) for i in sorted(wl["user_ids"])) or "(Trống)"
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"📋 <b>DANH SÁCH QUÂN MÌNH (MIỄN TRỪ):</b>\n"
                f"• <b>Usernames:</b> {ulist}\n"
                f"• <b>User IDs:</b> <code>{idlist}</code>\n\n"
                f"<i>Các lệnh đăng bài tự động (Cân bằng 5 nhóm nội dung):</i>\n"
                f"<code>/them @username</code> — Thêm quân mình\n"
                f"<code>/xoa @username</code> — Xóa khỏi danh sách\n"
                f"<code>/tintuc</code> — Đăng ngay bài Giải mã Tin tức Vĩ mô + Chỉ báo TradingView-TA\n"
                f"<code>/kol</code> — Đăng ngay bài Phương pháp thực chiến từ YouTube KOL Quốc tế\n"
                f"<code>/tiktok</code> — Đăng ngay bài Mẹo thực chiến từ TikTok KOL Quốc tế\n"
                f"<code>/reddit</code> — Đăng ngay Chủ đề tranh luận Reddit kèm Biểu đồ Nến XAU/USD M15 thực tế\n"
                f"<code>/vt</code> — Đăng ngay bài Cập nhật Tính năng &amp; Điều kiện giao dịch VT Markets VN\n"
                f"<code>/goichuyen</code> — Thả ngay tin nhắn gợi chuyện ngắn theo khung giờ giao dịch"
            ),
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/goichuyen":
        send_session_icebreaker(state, force=True, mode="icebreaker")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "🔥 Đã thả tin nhắn gợi chuyện theo khung giờ giao dịch lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/tintuc":
        news_and_kol_radar.generate_daily_buzz()
        send_session_icebreaker(state, force=True, mode="tintuc")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "📰 Đã đăng bài phân tích Tin tức Vĩ mô (100% Tiếng Việt) lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/kol":
        send_session_icebreaker(state, force=True, mode="kol")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "🎯 Đã đăng bài phương pháp từ YouTube KOL Quốc tế lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/tiktok":
        send_session_icebreaker(state, force=True, mode="tiktok")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "🎬 Đã đăng bài mẹo thực chiến từ TikTok KOL Quốc tế lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/reddit":
        send_session_icebreaker(state, force=True, mode="reddit")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "💬 Đã đăng Chủ đề tranh luận từ Reddit lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    if cmd == "/vt":
        send_session_icebreaker(state, force=True, mode="vt")
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": "⚡ Đã đăng bài cập nhật Tính năng / Điều kiện giao dịch thực tế của VT Markets VN lên nhóm Thảo Luận!",
            "parse_mode": "HTML"
        })
        return True

    return False


def handle_callback(cb, wl):
    cb_id = cb["id"]
    data = cb.get("data") or ""
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")

    if data.startswith("unmute:"):
        uid = int(data.split(":")[1])
        api_call("restrictChatMember", {
            "chat_id": DISCUSSION_CHAT_ID,
            "user_id": uid,
            "permissions": {
                "can_send_messages": True,
                "can_send_audios": True,
                "can_send_documents": True,
                "can_send_photos": True,
                "can_send_videos": True,
                "can_send_video_notes": True,
                "can_send_voice_notes": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": False
            }
        })
        api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Đã mở khóa chat cho thành viên!"})
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"🔓 Đã mở lại quyền chat cho User ID <code>{uid}</code> trong nhóm Thảo Luận.",
            "parse_mode": "HTML"
        })

    elif data.startswith("wl_add:"):
        parts = data.split(":")
        uid = int(parts[1])
        uname = parts[2].lower().lstrip("@") if len(parts) > 2 else ""
        wl["user_ids"].add(uid)
        if uname:
            wl["usernames"].add(uname)
        save_whitelist(wl)
        api_call("restrictChatMember", {
            "chat_id": DISCUSSION_CHAT_ID,
            "user_id": uid,
            "permissions": {
                "can_send_messages": True,
                "can_send_audios": True,
                "can_send_documents": True,
                "can_send_photos": True,
                "can_send_videos": True,
                "can_send_video_notes": True,
                "can_send_voice_notes": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True
            }
        })
        api_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Đã thêm vào Quân mình & mở khóa chat!"})
        api_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ Đã thêm User ID <code>{uid}</code> {('(@'+uname+')') if uname else ''} vào danh sách <b>Quân mình</b> và mở khóa chat.",
            "parse_mode": "HTML"
        })


BOT_ID = 8793731768


def should_bot_reply(msg):
    if msg.get("from", {}).get("is_bot"):
        return False
    if msg.get("sender_chat"):
        return False
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text or text.startswith("/"):
        return False

    lower_text = text.lower()
    if "@vtmarkets8386_bot" in lower_text or re.search(r"\b(bot|trợ\s+lý)\b", lower_text):
        return True

    reply_to = msg.get("reply_to_message")
    if reply_to:
        r_from = reply_to.get("from", {})
        if r_from.get("id") == BOT_ID or (r_from.get("username") or "").lower() == "vtmarkets8386_bot":
            return True
    return False


def handle_smart_bot_reply(msg):
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    clean_text = re.sub(r"@vtmarkets8386_bot", "", text, flags=re.I).strip() or text

    reply_to = msg.get("reply_to_message") or {}
    reply_context = (reply_to.get("text") or reply_to.get("caption") or "").strip()

    api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    time.sleep(2.2)

    reply_text = news_and_kol_radar.generate_smart_trader_reply(clean_text, reply_context=reply_context)
    if reply_text:
        res = api_call("sendMessage", {
            "chat_id": chat_id,
            "text": reply_text,
            "reply_to_message_id": msg_id
        })
        log_info(f"Replied to user message {msg_id} (ok={res.get('ok')})")


QUESTION_HINTS = ("làm sao", "thế nào", "như nào", "là gì", "bao nhiêu", "có nên", "ai biết", "ai rành", "giúp mình", "cho hỏi", "hỏi chút")
PENDING_WAIT = 8 * 60          # đợi 8 phút xem anh em trong nhóm có trả lời không
PENDING_MAX_AGE = 4 * 3600     # quá 4 giờ thì bỏ qua (trả lời muộn là vô duyên)
DAILY_AUTO_ANSWER_LIMIT = 6
AUTO_ANSWER_MIN_GAP = 15 * 60


def looks_like_question(text):
    t = (text or "").strip()
    if len(t) < 15 or t.startswith("/") or re.search(r"https?://", t):
        return False
    low = t.lower()
    return "?" in t or any(h in low for h in QUESTION_HINTS)


def track_question(msg, state):
    """Ghi nhận câu hỏi chưa ai trả lời; xoá khỏi hàng đợi khi có người khác trả lời."""
    rt = msg.get("reply_to_message")
    sender = msg.get("from", {}).get("id")
    pend = state.setdefault("pending_questions", [])
    if rt and sender != rt.get("from", {}).get("id"):
        state["pending_questions"] = pend = [q for q in pend if q["mid"] != rt.get("message_id")]
    text = (msg.get("text") or "").strip()
    if not msg.get("from", {}).get("is_bot") and looks_like_question(text):
        pend.append({"mid": msg["message_id"], "ts": time.time(), "uid": sender, "text": text[:400]})
        state["pending_questions"] = pend[-20:]


def check_pending_questions(state):
    """Câu hỏi nhóm chưa ai đáp sau 8 phút -> bot tự trả lời (có giới hạn/ngày, không trả lời ban đêm)."""
    pend = state.get("pending_questions") or []
    if not pend:
        return False
    now = time.time()
    dt = datetime.now()
    today = dt.strftime("%Y-%m-%d")
    counts = state.get("auto_answers", {})
    if counts.get("day") != today:
        counts = {"day": today, "n": 0}
    keep, answered = [], False
    for q in pend:
        age = now - q["ts"]
        if age > PENDING_MAX_AGE:
            continue
        can = (7 <= dt.hour < 23 and age >= PENDING_WAIT and not answered
               and counts["n"] < DAILY_AUTO_ANSWER_LIMIT
               and now - state.get("last_auto_answer", 0) >= AUTO_ANSWER_MIN_GAP)
        if can:
            log_info(f"Auto-answering unanswered question {q['mid']} (waited {int(age)}s)")
            handle_smart_bot_reply({"chat": {"id": DISCUSSION_CHAT_ID}, "message_id": q["mid"], "text": q["text"]})
            counts["n"] += 1
            state["last_auto_answer"] = now
            answered = True
            continue
        keep.append(q)
    state["pending_questions"] = keep
    state["auto_answers"] = counts
    save_state(state)
    return answered


def process_update(upd, wl, state):
    if "callback_query" in upd:
        handle_callback(upd["callback_query"], wl)
        return

    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return

    chat_id = msg.get("chat", {}).get("id")
    chat_type = msg.get("chat", {}).get("type")
    sender_id = msg.get("from", {}).get("id")

    if chat_id == INTERNAL_CHAT_ID or (chat_type == "private" and sender_id == OWNER_ID):
        if handle_admin_command(msg, wl, state):
            return

    if chat_id == DISCUSSION_CHAT_ID:
        state["last_group_activity"] = time.time()
        save_state(state)

        if "new_chat_members" in msg:
            handle_new_members(msg, wl)
            return

        exempt = is_exempt_user(msg, wl)
        if not exempt:
            violated, reason = detect_violation(msg)
            if violated:
                handle_violation(msg, reason)
                return

        if should_bot_reply(msg):
            handle_smart_bot_reply(msg)
        elif not exempt:
            track_question(msg, state)
        else:
            track_question({**msg, "text": ""}, state)  # admin/whitelist trả lời cũng được tính là đã có người đáp

        if not exempt:
            handle_member_message_lead(msg)


def main():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    wl = load_whitelist()
    save_whitelist(wl)
    state = load_state()
    if "last_group_activity" not in state:
        state["last_group_activity"] = time.time()
    save_state(state)

    log_info(f"[VT Markets Bot] Started PID={os.getpid()}. Running 1A (Anti-Seeding) + 1B (Scheduled/Catch-up & Icebreaker) + 1C (Lead Routing). Offset={state.get('offset', 0)}")

    # Kiểm tra và đăng bù ngay lập tức nếu vừa khởi động trong khung giờ có lịch (ví dụ khung 08:30 -> 11:30 sáng)
    try:
        run_live_v2_showcase(state)
        check_scheduled_daily_posts(state)
        send_session_icebreaker(state, force=False)
    except Exception as e:
        log_info(f"[Startup Schedule Check Error]: {e}")

    start_ts = time.time()
    max_runtime = 0
    if "--max-runtime-seconds" in sys.argv:
        try:
            idx = sys.argv.index("--max-runtime-seconds")
            max_runtime = int(sys.argv[idx + 1])
        except Exception:
            max_runtime = 19500  # 5h25m default for GitHub Actions

    while True:
        if max_runtime > 0 and (time.time() - start_ts) >= max_runtime:
            save_state(state)
            save_whitelist(wl)
            sync_git_state()
            log_info(f"[VT Markets Bot] Reached max_runtime ({max_runtime}s). Saving state and exiting cleanly for next Cloud cycle.")
            break

        res = api_call("getUpdates", {
            "offset": state.get("offset", 0),
            "timeout": 10,
            "allowed_updates": ["message", "edited_message", "callback_query"]
        })
        if res.get("ok"):
            updates = res.get("result", [])
            for upd in updates:
                state["offset"] = upd["update_id"] + 1
                try:
                    process_update(upd, wl, state)
                except Exception as e:
                    log_info(f"[Error processing update]: {e}")
            if updates:
                save_state(state)
        else:
            err_msg = str(res.get("error", ""))
            if "409" in err_msg or "Conflict" in err_msg:
                time.sleep(15)
            else:
                time.sleep(3)

        # Check scheduled daily posts + 1B Dynamic Icebreaker
        try:
            check_scheduled_daily_posts(state)
            check_pending_questions(state)
            send_session_icebreaker(state, force=False)
        except Exception as e:
            log_info(f"[Error in 1B / Scheduled posts]: {e}")


if __name__ == "__main__":
    main()
