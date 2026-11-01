import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import content_queue
import validators

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
BOT_ID = 8793731768
DISCUSSION_CHAT_ID = -1004375233328   # VT Markets | Thảo Luận & Thực Chiến
INTERNAL_CHAT_ID = -1003750255534     # Nhóm nội bộ của chủ nhóm
CHANNEL_CHAT_ID = -1003971455443      # VT Rewards HUB (@vtrewardshub)

WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.json")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")
METRICS_FILE = os.path.join(BASE_DIR, "metrics.json")
PID_FILE = os.path.join(BASE_DIR, "bot.pid")

# Lịch đăng: hai khung giờ, tối đa 2 bài/ngày, cách nhau ít nhất 4 giờ. Hàng đợi rỗng thì bot im lặng.
PUBLISH_WINDOWS = [(9 * 60, 11 * 60), (19 * 60 + 30, 21 * 60 + 30)]
MAX_POSTS_PER_DAY = 2
MIN_POST_GAP = 4 * 3600
VETO_SECONDS = 3600
DEBATE_RESULT_AFTER = 48 * 3600
MIN_VOTES_FOR_SHARE = 5
GIT_PULL_EVERY = 900
ANSWERS_PER_USER_PER_DAY = 5
STRIKE_WINDOW = 7 * 86400
MUTE_SECONDS = 86400

PINNED_TEXT = """VT Markets | Thảo Luận & Thực Chiến: review có nguồn, tranh luận có phe, tránh bẫy

DÀNH CHO AI
Người đang học hoặc giao dịch vàng, ngoại tệ, muốn lọc thông tin trên mạng trước khi tin.
Không dành cho người tìm tín hiệu, gọi lệnh hay cách kiếm tiền nhanh.

BẮT ĐẦU
1. Đọc tin này.
2. Bỏ phiếu ở poll gần nhất hoặc bình luận dưới một bài.
3. Thử /tinhlenh, /chiphi, /kiemtra, /thuvien.

LỊCH
Bot đăng tối đa 2 bài/ngày, tối đa 2 poll/tuần. Ngày không có bài đạt kiểm tra thì bot im lặng.
Kết quả tranh luận đăng sau 48 giờ.

AI VẬN HÀNH
Nhóm do bot tự động vận hành, không có nhân viên trực, không có ai cam kết trả lời.
Bài do AI tóm tắt từ nguồn gốc và có thể sai; hãy mở link để kiểm tra. Trong nhóm không có tài khoản giả, không có số phiếu giả.

CHỦ NHÓM KIẾM TIỀN THẾ NÀO
Nhóm có liên kết với VT Markets. Chủ nhóm có thể nhận hoa hồng khi bạn mở tài khoản qua link của nhóm và giao dịch, nên có lợi khi bạn giao dịch nhiều hơn. Bạn không cần mở tài khoản ở đâu để ở lại nhóm.

QUY TẮC
Hỏi gì cũng được, nhắc tên sàn nào cũng được. Không gọi lệnh, không mời chào, không gửi link giới thiệu, không rủ nhắn riêng.
Không kêu gọi vốn, không cam kết lợi nhuận, không ủy thác.
Nếu tin của bạn bị gỡ, bot sẽ nói lý do. Thấy nhầm thì gõ /baocao; khóa tạm sẽ tự hết hạn.

AN TOÀN
Không ai đại diện nhóm nhắn riêng trước, nhận tiền, giữ vốn hay vào lệnh hộ.
Ai hứa lấy lại tiền đã mất đều cần coi là dấu hiệu lừa đảo.

RỦI RO
Forex và CFD có thể làm mất toàn bộ vốn; phần lớn tài khoản cá nhân thua lỗ. Không có bằng chứng tham gia nhóm giúp giao dịch tốt hơn. Bot không tư vấn đầu tư.
Đừng dùng tiền vay hoặc tiền bạn không thể mất."""

CHECKLIST_TEXT = """Tự kiểm tra một lời mời đầu tư:
1. Có ai hứa lãi cố định hoặc cam kết không lỗ không?
2. Người mời có nhắn riêng trước và thúc bạn quyết định nhanh không?
3. Có ảnh khoe lãi nhưng không có lịch sử lệnh kiểm tra được không?
4. Lúc đầu rút được ít, sau đó bị yêu cầu nạp thêm mới rút được không?
5. Có ai xin giữ vốn, đăng nhập tài khoản hoặc vào lệnh hộ không?
6. Có ai hứa lấy lại tiền đã mất với một khoản phí không?
Có từ một dấu hiệu trở lên thì nên dừng lại kiểm tra. Danh sách này không kết luận nền tảng nào an toàn."""

