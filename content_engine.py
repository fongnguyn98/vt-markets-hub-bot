"""
Content engine v2.2: đi thẳng vào trọng tâm vấn đề, truyền đạt tự nhiên, hấp dẫn, tinh gọn.

Nguyên tắc:
- Vào thẳng sự kiện, con số hoặc câu chuyện ngay từ câu đầu tiên.
- CẤM mở đầu kiểu điểm báo gián tiếp ("Bài báo này đưa tin...", "Theo bản tin trên...", "Trang X vừa có bài viết...", "Mình vừa đọc/xem...").
- Bài KOL chỉ viết khi đọc được phụ đề thật của video (<= 30 ngày).
- Tin tức chỉ lấy trong 24h gần nhất.
- Không khuyên mua/bán, không dự đoán giá chủ quan, không hứa hẹn lợi nhuận.
"""
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import datetime

import news_and_kol_radar as radar

LLM_TIMEOUT = 45

SAFETY_RULES = (
    "Quy tắc bắt buộc: gọi người đọc là 'các sếp' (hoặc 'anh em'); văn phong đời thường, sắc gọn, vào thẳng vấn đề ngay từ câu đầu tiên; "
    "TUYỆT ĐỐI CẤM mở đầu bằng các cụm từ kiểu điểm báo như 'Bài báo đưa tin', 'Theo bản tin', 'Theo báo cáo', 'Trang X vừa đăng', 'Mình vừa đọc/xem', 'Cập nhật nhanh', 'Tình huống:'; "
    "KHÔNG khuyên mua/bán, KHÔNG dự đoán giá tăng/giảm chủ quan, KHÔNG hứa hẹn lợi nhuận, KHÔNG dùng ký tự ** hay markdown."
)

META_OPENER_RE = re.compile(
    r"^(?:theo\s+(?:bản\s+tin|bài\s+báo|bài\s+viết|bài\s+phân\s+tích|báo\s+cáo|thông\s+tin|ghi\s+nhận|nguồn\s+tin)[^,.:;\n]*[,:]\s*"
    r"|(?:trang|báo|tờ|kênh)\s+[^,.:;\n]{2,35}\s+(?:vừa\s+)?(?:có\s+bài\s+viết|đưa\s+tin|đăng\s+tải|cho\s+biết|chia\s+sẻ)[^,.:;\n]*[,:]\s*"
    r"|bài\s+(?:báo|viết)\s+(?:này\s+)?(?:đưa\s+tin|nói\s+về|ề\s+cập)[^,.:;\n]*[,:]\s*"
    r"|mình\s+(?:vừa\s+|mới\s+)?(?:đọc|xem|thấy|cập\s+nhật)[^,.:;\n]*[,:]\s*"
    r"|điểm\s+nhanh\s+[^,.:;\n]*[,:]\s*"
    r"|tình\s+huống\s*[:\-]\s*"
    r"|giả\s+sử\s+[:\-]\s*)+",
    re.I
)

FORBIDDEN_SUBSTRINGS = (
    "bài báo này đưa tin",
    "bài báo đưa tin",
    "vừa có bài viết",
    "theo bản tin trên",
    "đây là quan điểm của kênh chứ không phải",
)


def clean_direct_text(text):
    t = (text or "").replace("**", "").strip().strip('"').strip()
    t = META_OPENER_RE.sub("", t).strip()
    if t:
        t = t[0].upper() + t[1:]
    return t


def is_clean_direct(text, min_len=90, max_len=900):
    t = clean_direct_text(text)
    low = t.lower()
    if not (min_len <= len(t) <= max_len) or "?" not in t:
        return False
    if any(bad in low for bad in FORBIDDEN_SUBSTRINGS):
        return False
    return True


# ----------------------------------------------------------------------------
# LLM
# ----------------------------------------------------------------------------
def _ask_g4f(prompt):
    import g4f
    from g4f.client import Client
    client = Client()
    for prov in [g4f.Provider.Yqcloud, g4f.Provider.ChatGPT]:
        try:
            r = client.chat.completions.create(model="", provider=prov, messages=[{"role": "user", "content": prompt}])
            ans = (r.choices[0].message.content or "").strip()
            if len(ans) > 20 and "<!doctype" not in ans.lower():
                return ans
        except Exception:
            continue
    return ""


