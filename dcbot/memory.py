import json
import os
import re
import threading
from datetime import datetime

DEFAULT_ANONYMOUS_AUTHORS = [
    "ㅇㅇ", "ㅁㅇ", "ㅊㅊ", "익명", "아무개", "유동", "비회원", ""
]

_ANON_GALLERY_RE = re.compile(r"^[\w가-힣]{0,6}갤러\d*$")


class MemoryStore:
    def __init__(self, path, anonymous_authors=None):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"users": {}, "seen_posts": {}, "replied": {}}
        self.anonymous = set(
            a.strip() for a in (anonymous_authors or []) if a.strip()
        )
        self._load()

    def is_anonymous_author(self, author):
        if not author:
            return True
        name = author.strip()
        if name in self.anonymous:
            return True
        return bool(_ANON_GALLERY_RE.match(name))

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            for key, value in self.data.items():
                self.data[key] = loaded.get(key, value)
        except (ValueError, OSError):
            pass

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def is_first_run(self):
        return not self.data["seen_posts"]

    def note_user(self, author, topic=None):
        if not author or self.is_anonymous_author(author):
            return
        with self._lock:
            u = self.data["users"].setdefault(author, {"seen": 0, "last_seen": "", "topics": []})
            u["seen"] += 1
            u["last_seen"] = datetime.now().isoformat(timespec="seconds")
            if topic and topic not in u["topics"]:
                u["topics"].append(topic)
                if len(u["topics"]) > 10:
                    u["topics"] = u["topics"][-10:]

    def user_blurb(self, author):
        if not author or self.is_anonymous_author(author):
            return ""
        u = self.data["users"].get(author)
        if not u:
            return ""
        seen = u.get("seen", 0)
        topics = u.get("topics", [])
        if seen < 2 and not topics:
            return ""
        note = "봇이 갤에서 '%s' 유저의 글을 본 적 있다." % author
        if topics:
            note += " 이 유저가 쓴 글: " + " / ".join("'%s'" % t for t in topics[-3:])
        return note

    def is_seen_post(self, gallery, no):
        return self.data["seen_posts"].get("%s:%s" % (gallery, no), False)

    def mark_seen_post(self, gallery, no):
        with self._lock:
            self.data["seen_posts"]["%s:%s" % (gallery, no)] = True

    def mark_seen_posts(self, gallery, nos):
        with self._lock:
            for no in nos:
                self.data["seen_posts"]["%s:%s" % (gallery, no)] = True

    def is_replied(self, gallery, post_no, comment_no):
        return self.data["replied"].get("%s:%s:%s" % (gallery, post_no, comment_no), False)

    def mark_replied(self, gallery, post_no, comment_no):
        with self._lock:
            self.data["replied"]["%s:%s:%s" % (gallery, post_no, comment_no)] = True

    def add_own_post(self, gallery, post_no):
        self.data["seen_posts"]["%s:%s" % (gallery, post_no)] = True