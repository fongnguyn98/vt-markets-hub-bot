"""
Pipeline nội dung: tìm nguồn -> lọc -> lấy văn bản gốc -> trích dữ kiện kèm câu gốc -> dựng bài -> kiểm tra -> hàng đợi.
Chạy riêng với bot (python content_pipeline.py). Thiếu nguồn hoặc LLM lỗi thì không tạo bài, không có bài dự phòng.
LLM không viết tự do: nó trả JSON, code kiểm câu trích rồi dựng bài theo mẫu.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import content_queue
import validators

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_ID = "1-HgPzrchtbVtyskdawDfx5Hum4eaJK-8COgJ2Ytdoik"
INTERNAL_CHAT_ID = -1003750255534
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

TARGET_PENDING = {"video_review": 3, "thread_review": 2, "case_study": 1, "debate": 1, "poll": 2}

VIDEO_MAX_AGE_DAYS = 90
THREAD_MAX_AGE_DAYS = 30
THREAD_MIN_COMMENTS = 20
MIN_TRANSCRIPT_CHARS = 1500

TOPIC_RE = re.compile(
    r"\b(trad(?:e|er|ers|ing)|forex|gold|xau|risk|stop.?loss|journal|backtest|price action|liquidity|smc|ict|"
    r"strategy|drawdown|prop firm|funded|scalp|swing|psycholog|discipline|fomc|cpi|nfp|fed|candlestick|market structure)\b",
    re.I,
)
OFFTOPIC_RE = re.compile(
    r"mortgage|divorce|ex-husband|ex-wife|retire|bitcoin|\bbtc\b|crypto|meme|shitpost|giveaway|promo|discount|referral|"
    r"join .{0,20}rewards|removed by moderator|daily (?:discussion|thread)|for adoption|i built|my (?:bot|app|website)",
    re.I,
)
VIDEO_BLOCK_RE = re.compile(r"giveaway|signal group|copy my trades|free signals|join my|live stream|livestream|#shorts", re.I)

REDDIT_SUBS = ["Forex", "Daytrading", "RealDayTrading", "Gold", "FuturesTrading", "algotrading", "technicalanalysis", "InnerCircleTrader"]

CASE_SOURCES = [
    {"id": "warrior_trading_ftc", "url": "https://www.ftc.gov/node/78867",
     "label": "FTC"},
    {"id": "mr_pips", "url": "https://vietnamnet.vn/en/luxury-lies-and-losses-inside-mr-pips-fraud-empire-2352511.html", "label": "VietNamNet"},
    {"id": "verbo_capital", "url": "https://vietnamnet.vn/en/verbo-capital-scam-cons-4-000-victims-out-of-12-million-usd-2398740.html", "label": "VietNamNet"},
]

# Poll viết sẵn theo 6 nhóm, không dự đoán giá, không hỏi lãi lỗ
POLL_BANK = [
    {"id": "dis_rule", "group": "ky_luat", "q": "Quy tắc giao dịch nào bạn hay phá nhất?",
     "o": ["Giữ đúng điểm dừng lỗ", "Không vào lệnh ngoài kế hoạch", "Dừng sau khi thua liên tiếp", "Chưa có quy tắc viết ra"]},
    {"id": "dis_after_loss", "group": "ky_luat", "q": "Sau một lệnh thua khiến bạn bực, việc đầu tiên bạn làm là gì?",
     "o": ["Tắt màn hình một lúc", "Xem lại lệnh đó", "Tìm lệnh khác để gỡ", "Không làm gì khác thường"]},
    {"id": "risk_size", "group": "rui_ro", "q": "Bạn quyết định khối lượng lệnh theo cách nào?",
     "o": ["Theo % vốn chấp nhận mất", "Một mức cố định", "Theo cảm giác từng lệnh", "Chưa có cách cố định"]},
    {"id": "risk_stop", "group": "rui_ro", "q": "Khi nào bạn đặt điểm dừng lỗ?",
     "o": ["Trước khi vào lệnh", "Ngay sau khi khớp", "Khi giá bắt đầu đi ngược", "Thường không đặt"]},
    {"id": "method_source", "group": "phuong_phap", "q": "Bạn kiểm chứng một chiến lược mới trên mạng bằng cách nào?",
     "o": ["Backtest trên dữ liệu", "Chạy thử tài khoản demo", "Vào lệnh nhỏ tiền thật", "Thường không kiểm chứng"]},
    {"id": "method_tools", "group": "phuong_phap", "q": "Bạn đang nhìn bao nhiêu chỉ báo trên biểu đồ chính?",
     "o": ["Không có", "1 đến 2", "3 đến 4", "Từ 5 trở lên"]},
    {"id": "exp_journal", "group": "trai_nghiem", "q": "Lần gần nhất bạn xem lại nhật ký giao dịch là khi nào?",
     "o": ["Trong tuần này", "Trong tháng này", "Lâu hơn thế", "Tôi không ghi nhật ký"]},
    {"id": "exp_learn", "group": "trai_nghiem", "q": "Điều gì giúp bạn tiến bộ nhiều nhất cho tới giờ?",
     "o": ["Xem lại lệnh của mình", "Video và sách", "Trao đổi với người khác", "Chưa thấy tiến bộ rõ"]},
    {"id": "trap_dm", "group": "nhan_biet_bay", "q": "Người lạ nhắn riêng mời vào nhóm kín có chuyên gia, bạn thường làm gì?",
     "o": ["Chặn luôn", "Hỏi thêm cho biết", "Vào xem thử", "Chưa gặp trường hợp này"]},
    {"id": "trap_check", "group": "nhan_biet_bay", "q": "Dấu hiệu nào khiến bạn nghi ngờ một nền tảng đầu tư nhất?",
     "o": ["Khó rút tiền", "Khoe ảnh lãi liên tục", "Thúc nạp thêm", "Có người hứa gỡ lỗ"]},
    {"id": "quiz_drawdown", "group": "cau_do", "q": "Tài khoản giảm 50%, cần lãi bao nhiêu % để về lại mức cũ?",
     "o": ["50%", "75%", "100%", "150%"]},
    {"id": "quiz_spread", "group": "cau_do", "q": "Spread giãn rộng thường xảy ra lúc nào?",
     "o": ["Khi ra tin lớn", "Giữa phiên ổn định", "Khi mở biểu đồ", "Không bao giờ"]},
]

STATS = Counter()


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def reject(reason):
    STATS[reason] += 1


def fetch_url(url, timeout=15):
    try:
        from curl_cffi import requests as cffi_req
        r = cffi_req.get(url, impersonate="chrome120", timeout=timeout)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def ask_json(prompt):
    """Chỉ dùng một nhà cung cấp. Lỗi thì không có bài."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        reject("llm_no_key")
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4000, "responseMimeType": "application/json"}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        log(f"LLM lỗi: {e}")
        reject("llm_error")
        return None