def _ask_pollinations(prompt):
    for _ in range(2):
        try:
            seed = random.randint(1000, 999999)
            url = f"https://text.pollinations.ai/{urllib.parse.quote(prompt[:6000])}?model=openai-fast&seed={seed}"
            r = radar.cffi_req.get(url, impersonate="chrome120", timeout=25)
            ans = (r.text or "").strip()
            low = ans.lower()
            if r.status_code == 200 and len(ans) > 20 and "<!doctype" not in low and "free limit" not in low and "pollinations" not in low:
                return ans
        except Exception:
            time.sleep(1)
    return ""


def _ask_gemini(prompt):
    """Ưu tiên số 1 nếu có GEMINI_API_KEY."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return ""
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.75, "maxOutputTokens": 800}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["candidates"][0]["content"]["parts"][0].get("text") or "").strip()


def ask_llm(prompt, validate=None):
    """Gọi LLM với timeout cứng; tự làm sạch câu mở đầu rườm rà trước khi kiểm tra validate."""
    for fn in (_ask_gemini, _ask_g4f, _ask_pollinations):
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            raw = ex.submit(fn, prompt).result(timeout=LLM_TIMEOUT)
            ans = clean_direct_text(raw)
            if ans and (validate is None or validate(ans)):
                return ans
        except (FutTimeout, Exception) as e:
            print(f"[LLM {fn.__name__}]: {e}")
        finally:
            ex.shutdown(wait=False)
    return ""


def _extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Lịch sử (dùng chung content_balance_state.json)
# ----------------------------------------------------------------------------
def _state():
    return radar.load_balance_state()


def _used(st, key):
    return key in set(st.get("posted_urls", []))


def record(kind, key, title=""):
    st = _state()
    st.setdefault("posted_urls", []).append(key)
    st["posted_urls"] = st["posted_urls"][-500:]
    log = st.setdefault("post_log", [])
    log.append({"t": int(time.time()), "kind": kind, "title": (title or "")[:140]})
    st["post_log"] = log[-80:]
    radar.save_balance_state(st)


def _pick_unused(items, st, prefix):
    pool = [i for i in items if not _used(st, f"{prefix}_{i['id']}")]
    if not pool:
        pool = items
    return random.choice(pool)


# ----------------------------------------------------------------------------
# Kho dự phòng viết sẵn (trực diện, gọn, tự nhiên)
# ----------------------------------------------------------------------------
POLL_BANK = [
    {"id": "p_sl_habit", "q": "Khi vào lệnh, các sếp thường đặt Stop Loss theo cách nào?",
     "o": ["Cố định % rủi ro trên mỗi lệnh", "Đặt theo vùng hỗ trợ/kháng cự", "Đặt theo độ biến động (ATR/nến)", "Canh cắt tay, ít khi đặt sẵn"]},
    {"id": "p_session", "q": "Khung giờ nào các sếp vào lệnh thấy hợp nhịp với mình nhất?",
     "o": ["Phiên Á (sáng)", "Đầu phiên Âu (14h-16h)", "Đầu phiên Mỹ (20h-22h)", "Chỉ vào khi có setup, không cố định giờ"]},
    {"id": "p_biggest_mistake", "q": "Thói quen nào từng làm tài khoản của các sếp hao hụt nhiều nhất?",
     "o": ["Đu theo nến đang chạy mạnh (FOMO)", "Dời SL hoặc gồng lỗ", "Chốt non nhưng gồng lỗ dài", "Tăng lot muốn gỡ nhanh sau lệnh thua"]},
    {"id": "p_journal", "q": "Sau mỗi tuần giao dịch, các sếp có xem lại lịch sử lệnh của mình không?",
     "o": ["Ghi chép và xem lại đều đặn", "Chỉ xem lại những lệnh thua lớn", "Chỉ chụp màn hình lưu lại", "Ít khi xem lại"]},
    {"id": "p_news_day", "q": "Trước giờ ra tin đỏ (CPI, Non-Farm, FOMC) 15 phút, các sếp thường làm gì?",
     "o": ["Đóng hết lệnh, đứng ngoài xem", "Dời SL về hòa vốn rồi giữ tiếp", "Giảm một nửa khối lượng", "Vẫn giữ nguyên kế hoạch ban đầu"]},
    {"id": "p_timeframe", "q": "Các sếp đang dùng khung thời gian nào làm khung chính để bấm lệnh?",
     "o": ["M5 - M15", "M30 - H1", "H4 - D1", "Nhìn H1/H4 tìm hướng, vào ở M15"]},
    {"id": "p_withdraw", "q": "Khi tài khoản có tuần lãi tốt, các sếp xử lý phần lãi đó thế nào?",
     "o": ["Rút một phần về ngân hàng ngay", "Đợi cuối tháng mới tổng kết rút", "Để nguyên nuôi tài khoản lớn hơn", "Chuyển bớt sang tài khoản phụ"]},
    {"id": "p_learn", "q": "Yếu tố nào các sếp thấy khó rèn nhất khi giao dịch thực tế?",
     "o": ["Kiên nhẫn ngồi chờ đúng vùng giá", "Chấp nhận cắt lỗ dứt khoát", "Giữ lệnh khi đã đi đúng hướng", "Đứng ngoài sau khi đã đủ mục tiêu"]},
]

SCENARIO_BANK = [
    {"id": "s_three_losses", "t": "Sáng vào 2 lệnh nhỏ đều chạm SL, đến đầu phiên Âu lại xuất hiện đúng thế nến sở trường ngay vùng cản cứng. Gặp cảnh này các sếp vẫn vào lệnh thứ 3 với khối lượng nhỏ hơn hay đóng bảng điện nghỉ luôn?"},
    {"id": "s_news_5min", "t": "Lệnh đang xanh đẹp khoảng 1.5R thì còn 10 phút nữa tới giờ công bố CPI Mỹ. Các sếp thường chốt bỏ túi luôn, chốt nửa lệnh dời SL về hòa vốn, hay giữ nguyên cược qua tin?"},
    {"id": "s_hit_target", "t": "Mới đầu phiên chiều đã hoàn thành mục tiêu ngày, nhưng tối vào phiên Mỹ thị trường lại chạy sóng rất mượt. Các sếp chọn nghỉ giữ thành quả hay trích một phần lãi buổi chiều ra đi lệnh nhỏ?"},
    {"id": "s_small_account", "t": "Với một tài khoản nhỏ khoảng 500 USD, giữa việc chia nhỏ 0.01 - 0.02 lot đánh đều tay với việc chờ thật kỹ mới vào 1 lệnh 0.05 lot, cách nào giúp các sếp giữ tâm lý ổn định hơn?"},
    {"id": "s_office", "t": "Vừa đi làm công việc chính vừa giao dịch, nhiều lúc đang họp thì giá chạm đúng vùng chờ. Các sếp hay đặt sẵn lệnh Limit kèm SL/TP từ đầu ngày hay chỉ đánh khi trực tiếp ngồi trước màn hình?"},
    {"id": "s_revenge", "t": "Cảm giác cay cú muốn vào ngay lệnh lớn để gỡ sau một cú quét SL có lẽ ai cũng từng trải qua. Các sếp có quy tắc riêng nào để khóa tay mình lại trong 15 phút đầu sau khi vừa cắt lỗ không?"},
]

GLOSSARY_BANK = [
    {"id": "g_spread", "term": "Spread",
     "t": "Nhiều anh em mới nhìn biểu đồ thấy giá chưa chạm SL mà lệnh đã đóng — thủ phạm thường là Spread (chênh lệch giá Mua - Bán).\n\nVí dụ giá Bán đang 2000.00, giá Mua 2000.25 thì spread là 2.5 pip. Lệnh Sell mở bằng giá Bán nhưng khi đóng lại tính theo giá Mua, nên lúc ra tin spread giãn rộng rất dễ quét SL đặt sát.\n\nCác sếp có hay cộng thêm phần giãn spread khi đặt SL cho lệnh Sell không?"},
    {"id": "g_slippage", "term": "Slippage",
     "t": "Bấm lệnh hay đặt SL ở 2000.00 nhưng lúc khớp lại nhảy sang 2000.40 — đó là trượt giá (Slippage).\n\nHiện tượng này xảy ra khi thị trường giật mạnh (như giây đầu ra tin Non-Farm, CPI), thanh khoản tại mức giá đặt không đủ khớp hết nên lệnh bị đẩy tới mức giá có người đối ứng tiếp theo.\n\nCác sếp từng gặp pha trượt giá nào đáng nhớ lúc giao dịch tin chưa?"},
    {"id": "g_rr", "term": "R:R",
     "t": "Thắng có 4 trên 10 lệnh mà cuối tháng tài khoản vẫn dương — điểm mấu chốt nằm ở tỷ lệ R:R (Rủi ro / Lợi nhuận).\n\nNếu mỗi lệnh chấp nhận mất 15 USD nhưng khi thắng ăn được 35 - 40 USD (R:R hơn 1:2), thì 4 lệnh thắng (+150 USD) vẫn dư sức bù 6 lệnh thua (-90 USD).\n\nThực tế giao dịch, các sếp thích đánh R:R cao (1:2, 1:3) hay đánh ngắn ăn chắc 1:1?"},
    {"id": "g_drawdown", "term": "Drawdown",
     "t": "Trong quản lý vốn, con số đáng sợ hơn một lệnh thua là Drawdown — mức sụt giảm tính từ đỉnh vốn xuống đáy.\n\nTài khoản 1,000 USD tụt xuống 500 USD là mất 50%, nhưng để từ 500 USD quay lại 1,000 USD thì phải lãi tới 100%. Vì vậy nhiều người tự đặt ngưỡng sụt giảm 10% - 15% là nghỉ vài ngày để cắt chuỗi tâm lý xấu.\n\nCác sếp có đặt mức dừng trong tuần cho tài khoản của mình không?"},
    {"id": "g_sweep", "term": "Quét thanh khoản",
     "t": "Đặt SL ngay dưới đáy cũ, giá thò râu quét đúng SL xong mới bật tăng mạnh — anh em theo trường phái SMC/Price Action hay gọi đây là pha Quét thanh khoản (Liquidity Sweep).\n\nVùng ngay sát đỉnh/đáy cũ là nơi tập trung rất nhiều lệnh dừng lỗ. Thay vì vào sớm, nhiều trader chọn đợi giá chọc qua đỉnh/đáy đó rút râu đóng nến quay lại rồi mới tìm điểm vào.\n\nCác sếp hay đặt SL cách đỉnh/đáy cũ bao nhiêu giá để hạn chế bị quét râu?"},
    {"id": "g_swap", "term": "Swap",
     "t": "Giữ lệnh vài ngày thấy có thêm khoản phí hoặc tiền cộng vào mỗi sáng — đó là phí qua đêm (Swap), phát sinh khi giữ vị thế qua thời điểm kết thúc phiên ngày của máy chủ.\n\nDo chênh lệch lãi suất giữa các đồng tiền hoặc chi phí lưu giữ hợp đồng, có chiều lệnh bị trừ phí nhưng cũng có chiều được cộng. Đánh ngắn đóng lệnh trong ngày thì không tốn khoản này.\n\nCác sếp trong nhóm mình thiên về đóng lệnh gọn trong ngày hay giữ lệnh qua đêm?"},
]

TERM_LIST = ["spread", "trượt giá (slippage)", "margin call", "đòn bẩy", "tỷ lệ R:R",
             "drawdown (mức sụt giảm tài khoản)", "quét thanh khoản (liquidity sweep)", "phí qua đêm (swap)",
             "lệnh chờ Limit và Stop", "dời SL về hòa vốn (breakeven)", "chốt lời từng phần (partial close)"]

POLL_TOPICS = ["thói quen đặt Stop Loss", "cách xử lý ngày có tin đỏ", "tâm lý sau chuỗi lệnh thua",
               "chọn khung giờ giao dịch khi đi làm", "quản lý khối lượng lệnh", "ghi nhật ký giao dịch",
               "chốt lời từng phần hay chốt một lần", "tránh FOMO khi giá chạy nhanh"]

SCENARIO_TOPICS = ["vừa thua 2 lệnh liên tiếp mà lại thấy tín hiệu mới", "có lệnh đang lãi trước giờ ra tin đỏ 10 phút",
                   "đang gồng lãi thì giá quay đầu rút một nửa lợi nhuận", "chia khối lượng cho tài khoản 500 USD",
                   "vừa đi làm văn phòng vừa canh điểm vào lệnh", "đạt mục tiêu ngày từ sớm nhưng phiên Mỹ sóng lại rất đẹp"]


# ----------------------------------------------------------------------------
# Các dạng bài
# ----------------------------------------------------------------------------
def make_poll():
    st = _state()
    topic = random.choice(POLL_TOPICS)
    raw = ask_llm(
        f"Tạo 1 câu hỏi khảo sát (poll) thực tế cho nhóm trader Việt Nam về chủ đề: {topic}. {SAFETY_RULES} "
        "Câu hỏi vào thẳng tình huống/thói quen thực tế (KHÔNG mở đầu bằng 'Mình muốn hỏi các sếp...' hay 'Các sếp ơi cho mình hỏi'). "
        'Chỉ trả về JSON đúng dạng {"question": "...", "options": ["...", "...", "...", "..."]}. '
        "Câu hỏi dưới 140 ký tự; 4 lựa chọn ngắn gọn, mỗi lựa chọn dưới 55 ký tự."
    )
    data = _extract_json(raw)
    if data and isinstance(data.get("options"), list) and 2 <= len(data["options"]) <= 5 and str(data.get("question", "")).strip():
        q = clean_direct_text(str(data["question"]))[:280]
        q = re.sub(r"^(?:các sếp ơi[,!\s]*|mình muốn hỏi\s*|cho mình hỏi\s*)+", "", q, flags=re.I).strip()
        if q:
            q = q[0].upper() + q[1:]
        opts = [str(o).strip()[:95] for o in data["options"] if str(o).strip()]
        key = f"ce_poll_gen_{abs(hash(q)) % 10**8}"
        if len(opts) >= 2 and len(q) >= 15 and not _used(st, key):
            return {"id_key": key, "kind": "poll", "title": q, "caption": q, "poll": {"question": q, "options": opts}}
    item = _pick_unused(POLL_BANK, st, "ce_poll")
    return {"id_key": f"ce_poll_{item['id']}", "kind": "poll", "title": item["q"], "caption": item["q"],
            "poll": {"question": item["q"], "options": item["o"]}}


def make_scenario():
    st = _state()
    topic = random.choice(SCENARIO_TOPICS)
    txt = ask_llm(
        f"Viết 1 bài thảo luận tình huống cực ngắn (2-3 câu, tối đa 350 ký tự) cho nhóm trader Vàng/ngoại tệ Việt Nam, chủ đề: {topic}. {SAFETY_RULES}\n"
        "YÊU CẦU CÁCH VIẾT: Đi thẳng vào tình huống ngay câu đầu tiên (ví dụ: 'Lệnh đang xanh 20 pip thì còn 10 phút nữa ra tin CPI...'), "
        "rồi hỏi ngắn gọn cách các sếp xử lý. KHÔNG dùng nhãn 'Tình huống:', KHÔNG mở đầu bằng 'Mình thấy nhiều thành viên...', KHÔNG nhắc coin/crypto, không dùng icon. Chỉ trả về nội dung bài.",
        validate=lambda a: is_clean_direct(a, 70, 420)
    )
    if txt:
        return {"id_key": f"ce_scn_gen_{abs(hash(txt)) % 10**8}", "kind": "scenario", "title": txt[:80], "caption": txt}
    item = _pick_unused(SCENARIO_BANK, st, "ce_scn")
    return {"id_key": f"ce_scn_{item['id']}", "kind": "scenario", "title": item["t"][:80], "caption": item["t"]}


def make_glossary():
    st = _state()
    terms = [t for t in TERM_LIST if not _used(st, f"ce_gloss_gen_{t}")]
    if terms:
        term = random.choice(terms)
        txt = ask_llm(
            f"Chia sẻ ngắn gọn về khái niệm '{term}' trong giao dịch Vàng/ngoại tệ theo góc nhìn thực chiến. {SAFETY_RULES}\n"
            "YÊU CẦU CÁCH VIẾT: Câu đầu tiên đi thẳng vào vấn đề thực tế mà trader hay gặp liên quan đến khái niệm này (kèm ví dụ con số dễ hình dung), "
            "đoạn hai giải thích cơ chế ngắn gọn, kết bài bằng 1 câu hỏi mở về thói quen của các sếp. "
            "Không dùng tiêu đề cứng nhắc kiểu 'Giải thích thuật ngữ:', không dùng icon, dưới 550 ký tự. Chỉ trả về nội dung bài.",
            validate=lambda a: is_clean_direct(a, 140, 750)
        )
        if txt:
            return {"id_key": f"ce_gloss_gen_{term}", "kind": "glossary", "title": f"Khái niệm: {term}", "caption": txt}
    item = _pick_unused(GLOSSARY_BANK, st, "ce_gloss")
    return {"id_key": f"ce_gloss_{item['id']}", "kind": "glossary", "title": f"Khái niệm: {item['term']}", "caption": item["t"]}


KOL_MAX_AGE_DAYS = 30
YT_THIS_MONTH = "EgIIBA%253D%253D"


def _age_days_from_text(txt):
    m = re.search(r"(\d+)\s*(min|h|d|w|mo|y)\b", txt or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"min": n / 1440, "h": n / 24, "d": n, "w": n * 7, "mo": n * 30, "y": n * 365}[unit]


def _unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def _same_channel(kol, owner):
    kol, owner = kol.lower().strip(), owner.lower().strip()
    toks = [w for w in re.split(r"\W+", kol) if w][:2]
    return bool(toks) and (kol in owner or owner in kol or all(w in owner for w in toks))


def fresh_kol_videos(max_channels=12, want=4):
    """Video MỚI (<= 30 ngày) đúng kênh KOL trong Sheet."""
    st = _state()
    try:
        rows = list(radar.fetch_online_sheets().get("YouTube", []))
    except Exception:
        rows = []
    random.shuffle(rows)
    out, checked = [], 0
    pat = (r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"\}\].*?'
           r'"publishedTimeText":\{"simpleText":"(.*?)"\}.*?"ownerText":\{"runs":\[\{"text":"(.*?)"')
    for row in rows:
        if len(row) < 3:
            continue
        kol = re.sub(r"\([^)]*\)", "", row[2]).strip()
        if not kol:
            continue
        checked += 1
        try:
            html = radar.fetch_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote(kol)}&sp={YT_THIS_MONTH}", timeout=15)
            for vid, title, pub, owner in re.findall(pat, html)[:20]:
                if sum(1 for o in out if o["kol"] == kol) >= 2:
                    break
                age = _age_days_from_text(pub)
                if age is None or age > KOL_MAX_AGE_DAYS or not _same_channel(kol, owner) or _used(st, f"ce_kol_{vid}"):
                    continue
                out.append({"video_id": vid, "kol": kol, "title": _unescape(title),
                            "source_url": f"https://www.youtube.com/watch?v={vid}",
                            "image_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"})
        except Exception:
            pass
        if len(out) >= want or checked >= max_channels:
            break
    random.shuffle(out)
    return out


def make_kol_insight(buzz):
    """Đúc kết ý thực chiến từ phụ đề thật của video KOL mới (<=30 ngày) — đi thẳng vào góc nhìn/phương pháp."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return None
    api = YouTubeTranscriptApi()
    cands = fresh_kol_videos()
    for p in cands[:5]:
        vid = p["video_id"]
        try:
            segs = api.fetch(vid, languages=["en", "en-US", "en-GB"])
            text = re.sub(r"\s+", " ", " ".join(s.text.replace("\n", " ") for s in segs))[:7000]
        except Exception:
            continue
        if len(text) < 600:
            continue
        kol = p.get("kol", "chuyên gia")
        title = p.get("title", "")
        out = ask_llm(
            f"Dưới đây là phụ đề tiếng Anh từ video '{title}' của {kol}:\n---\n{text}\n---\n"
            f"Chỉ dựa vào nội dung trên, viết 1 bài chia sẻ ngắn gọn cho nhóm trader Việt Nam. {SAFETY_RULES}\n"
            "YÊU CẦU CÁCH VIẾT:\n"
            f"1) Câu đầu đi thẳng vào luận điểm/cách xử lý đáng chú ý nhất mà {kol} nêu ra (tuyệt đối KHÔNG mở đầu bằng 'Mình vừa xem video', 'Kênh {kol} vừa chia sẻ', hay 'Đây là quan điểm của kênh').\n"
            "2) Tóm gọn 2-3 ý thực chiến cốt lõi bằng gạch đầu dòng '•' (ngắn gọn, dễ đọc lướt, không nhắc số tiền lãi/lỗ cá nhân).\n"
            "3) Kết bài bằng 1 câu hỏi mở tự nhiên để các sếp bàn luận. Nếu phụ đề không có nội dung giao dịch/phân tích thị trường rõ ràng, chỉ trả lời đúng chữ: SKIP. Dưới 650 ký tự.",
            validate=lambda a: a.strip().upper().startswith("SKIP") or is_clean_direct(a, 140, 950)
        )
        if not out or out.strip().upper().startswith("SKIP") or not is_clean_direct(out, 140, 950):
            continue
        return {"id_key": f"ce_kol_{vid}", "kind": "kol_insight", "title": f"{kol}: {title}",
                "image_url": p.get("image_url", ""), "source_url": p["source_url"], "caption": out}
    return None


