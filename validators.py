"""
Bộ kiểm tra chạy trước khi một bài được vào hàng đợi và trước khi bot đăng.
Một lỗi là loại bài. File này không gọi mạng và không gọi LLM.
"""
import re
import unicodedata

KINDS = ("video_review", "thread_review", "case_study", "debate", "poll")

AI_LABEL = "AI"

# Pip và thu nhập không được làm mồi ở tiêu đề và 2 dòng đầu
HOOK_RE = re.compile(
    r"\bpips?\b|đang\s+lãi|lãi\s+\d|\$\s?\d[\d.,]*\s*/\s*(?:ngày|tuần|tháng)|"
    r"\d[\d.,]*\s*(?:usd|đô|triệu|tr|k)\s*/\s*(?:ngày|tuần|tháng)|x\s?\d+\s+tài\s+khoản|\d+\s?%\s+mỗi\s+(?:ngày|tuần)",
    re.I,
)

# Quy tắc cứng của chủ nhóm: không cam kết lợi nhuận, không kêu gọi vốn
COMMITMENT_RE = re.compile(
    r"cam\s+kết\s+(?:lợi\s+nhuận|lãi)|đảm\s+bảo\s+(?:lợi\s+nhuận|lãi|có\s+lãi)|chắc\s+chắn\s+(?:thắng|có\s+lãi|lãi)|"
    r"lãi\s+chắc|không\s+rủi\s+ro|kêu\s+gọi\s+(?:vốn|đầu\s+tư)|góp\s+vốn|ủy\s+thác\s+(?:vốn|đầu\s+tư|cho)|"
    r"nhận\s+vốn|kéo\s+tài\s+khoản|kiếm\s+tiền\s+(?:dễ|nhanh)|thu\s+nhập\s+thụ\s+động",
    re.I,
)

# Không gọi lệnh, không đẩy tới nạp tiền
CALL_TO_TRADE_RE = re.compile(
    r"\b(?:nên|hãy|cứ)\s+(?:mua|bán|buy|sell|vào\s+lệnh|nạp|múc)|vào\s+lệnh\s+ngay|mở\s+tài\s+khoản\s+ngay|nạp\s+(?:tiền\s+)?ngay|"
    r"\bbuy\s+ngay|\bsell\s+ngay|đăng\s+ký\s+ngay",
    re.I,
)

SLOP_RE = re.compile(
    r"các\s+sếp|anh\s+em\s+ơi|đừng\s+bỏ\s+lỡ|cơ\s+hội\s+vàng|cơ\s+hội\s+(?:hiếm|cuối)|bùng\s+nổ|siêu\s+lợi\s+nhuận|"
    r"trong\s+thế\s+giới\s+trading|hành\s+trình\s+trading|bí\s+mật\s+(?:của|mà)",
    re.I,
)

REFERRAL_RE = re.compile(r"[?&](?:ref|aff|affiliate|invite|cxd|ib)=|/ref/|bit\.ly|tinyurl\.com|t\.me/\+", re.I)

REQUIRED_FIELDS = {
    "video_review": ("title", "text", "source_url", "author", "platform", "transcript_kind", "facts"),
    "thread_review": ("title", "text", "source_url", "facts"),
    "case_study": ("title", "text", "source_url", "facts"),
    "debate": ("title", "text", "source_url", "facts", "poll"),
    "poll": ("title", "poll", "group"),
}

MAX_TEXT = 3500


