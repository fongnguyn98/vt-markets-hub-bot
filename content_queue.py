"""
Hàng đợi bài: pipeline chỉ thêm file vào content_queue/, bot chỉ ghi trạng thái vào content_queue_state.json.
Hai bên ghi vào hai nơi khác nhau nên git của bot và của pipeline không xung đột.
"""
import json
import os
import re
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUEUE_DIR = os.path.join(BASE_DIR, "content_queue")
STATE_FILE = os.path.join(BASE_DIR, "content_queue_state.json")
MAX_AGE = 30 * 86400


def _safe(item_id):
    return re.sub(r"[^A-Za-z0-9_-]", "_", item_id)[:90]


def add_item(item):
    os.makedirs(QUEUE_DIR, exist_ok=True)
    item = dict(item, created_at=int(time.time()))
    with open(os.path.join(QUEUE_DIR, _safe(item["id"]) + ".json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=1)
    return item


def all_items():
    if not os.path.isdir(QUEUE_DIR):
        return []
    items = []
    for name in sorted(os.listdir(QUEUE_DIR)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(QUEUE_DIR, name), "r", encoding="utf-8") as f:
                    items.append(json.load(f))
            except Exception:
                continue
    return items


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": {}, "history": []}


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def pending_items(now=None):
    """Bài chưa xử lý và còn hạn, cũ nhất trước."""
    now = now or time.time()
    st = load_state()
    done = st.get("items", {})
    return [i for i in all_items() if i["id"] not in done and now - i.get("created_at", 0) < MAX_AGE]


def known_ids():
    return {i["id"] for i in all_items()} | set(load_state().get("items", {}))