def make_recap():
    st = _state()
    week_ago = time.time() - 7 * 86400
    rows = [r for r in st.get("post_log", []) if r.get("t", 0) >= week_ago and r.get("kind") in ("news", "kol_insight", "reddit", "vt", "glossary")]
    titles = [r["title"] for r in rows if r.get("title")][-5:]
    if len(titles) >= 2:
        body = "\n".join(f"• {t}" for t in titles)
        txt = (f"Khép lại một tuần giao dịch nhiều biến động, điểm nhanh vài chủ đề đáng chú ý nhóm mình đã bàn qua:\n\n{body}\n\n"
               "Tuần vừa rồi các sếp tâm đắc nhất bài học hay nhịp sóng nào? Chia sẻ cùng anh em nhé.")
    else:
        txt = ("Khép lại tuần giao dịch vừa qua, nhịp sóng nào làm các sếp ấn tượng nhất, và có điểm gì trong cách quản lý lệnh mình muốn chỉnh lại cho tuần tới không?")
    return {"id_key": f"ce_recap_{datetime.now().strftime('%Y-%m-%d')}", "kind": "recap", "title": "Tổng kết tuần", "caption": txt}


WEEKAHEAD_POLLS = [
    {"id": "w1", "q": "Bước vào tuần giao dịch mới, ưu tiên số 1 của các sếp là gì?",
     "o": ["Tuân thủ tuyệt đối SL/TP đã đặt", "Giảm số lệnh, chỉ chọn setup đẹp nhất", "Ưu tiên bảo toàn vốn trước các tin lớn", "Nghỉ ngơi, quan sát thị trường là chính"]},
    {"id": "w2", "q": "Trước khi vào lệnh đầu tiên của tuần mới, các sếp thường làm gì?",
     "o": ["Điểm qua lịch tin đỏ cả tuần", "Vẽ sẵn các mốc giá trên H4/H1", "Xem lại nhật ký lệnh tuần trước", "Đợi hết sáng thứ Hai mới tính"]},
]