RULES = (
    "Viết tiếng Việt tự nhiên, gọi người đọc là 'bạn'. Không dùng 'các sếp', không dùng icon, không dùng markdown. "
    "Chỉ dùng thông tin trong nguồn; không thêm con số nào không có trong nguồn. Không khuyên mua, bán, nạp tiền, không dự đoán giá, không hứa lợi nhuận. "
    "Mọi trường 'quote' phải chép nguyên văn tiếng gốc, đúng từng chữ, từ nguồn, dài 8 đến 30 từ. "
    "Nhận xét nhắm vào luận điểm, không kết luận tác giả lừa đảo. Chỉ trả về JSON."
)


# ----------------------------------------------------------------------------
# Tìm và lấy nguồn
# ----------------------------------------------------------------------------
def youtube_channels():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=YouTube"
    try:
        rows = list(csv.reader(fetch_url(url).splitlines()))[1:]
    except Exception as e:
        log(f"Không đọc được Sheet YouTube: {e}")
        reject("sheet_error")
        return []
    names = [re.sub(r"\([^)]*\)", "", r[2]).strip() for r in rows if len(r) >= 3 and r[2].strip()]
    random.shuffle(names)
    return names


def _age_days(text):
    m = re.search(r"(\d+)\s*(min|h|d|w|mo|y)", text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"min": n / 1440, "h": n / 24, "d": n, "w": n * 7, "mo": n * 30, "y": n * 365}[unit]


def _same_channel(name, owner):
    name, owner = name.lower().strip(), owner.lower().strip()
    toks = [w for w in re.split(r"\W+", name) if w][:2]
    return bool(toks) and (name in owner or owner in name or all(w in owner for w in toks))


