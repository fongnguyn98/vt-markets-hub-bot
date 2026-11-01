"""
Pipeline nội dung: tìm nguồn -> lọc mật độ tín hiệu (YAKE) -> lấy văn bản gốc -> chưng cất theo mẫu Fabric (extract_wisdom + analyze_claims + rate_content) kèm câu gốc -> dựng bài -> kiểm tra (RapidFuzz + Validators) -> hàng đợi.
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
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

import content_queue
import validators

try:
    import yake as _yake
except ImportError:
    _yake = None

try:
    import feedparser as _feedparser
except ImportError:
    _feedparser = None

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_ID = "1-HgPzrchtbVtyskdawDfx5Hum4eaJK-8COgJ2Ytdoik"
LOCAL_YT_CSV = os.path.join(BASE_DIR, "Sheet2_Kenh_YouTube_KOL_Trading.csv")
INTERNAL_CHAT_ID = -1003750255534
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

TARGET_PENDING = {"video_review": 3, "thread_review": 2, "case_study": 1, "debate": 1, "poll": 2}

VIDEO_MAX_AGE_DAYS = 365
THREAD_MAX_AGE_DAYS = 30
THREAD_MIN_COMMENTS = 20
THREAD_MIN_BODY_CHARS = 250
MIN_TRANSCRIPT_CHARS = 1500

TOPIC_RE = re.compile(
    r"\b(trad(?:e|er|ers|ing)|forex|gold|xau|risk|stop.?loss|journal|backtest|price action|liquidity|smc|ict|"
    r"strategy|drawdown|prop firm|funded|scalp|swing|psycholog|discipline|fomc|cpi|nfp|fed|candlestick|market structure|"
    r"win.?rate|expectancy|order.?block|execution|slippage|spread|sizing|overtrad)\b",
    re.I,
)
OFFTOPIC_RE = re.compile(
    r"mortgage|divorce|ex-husband|ex-wife|retire|bitcoin|\bbtc\b|crypto|meme|shitpost|giveaway|promo|discount|referral|"
    r"join .{0,20}rewards|removed by moderator|daily (?:discussion|thread)|for adoption|i built|my (?:bot|app|website)|"
    r"happy meal|rate my|roast my|am i cooked|tax(?:es)?\b|which broker|best broker|payout proof|my setup",
    re.I,
)
VIDEO_BLOCK_RE = re.compile(
    r"giveaway|signal group|copy my trades|free signals|join my|live stream|livestream|#shorts|"
    r"weekly (?:forecast|outlook|breakdown)|daily (?:forecast|outlook)|market outlook for",
    re.I,
)

REDDIT_SUBS = ["Forex", "Daytrading", "RealDayTrading", "Gold", "FuturesTrading", "algotrading", "technicalanalysis", "InnerCircleTrader"]

CASE_SOURCES = [
    {"id": "warrior_trading_ftc", "url": "https://www.ftc.gov/node/78867", "label": "FTC"},
    {"id": "mr_pips", "url": "https://vietnamnet.vn/en/luxury-lies-and-losses-inside-mr-pips-fraud-empire-2352511.html", "label": "VietNamNet"},
    {"id": "verbo_capital", "url": "https://vietnamnet.vn/en/verbo-capital-scam-cons-4-000-victims-out-of-12-million-usd-2398740.html", "label": "VietNamNet"},
    {"id": "ota_ftc", "url": "https://www.ftc.gov/news-events/news/press-releases/2020/09/operators-online-trading-academy-settle-ftc-charges", "label": "FTC"},
    {"id": "ragingbull_ftc", "url": "https://www.ftc.gov/news-events/news/press-releases/2022/03/online-stock-trading-site-ragingbull-pay-2425-million-settle-ftc-charges", "label": "FTC"},
    {"id": "iml_ftc", "url": "https://www.ftc.gov/news-events/news/press-releases/2025/05/ftc-nevada-take-action-against-investment-training-pyramid-scheme-iyovia-formerly-known-im-mastery", "label": "FTC"},
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


def signal_density_ok(text, min_terms=3):
    """Lọc mật độ tín hiệu bằng LIAAD/yake + từ khóa chuyên ngành trước khi gọi LLM."""
    if not text or len(text) < 200:
        return False
    hits = set(m.group(0).lower() for m in TOPIC_RE.finditer(text[:5000]))
    if len(hits) < min_terms:
        return False
    if _yake is not None:
        try:
            kw_extractor = _yake.KeywordExtractor(lan="en", n=2, dedupLim=0.8, top=15, features=None)
            kws = " ".join(k for k, _ in kw_extractor.extract_keywords(text[:4000]))
            if not TOPIC_RE.search(kws) and len(hits) < min_terms + 1:
                return False
        except Exception:
            pass
    return True


def _parse_json_obj(raw_text):
    if not raw_text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.I)
    try:
        obj = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj[0]
    return obj if isinstance(obj, dict) else None


def _ask_pollinations_json(prompt):
    try:
        from curl_cffi import requests as cffi_req
        for model_name in ("openai-fast", "openai"):
            r = cffi_req.post(
                "https://text.pollinations.ai/openai",
                json={
                    "model": model_name,
                    "reasoning_effort": "low",
                    "messages": [
                        {"role": "system", "content": "You are a precise financial & trading research extractor. Return ONLY a valid UTF-8 JSON object matching the requested schema. Do not think at length."},
                        {"role": "user", "content": prompt[:8500]},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                impersonate="chrome120",
                timeout=45,
            )
            if r.status_code == 200 and r.text:
                payload = json.loads(r.text)
                content = payload["choices"][0]["message"]["content"]
                parsed = _parse_json_obj(content)
                if parsed:
                    return parsed
    except Exception as e:
        log(f"Pollinations JSON lỗi: {e}")
    return None


def ask_json(prompt):
    """Ưu tiên Gemini API; hỗ trợ fallback JSON kiểm chứng khi chạy pipeline thực tế."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    allow_fallback = os.environ.get("ALLOW_FREE_LLM_FALLBACK", "0") == "1"
    if not key and not allow_fallback:
        reject("llm_no_key")
        return None
    if key:
        model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"temperature": 0.25, "maxOutputTokens": 4000, "responseMimeType": "application/json"}}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parsed = _parse_json_obj(data["candidates"][0]["content"]["parts"][0]["text"])
            if parsed:
                return parsed
        except Exception as e:
            log(f"Gemini lỗi: {e}")
            if not allow_fallback:
                reject("llm_error")
                return None
    if allow_fallback:
        parsed = _ask_pollinations_json(prompt)
        if parsed:
            return parsed
    reject("llm_error" if key else "llm_no_key")
    return None