ADVICE_REPLY = "Bot không trả lời có nên vào lệnh, mua, bán hay nạp tiền. Gõ /kiemtra hoặc /tinhlenh để tự kiểm tra rủi ro của mình."
CRISIS_REPLY = ("Bot không tư vấn trường hợp này. Đừng vay thêm hoặc nạp thêm để gỡ, và đừng trả phí cho ai hứa lấy lại tiền đã mất. "
                "Hãy nói với người thân bạn tin, và trình báo công an nếu bị lừa.")
NO_ANSWER_REPLY = "Bot chưa có bài về chủ đề này. Thành viên khác có thể trả lời bạn."

ADVICE_RE = re.compile(r"có\s+nên\s+(?:mua|bán|buy|sell|vào|nạp|giữ|gồng)|nên\s+(?:mua|bán|buy|sell)\s|sàn\s+nào\s+tốt|vàng\s+.{0,20}(?:lên|xuống)\s+không", re.I)
CRISIS_RE = re.compile(r"cháy\s+tài\s+khoản|vay\s+(?:tiền|nóng)|gỡ\s+(?:lỗ|lại)|lấy\s+lại\s+tiền|mất\s+hết\s+tiền|bị\s+lừa", re.I)
EXPLICIT_LEAD_RE = re.compile(r"mở\s+tài\s+khoản|backcom|hoàn\s+phí|raw\s+ecn|tư\s+vấn\s+(?:sàn|tài\s+khoản)", re.I)
BLOCKED_LINK_RE = re.compile(r"(?:t\.me/(?!vtrewardshub)|telegram\.me/|zalo\.me/|wa\.me/|discord\.gg/|bit\.ly/|tinyurl\.com/|[?&](?:ref|aff|affiliate|invite)=)\S*", re.I)
SCAM_RE = re.compile(r"kéo\s+tài\s+khoản|ib\s+mình\s+kéo|nhóm\s+tín\s+hiệu|nhóm\s+vip|bán\s+bot|cứu\s+cháy|nhận\s+ủy\s+thác|cam\s+kết\s+(?:lợi\s+nhuận|lãi)|kêu\s+gọi\s+(?:vốn|đầu\s+tư)", re.I)


def log_info(msg_str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg_str}", flush=True)


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
        json.dump({"user_ids": sorted(wl["user_ids"]), "usernames": sorted(wl["usernames"])}, f, ensure_ascii=False, indent=2)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"offset": 0}


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


def send_text(chat_id, text, **extra):
    return api_call("sendMessage", {"chat_id": chat_id, "text": text, **extra})


ADMIN_CACHE = {"ids": {OWNER_ID}, "updated_at": 0}


def get_discussion_admins():
    now = time.time()
    if now - ADMIN_CACHE["updated_at"] > 300:
        res = api_call("getChatAdministrators", {"chat_id": DISCUSSION_CHAT_ID})
        if res.get("ok"):
            ADMIN_CACHE["ids"] = {OWNER_ID} | {m["user"]["id"] for m in res.get("result", []) if m.get("user", {}).get("id")}
            ADMIN_CACHE["updated_at"] = now
    return ADMIN_CACHE["ids"]


def is_exempt_user(msg, wl):
    if msg.get("sender_chat", {}).get("id") in (CHANNEL_CHAT_ID, DISCUSSION_CHAT_ID) or msg.get("is_automatic_forward"):
        return True
    user = msg.get("from", {})
    uid = user.get("id")
    uname = (user.get("username") or "").lower().lstrip("@")
    if not uid:
        return False
    return uid in wl["user_ids"] or (uname and uname in wl["usernames"]) or uid in get_discussion_admins()


# ----------------------------------------------------------------------------
# Đo lường: lưu ID đã băm, chỉ lưu số đếm, không lưu nội dung tin nhắn
# ----------------------------------------------------------------------------
def hash_user(uid):
    return hashlib.sha256(f"{BOT_TOKEN}:{uid}".encode()).hexdigest()[:16]


def load_metrics():
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"events": [], "activity": []}


def save_metrics(m):
    m["events"] = m["events"][-5000:]
    m["activity"] = m["activity"][-5000:]
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=0)


def record_member_update(cm):
    if cm.get("chat", {}).get("id") != DISCUSSION_CHAT_ID:
        return
    old, new = cm.get("old_chat_member", {}), cm.get("new_chat_member", {})
    user = new.get("user", {})
    if user.get("is_bot"):
        return
    inside = ("member", "administrator", "creator", "restricted")
    was_in, is_in = old.get("status") in inside, new.get("status") in inside
    if was_in == is_in:
        return
    m = load_metrics()
    m["events"].append({"t": int(time.time()), "e": "join" if is_in else "leave", "u": hash_user(user.get("id")),
                        "link": (cm.get("invite_link") or {}).get("name") or ""})
    save_metrics(m)