def find_videos(want=5, max_channels=15):
    pat = (r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"\}\].*?'
           r'"publishedTimeText":\{"simpleText":"(.*?)"\}.*?"ownerText":\{"runs":\[\{"text":"(.*?)"')
    known = content_queue.known_ids()
    out = []
    for name in youtube_channels()[:max_channels]:
        try:
            html = fetch_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote(name)}&sp=EgIIBQ%253D%253D")
        except Exception:
            reject("youtube_search_error")
            continue
        for vid, title, pub, owner in re.findall(pat, html)[:20]:
            age = _age_days(pub)
            try:
                title = json.loads('"' + title + '"')
            except Exception:
                pass
            if age is None or age > VIDEO_MAX_AGE_DAYS:
                continue
            if not _same_channel(name, owner) or f"video_{vid}" in known:
                continue
            if VIDEO_BLOCK_RE.search(title) or OFFTOPIC_RE.search(title):
                reject("video_filtered")
                continue
            out.append({"video_id": vid, "title": title, "author": owner, "published": pub})
            break
        if len(out) >= want:
            break
    return out


def fetch_transcript(video_id):
    """Trả về (đoạn phụ đề, loại phụ đề). Không có phụ đề thì coi như chưa xem video."""
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        api = YouTubeTranscriptApi()
        listing = api.list(video_id)
        try:
            t = listing.find_manually_created_transcript(["en", "en-US", "en-GB"])
            kind = "manual"
        except Exception:
            t = listing.find_generated_transcript(["en", "en-US", "en-GB"])
            kind = "auto"
        segs = [{"text": s.text.replace("\n", " "), "start": s.start} for s in t.fetch()]
        return segs, kind
    except Exception as e:
        reason = type(e).__name__
        reject(f"transcript_{reason}")
        log(f"Không lấy được phụ đề {video_id}: {reason}")
        return None, None


