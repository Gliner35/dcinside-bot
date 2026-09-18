import json
import os
import threading
from datetime import datetime

import chromadb
from google import genai


class RagMemory:
    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()

        self.ai = genai.Client(api_key=config.gemini_api_key)
        self._dim = None

        self.client = chromadb.PersistentClient(path=config.chroma_db_path)

        self.posts = self.client.get_or_create_collection(
            name="posts",
            metadata={"hnsw:space": "cosine"}
        )
        self.comments = self.client.get_or_create_collection(
            name="comments",
            metadata={"hnsw:space": "cosine"}
        )
        self.interactions = self.client.get_or_create_collection(
            name="interactions",
            metadata={"hnsw:space": "cosine"}
        )

        self.user_data = {"users": {}, "seen_posts": {}, "replied": {}}
        self._load_user_data()

    def _load_user_data(self):
        path = self.config.memory_file
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            for key in self.user_data:
                self.user_data[key] = loaded.get(key, self.user_data[key])
        except (ValueError, OSError):
            pass

    def _zero_embed(self):
        if self._dim:
            return [0.0] * self._dim
        return [0.0] * 3072

    def _embed(self, text):
        if not text or not text.strip():
            return self._zero_embed()
        try:
            result = self.ai.models.embed_content(
                model=self.config.gemini_embedding_model,
                contents=text[:8000],
            )
            emb = result.embeddings[0].values
            self._dim = len(emb)
            return emb
        except Exception:
            return self._zero_embed()

    def _embed_batch(self, texts):
        if not texts:
            return []
        try:
            result = self.ai.models.embed_content(
                model=self.config.gemini_embedding_model,
                contents=texts,
            )
            embs = [e.values for e in result.embeddings]
            self._dim = len(embs[0]) if embs else self._dim
            if len(embs) < len(texts):
                embs = [self._embed(t) for t in texts]
            return embs
        except Exception:
            return [self._embed(t) for t in texts]

    def is_first_run(self):
        return not self.user_data["seen_posts"]

    def note_user(self, author, topic=None):
        if not author:
            return
        with self._lock:
            u = self.user_data["users"].setdefault(
                author, {"seen": 0, "last_seen": "", "topics": []}
            )
            u["seen"] += 1
            u["last_seen"] = datetime.now().isoformat(timespec="seconds")
            if topic and topic not in u["topics"]:
                u["topics"].append(topic)
                if len(u["topics"]) > 10:
                    u["topics"] = u["topics"][-10:]

    def user_blurb(self, author):
        if not author:
            return ""
        u = self.user_data["users"].get(author)
        if not u:
            return ""
        topics = u.get("topics", [])
        note = "봇이 갤에서 '%s' 유저의 글을 본 적 있다." % author
        if topics:
            note += " 이 유저가 쓴 글: " + " / ".join("'%s'" % t for t in topics[-3:])
        return note

    def is_seen_post(self, gallery, no):
        return self.user_data["seen_posts"].get("%s:%s" % (gallery, no), False)

    def mark_seen_post(self, gallery, no):
        with self._lock:
            self.user_data["seen_posts"]["%s:%s" % (gallery, no)] = True

    def mark_seen_posts(self, gallery, nos):
        with self._lock:
            for no in nos:
                self.user_data["seen_posts"]["%s:%s" % (gallery, no)] = True

    def is_replied(self, gallery, post_no, comment_no):
        return self.user_data["replied"].get(
            "%s:%s:%s" % (gallery, post_no, comment_no), False
        )

    def mark_replied(self, gallery, post_no, comment_no):
        with self._lock:
            self.user_data["replied"]["%s:%s:%s" % (gallery, post_no, comment_no)] = True

    def add_own_post(self, gallery, no):
        self.user_data["seen_posts"]["%s:%s" % (gallery, no)] = True

    def save(self):
        with self._lock:
            path = self.config.memory_file
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.user_data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    def store_post(self, gallery, post_no, title, content, author, comments=None):
        doc_id = "%s:%s" % (gallery, post_no)
        text = "%s %s %s" % (title, content, author)
        embedding = self._embed(text)

        with self._lock:
            self.posts.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text[:2000]],
                metadatas=[{
                    "gallery": gallery,
                    "author": author or "",
                    "title": title or "",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "comment_count": len(comments) if comments else 0,
                }]
            )

        if comments:
            cmt_ids = []
            cmt_docs = []
            cmt_embeddings = []
            cmt_metas = []

            for c in comments:
                cmt_id = "%s:%s:%s" % (gallery, post_no, c.get("no", ""))
                cmt_text = "%s %s" % (c.get("author", ""), c.get("content", ""))
                cmt_ids.append(cmt_id)
                cmt_docs.append(cmt_text[:500])
                cmt_metas.append({
                    "gallery": gallery,
                    "post_no": str(post_no),
                    "author": c.get("author", ""),
                    "is_reply": bool(c.get("is_reply", False)),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })

            cmt_embeddings = self._embed_batch(cmt_docs)

            with self._lock:
                self.comments.upsert(
                    ids=cmt_ids,
                    embeddings=cmt_embeddings,
                    documents=cmt_docs,
                    metadatas=cmt_metas
                )

    def store_interaction(self, content, target_user, gallery, post_no, is_bot_initiated):
        doc_id = "interaction_%s_%s" % (
            datetime.now().strftime("%Y%m%d_%H%M%S"),
            hash(content) % 100000
        )
        embedding = self._embed(content)

        with self._lock:
            self.interactions.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content[:500]],
                metadatas=[{
                    "type": "bot_comment" if is_bot_initiated else "comment_to_bot",
                    "target_user": target_user or "",
                    "gallery": gallery,
                    "post_no": str(post_no),
                    "is_bot_initiated": is_bot_initiated,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }]
            )

    def get_context(self, author=None, title=None, content=None, gallery=None):
        context = {}

        if author:
            user_blurb = self.user_blurb(author)
            if user_blurb:
                context["user_history"] = user_blurb

            user_interactions = self.search_user_interactions(author, n_results=3)
            if user_interactions:
                items = ["'%s'" % i["document"][:100] for i in user_interactions]
                context["recent_interactions"] = ", ".join(items)

        if title or content:
            query = "%s %s" % (title or "", content or "")
            similar = self.search_similar_posts(query, n_results=3)
            if similar:
                items = ["'%s'" % s["metadata"].get("title", "") for s in similar]
                context["similar_topics"] = ", ".join(items)

        return context

    def search_similar_posts(self, query, n_results=5):
        if not query or not query.strip():
            return []
        try:
            embedding = self._embed(query)
            results = self.posts.query(
                query_embeddings=[embedding],
                n_results=min(n_results, self.posts.count() or 1),
                include=["documents", "metadatas", "distances"]
            )
            if not results or not results.get("ids"):
                return []
            output = []
            for i, doc_id in enumerate(results["ids"][0]):
                output.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results.get("documents") else "",
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                })
            return output
        except Exception:
            return []

    def search_user_interactions(self, user, n_results=5):
        if not user:
            return []
        try:
            query_text = "유저 %s와의 대화" % user
            embedding = self._embed(query_text)
            results = self.interactions.query(
                query_embeddings=[embedding],
                n_results=min(n_results, self.interactions.count() or 1),
                include=["documents", "metadatas", "distances"]
            )
            if not results or not results.get("ids"):
                return []
            output = []
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                if meta.get("target_user") == user:
                    output.append({
                        "id": doc_id,
                        "document": results["documents"][0][i] if results.get("documents") else "",
                        "metadata": meta,
                        "distance": results["distances"][0][i] if results.get("distances") else 0,
                    })
            return output
        except Exception:
            return []