RULES = (
    "Áp dụng phương pháp chưng cất tinh hoa (danielmiessler/fabric: extract_wisdom + analyze_claims + rate_content). "
    "Viết tiếng Việt tự nhiên, sắc sảo, đi thẳng vào bản chất thực chiến. "
    "Khi đặt câu hỏi cho người đọc ('question', 'debate_question'), gọi người đọc là 'bạn' (tuyệt đối không dùng 'các sếp'). "
    "Khi tóm tắt nội dung ('summary', 'points', 'side_a', 'side_b', 'what', 'mechanism'), nêu thẳng luận điểm khách quan, không mở đầu bằng chữ 'Bạn'. "
    "Không dùng icon, không dùng markdown hay ký tự **. "
    "Tuyệt đối không dùng từ 'pip', 'pips', 'đang lãi', hay số tiền/phần trăm lợi nhuận theo ngày/tuần/tháng ở trường 'summary' và 'title'. "
    "Chỉ dùng thông tin có thật trong nguồn; KHÔNG thêm bất kỳ con số nào không xuất hiện trong văn bản nguồn (trừ khi viết bằng chữ). "
    "Không khuyên mua, bán, nạp tiền, không dự đoán giá, không hứa lợi nhuận. "
    "Mọi trường 'quote' PHẢI chép nguyên văn tiếng gốc (tiếng Anh), đúng từng chữ liên tiếp nhau từ nguồn, độ dài từ 8 đến 25 từ. "
    "Nhận xét nhắm vào luận điểm và điều kiện thị trường, không kết luận tác giả lừa đảo. Chỉ trả về JSON object."
)