def record_activity(msg, is_reply_to_member):
    m = load_metrics()
    m["activity"].append({"t": int(time.time()), "u": hash_user(msg.get("from", {}).get("id")), "r": 1 if is_reply_to_member else 0})
    save_metrics(m)


def stats_text(now=None):
    now = now or time.time()
    m = load_metrics()
    week = now - 7 * 86400
    events = [e for e in m["events"] if e["t"] >= week]
    joins = [e for e in events if e["e"] == "join"]
    leaves = [e for e in events if e["e"] == "leave"]
    join_at = {e["u"]: e["t"] for e in m["events"] if e["e"] == "join"}
    fast = sum(1 for e in leaves if e["u"] in join_at and e["t"] - join_at[e["u"]] < 86400)
    act = [a for a in m["activity"] if a["t"] >= week]
    return (f"Số liệu 7 ngày:\nVào: {len(joins)}\nRời: {len(leaves)}\nRời trong 24 giờ sau khi vào: {fast}\n"
            f"Người nhắn tin: {len({a['u'] for a in act})}\nLượt thành viên trả lời nhau: {sum(a['r'] for a in act)}\n"
            f"Bài chờ đăng: {len(content_queue.pending_items())}")


# ----------------------------------------------------------------------------
# Kiểm duyệt: gỡ có giải thích, lần đầu không khóa, khóa có thời hạn
# ----------------------------------------------------------------------------
def detect_violation(msg):
    if any(k in msg for k in ("forward_origin", "forward_from", "forward_from_chat", "forward_sender_name")):
        origin = msg.get("forward_from_chat", {}).get("id") or msg.get("forward_origin", {}).get("chat", {}).get("id")
        if origin not in (CHANNEL_CHAT_ID, DISCUSSION_CHAT_ID):
            return True, "tin chuyển tiếp từ nơi khác"
    text = (msg.get("text") or msg.get("caption") or "").strip()
    urls = [e.get("url", "") for e in (msg.get("entities") or []) + (msg.get("caption_entities") or []) if e.get("type") == "text_link"]
    for candidate in [text] + urls:
        if BLOCKED_LINK_RE.search(candidate):
            return True, "link mời nhóm khác hoặc link giới thiệu"
    if SCAM_RE.search(text):
        return True, "nội dung mời chào, kêu gọi vốn hoặc cam kết lợi nhuận"
    return False, ""


def format_user_internal(user):
    full = html.escape(f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip() or "Thành viên")
    uid = user.get("id", "")
    uname = f"@{user['username']} | " if user.get("username") else ""
    return f'<a href="tg://user?id={uid}">{full}</a> ({uname}ID: <code>{uid}</code>)'


def mention_public(user):
    full = html.escape(f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip() or "bạn")
    return f'<a href="tg://user?id={user.get("id", "")}">{full}</a>'


def set_chat_permission(uid, allowed, until=None):
    perms = {k: allowed for k in ("can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos", "can_send_videos",
                                  "can_send_video_notes", "can_send_voice_notes", "can_send_polls", "can_send_other_messages",
                                  "can_add_web_page_previews")}
    payload = {"chat_id": DISCUSSION_CHAT_ID, "user_id": uid, "permissions": perms}
    if until:
        payload["until_date"] = until
    return api_call("restrictChatMember", payload)


def handle_violation(msg, reason, state):
    user = msg.get("from", {})
    uid = user.get("id")
    now = int(time.time())
    api_call("deleteMessage", {"chat_id": msg["chat"]["id"], "message_id": msg["message_id"]})

    strikes = state.setdefault("strikes", {})
    recent = [t for t in strikes.get(str(uid), []) if now - t < STRIKE_WINDOW] + [now]
    strikes[str(uid)] = recent
    muted = len(recent) >= 2 and uid
    if muted:
        set_chat_permission(uid, False, until=now + MUTE_SECONDS)
    suffix = " Đây là lần thứ hai nên tài khoản bị khóa chat 24 giờ, sau đó tự mở." if muted else " Lần tới có thể bị khóa chat 24 giờ."
    send_text(DISCUSSION_CHAT_ID, f"Bot đã gỡ tin của {mention_public(user)} vì {html.escape(reason)}.{suffix} Nếu thấy nhầm, gõ /baocao.", parse_mode="HTML")

    text_esc = html.escape((msg.get("text") or msg.get("caption") or "[Media/Forward]").strip()[:500])
    buttons = [[{"text": "Mở khóa", "callback_data": f"unmute:{uid}"},
                {"text": "Thêm vào danh sách miễn trừ", "callback_data": f"wl_add:{uid}:{user.get('username') or ''}"}]] if uid else []
    send_text(INTERNAL_CHAT_ID, f"Đã gỡ tin\nNgười gửi: {format_user_internal(user)}\nLý do: {html.escape(reason)}\nNội dung: <code>{text_esc}</code>",
              parse_mode="HTML", reply_markup={"inline_keyboard": buttons})


