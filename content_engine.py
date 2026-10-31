"""
Content engine: đa dạng hoá nội dung bot & tạo tương tác thật cho cộng đồng.

Nguyên tắc:
- KHÔNG gán cho KOL/Reddit những điều họ không nói: bài KOL chỉ viết khi đọc được phụ đề thật của video.
- Nhiều dạng bài: tóm tắt video thật, poll, câu hỏi tình huống, giải thích thuật ngữ, tổng kết cuối tuần.
- LLM (g4f/Pollinations) chỉ là bộ viết; mọi dạng bài đều có kho dự phòng viết sẵn nên bot không bao giờ im hoặc đăng bài rỗng.
- Không khuyên mua/bán, không dự đoán giá, không hứa lợi nhuận.
"""
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import datetime, timedelta

import news_and_kol_radar as radar

LLM_TIMEOUT = 45

SAFETY_RULES = (
    "Quy tắc bắt buộc: xưng 'mình', gọi người đọc là 'các sếp'; tiếng Việt đời thường; "
    "KHÔNG khuyên mua/bán, KHÔNG dự đoán giá tăng/giảm, KHÔNG hứa hẹn lợi nhuận, KHÔNG dùng ký tự ** hay markdown."
)

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
    """Ưu tiên số 1 nếu có GEMINI_API_KEY (ổn định hơn LLM miễn phí trên GitHub Actions)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return ""
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")  # alias luôn trỏ tới bản Flash mới nhất, tránh model bị ngừng
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.8, "maxOutputTokens": 900}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["candidates"][0]["content"]["parts"][0].get("text") or "").strip()


def ask_llm(prompt, validate=None):
    """Gọi LLM với timeout cứng để không làm treo vòng getUpdates của bot.
    validate(ans) -> bool: câu trả lời không đạt thì thử nguồn LLM kế tiếp."""
    for fn in (_ask_gemini, _ask_g4f, _ask_pollinations):
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            ans = ex.submit(fn, prompt).result(timeout=LLM_TIMEOUT)
            ans = (ans or "").replace("**", "").strip()
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
    if not pool:  # kho dự phòng cạn thì cho quay vòng, tuyệt đối không để bot im
        pool = items
    return random.choice(pool)


# ----------------------------------------------------------------------------
# Kho dự phòng viết sẵn (trung lập, không khuyên mua/bán)
# ----------------------------------------------------------------------------
POLL_BANK = [
    {"id": "p_sl_habit", "q": "Các sếp thường đặt Stop Loss vào lúc nào?",
     "o": ["Đặt ngay khi vào lệnh", "Đặt sau khi lệnh chạy một lúc", "Chỉ nhắm trong đầu, không đặt", "Tuỳ lệnh, không cố định"]},
    {"id": "p_session", "q": "Khung giờ nào các sếp hay theo dõi thị trường nhất?",
     "o": ["Phiên Á (sáng)", "Đầu phiên Âu (14h-16h)", "Đầu phiên Mỹ (20h-22h)", "Rảnh lúc nào xem lúc đó"]},
    {"id": "p_biggest_mistake", "q": "Lỗi nào khiến các sếp tiếc nhất trong tháng qua?",
     "o": ["Vào lệnh vì FOMO", "Gồng lỗ quá lâu", "Chốt lãi quá sớm", "Vào khối lượng quá lớn", "Tháng này không mắc lỗi nào"]},
    {"id": "p_journal", "q": "Các sếp có ghi nhật ký giao dịch không?",
     "o": ["Ghi đều từng lệnh", "Thỉnh thoảng mới ghi", "Chỉ chụp màn hình", "Chưa bao giờ ghi"]},
    {"id": "p_news_day", "q": "Ngày có tin đỏ (CPI, NFP, FOMC) các sếp xử lý thế nào?",
     "o": ["Đứng ngoài hoàn toàn", "Giảm khối lượng", "Vẫn giao dịch như thường", "Chỉ vào sau khi tin ra xong"]},
    {"id": "p_timeframe", "q": "Khung thời gian chính các sếp dùng để tìm điểm vào lệnh?",
     "o": ["M5 - M15", "M30 - H1", "H4 trở lên", "Kết hợp nhiều khung"]},
    {"id": "p_withdraw", "q": "Các sếp có thói quen rút lợi nhuận định kỳ không?",
     "o": ["Rút đều hàng tuần", "Rút hàng tháng", "Để cộng dồn vốn", "Chưa có lãi để rút"]},
    {"id": "p_learn", "q": "Hiện giờ các sếp đang muốn học sâu hơn về mảng nào?",
     "o": ["Quản lý vốn và rủi ro", "Phân tích kỹ thuật", "Đọc tin tức vĩ mô", "Tâm lý giao dịch"]},
]

SCENARIO_BANK = [
    {"id": "s_three_losses", "t": "Tình huống: sáng nay các sếp thua liên tiếp 3 lệnh nhỏ, vẫn còn một lệnh đẹp theo kế hoạch xuất hiện. Các sếp sẽ vào tiếp, nghỉ hẳn hay giảm khối lượng? Chia sẻ cách xử lý của mình giúp anh em nhé."},
    {"id": "s_news_5min", "t": "Còn 5 phút nữa có tin đỏ của Mỹ, các sếp đang có lệnh đang lãi nhẹ. Các sếp thường chốt, dời SL về hoà vốn hay để nguyên? Mỗi người một cách, kể thử xem."},
    {"id": "s_hit_target", "t": "Mới 10h sáng mà các sếp đã đạt mục tiêu lãi của cả ngày. Các sếp tắt máy luôn hay vẫn ngồi canh tiếp? Lý do là gì?"},
    {"id": "s_small_account", "t": "Giả sử tài khoản 500 USD, các sếp chọn rủi ro tối đa bao nhiêu phần trăm cho mỗi lệnh và vì sao? Em muốn nghe kinh nghiệm thật từ anh em."},
    {"id": "s_office", "t": "Các sếp đi làm văn phòng, giờ nghỉ trưa chỉ có 30 phút. Các sếp dùng khoảng thời gian đó để làm gì với thị trường: xem biểu đồ, đặt lệnh chờ hay không đụng vào?"},
    {"id": "s_revenge", "t": "Vừa dính lệnh thua lớn, tay đang muốn vào gỡ ngay. Cách nào giúp các sếp kìm lại được cái tay đó? Ai có mẹo hay thì chia sẻ cho anh em."},
]

GLOSSARY_BANK = [
    {"id": "g_spread", "term": "Spread",
     "t": "Giải thích nhanh: Spread là gì?\n\nSpread là chênh lệch giữa giá mua và giá bán. Ví dụ giá mua 2000.30, giá bán 2000.10 thì spread là 0.20 điểm. Spread càng nhỏ thì chi phí vào lệnh càng thấp, lúc có tin lớn spread thường giãn rộng.\n\nCác sếp thường để ý spread vào lúc nào trong ngày?"},
    {"id": "g_slippage", "term": "Slippage",
     "t": "Giải thích nhanh: Trượt giá (Slippage) là gì?\n\nLà khi lệnh khớp ở mức giá khác với giá lúc các sếp bấm. Hay gặp lúc thị trường chạy rất nhanh như khi ra tin đỏ. Ví dụ bấm Buy ở 2000.00 nhưng khớp ở 2000.40.\n\nCác sếp đã từng gặp trượt giá lớn chưa, lúc nào?"},
    {"id": "g_margin", "term": "Margin call",
     "t": "Giải thích nhanh: Margin call là gì?\n\nMargin là số tiền ký quỹ để giữ lệnh. Khi lỗ làm vốn còn lại xuống quá thấp so với ký quỹ, sàn sẽ cảnh báo (margin call) và có thể tự đóng lệnh (stop out). Cách đơn giản để tránh là dùng khối lượng vừa phải và luôn đặt Stop Loss.\n\nCác sếp thường giữ mức ký quỹ sử dụng khoảng bao nhiêu phần trăm?"},
    {"id": "g_leverage", "term": "Đòn bẩy",
     "t": "Giải thích nhanh: Đòn bẩy là gì?\n\nĐòn bẩy 1:100 nghĩa là với 1 USD vốn các sếp điều khiển được vị thế 100 USD. Nó khuếch đại cả lãi lẫn lỗ, nên đòn bẩy cao không có nghĩa là nên đánh nhiều hơn.\n\nCác sếp đang dùng mức đòn bẩy nào và vì sao?"},
    {"id": "g_rr", "term": "R:R",
     "t": "Giải thích nhanh: Tỷ lệ R:R là gì?\n\nR:R so sánh số tiền sẵn sàng lỗ với số tiền kỳ vọng lãi. Ví dụ rủi ro 10 USD để kỳ vọng 25 USD là R:R 1:2.5. Tỷ lệ này chỉ có ý nghĩa khi đi cùng tỷ lệ thắng thực tế của từng người.\n\nCác sếp hay dùng R:R bao nhiêu?"},
    {"id": "g_drawdown", "term": "Drawdown",
     "t": "Giải thích nhanh: Drawdown là gì?\n\nLà mức sụt giảm của tài khoản từ đỉnh vốn gần nhất xuống đáy. Vốn từ 1000 xuống 850 USD là drawdown 15%. Nhiều người chọn dừng giao dịch một thời gian khi drawdown chạm mức mình tự đặt ra.\n\nCác sếp có đặt giới hạn drawdown cho mình không?"},
    {"id": "g_sweep", "term": "Quét thanh khoản",
     "t": "Giải thích nhanh: Quét thanh khoản (Liquidity Sweep) là gì?\n\nLà khi giá chọc nhanh qua một đỉnh/đáy cũ, nơi nhiều lệnh dừng lỗ đang nằm, rồi quay lại. Nhiều trader gọi đó là quét râu. Đây là cách một số trader giải thích vì sao Stop Loss đặt sát đỉnh/đáy hay bị chạm.\n\nCác sếp có hay gặp tình huống bị quét SL rồi giá đi đúng hướng không?"},
    {"id": "g_swap", "term": "Swap",
     "t": "Giải thích nhanh: Phí qua đêm (Swap) là gì?\n\nLà khoản phí hoặc lãi nhỏ phát sinh khi giữ lệnh qua 0h theo giờ máy chủ. Lệnh đánh trong ngày đóng trước giờ đó thì không bị tính. Mỗi sản phẩm có mức swap khác nhau, các sếp xem trong thông số hợp đồng trên nền tảng.\n\nCác sếp thường đánh trong ngày hay giữ qua đêm?"},
]

TERM_LIST = ["spread", "slippage", "margin call", "đòn bẩy", "lot và pip", "stop loss", "take profit",
             "drawdown", "R:R", "nến rút râu", "hỗ trợ và kháng cự", "tin đỏ NFP", "CPI", "phiên Âu - phiên Mỹ",
             "lệnh chờ (pending order)", "trailing stop"]

POLL_TOPICS = ["thói quen đặt Stop Loss", "cách xử lý ngày có tin đỏ", "tâm lý sau chuỗi lệnh thua",
               "chọn khung giờ giao dịch khi đi làm", "quản lý khối lượng lệnh", "ghi nhật ký giao dịch",
               "chốt lời từng phần hay chốt một lần", "tránh FOMO khi giá chạy nhanh"]

SCENARIO_TOPICS = ["vừa thua liên tiếp và muốn vào gỡ", "có lệnh đang lãi trước giờ ra tin", "chốt non hay gồng lãi",
                   "chia khối lượng cho tài khoản nhỏ", "tranh thủ giờ nghỉ trưa", "đạt mục tiêu ngày nhưng vẫn muốn đánh tiếp"]


# ----------------------------------------------------------------------------
# Các dạng bài
# ----------------------------------------------------------------------------
def make_poll():
    st = _state()
    topic = random.choice(POLL_TOPICS)
    raw = ask_llm(
        f"Tạo 1 câu hỏi khảo sát (poll) cho nhóm trader Việt Nam về chủ đề: {topic}. {SAFETY_RULES} "
        'Chỉ trả về JSON đúng dạng {"question": "...", "options": ["...", "...", "...", "..."]}. '
        "Câu hỏi dưới 150 ký tự, hỏi về thói quen/kinh nghiệm của chính người trả lời; 3-4 lựa chọn, mỗi lựa chọn dưới 60 ký tự."
    )
    data = _extract_json(raw)
    if data and isinstance(data.get("options"), list) and 2 <= len(data["options"]) <= 5 and str(data.get("question", "")).strip():
        q = str(data["question"]).strip()[:290]
        opts = [str(o).strip()[:95] for o in data["options"] if str(o).strip()]
        key = f"ce_poll_gen_{abs(hash(q)) % 10**8}"
        if len(opts) >= 2 and not _used(st, key):
            return {"id_key": key, "kind": "poll", "title": q, "caption": q, "poll": {"question": q, "options": opts}}
    item = _pick_unused(POLL_BANK, st, "ce_poll")
    return {"id_key": f"ce_poll_{item['id']}", "kind": "poll", "title": item["q"], "caption": item["q"],
            "poll": {"question": item["q"], "options": item["o"]}}


def make_scenario():
    st = _state()
    topic = random.choice(SCENARIO_TOPICS)
    txt = ask_llm(
        f"Viết 1 câu hỏi tình huống ngắn (2-3 câu) cho nhóm trader Việt Nam, chủ đề: {topic}. {SAFETY_RULES} "
        "Mở đầu bằng 'Giả sử các sếp...' hoặc 'Tình huống:', mô tả tình huống đời thường rồi hỏi các sếp sẽ xử lý thế nào và mời chia sẻ kinh nghiệm. KHÔNG kể như chính bạn đang giao dịch hay có lệnh riêng, KHÔNG nhắc tiền mã hóa/coin, chỉ nói chung về giao dịch Vàng/ngoại tệ. Không dùng icon. Dưới 400 ký tự. Chỉ trả về nội dung bài.",
        validate=lambda a: 60 <= len(a) <= 600 and "?" in a
    )
    if txt and 60 <= len(txt) <= 600 and "?" in txt:
        return {"id_key": f"ce_scn_gen_{abs(hash(txt)) % 10**8}", "kind": "scenario", "title": txt[:80], "caption": txt}
    item = _pick_unused(SCENARIO_BANK, st, "ce_scn")
    return {"id_key": f"ce_scn_{item['id']}", "kind": "scenario", "title": item["t"][:80], "caption": item["t"]}


def make_glossary():
    st = _state()
    terms = [t for t in TERM_LIST if not _used(st, f"ce_gloss_gen_{t}")]
    if terms:
        term = random.choice(terms)
        txt = ask_llm(
            f"Giải thích thuật ngữ '{term}' trong giao dịch tài chính cho người mới, bằng tiếng Việt đời thường. {SAFETY_RULES} "
            "Cấu trúc: dòng đầu 'Giải thích nhanh: ...?', một đoạn giải thích kèm 1 ví dụ số tiền USD cụ thể, rồi 1 câu hỏi mở mời các sếp chia sẻ kinh nghiệm. "
            "Không icon. Dưới 700 ký tự. Chỉ trả về nội dung bài.",
            validate=lambda a: 150 <= len(a) <= 1000 and "?" in a
        )
        if txt and 150 <= len(txt) <= 1000 and "?" in txt:
            return {"id_key": f"ce_gloss_gen_{term}", "kind": "glossary", "title": f"Giải thích: {term}", "caption": txt}
    item = _pick_unused(GLOSSARY_BANK, st, "ce_gloss")
    return {"id_key": f"ce_gloss_{item['id']}", "kind": "glossary", "title": f"Giải thích: {item['term']}", "caption": item["t"]}


KOL_MAX_AGE_DAYS = 30
YT_THIS_MONTH = "EgIIBA%253D%253D"  # bộ lọc YouTube: video đăng trong tháng này


def _age_days_from_text(txt):
    """'18h ago' / '6d ago' / '2w ago' / 'Streamed 4d ago' -> số ngày; None nếu quá cũ/không hiểu."""
    m = re.search(r"(\d+)\s*(min|h|d|w|mo|y)\b", txt or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {"min": n / 1440, "h": n / 24, "d": n, "w": n * 7, "mo": n * 30, "y": n * 365}[unit]
    return days


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
    """Video MỚI (<= 30 ngày) đúng kênh KOL trong Sheet: tìm trên YouTube với bộ lọc 'tháng này' rồi đối chiếu tên kênh."""
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
                if sum(1 for o in out if o["kol"] == kol) >= 2:  # tối đa 2 video mỗi kênh
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
    """Tóm tắt video KOL dựa trên PHỤ ĐỀ THẬT. Không có phụ đề hoặc LLM lỗi thì bỏ qua (không bịa)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return None
    st = _state()
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
        kol = p.get("kol", "kênh")
        title = p.get("title", "")
        out = ask_llm(
            f"Dưới đây là phụ đề THẬT (tiếng Anh) của video '{title}' trên kênh {kol}.\n---\n{text}\n---\n"
            f"Chỉ dựa vào phụ đề trên, viết 1 bài đăng Telegram tiếng Việt cho nhóm trader. {SAFETY_RULES}\n"
            "Cấu trúc: (1) 1 câu mở đầu nêu video nói về vấn đề gì; (2) 2-3 ý chính mà người trong video thực sự nói, mỗi ý 1 dòng bắt đầu bằng dấu '•'; "
            "(3) 1 câu hỏi mở để các sếp chia sẻ kinh nghiệm hoặc quan điểm riêng. Luôn nêu rõ đó là quan điểm của kênh, không phải của nhóm. "
            "Tuyệt đối không thêm thông tin ngoài phụ đề. Không nhắc số tiền lãi/lỗ cụ thể của người trong video, không dùng ngôn từ khoe lợi nhuận. Nếu phụ đề không có nội dung giao dịch/phân tích rõ ràng, chỉ trả lời đúng một chữ: SKIP. Dưới 900 ký tự.",
            validate=lambda a: a.strip().upper().startswith("SKIP") or 150 <= len(a) <= 1500
        )
        if not out or out.strip().upper().startswith("SKIP") or not (150 <= len(out) <= 1500):
            continue
        return {"id_key": f"ce_kol_{vid}", "kind": "kol_insight", "title": f"{kol}: {title}",
                "image_url": p.get("image_url", ""), "source_url": p["source_url"], "caption": f"🎬 {kol}\n\n{out}"}
    return None