def _norm(text):
    t = unicodedata.normalize("NFC", text or "").lower()
    t = re.sub(r"[‘’“”\"'`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def quote_in_source(quote, source):
    """Câu trích phải khớp nguyên chuỗi trong văn bản gốc, bỏ qua hoa thường, dấu nháy và khoảng trắng."""
    q = _norm(quote)
    return len(q) >= 12 and q in _norm(source)


def _numbers(text):
    out = set()
    for tok in re.findall(r"\d+(?:[.,:]\d+)*", text or ""):
        out.add(re.sub(r"[.,:]", "", tok).lstrip("0") or "0")
    return out


def unknown_numbers(text, source):
    """Những số có trong bài nhưng không có trong nguồn."""
    return sorted(_numbers(text) - _numbers(source))


def shingles(text, n=3):
    words = re.findall(r"\w+", _norm(text))
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a, b):
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def check_item(item):
    """Trả về danh sách lỗi; rỗng nghĩa là đạt."""
    errors = []
    kind = item.get("kind")
    if kind not in KINDS:
        return [f"kind_invalid:{kind}"]
    for field in REQUIRED_FIELDS[kind]:
        if not item.get(field):
            errors.append(f"missing:{field}")

    poll = item.get("poll")
    if poll:
        q, opts = poll.get("question", ""), poll.get("options", [])
        if not (10 <= len(q) <= 300):
            errors.append("poll_question_length")
        if not (2 <= len(opts) <= 10) or any(not (1 <= len(o) <= 100) for o in opts):
            errors.append("poll_options")

    body = "\n".join(x for x in (item.get("title", ""), item.get("text", ""), (poll or {}).get("question", ""),
                                 " | ".join((poll or {}).get("options", []))) if x)
    head = "\n".join([item.get("title", "")] + item.get("text", "").splitlines()[:3])
    if HOOK_RE.search(head):
        errors.append("hook_pip_or_income")
    if kind == "poll" and HOOK_RE.search(body):
        errors.append("poll_pip_or_income")
    if COMMITMENT_RE.search(_without_claims(item, body)):
        errors.append("profit_commitment_or_fundraising")
    if CALL_TO_TRADE_RE.search(_without_claims(item, body)):
        errors.append("call_to_trade")
    if SLOP_RE.search(body):
        errors.append("slop_phrase")
    if REFERRAL_RE.search(body) or REFERRAL_RE.search(item.get("source_url", "")):
        errors.append("referral_link")
    if len(item.get("text", "")) > MAX_TEXT:
        errors.append("too_long")

    if kind != "poll":
        if AI_LABEL not in item.get("text", ""):
            errors.append("missing_ai_label")
        if item.get("source_url") and item["source_url"] not in item.get("text", ""):
            errors.append("missing_source_link")
        source = item.get("source_text", "")
        if not source:
            errors.append("missing_source_text")
        for fact in item.get("facts", []):
            if not quote_in_source(fact.get("quote", ""), source):
                errors.append("quote_not_in_source")
                break
        allowed = source + " " + " ".join(item.get("code_numbers", []))
        bad = unknown_numbers(item.get("generated_text", ""), allowed)
        if bad:
            errors.append("number_not_in_source:" + ",".join(bad[:5]))
    if kind == "video_review" and item.get("transcript_kind") not in ("manual", "auto"):
        errors.append("no_transcript")
    return errors


def _without_claims(item, body):
    """Tuyên bố của người khác được phép xuất hiện ở mục tuyên bố, có nhãn chưa kiểm chứng; phần còn lại phải sạch."""
    for claim in item.get("claims_text", []):
        body = body.replace(claim, "")
    return body


def check_schedule(item, history, now):
    """
    Quy tắc đa dạng và tần suất. history là các bài đã đăng, mới nhất ở cuối:
    {"kind", "group", "author", "topic", "title", "text", "ts"}.
    """
    errors = []
    kind = item.get("kind")
    last14 = history[-14:]
    if kind != "poll":
        if sum(1 for h in last14 if h.get("kind") == kind) >= 6:
            errors.append("format_cap")
        if item.get("topic") and sum(1 for h in last14 if h.get("topic") == item["topic"]) >= 3:
            errors.append("topic_cap")
    if history and history[-1].get("kind") == kind and kind != "video_review":
        errors.append("same_format_twice")

    author = item.get("author")
    if author and any(h.get("author") == author and now - h.get("ts", 0) < 14 * 86400 for h in history):
        errors.append("author_cooldown")

    if kind == "poll":
        polls = [h for h in history if h.get("kind") in ("poll", "debate")]
        if sum(1 for h in polls if now - h.get("ts", 0) < 7 * 86400) >= 2:
            errors.append("poll_weekly_cap")
        group = item.get("group")
        plain = [h for h in history if h.get("kind") == "poll"]
        if plain and plain[-1].get("group") == group:
            errors.append("poll_group_twice")
        if sum(1 for h in plain[-8:] if h.get("group") == group) >= 2:
            errors.append("poll_group_cap")
    if kind == "debate" and sum(1 for h in history if h.get("kind") == "debate" and now - h.get("ts", 0) < 7 * 86400) >= 1:
        errors.append("debate_weekly_cap")

    recent = [h for h in history if now - h.get("ts", 0) < 30 * 86400]
    candidate = item.get("text") or (item.get("poll") or {}).get("question", "")
    for h in recent:
        if similarity(candidate, h.get("text") or h.get("title", "")) >= 0.35:
            errors.append("too_similar")
            break
    return errors