def welcome_new_members(members, state):
    """Clean up any legacy welcome message without posting publicly."""
    old = state.pop("welcome_msg_id", None)
    if old:
        api_call("deleteMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": old})


def notify_explicit_lead(msg):
    """Chỉ báo khi thành viên tự hỏi về tài khoản. Trả lời trong nhóm, không nhắn riêng trước."""
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not EXPLICIT_LEAD_RE.search(text):
        return
    link = f"https://t.me/c/4375233328/{msg['message_id']}"
    send_text(INTERNAL_CHAT_ID, f"Thành viên hỏi về tài khoản: {html.escape(text[:400])}\nTrả lời ngay trong nhóm nếu phù hợp, không nhắn riêng trước.\n{link}", parse_mode="HTML")


# ----------------------------------------------------------------------------
# Trả lời thành viên: không dùng LLM, chỉ tìm trong bài đã đăng
# ----------------------------------------------------------------------------
def search_library(query, history, limit=3):
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3}
    scored = []
    for h in history:
        hay = (h.get("title", "") + " " + h.get("text", "")).lower()
        score = sum(1 for w in words if w in hay)
        if score >= 2 or (len(words) == 1 and score == 1):
            scored.append((score, h.get("ts", 0), h))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored[:limit]]


def format_library(rows):
    return "\n".join(f"- {r.get('title', '')[:90]}" + (f"\n  {r['source_url']}" if r.get("source_url") else "") for r in rows)


def answer_text(text, history):
    """Trả về (câu trả lời, có cần báo chủ nhóm không)."""
    if CRISIS_RE.search(text):
        return CRISIS_REPLY, True
    if ADVICE_RE.search(text):
        return ADVICE_REPLY, False
    rows = search_library(text, history)
    if rows:
        return "Bài liên quan trong nhóm:\n" + format_library(rows), False
    return NO_ANSWER_REPLY, False


def should_bot_reply(msg):
    if msg.get("from", {}).get("is_bot") or msg.get("sender_chat"):
        return False
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text or text.startswith("/"):
        return False
    if "@vtmarkets8386_bot" in text.lower() or re.search(r"\bbot\b", text.lower()):
        return True
    r_from = (msg.get("reply_to_message") or {}).get("from", {})
    return r_from.get("id") == BOT_ID


def handle_bot_reply(msg, state):
    uid = str(msg.get("from", {}).get("id"))
    today = datetime.now().strftime("%Y-%m-%d")
    counts = state.setdefault("answer_counts", {})
    if counts.get("day") != today:
        counts.clear()
        counts["day"] = today
    if counts.get(uid, 0) >= ANSWERS_PER_USER_PER_DAY:
        return
    counts[uid] = counts.get(uid, 0) + 1
    text = re.sub(r"@vtmarkets8386_bot", "", msg.get("text") or msg.get("caption") or "", flags=re.I).strip()
    reply, alert = answer_text(text, content_queue.load_state().get("history", []))
    send_text(msg["chat"]["id"], reply, reply_to_message_id=msg["message_id"], disable_web_page_preview=True)
    if alert:
        send_text(INTERNAL_CHAT_ID, f"Thành viên có dấu hiệu cần chú ý: {html.escape(text[:400])}\nhttps://t.me/c/4375233328/{msg['message_id']}", parse_mode="HTML")


def _num(s):
    return float(s.replace(",", "."))


def calc_lot(args):
    """Vàng: 1 lot = 100 oz, giá đi 1 USD thì lãi/lỗ 100 USD trên 1 lot."""
    capital, risk_pct, stop_usd = _num(args[0]), _num(args[1]), _num(args[2])
    if capital <= 0 or risk_pct <= 0 or stop_usd <= 0:
        raise ValueError
    risk = capital * risk_pct / 100
    return (f"Vốn {capital:g} USD, chấp nhận mất {risk_pct:g}% tức {risk:.2f} USD, giá vàng đi ngược {stop_usd:g} USD thì dừng:\n"
            f"Khối lượng tối đa khoảng {risk / (stop_usd * 100):.2f} lot.\nHợp đồng tiêu chuẩn 100 oz; kiểm tra lại thông số của sàn bạn dùng. Đây là phép tính, không phải khuyến nghị.")