def make_weekahead():
    st = _state()
    item = _pick_unused(WEEKAHEAD_POLLS, st, "ce_wk")
    return {"id_key": f"ce_wk_{item['id']}", "kind": "poll", "title": item["q"], "caption": item["q"],
            "poll": {"question": item["q"], "options": item["o"]}}


def _article_text(url):
    try:
        import trafilatura
        html = radar.fetch_url(url, timeout=12)
        return (trafilatura.extract(html, include_comments=False, include_tables=False) or "").strip()
    except Exception:
        return ""


def make_news(buzz):
    """Tin mới (<= 24h): đi thẳng vào sự kiện, con số và tác động thị trường, tinh gọn, sắc bén, không điểm báo rườm rà."""
    st = _state()
    cands = [p for p in buzz.get("macro_posts", [])
             if str(p.get("id_key", "")).startswith("http") and not _used(st, p.get("id_key", ""))]
    if not cands:
        return None
    cands.sort(key=lambda x: (0 if any(d in x.get("id_key", "") for d in ("cnbc.com", "fxempire.com", "marketwatch.com")) else 1))
    for item in cands[:5]:
        key = item["id_key"]
        text = _article_text(key)
        raw_parts = [item.get("raw_title") or item.get("title") or "", item.get("raw_summary") or "", text]
        raw_source = "\n".join(p for p in raw_parts if p).strip()
        if len(raw_source) < 40:
            continue
        out = ask_llm(
            f"Thông tin gốc:\n---\n{raw_source[:4500]}\n---\n"
            f"Viết 1 bản tin ngắn gọn, sắc bén bằng tiếng Việt cho nhóm trader. {SAFETY_RULES}\n"
            "YÊU CẦU CÁCH VIẾT:\n"
            "1) Câu đầu tiên đi thẳng ngay vào sự kiện, con số hoặc diễn biến cốt lõi (ví dụ: 'Lạm phát PCE tháng 9 của Mỹ bật tăng 0.5%, đẩy mức cả năm lên 3.6% trong khi GDP quý 3 đạt 3.4%...').\n"
            "2) TUYỆT ĐỐI CẤM mở đầu bằng 'Theo bản tin...', 'Bài báo đưa tin...', 'Trang X vừa có bài viết...', 'Mình vừa đọc...' (link nguồn đã đính kèm riêng ở cuối bài).\n"
            "3) Chỉ 1-2 câu tiếp theo nối thẳng sang ý nghĩa với thị trường (lãi suất Fed, đồng USD, tâm lý Vàng/Dầu) một cách tự nhiên, rồi kết bằng 1 câu hỏi ngắn gọn để các sếp bàn luận.\n"
            "4) Tinh gọn tối đa (3-4 câu, dài 180-480 ký tự), không dùng icon. Chỉ trả về nội dung bài.",
            validate=lambda a: is_clean_direct(a, 130, 620)
        )
        if out:
            return dict(item, kind="news", caption=out)
    return None