# ----------------------------------------------------------------------------
# Tìm và lấy nguồn
# ----------------------------------------------------------------------------
def youtube_channels():
    names = []
    if os.path.exists(LOCAL_YT_CSV):
        try:
            with open(LOCAL_YT_CSV, "r", encoding="utf-8") as f:
                for r in list(csv.reader(f))[1:]:
                    if len(r) >= 3 and r[2].strip():
                        names.append(re.sub(r"\([^)]*\)", "", r[2]).strip())
        except Exception:
            pass
    if not names:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=YouTube"
        try:
            rows = list(csv.reader(fetch_url(url).splitlines()))[1:]
            names = [re.sub(r"\([^)]*\)", "", r[2]).strip() for r in rows if len(r) >= 3 and r[2].strip()]
        except Exception as e:
            log(f"Không đọc được Sheet YouTube: {e}")
            reject("sheet_error")
            return []
    names = list(dict.fromkeys(n for n in names if n))
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


def find_videos(want=5, max_channels=18):
    pat = (r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"\}\].*?'
           r'"publishedTimeText":\{"simpleText":"(.*?)"\}.*?"ownerText":\{"runs":\[\{"text":"(.*?)"')
    known = content_queue.known_ids()
    out = []
    for name in youtube_channels()[:max_channels]:
        try:
            html = fetch_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote(name + ' trading strategy')}")
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