def calc_cost(args):
    lot, spread_usd = _num(args[0]), _num(args[1])
    if lot <= 0 or spread_usd < 0:
        raise ValueError
    return f"{lot:g} lot vàng với spread {spread_usd:g} USD: chi phí spread khoảng {lot * spread_usd * 100:.2f} USD mỗi lần vào lệnh, chưa tính hoa hồng và phí qua đêm."


def handle_member_command(msg):
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return False
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    chat_id, mid = msg["chat"]["id"], msg["message_id"]
    if cmd == "/tinhlenh":
        try:
            out = calc_lot(parts[1:4])
        except (ValueError, IndexError):
            out = "Cách dùng: /tinhlenh vốn %rủi_ro khoảng_dừng_USD\nVí dụ: /tinhlenh 1000 1 5"
    elif cmd == "/chiphi":
        try:
            out = calc_cost(parts[1:3])
        except (ValueError, IndexError):
            out = "Cách dùng: /chiphi lot spread_USD\nVí dụ: /chiphi 0.01 0.3"
    elif cmd == "/kiemtra":
        out = CHECKLIST_TEXT
    elif cmd == "/thuvien":
        history = content_queue.load_state().get("history", [])
        query = " ".join(parts[1:])
        rows = search_library(query, history) if query else history[-5:][::-1]
        out = format_library(rows) or "Chưa có bài phù hợp. Cách dùng: /thuvien từ khóa"
    elif cmd == "/baocao":
        rt = msg.get("reply_to_message") or {}
        detail = html.escape(" ".join(parts[1:]) or (rt.get("text") or rt.get("caption") or "(không có nội dung)"))[:800]
        send_text(INTERNAL_CHAT_ID, f"Báo cáo từ {format_user_internal(msg.get('from', {}))}:\n{detail}", parse_mode="HTML")
        out = "Bot đã chuyển báo cáo tới chủ nhóm. Chưa chắc được xem ngay."
    else:
        return False
    send_text(chat_id, out, reply_to_message_id=mid, disable_web_page_preview=True)
    return True


# ----------------------------------------------------------------------------
# Đăng tự động từ hàng đợi: qua cổng kiểm duyệt tự động (Pre-Publish Gate) là đăng ngay
# ----------------------------------------------------------------------------
def in_window(dt):
    mins = dt.hour * 60 + dt.minute
    return any(a <= mins <= b for a, b in PUBLISH_WINDOWS)


def posts_today(history, dt):
    return sum(1 for h in history if datetime.fromtimestamp(h.get("ts", 0)).date() == dt.date())


def pre_publish_audit(item, history, now):
    """Lớp kiểm duyệt tự động trước khi đăng: trả về (hard_errors, schedule_errors)."""
    hard_errors = list(validators.check_item(item))
    violated, reason = detect_violation({"text": item.get("text", "")})
    if violated:
        hard_errors.append(f"moderation:{reason}")
    if hard_errors:
        return hard_errors, []
    sched_errors = list(validators.check_schedule(item, history, now))
    return [], sched_errors


def next_item(qstate, now):
    history = qstate.get("history", [])
    items = qstate.setdefault("items", {})
    last_kind = history[-1].get("kind") if history else ""
    pending = content_queue.pending_items(now)
    pending.sort(key=lambda i: (i.get("kind") == last_kind, i.get("kind") == "poll", i.get("created_at", 0)))
    changed = False
    chosen = None
    for item in pending:
        hard_errors, sched_errors = pre_publish_audit(item, history, now)
        if hard_errors:
            items[item["id"]] = {"status": "rejected", "ts": int(now), "errors": hard_errors}
            changed = True
            continue
        if not sched_errors:
            chosen = item
            break
    if changed:
        content_queue.save_state(qstate)
    return chosen


def publish_item(item):
    """Mọi bài viết đều đính kèm ảnh thật trên mạng (image_url). Tranh luận gửi kèm poll gốc của Telegram."""
    poll_msg_id = None
    res = {"ok": False}
    if item.get("text"):
        sent_photo = False
        img_url = item.get("image_url", "")
        if not img_url and item.get("kind") == "video_review":
            img_url = f"https://i.ytimg.com/vi/{item.get('id', '').replace('video_', '')}/hqdefault.jpg"
        if BOT_TOKEN and img_url and len(item["text"]) <= 1024:
            res = api_call("sendPhoto", {"chat_id": DISCUSSION_CHAT_ID, "photo": img_url, "caption": item["text"]})
            sent_photo = bool(res.get("ok"))
        if not sent_photo:
            res = send_text(DISCUSSION_CHAT_ID, item["text"])
        if not res.get("ok"):
            return res, None
    if item.get("poll"):
        res = api_call("sendPoll", {"chat_id": DISCUSSION_CHAT_ID, "question": item["poll"]["question"][:300],
                                    "options": item["poll"]["options"][:10], "is_anonymous": True, "allows_multiple_answers": False})
        if not res.get("ok"):
            return res, None
        poll_msg_id = res["result"]["message_id"]
    return res, poll_msg_id