BANNED_ATTRIBUTION = ("Raja Banks", "Smart Risk", "Brad Goh", "Rayner", "TJR", "r/")


def make_reddit(buzz):
    """Chuyển hóa chủ đề thảo luận thực tế từ Reddit thành câu chuyện trực diện, tự nhiên (không 'Điểm nhanh một chủ đề trên r/...')."""
    st = _state()
    pool = [p for p in buzz.get("reddit_posts", []) if str(p.get("id_key", "")).startswith("reddit_thread_") and not _used(st, p["id_key"])]
    if not pool:
        return None
    random.shuffle(pool)
    for item in pool[:3]:
        raw = f"{item.get('raw_title', '')}\n{item.get('raw_body', '')}".strip()
        if len(raw) < 60:
            continue
        out = ask_llm(
            f"Chủ đề thảo luận của các trader quốc tế:\n---\n{raw[:3000]}\n---\n"
            f"Hãy truyền đạt lại góc nhìn/vấn đề thực tế trên thành 1 bài thảo luận ngắn gọn, tự nhiên cho nhóm trader Việt Nam. {SAFETY_RULES}\n"
            "YÊU CẦU CÁCH VIẾT: Đi thẳng vào vấn đề hoặc câu chuyện thực tế ngay từ câu đầu tiên (CẤM mở đầu bằng 'Điểm nhanh một chủ đề trên cộng đồng Reddit...', 'Bài viết nói về...'). "
            "Gói gọn trong 3-4 câu (dưới 500 ký tự), không icon, kết bằng 1 câu hỏi mở để các sếp chia sẻ kinh nghiệm thực tế. Chỉ trả về nội dung bài.",
            validate=lambda a: is_clean_direct(a, 120, 620)
        )
        if out:
            return dict(item, kind="reddit", caption=out)
    return None