def make_recap():
    st = _state()
    week_ago = time.time() - 7 * 86400
    rows = [r for r in st.get("post_log", []) if r.get("t", 0) >= week_ago and r.get("kind") in ("news", "kol_insight", "reddit", "vt", "glossary")]
    titles = [r["title"] for r in rows if r.get("title")][-5:]
    if len(titles) >= 2:
        body = "\n".join(f"• {t}" for t in titles)
        txt = (f"Cuối tuần rồi, nhìn lại vài chủ đề nhóm mình đã bàn trong tuần:\n\n{body}\n\n"
               "Chủ đề nào hữu ích nhất với các sếp? Hoặc tuần này có bài học nào từ chính lệnh của mình muốn chia sẻ không?")
    else:
        txt = ("Cuối tuần rồi, các sếp nhìn lại tuần giao dịch vừa qua nhé: điều gì làm tốt nhất, điều gì muốn làm khác đi vào tuần sau? "
               "Chia sẻ một bài học nhỏ của mình để anh em cùng tham khảo.")
    return {"id_key": f"ce_recap_{datetime.now().strftime('%Y-%m-%d')}", "kind": "recap", "title": "Tổng kết tuần", "caption": txt}


WEEKAHEAD_POLLS = [
    {"id": "w1", "q": "Tuần mới sắp tới, các sếp ưu tiên điều gì nhất?",
     "o": ["Giữ kỷ luật SL/TP", "Giảm số lệnh, tăng chất lượng", "Học thêm kiến thức mới", "Nghỉ ngơi, theo dõi là chính"]},
    {"id": "w2", "q": "Đầu tuần các sếp hay làm gì trước khi vào lệnh đầu tiên?",
     "o": ["Xem lịch kinh tế cả tuần", "Xem lại nhật ký tuần trước", "Vẽ vùng giá quan trọng", "Không chuẩn bị gì đặc biệt"]},
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
    """Tin mới (<= 24h) từ RSS: ưu tiên bài bóc được toàn văn (CNBC/MarketWatch/FXEmpire) để LLM viết tự nhiên."""
    st = _state()
    cands = [p for p in buzz.get("macro_posts", [])
             if str(p.get("id_key", "")).startswith("http") and not _used(st, p.get("id_key", ""))]
    if not cands:
        return None
    # Ưu tiên các nguồn không chặn bóc toàn văn trước
    cands.sort(key=lambda x: (0 if any(d in x.get("id_key", "") for d in ("cnbc.com", "fxempire.com", "marketwatch.com")) else 1))
    for item in cands[:4]:
        key = item["id_key"]
        text = _article_text(key)
        raw_source = text if len(text) > 300 else f"Tiêu đề: {item.get('title', '')}"
        if len(raw_source) < 40:
            continue
        src = urllib.parse.urlparse(key).netloc.replace("www.", "")
        out = ask_llm(
            f"Dưới đây là nội dung bản tin từ {src}:\n---\n{raw_source[:5000]}\n---\n"
            f"Chỉ dựa vào thông tin trên, viết 1 bài đăng Telegram tiếng Việt cho nhóm trader. {SAFETY_RULES}\n"
            f"Cấu trúc: (1) 1-2 câu nêu sự kiện/số liệu chính, dẫn nguồn {src}; (2) 1-2 câu giải thích vì sao tin này đáng chú ý với thị trường "
            "(USD, lãi suất, Vàng) sát với nội dung bài; (3) 1 câu hỏi mở để các sếp chia sẻ góc nhìn. Không icon. Dưới 700 ký tự. Chỉ trả về nội dung bài.",
            validate=lambda a: 140 <= len(a) <= 1100 and "?" in a
        )
        if out:
            post = dict(item, kind="news", caption=out)
            return post
    return None


BANNED_ATTRIBUTION = ("Raja Banks", "Smart Risk", "Brad Goh", "Rayner", "TJR", "r/")


def make_reddit(buzz):
    """Chỉ đăng thread Reddit thật (có nội dung); không có thì trả None."""
    st = _state()
    pool = [p for p in buzz.get("reddit_posts", []) if str(p.get("id_key", "")).startswith("reddit_thread_") and not _used(st, p["id_key"])]
    if not pool:
        return None
    return dict(random.choice(pool), kind="reddit")


def make_vt(buzz):
    """Chỉ đăng bài VT thuần thông tin sản phẩm, chưa đăng, không gán lời cho KOL/Reddit."""
    st = _state()
    pool = [v for v in buzz.get("vt_posts", [])
            if not _used(st, v.get("id_key", "")) and not any(b in v.get("caption", "") for b in BANNED_ATTRIBUTION)]
    if not pool:
        return None
    return dict(random.choice(pool), kind="vt")


def make_discussion(buzz, dt):
    """Slot tối: xoay vòng theo thứ để không bao giờ giống nhau 2 ngày liền."""
    wd = dt.weekday()
    post = make_reddit(buzz) if wd in (0, 3) else make_vt(buzz) if wd == 2 else None
    return post or make_glossary()


NEEDS_BUZZ = {"news", "kol_insight", "discussion", "reddit", "vt"}


def make_post(kind, buzz=None, dt=None):
    """Trả về post dict (có thể có key 'poll') hoặc None."""
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