def process_queue(state, now=None, force_window=False):
    now = now or time.time()
    dt = datetime.fromtimestamp(now)
    if state.get("paused"):
        return False
    if not force_window and not in_window(dt):
        return False
    qstate = content_queue.load_state()
    items = qstate.setdefault("items", {})
    history = qstate.setdefault("history", [])

    if not force_window and posts_today(history, dt) >= MAX_POSTS_PER_DAY:
        return False
    if not force_window and history and now - history[-1].get("ts", 0) < MIN_POST_GAP:
        return False
    item = next_item(qstate, now)
    if not item:
        return False
    res, poll_msg_id = publish_item(item)
    if not res.get("ok"):
        log_info(f"Không đăng được {item['id']}: {res.get('error')}")
        return False
    msg_id = res["result"]["message_id"]
    rec = {"status": "posted", "ts": int(now), "msg_id": msg_id}
    if item.get("kind") == "debate":
        rec.update(poll_msg_id=poll_msg_id, result_due=int(now + DEBATE_RESULT_AFTER), poll_options=item["poll"]["options"])
    items[item["id"]] = rec
    history.append({k: item.get(k, "") for k in ("id", "kind", "group", "author", "topic", "title", "text", "source_url")} | {"ts": int(now)})
    qstate["history"] = history[-200:]
    content_queue.save_state(qstate)
    sync_git_state()
    log_info(f"Đã đăng {item['id']}")
    send_text(INTERNAL_CHAT_ID, f"Đã qua kiểm duyệt tự động & đăng bài: {item['id']} ({item['kind']})",
              disable_web_page_preview=True,
              reply_markup={"inline_keyboard": [[{"text": "Gỡ bài vừa đăng", "callback_data": f"delpost:{msg_id}"}]]})
    return True


def check_debate_results(now=None):
    now = now or time.time()
    qstate = content_queue.load_state()
    changed = False
    for item_id, rec in qstate.get("items", {}).items():
        if rec.get("status") != "posted" or not rec.get("result_due") or now < rec["result_due"] or rec.get("result_posted"):
            continue
        res = api_call("stopPoll", {"chat_id": DISCUSSION_CHAT_ID, "message_id": rec["poll_msg_id"]})
        rec["result_posted"] = True
        changed = True
        if not res.get("ok"):
            log_info(f"Không lấy được kết quả poll {item_id}: {res.get('error')}")
            continue
        send_text(DISCUSSION_CHAT_ID, format_poll_result(res["result"]), reply_to_message_id=rec["poll_msg_id"])
    if changed:
        content_queue.save_state(qstate)


def format_poll_result(poll):
    total = poll.get("total_voter_count", 0)
    lines = [f"- {o['text']}: {o['voter_count']} phiếu" for o in poll.get("options", [])]
    note = "Quá ít phiếu nên không rút ra kết luận." if total < MIN_VOTES_FOR_SHARE else "Đây là ý kiến của người đã bỏ phiếu, không đại diện cho ai và không phải khuyến nghị."
    return "\n".join([f"Kết quả tranh luận, tổng {total} phiếu:"] + lines + [note])


