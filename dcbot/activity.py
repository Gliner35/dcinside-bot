import json
import os
import threading
from datetime import datetime

MOBILE_ROOT = "https://m.dcinside.com"


class ActivityLog:
    """성공한 글/댓글 작성 기록 (append-only JSONL). 피드백/검토용."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def record(self, category, gallery, post_no, comment_no="", title="", content=""):
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "category": category,
            "gallery": gallery,
            "post_no": str(post_no),
            "comment_no": str(comment_no or ""),
            "title": title or "",
            "content": content or "",
            "link": self._make_link(category, gallery, post_no, comment_no),
        }
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _make_link(category, gallery, post_no, comment_no=""):
        base = "%s/board/%s/%s" % (MOBILE_ROOT, gallery, post_no)
        if category == "comment" and comment_no:
            return "%s#c_%s" % (base, comment_no)
        if category == "post":
            return base
        return base