def make_vt(buzz):
    """Chia sẻ mẹo công cụ/tính năng giao dịch trực diện, hữu ích, không văn mẫu quảng cáo."""
    st = _state()
    pool = [v for v in buzz.get("vt_posts", [])
            if not _used(st, v.get("id_key", "")) and not any(b in v.get("caption", "") for b in BANNED_ATTRIBUTION)]
    if not pool:
        return None
    chosen = dict(random.choice(pool), kind="vt")
    out = ask_llm(
        f"Nội dung gốc về công cụ giao dịch:\n---\n{chosen.get('caption', '')}\n---\n"
        f"Viết lại thật ngắn gọn, tự nhiên, đi thẳng vào mẹo sử dụng thực tế cho anh em trader. {SAFETY_RULES}\n"
        "CẤM mở đầu bằng 'Theo hướng dẫn công cụ trên website...' hay 'Theo tài liệu tính năng...'. "
        "Dài 2-3 câu (dưới 420 ký tự), không icon, kết bằng 1 câu hỏi nhẹ nhàng. Chỉ trả về nội dung bài.",
        validate=lambda a: is_clean_direct(a, 100, 520)
    )
    if out:
        chosen["caption"] = out
    return chosen


def make_discussion(buzz, dt):
    wd = dt.weekday()
    post = make_reddit(buzz) if wd in (0, 3) else make_vt(buzz) if wd == 2 else None
    return post or make_glossary()


NEEDS_BUZZ = {"news", "kol_insight", "discussion", "reddit", "vt"}


def make_post(kind, buzz=None, dt=None):
    dt = dt or datetime.now()
    if kind == "news":
        return make_news(buzz) or make_poll()
    if kind == "kol_insight":
        return make_kol_insight(buzz) or make_scenario()
    if kind == "discussion":
        return make_discussion(buzz, dt)
    if kind == "reddit":
        return make_reddit(buzz) or make_scenario()
    if kind == "vt":
        return make_vt(buzz) or make_glossary()
    if kind == "poll":
        return make_poll()
    if kind == "scenario":
        return make_scenario()
    if kind == "glossary":
        return make_glossary()
    if kind == "recap":
        return make_recap()
    if kind == "weekahead":
        return make_weekahead()
    return None