# ----------------------------------------------------------------------------
# Lệnh của chủ nhóm
# ----------------------------------------------------------------------------
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
        send_text(chat_id, f"Đã thêm {target} vào danh sách miễn trừ.")
    elif cmd == "/xoa" and len(parts) >= 2:
        target = parts[1].strip()
        if target.lstrip("-").isdigit():
            wl["user_ids"].discard(int(target))
        else:
            wl["usernames"].discard(target.lower().lstrip("@"))
        save_whitelist(wl)
        send_text(chat_id, f"Đã xóa {target} khỏi danh sách miễn trừ.")
    elif cmd == "/danhsach":
        send_text(chat_id, ("Danh sách miễn trừ: " + (", ".join(f"@{u}" for u in sorted(wl["usernames"])) or "(trống)") + "\n"
                            "Lệnh: /them, /xoa, /tamdung, /tieptuc, /thongke, /hangdoi, /ghim"))
    elif cmd == "/tamdung":
        state["paused"] = True
        save_state(state)
        send_text(chat_id, "Bot đã dừng đăng bài. Gõ /tieptuc để bật lại.")
    elif cmd == "/tieptuc":
        state["paused"] = False
        save_state(state)
        send_text(chat_id, "Bot đăng bài trở lại.")
    elif cmd == "/thongke":
        send_text(chat_id, stats_text())
    elif cmd == "/hangdoi":
        rows = content_queue.pending_items()
        send_text(chat_id, "\n".join(f"- {i['kind']}: {i.get('title', '')[:80]}" for i in rows) or "Hàng đợi trống.")
    elif cmd == "/ghim":
        res = send_text(DISCUSSION_CHAT_ID, PINNED_TEXT)
        if res.get("ok"):
            api_call("pinChatMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": res["result"]["message_id"], "disable_notification": True})
        send_text(chat_id, "Đã ghim tin giới thiệu." if res.get("ok") else f"Không ghim được: {res.get('error')}")
    elif cmd == "/donrac":
        mids = [int(x) for x in parts[1:] if x.isdigit()]
        if not mids:
            mids = [p.get("msg_id") for p in state.get("last_live_test_result", {}).get("posts", []) if p.get("msg_id")]
        deleted = sum(1 for mid in mids if api_call("deleteMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": mid}).get("ok"))
        send_text(chat_id, f"Đã gỡ {deleted}/{len(mids)} tin cũ khỏi nhóm thảo luận.")
    else:
        return False
    return True


def handle_callback(cb, wl):
    data = cb.get("data") or ""
    chat_id = cb.get("message", {}).get("chat", {}).get("id")
    answer = ""
    if data.startswith("unmute:"):
        uid = int(data.split(":")[1])
        set_chat_permission(uid, True)
        answer = "Đã mở khóa"
    elif data.startswith("wl_add:"):
        parts = data.split(":")
        uid = int(parts[1])
        wl["user_ids"].add(uid)
        if len(parts) > 2 and parts[2]:
            wl["usernames"].add(parts[2].lower().lstrip("@"))
        save_whitelist(wl)
        set_chat_permission(uid, True)
        answer = "Đã thêm vào danh sách miễn trừ"
    elif data.startswith("block:"):
        item_id = data.split(":", 1)[1]
        qstate = content_queue.load_state()
        if qstate.setdefault("items", {}).get(item_id, {}).get("status") == "preview":
            qstate["items"][item_id] = {"status": "blocked", "ts": int(time.time())}
            content_queue.save_state(qstate)
            answer = "Đã chặn bài"
        else:
            answer = "Bài đã đăng hoặc đã xử lý"
    elif data.startswith("delpost:"):
        mid = int(data.split(":", 1)[1])
        ok = api_call("deleteMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": mid}).get("ok")
        answer = "Đã gỡ bài khỏi nhóm thảo luận" if ok else "Không gỡ được bài"
    if answer:
        api_call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": answer})
        send_text(chat_id, answer)


def process_update(upd, wl, state):
    if "callback_query" in upd:
        handle_callback(upd["callback_query"], wl)
        return
    if "chat_member" in upd:
        record_member_update(upd["chat_member"])
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

    if chat_id != DISCUSSION_CHAT_ID:
        return
    if "new_chat_members" in msg:
        welcome_new_members([m for m in msg["new_chat_members"] if not m.get("is_bot") and m.get("id") not in wl["user_ids"]], state)
        save_state(state)
        return

    exempt = is_exempt_user(msg, wl)
    if not exempt:
        violated, reason = detect_violation(msg)
        if violated:
            handle_violation(msg, reason, state)
            save_state(state)
            return
    if handle_member_command(msg):
        return
    if msg.get("from", {}).get("is_bot") or msg.get("sender_chat") or "message" not in upd:
        return

    r_from = (msg.get("reply_to_message") or {}).get("from", {})
    is_member_reply = bool(r_from) and not r_from.get("is_bot") and r_from.get("id") != sender_id and not exempt
    if not exempt:
        record_activity(msg, is_member_reply)
        notify_explicit_lead(msg)
    if should_bot_reply(msg):
        handle_bot_reply(msg, state)
        save_state(state)


# ----------------------------------------------------------------------------
# Git: pipeline ghi bài mới, bot ghi trạng thái
# ----------------------------------------------------------------------------
def _git(*args, timeout=30):
    kw = {"cwd": BASE_DIR, "capture_output": True, "text": True}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(["git", *args], timeout=timeout, **kw)