def find_threads(want=4):
    known = content_queue.known_ids()
    subs = REDDIT_SUBS[:]
    random.shuffle(subs)
    out = []
    now = time.time()
    for sub in subs:
        try:
            data = json.loads(fetch_url(f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit={sub}&sort=desc&limit=100", timeout=20))
        except Exception:
            reject("reddit_search_error")
            continue
        rows = data.get("data", [])
        rows.sort(key=lambda r: r.get("num_comments", 0), reverse=True)
        for p in rows[:25]:
            title = (p.get("title") or "").strip()
            body = (p.get("selftext") or "").strip()
            pid = p.get("id")
            if not pid or f"thread_{pid}" in known or body in ("[removed]", "[deleted]"):
                continue
            if now - p.get("created_utc", 0) > THREAD_MAX_AGE_DAYS * 86400:
                continue
            if OFFTOPIC_RE.search(title) or not TOPIC_RE.search(title + " " + body[:400]):
                reject("thread_filtered")
                continue
            comments = fetch_comments(pid)
            if len(comments) < THREAD_MIN_COMMENTS:
                reject("thread_few_comments")
                continue
            out.append({"id": pid, "sub": sub, "title": title, "body": body[:2500], "comments": comments,
                        "url": f"https://www.reddit.com{p.get('permalink')}"})
            break
        if len(out) >= want:
            break
    return out


def fetch_comments(pid):
    try:
        data = json.loads(fetch_url(f"https://arctic-shift.photon-reddit.com/api/comments/search?link_id={pid}&limit=100", timeout=20))
    except Exception:
        reject("reddit_comment_error")
        return []
    rows = []
    for c in data.get("data", []):
        text = (c.get("body") or "").strip()
        if len(text) >= 40 and text not in ("[removed]", "[deleted]") and (c.get("author") or "") != "AutoModerator":
            rows.append(text[:700])
    return rows


def fetch_article(url):
    try:
        import trafilatura
        return (trafilatura.extract(fetch_url(url, timeout=25), include_comments=False, include_tables=False) or "").strip()
    except Exception:
        reject("article_error")
        return ""


# ----------------------------------------------------------------------------
# Dựng bài
# ----------------------------------------------------------------------------
def _facts_ok(rows, source):
    good = [r for r in rows if isinstance(r, dict) and validators.quote_in_source(r.get("quote", ""), source)]
    if len(good) < len(rows):
        reject("quote_dropped")
    return good


def _timestamp(quote, segs):
    """Mốc thời gian do code tính từ phụ đề, không lấy từ LLM."""
    joined, starts = "", []
    for seg in segs:
        starts.append((len(joined), seg["start"]))
        joined += validators._norm(seg["text"]) + " "
    pos = joined.find(validators._norm(quote))
    if pos < 0:
        return ""
    sec = int([st for offset, st in starts if offset <= pos][-1])
    return f"{sec // 60:02d}:{sec % 60:02d}"


def build_video_review(video, segs, kind):
    source = re.sub(r"\s+", " ", " ".join(s["text"] for s in segs))
    if len(source) < MIN_TRANSCRIPT_CHARS:
        reject("transcript_too_short")
        return None
    data = ask_json(
        f"Phụ đề video '{video['title']}' của {video['author']}:\n---\n{source[:12000]}\n---\n"
        "Đọc phụ đề và trả JSON: {\"relevant\": true nếu video có phương pháp hoặc luận điểm giao dịch cụ thể, false nếu chỉ khoe, quảng cáo hay chung chung, "
        "\"topic\": một trong [quan_tri_rui_ro, tam_ly, phuong_phap, phan_tich_thi_truong, kiem_chung, nhan_biet_bay], "
        "\"summary\": một câu tiếng Việt video bàn gì, "
        "\"points\": 2-3 mục {\"text\": ý chính, \"quote\": câu gốc}, "
        "\"claims\": 1-2 mục {\"claim\": tuyên bố quan trọng nhất của tác giả, \"quote\": câu gốc, \"evidence\": video đưa bằng chứng gì, ghi 'không đưa bằng chứng' nếu không có}, "
        "\"fits\": hợp với ai, \"not_fits\": không hợp với ai, "
        "\"weakness\": điểm yếu cụ thể hoặc điều video không nói tới như phí, cỡ mẫu, giai đoạn thị trường, "
        "\"author_interest\": tác giả có quảng cáo sàn, khóa học hay dịch vụ gì trong phụ đề không, ghi 'không thấy trong phụ đề' nếu không, "
        "\"question\": một câu hỏi về trải nghiệm thật của người đọc}. " + RULES
    )
    if not data or not data.get("relevant"):
        reject("video_not_relevant" if data else "video_no_llm")
        return None
    points = _facts_ok(data.get("points", []), source)
    claims = _facts_ok(data.get("claims", []), source)
    if len(points) < 2 or not claims:
        reject("video_few_verified_facts")
        return None

    url = f"https://www.youtube.com/watch?v={video['video_id']}"
    code_numbers = []
    pt_lines = []
    for p in points:
        ts = _timestamp(p["quote"], segs)
        code_numbers.append(ts)
        pt_lines.append(f"- {p['text']}" + (f" (phút {ts})" if ts else ""))
    claim_lines = [f"- Tuyên bố (chưa kiểm chứng): {c['claim']}\n  Bằng chứng video đưa ra: {c.get('evidence', 'không đưa bằng chứng')}" for c in claims]
    claims_text = [c["claim"] for c in claims]
    source_label = "phụ đề của tác giả" if kind == "manual" else "phụ đề tự động, có thể sai chữ và số"
    text = "\n".join([
        "REVIEW VIDEO. Tóm tắt do AI từ phụ đề, bot đăng tự động.",
        f"Chủ đề: {data.get('summary', '')}",
        f"Nguồn: {video['author']} · YouTube · {url}",
        f"Nguồn lời: {source_label}",
        "",
        "Video nói gì",
        *pt_lines,
        "",
        "Tuyên bố và bằng chứng",
        *claim_lines,
        "",
        f"Hợp với ai: {data.get('fits', '')}",
        f"Không hợp với ai: {data.get('not_fits', '')}",
        f"Bot nhận xét: {data.get('weakness', '')}",
        f"Lợi ích của tác giả: {data.get('author_interest', '')}",
        "",
        data.get("question", ""),
        "Đây không phải khuyến nghị giao dịch.",
    ])
    generated = "\n".join([data.get("summary", ""), data.get("fits", ""), data.get("not_fits", ""), data.get("weakness", ""),
                           data.get("question", "")] + [p["text"] for p in points] + claims_text)
    return {"id": f"video_{video['video_id']}", "kind": "video_review", "title": f"{video['author']}: {video['title']}",
            "author": video["author"], "platform": "YouTube", "transcript_kind": kind, "topic": data.get("topic", ""),
            "source_url": url, "text": text, "facts": points + claims, "claims_text": claims_text,
            "generated_text": generated, "source_text": source[:20000], "code_numbers": code_numbers}


def _thread_source(th):
    return th["title"] + "\n" + th["body"] + "\n" + "\n".join(th["comments"])


def build_thread_items(th, want_debate):
    source = _thread_source(th)
    data = ask_json(
        f"Thread trên r/{th['sub']}:\n---\n{source[:12000]}\n---\n"
        "Trả JSON: {\"relevant\": true nếu thread bàn một vấn đề giao dịch có lập luận thật, "
        "\"topic\": một trong [quan_tri_rui_ro, tam_ly, phuong_phap, phan_tich_thi_truong, kiem_chung, nhan_biet_bay], "
        "\"summary\": một câu tiếng Việt thread bàn gì, "
        "\"has_two_sides\": true chỉ khi các bình luận thật sự có hai phía khác nhau, "
        "\"side_a\": {\"text\": lập luận mạnh nhất phía A, \"quote\": câu gốc từ bình luận}, "
        "\"side_b\": {\"text\": lập luận mạnh nhất phía B, \"quote\": câu gốc từ bình luận}, "
        "\"missing\": điều cả hai phía chưa nói, "
        "\"survivor_note\": true nếu thread có người khoe kết quả, "
        "\"debate_question\": câu hỏi về một quyết định cách làm, không hỏi về lệnh hay giá cụ thể, dưới 200 ký tự, "
        "\"option_a\": lựa chọn cho phía A dưới 90 ký tự, \"option_b\": lựa chọn cho phía B dưới 90 ký tự, "
        "\"question\": một câu hỏi về trải nghiệm thật của người đọc}. " + RULES
    )
    if not data or not data.get("relevant") or not data.get("has_two_sides"):
        reject("thread_no_two_sides" if data else "thread_no_llm")
        return None
    sides = _facts_ok([data.get("side_a") or {}, data.get("side_b") or {}], source)
    if len(sides) < 2:
        reject("thread_side_unverified")
        return None
    a, b = sides
    note = "Lưu ý: người khoe kết quả thường nói nhiều hơn người đã bỏ cuộc, nên thread này có thể lệch." if data.get("survivor_note") else ""
    generated = "\n".join([data.get("summary", ""), a["text"], b["text"], data.get("missing", ""), data.get("question", ""),
                           data.get("debate_question", ""), data.get("option_a", ""), data.get("option_b", "")])
    base = {"topic": data.get("topic", ""), "source_url": th["url"], "facts": sides, "generated_text": generated,
            "source_text": source[:20000], "author": f"r/{th['sub']}"}
    if want_debate and data.get("debate_question") and data.get("option_a") and data.get("option_b"):
        text = "\n".join(filter(None, [
            "TRANH LUẬN. AI dựng từ một thread thật, không phải thành viên nhóm nói.",
            f"Câu hỏi: {data['debate_question']}",
            "",
            f"Phe A: {a['text']}",
            f"Phe B: {b['text']}",
            f"Cả hai phe chưa nói: {data.get('missing', '')}",
            f"Nguồn: {th['url']}",
            note,
            "",
            "Bỏ phiếu ở poll bên dưới. Bot không đứng về phe nào. Kết quả đăng sau 48 giờ.",
        ]))
        return dict(base, id=f"thread_{th['id']}", kind="debate", title=data["debate_question"], text=text,
                    code_numbers=["48"], poll={"question": data["debate_question"],
                                               "options": [data["option_a"], data["option_b"], "Tùy trường hợp"]})
    text = "\n".join(filter(None, [
        "REVIEW THẢO LUẬN. AI tóm tắt từ một thread thật, không đại diện cho ai.",
        f"Chủ đề: {data.get('summary', '')}",
        f"Nguồn: r/{th['sub']} · {th['url']}",
        "",
        f"Một phía: {a['text']}",
        f"Phía kia: {b['text']}",
        f"Cả hai chưa nói: {data.get('missing', '')}",
        note,
        "",
        data.get("question", ""),
    ]))
    return dict(base, id=f"thread_{th['id']}", kind="thread_review", title=f"r/{th['sub']}: {th['title']}", text=text, code_numbers=[])


def build_case(case, source):
    if len(source) < 500:
        reject("case_source_short")
        return None
    data = ask_json(
        f"Tài liệu về một vụ việc có thật ({case['label']}):\n---\n{source[:12000]}\n---\n"
        "Trả JSON: {\"title\": tên vụ việc, \"what\": chuyện gì xảy ra, 2 câu, "
        "\"mechanism\": cơ chế gây thiệt hại, 2 câu, "
        "\"figures\": 1-3 mục {\"text\": con số quan trọng, \"quote\": câu gốc chứa số đó}, "
        "\"status\": trạng thái pháp lý theo tài liệu, dùng 'bị cáo buộc' nếu chưa có bản án, không nêu tên cá nhân, "
        "\"lesson\": 2-3 dấu hiệu người đọc nên nhận ra, "
        "\"question\": một câu hỏi về việc người đọc từng gặp dấu hiệu nào}. " + RULES
    )
    if not data:
        reject("case_no_llm")
        return None
    figures = _facts_ok(data.get("figures", []), source)
    if not figures:
        reject("case_no_verified_figure")
        return None
    text = "\n".join([
        f"CASE STUDY: {data.get('title', '')}. AI tóm tắt từ tài liệu gốc, bot đăng tự động.",
        f"Nguồn: {case['label']} · {case['url']}",
        "",
        f"Chuyện gì xảy ra: {data.get('what', '')}",
        f"Cơ chế: {data.get('mechanism', '')}",
        "Con số: " + "; ".join(f["text"] for f in figures),
        f"Trạng thái: {data.get('status', '')}",
        f"Dấu hiệu cần nhận ra: {data.get('lesson', '')}",
        "",
        data.get("question", ""),
    ])
    generated = "\n".join([data.get("what", ""), data.get("mechanism", ""), data.get("status", ""), data.get("lesson", ""),
                           data.get("question", "")] + [f["text"] for f in figures])
    return {"id": f"case_{case['id']}", "kind": "case_study", "title": data.get("title", case["id"]), "topic": "nhan_biet_bay",
            "source_url": case["url"], "text": text, "facts": figures, "generated_text": generated,
            "source_text": source[:20000], "code_numbers": []}


def build_poll(entry):
    return {"id": f"poll_{entry['id']}", "kind": "poll", "group": entry["group"], "title": entry["q"],
            "topic": entry["group"], "poll": {"question": entry["q"], "options": entry["o"]}}


# ----------------------------------------------------------------------------
# Chạy
# ----------------------------------------------------------------------------
def enqueue(item, dry_run):
    if not item:
        return False
    errors = validators.check_item(item)
    if errors:
        for e in errors:
            reject("validator_" + e.split(":")[0])
        log(f"Loại {item.get('id')}: {errors}")
        return False
    if dry_run:
        log(f"[dry-run] Đạt: {item['id']}\n{item.get('text') or item['poll']['question']}")
    else:
        content_queue.add_item(item)
        log(f"Đã vào hàng đợi: {item['id']}")
    return True


def notify_internal(text):
    token = os.environ.get("VT_BOT_TOKEN", "").strip()
    if not token:
        return
    body = json.dumps({"chat_id": INTERNAL_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        log(f"Không báo được nội bộ: {e}")


def run(dry_run=False, only=None):
    have = Counter(i["kind"] for i in content_queue.pending_items())
    need = {k: max(0, v - have[k]) for k, v in TARGET_PENDING.items()}
    if only:
        need = {k: (v if k in only else 0) for k, v in need.items()}
    log(f"Hàng đợi hiện có: {dict(have)}; cần thêm: {need}")
    added = Counter()

    if need["poll"]:
        known = content_queue.known_ids()
        pool = [p for p in POLL_BANK if f"poll_{p['id']}" not in known]
        random.shuffle(pool)
        for entry in pool[:need["poll"]]:
            if enqueue(build_poll(entry), dry_run):
                added["poll"] += 1

    if need["video_review"]:
        for video in find_videos(want=need["video_review"] + 3):
            if added["video_review"] >= need["video_review"]:
                break
            segs, kind = fetch_transcript(video["video_id"])
            if not segs:
                continue
            if enqueue(build_video_review(video, segs, kind), dry_run):
                added["video_review"] += 1

    if need["thread_review"] or need["debate"]:
        for th in find_threads(want=need["thread_review"] + need["debate"] + 2):
            want_debate = added["debate"] < need["debate"]
            if not want_debate and added["thread_review"] >= need["thread_review"]:
                break
            item = build_thread_items(th, want_debate)
            if enqueue(item, dry_run):
                added[item["kind"]] += 1

    if need["case_study"]:
        known = content_queue.known_ids()
        for case in [c for c in CASE_SOURCES if f"case_{c['id']}" not in known]:
            if enqueue(build_case(case, fetch_article(case["url"])), dry_run):
                added["case_study"] += 1
                break

    log(f"Đã thêm: {dict(added)}; lý do loại: {dict(STATS)}")
    if not dry_run and not sum(added.values()) and any(need.values()):
        notify_internal(f"Pipeline nội dung không tạo được bài nào. Cần thêm: {need}. Lý do: {dict(STATS)}")
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Không ghi vào hàng đợi")
    ap.add_argument("--only", nargs="*", choices=validators.KINDS)
    args = ap.parse_args()
    run(dry_run=args.dry_run, only=args.only)