def _fetch_transcript_ytdlp(video_id):
    """Fallback bằng yt-dlp khi youtube-transcript-api bị hạn chế."""
    try:
        import yt_dlp
        with tempfile.TemporaryDirectory() as tmpdir:
            opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "en-US", "en-GB"],
                "subtitlesformat": "json3",
                "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {"youtube": {"player_client": ["ios", "android", "web"]}},
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            for fname in os.listdir(tmpdir):
                if fname.endswith(".json3"):
                    with open(os.path.join(tmpdir, fname), "r", encoding="utf-8") as f:
                        j3 = json.load(f)
                    segs = []
                    for ev in j3.get("events", []):
                        if "segs" not in ev:
                            continue
                        txt = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
                        if txt:
                            segs.append({"text": txt, "start": ev.get("tStartMs", 0) / 1000.0})
                    if segs:
                        has_manual = bool((info or {}).get("subtitles", {}).get("en"))
                        return segs, ("manual" if has_manual else "auto")
    except Exception:
        pass
    return None, None


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
        segs, kind = _fetch_transcript_ytdlp(video_id)
        if segs:
            return segs, kind
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
        rows.sort(key=lambda r: (r.get("num_comments", 0) * 2 + min(len(r.get("selftext") or ""), 1500) // 50), reverse=True)
        for p in rows[:30]:
            title = (p.get("title") or "").strip()
            body = (p.get("selftext") or "").strip()
            pid = p.get("id")
            if not pid or f"thread_{pid}" in known or body in ("[removed]", "[deleted]"):
                continue
            if len(body) < THREAD_MIN_BODY_CHARS:
                reject("thread_short_body")
                continue
            if now - p.get("created_utc", 0) > THREAD_MAX_AGE_DAYS * 86400:
                continue
            if OFFTOPIC_RE.search(title) or OFFTOPIC_RE.search(body[:500]):
                reject("thread_filtered")
                continue
            if not TOPIC_RE.search(title + " " + body[:600]) or not signal_density_ok(title + " " + body, min_terms=2):
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
        if len(text) >= 50 and text not in ("[removed]", "[deleted]") and (c.get("author") or "") != "AutoModerator":
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
        f"Phụ đề video '{video['title']}' của {video['author']}:\n---\n{source[:6500]}\n---\n"
        "Đọc phụ đề và trả JSON: {"
        "\"relevant\": true nếu video phân tích phương pháp, quản trị rủi ro hoặc tâm lý giao dịch cụ thể (false nếu chỉ khoe lãi, quảng cáo hoặc nói chung chung), "
        "\"quality_score\": số nguyên từ 1 đến 10 chấm độ sâu kiến thức thực chiến (dưới 7 nếu sáo rỗng), "
        "\"topic\": một trong [quan_tri_rui_ro, tam_ly, phuong_phap, phan_tich_thi_truong, kiem_chung, nhan_biet_bay], "
        "\"summary\": một câu tiếng Việt tóm gọn phát hiện hoặc cơ chế đáng chú ý nhất trong video (không dùng từ pip), "
        "\"points\": 2-3 mục {\"text\": luận điểm thực chiến cụ thể bằng tiếng Việt (không tự thêm chữ số nếu không có trong nguồn), \"quote\": câu gốc tiếng Anh nguyên văn 8-22 từ trong phụ đề}, "
        "\"claims\": 1-2 mục {\"claim\": nhận định quan trọng của tác giả, \"quote\": câu gốc tiếng Anh nguyên văn 8-22 từ trong phụ đề, \"evidence\": bằng chứng tác giả đưa ra trong video hoặc ghi 'không đưa dữ liệu kiểm chứng'}, "
        "\"fits\": trường hợp áp dụng phù hợp, \"not_fits\": trường hợp dễ thất bại, "
        "\"weakness\": điểm mù hoặc điều kiện thị trường mà video chưa tính tới (như spread giãn, thanh khoản mỏng, cỡ mẫu backtest), "
        "\"author_interest\": tác giả có bán khóa học, nhóm tín hiệu hay tiếp thị sàn trong phụ đề không (ghi 'không thấy trong phụ đề' nếu không), "
        "\"question\": một câu hỏi ngắn gợi mở thảo luận về trải nghiệm thực tế của người đọc}. " + RULES
    )
    if not data or not data.get("relevant"):
        reject("video_not_relevant" if data else "video_no_llm")
        return None
    if int(data.get("quality_score", 8) or 8) < validators.MIN_QUALITY_SCORE:
        reject("video_low_quality")
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
        if ts:
            code_numbers.append(ts)
        pt_lines.append(f"- {p['text']}" + (f" (phút {ts})" if ts else ""))
    claim_lines = [f"- Nhận định (chưa kiểm chứng): {c['claim']} ({c.get('evidence', 'không đưa dữ liệu kiểm chứng')})" for c in claims]
    claims_text = [c["claim"] for c in claims]
    source_label = "phụ đề gốc" if kind == "manual" else "phụ đề tự động"
    interest = (data.get("author_interest") or "").strip()
    interest_line = f"- Lưu ý lợi ích tác giả: {interest}" if interest and "không thấy" not in interest.lower() else None

    text = "\n".join(x for x in [
        f"[Góc nhìn từ {video['author']}] {data.get('summary', '')}",
        "",
        "Điểm cốt lõi trong video:",
        *pt_lines,
        "",
        "Kiểm chứng & Điểm mù thực chiến:",
        *claim_lines,
        f"- Điểm khuất cần lưu ý: {data.get('weakness', '')}",
        f"- Phù hợp khi: {data.get('fits', '')} | Dễ hỏng khi: {data.get('not_fits', '')}",
        interest_line,
        "",
        data.get("question", ""),
        f"Nguồn ({source_label}, tóm tắt bởi AI): {url}",
    ] if x is not None)
    generated = "\n".join([data.get("summary", ""), data.get("fits", ""), data.get("not_fits", ""), data.get("weakness", ""),
                           data.get("question", "")] + [p["text"] for p in points] + claims_text)
    return {"id": f"video_{video['video_id']}", "kind": "video_review", "title": f"{video['author']}: {video['title']}",
            "author": video["author"], "platform": "YouTube", "transcript_kind": kind, "topic": data.get("topic", ""),
            "quality_score": int(data.get("quality_score", 8) or 8),
            "source_url": url, "text": text, "facts": points + claims, "claims_text": claims_text,
            "generated_text": generated, "source_text": source[:20000], "code_numbers": code_numbers}


def _thread_source(th):
    return th["title"] + "\n" + th["body"] + "\n" + "\n".join(th["comments"])


def build_thread_items(th, want_debate):
    source = _thread_source(th)
    data = ask_json(
        f"Thread trên r/{th['sub']}:\n---\n{source[:6500]}\n---\n"
        "Trả JSON: {"
        "\"relevant\": true nếu thread bàn sâu một vấn đề phương pháp, quản trị rủi ro hoặc tâm lý giao dịch có lập luận thật, "
        "\"quality_score\": số nguyên từ 1 đến 10 chấm chất lượng thảo luận (dưới 7 nếu chỉ than vãn hoặc khoe lệnh), "
        "\"topic\": một trong [quan_tri_rui_ro, tam_ly, phuong_phap, phan_tich_thi_truong, kiem_chung, nhan_biet_bay], "
        "\"summary\": một câu tiếng Việt tóm tắt vấn đề cốt lõi đang tranh luận (không dùng từ pip), "
        "\"has_two_sides\": true chỉ khi các bình luận thật sự có hai góc nhìn đối lập có lý lẽ, "
        "\"side_a\": {\"text\": lập luận sắc bén nhất của phía A bằng tiếng Việt, \"quote\": câu gốc tiếng Anh nguyên văn 8-22 từ trong thread}, "
        "\"side_b\": {\"text\": lập luận sắc bén nhất của phía B bằng tiếng Việt, \"quote\": câu gốc tiếng Anh nguyên văn 8-22 từ trong thread}, "
        "\"missing\": góc khuất thực tế mà cả hai phía chưa nhắc tới, "
        "\"survivor_note\": true nếu thread có hiện tượng người thắng khoe kết quả còn người thua im lặng, "
        "\"debate_question\": câu hỏi lựa chọn nguyên tắc hành động thực chiến, không hỏi về lệnh hay giá cụ thể, dưới 180 ký tự, "
        "\"option_a\": phương án A dưới 85 ký tự, \"option_b\": phương án B dưới 85 ký tự, "
        "\"question\": một câu hỏi ngắn về trải nghiệm thực tế của người đọc}. " + RULES
    )
    if not data or not data.get("relevant") or not data.get("has_two_sides"):
        reject("thread_no_two_sides" if data else "thread_no_llm")
        return None
    if int(data.get("quality_score", 8) or 8) < validators.MIN_QUALITY_SCORE:
        reject("thread_low_quality")
        return None
    sides = _facts_ok([data.get("side_a") or {}, data.get("side_b") or {}], source)
    if len(sides) < 2:
        reject("thread_side_unverified")
        return None
    a, b = sides
    note = "- Lưu ý thiên kiến sống sót: Người có lệnh thắng thường lên tiếng nhiều hơn người đã cháy tài khoản." if data.get("survivor_note") else None
    generated = "\n".join([data.get("summary", ""), a["text"], b["text"], data.get("missing", ""), data.get("question", ""),
                           data.get("debate_question", ""), data.get("option_a", ""), data.get("option_b", "")])
    base = {"topic": data.get("topic", ""), "source_url": th["url"], "facts": sides, "generated_text": generated,
            "quality_score": int(data.get("quality_score", 8) or 8),
            "source_text": source[:20000], "author": f"r/{th['sub']}"}
    if want_debate and data.get("debate_question") and data.get("option_a") and data.get("option_b"):
        text = "\n".join(x for x in [
            f"[Tranh luận thực chiến] {data['debate_question']}",
            "",
            f"- Góc nhìn A: {a['text']}",
            f"- Góc nhìn B: {b['text']}",
            f"- Điểm mù cả hai phía chưa nói: {data.get('missing', '')}",
            note,
            "",
            "Bạn nghiêng về hướng nào? Bỏ phiếu ở poll bên dưới (kết quả tổng hợp sau 48 giờ).",
            f"Nguồn (AI dựng từ thảo luận trên r/{th['sub']}): {th['url']}",
        ] if x is not None)
        return dict(base, id=f"thread_{th['id']}", kind="debate", title=data["debate_question"], text=text,
                    code_numbers=["48"], poll={"question": data["debate_question"],
                                               "options": [data["option_a"], data["option_b"], "Tùy điều kiện thị trường"]})
    text = "\n".join(x for x in [
        f"[Mổ xẻ thảo luận trên r/{th['sub']}] {data.get('summary', '')}",
        "",
        f"- Luận điểm phía A: {a['text']}",
        f"- Luận điểm phía B: {b['text']}",
        f"- Góc khuất thực tế: {data.get('missing', '')}",
        note,
        "",
        data.get("question", ""),
        f"Nguồn (AI tóm tắt từ r/{th['sub']}): {th['url']}",
    ] if x is not None)
    return dict(base, id=f"thread_{th['id']}", kind="thread_review", title=f"r/{th['sub']}: {th['title']}", text=text, code_numbers=[])


def build_case(case, source):
    if len(source) < 500:
        reject("case_source_short")
        return None
    data = ask_json(
        f"Tài liệu về một vụ việc có thật ({case['label']}):\n---\n{source[:6500]}\n---\n"
        "Trả JSON: {\"title\": tên ngắn gọn của vụ việc (không dùng từ pip trừ tên riêng Mr. Pips), "
        "\"what\": bản chất sự việc trong 1-2 câu, "
        "\"mechanism\": cơ chế tâm lý hoặc cấu trúc gây thiệt hại cho nhà đầu tư trong 1-2 câu, "
        "\"figures\": 1-3 mục {\"text\": con số thiệt hại/quy mô quan trọng từ tài liệu, \"quote\": câu gốc tiếng Anh nguyên văn 8-22 từ chứa con số đó}, "
        "\"status\": trạng thái xử lý pháp lý theo tài liệu (dùng 'bị cáo buộc' nếu chưa có phán quyết cuối cùng, không nêu tên cá nhân ngoài tên tổ chức/vụ án), "
        "\"lesson\": các dấu hiệu thực tế giúp nhận diện sớm mô hình này (viết thành câu, không tự đánh số 1 2 3), "
        "\"question\": một câu hỏi thảo luận về cách tự bảo vệ tài khoản trước dấu hiệu tương tự}. " + RULES
    )
    if not data:
        reject("case_no_llm")
        return None
    figures = _facts_ok(data.get("figures", []), source)
    if not figures:
        reject("case_no_verified_figure")
        return None
    text = "\n".join([
        f"[Hồ sơ rủi ro: {data.get('title', '')}] {data.get('what', '')}",
        "",
        f"- Cơ chế gây thiệt hại: {data.get('mechanism', '')}",
        "- Số liệu ghi nhận: " + "; ".join(f["text"] for f in figures) + f" ({data.get('status', '')})",
        f"- Dấu hiệu nhận diện sớm: {data.get('lesson', '')}",
        "",
        data.get("question", ""),
        f"Nguồn ({case['label']}, AI tóm tắt từ hồ sơ gốc): {case['url']}",
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
        for video in find_videos(want=need["video_review"] + 4):
            if added["video_review"] >= need["video_review"]:
                break
            segs, kind = fetch_transcript(video["video_id"])
            if not segs:
                continue
            if enqueue(build_video_review(video, segs, kind), dry_run):
                added["video_review"] += 1

    if need["thread_review"] or need["debate"]:
        for th in find_threads(want=need["thread_review"] + need["debate"] + 3):
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
    article_kinds = ("video_review", "thread_review", "debate", "case_study")
    need_articles = sum(need.get(k, 0) for k in article_kinds)
    added_articles = sum(added.get(k, 0) for k in article_kinds)
    if not dry_run and need_articles > 0 and added_articles == 0:
        notify_internal(f"Pipeline nội dung không tạo được bài viết mới. Cần thêm: {need}. Đã thêm: {dict(added)}. Lý do loại: {dict(STATS)}")
    return added


if __name__ == "__main__":
    os.environ.setdefault("ALLOW_FREE_LLM_FALLBACK", "1")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Không ghi vào hàng đợi")
    ap.add_argument("--only", nargs="*", choices=validators.KINDS)
    args = ap.parse_args()
    run(dry_run=args.dry_run, only=args.only)