def sync_git_state():
    """Commit + push state an toàn: autostash vì state bị ghi liên tục, retry khi push bị từ chối."""
    try:
        if not os.path.exists(os.path.join(BASE_DIR, ".git")):
            return
        _git("config", "user.name", "VT-Markets-Bot-Cloud", timeout=8)
        _git("config", "user.email", "bot@vtmarketshub.local", timeout=8)
        _git("add", "bot_state.json", "content_queue_state.json", "metrics.json", "whitelist.json", timeout=15)
        if _git("diff", "--staged", "--quiet", timeout=8).returncode == 0:
            return
        _git("commit", "-m", "chore: auto-sync bot state [skip ci]", timeout=15)
        res = None
        for attempt in range(3):
            _git("pull", "--rebase", "--autostash", "origin", "main", timeout=60)
            res = _git("push", "origin", "main", timeout=60)
            if res.returncode == 0:
                return
            time.sleep(2 + attempt * 3)
        log_info(f"[Git Sync Warning]: push failed: {(res.stderr or '')[:200]}")
    except Exception as e:
        log_info(f"[Git Sync Warning]: {e}")


def pull_new_content():
    try:
        if os.path.exists(os.path.join(BASE_DIR, ".git")):
            _git("pull", "--rebase", "--autostash", "origin", "main", timeout=60)
    except Exception as e:
        log_info(f"[Git Pull Warning]: {e}")


def ensure_setup(state):
    """Việc thiết lập tự làm một lần; chỉ báo chủ nhóm khi bot thiếu quyền hoặc không làm được."""
    res = api_call("getChatMember", {"chat_id": DISCUSSION_CHAT_ID, "user_id": BOT_ID})
    member = res.get("result", {}) if res.get("ok") else {}
    if member.get("status") != "administrator" or not member.get("can_pin_messages") or not member.get("can_restrict_members"):
        if not state.get("admin_alerted"):
            send_text(INTERNAL_CHAT_ID, "Bot cần quyền admin trong nhóm thảo luận, gồm ghim tin và hạn chế thành viên, để ghim tin giới thiệu, gỡ spam và đo lượt vào, rời.")
            state["admin_alerted"] = True
            save_state(state)
        return
    state["admin_alerted"] = False
    if state.get("intro_pinned"):
        return
    sent = send_text(DISCUSSION_CHAT_ID, PINNED_TEXT)
    if sent.get("ok"):
        pinned = api_call("pinChatMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": sent["result"]["message_id"], "disable_notification": True})
        state["intro_pinned"] = bool(pinned.get("ok"))
    save_state(state)


def send_weekly_report(state, now=None):
    """Sáng thứ Hai tự gửi số liệu tuần vào nhóm nội bộ."""
    dt = datetime.fromtimestamp(now or time.time())
    week = dt.strftime("%G-W%V")
    if dt.weekday() != 0 or dt.hour < 9 or state.get("last_report_week") == week:
        return False
    if send_text(INTERNAL_CHAT_ID, stats_text(now)).get("ok"):
        state["last_report_week"] = week
        save_state(state)
        return True
    return False


def main():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    wl = load_whitelist()
    save_whitelist(wl)
    state = load_state()
    save_state(state)
    log_info(f"[VT Markets Bot] Started PID={os.getpid()}. Offset={state.get('offset', 0)}")
    try:
        if state.get("welcome_msg_id"):
            api_call("deleteMessage", {"chat_id": DISCUSSION_CHAT_ID, "message_id": state.pop("welcome_msg_id")})
            save_state(state)
            sync_git_state()
        ensure_setup(state)
        if not state.get("v3_web_photo_showcase_posted"):
            if process_queue(state, force_window=True):
                state["v3_web_photo_showcase_posted"] = True
                save_state(state)
                sync_git_state()
    except Exception as e:
        log_info(f"[Setup error]: {e}")

    start_ts = time.time()
    last_pull = 0
    max_runtime = 0
    if "--max-runtime-seconds" in sys.argv:
        try:
            max_runtime = int(sys.argv[sys.argv.index("--max-runtime-seconds") + 1])
        except Exception:
            max_runtime = 19500  # 5h25m default for GitHub Actions

    while True:
        if max_runtime > 0 and (time.time() - start_ts) >= max_runtime:
            save_state(state)
            save_whitelist(wl)
            sync_git_state()
            log_info(f"[VT Markets Bot] Reached max_runtime ({max_runtime}s). Exiting cleanly for next Cloud cycle.")
            break

        res = api_call("getUpdates", {
            "offset": state.get("offset", 0),
            "timeout": 10,
            "allowed_updates": ["message", "edited_message", "callback_query", "chat_member"]
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
            time.sleep(15 if "409" in err_msg or "Conflict" in err_msg else 3)

        try:
            if time.time() - last_pull >= GIT_PULL_EVERY:
                last_pull = time.time()
                sync_git_state()
                pull_new_content()
            process_queue(state)
            check_debate_results()
            send_weekly_report(state)
        except Exception as e:
            log_info(f"[Error in queue]: {e}")


if __name__ == "__main__":
    main()
