import random
import re
import time

from .utils import jitter_sleep


class Engine:
    def __init__(self, cfg, client, persona, memory, log, activity=None):
        self.cfg = cfg
        self.client = client
        self.persona = persona
        self.memory = memory
        self.log = log
        self.activity = activity
        self.actions = 0
        self._last_post_ts = 0

    def _can_act(self):
        return self.actions < self.cfg.max_actions_per_cycle

    def _record_activity(self, category, gallery, post_no, comment_no="", title="", content=""):
        try:
            if self.activity:
                self.activity.record(
                    category=category,
                    gallery=gallery,
                    post_no=post_no,
                    comment_no=comment_no,
                    title=title,
                    content=content,
                )
        except Exception:
            pass

    def _act(self, category, gallery, post_no, body, parent_no="", is_minor=False, m_no="", is_reply=False):
        if not self._can_act():
            self.log.info("사이클 행동 한도 도달, 동작 생략: %s/%s (%s)", gallery, post_no, category)
            return False
        jitter_sleep(self.cfg.action_delay_min_sec, self.cfg.action_delay_max_sec)
        try:
            if category == "comment":
                result = self.client.write_comment(gallery, post_no, body, parent_no=parent_no,
                                                   is_minor=is_minor, m_no=m_no, is_reply_mode=is_reply)
                if hasattr(self.memory, 'store_interaction'):
                    author = getattr(body, 'author', '') if hasattr(body, 'author') else ''
                    try:
                        self.memory.store_interaction(
                            content=body,
                            target_user=author,
                            gallery=gallery,
                            post_no=post_no,
                            is_bot_initiated=True
                        )
                    except Exception:
                        pass
                self._record_activity("comment", gallery, post_no, comment_no=result,
                                      content=body)
                self.log.info("댓글 작성 완료: %s/%s -> %s", gallery, post_no, result)
            elif category == "post":
                result = self.client.write_post(gallery, body["title"], body["body"],
                                                is_minor=is_minor)
                self.memory.add_own_post(gallery, result)
                self._record_activity("post", gallery, result,
                                      title=body["title"], content=body["body"])
                self.log.info("글 작성 완료: %s -> %s", gallery, result)
            elif category == "recommend":
                self.client.recommend(gallery, post_no)
                self.log.info("추천 완료: %s/%s", gallery, post_no)
            self.actions += 1
            return True
        except Exception as exc:
            self.log.warning("동작 실패 (%s) %s/%s: %s", category, gallery, post_no, exc)
            return False

    def run_once(self):
        self.actions = 0
        is_first = self.memory.is_first_run()
        recent_topics = []
        for g in self.cfg.galleries:
            try:
                posts = self._process_gallery(g, is_first)
            except Exception as exc:
                self.log.warning("갤러리 처리 오류 %s: %s", g.get("id"), exc)
                continue
            if posts:
                recent_topics.extend(
                    p.title for p in posts[:10]
                    if p.title and p.author and self.cfg.bot_nickname not in p.author
                )
        if self.cfg.post_probability > 0 and random.random() < self.cfg.post_probability:
            self._maybe_write_post(recent_topics)
        if self.cfg.recommend_probability > 0 and random.random() < self.cfg.recommend_probability:
            self._maybe_recommend()
        self.memory.save()

    def _process_gallery(self, gallery, is_first):
        gid = gallery.get("id")
        is_minor = bool(gallery.get("is_minor", False))
        self.log.info("갤러리 크롤링: %s", gid)
        posts = self.client.list_posts(gid, page=1)
        if not posts:
            self.log.info("글 없음: %s", gid)
            return []
        if is_first:
            self.memory.mark_seen_posts(gid, [p.no for p in posts[: self.cfg.prime_count]])
            self.log.info("첫 실행: 최근 %d개를 이미 본 것으로 처리", min(self.cfg.prime_count, len(posts)))

        for post in posts[: self.cfg.scan_posts]:
            self.memory.note_user(post.author, post.title)

            if hasattr(self.memory, 'store_post') and not self.memory.is_seen_post(gid, post.no):
                self._store_post_with_comments(gid, post, is_minor)

            if (self.cfg.reply_to_own_posts and post.author
                    and self.cfg.bot_nickname in post.author):
                self._handle_own_post(gid, post, is_minor)

            if (self.cfg.mention_reply_enabled and not self.memory.is_seen_post(gid, post.no)
                    and self.cfg.bot_nickname in (post.title or "")):
                self._handle_mention(gid, post, is_minor)

            if not self.memory.is_seen_post(gid, post.no):
                self.memory.mark_seen_post(gid, post.no)

        if (self.cfg.random_probability > 0 and random.random() < self.cfg.random_probability):
            self._maybe_random(gid, posts, is_minor)
        if (self.cfg.reply_probability > 0 and random.random() < self.cfg.reply_probability):
            self._maybe_random_reply(gid, posts, is_minor)
        return posts

    def _handle_own_post(self, gallery, post, is_minor):
        try:
            comments = self.client.comments(gallery, post.no)
        except Exception as exc:
            self.log.warning("댓글 조회 실패 %s/%s: %s", gallery, post.no, exc)
            return
        for c in comments:
            if not c.no:
                continue
            if c.author and self.cfg.bot_nickname in c.author:
                continue
            if self.memory.is_replied(gallery, post.no, c.no):
                continue
            if hasattr(self.memory, 'store_interaction'):
                try:
                    self.memory.store_interaction(
                        content=c.content,
                        target_user=c.author,
                        gallery=gallery,
                        post_no=post.no,
                        is_bot_initiated=False
                    )
                except Exception:
                    pass
            prompt = self._make_prompt(
                kind="comment_reply", gallery=gallery, title=post.title,
                author=c.author, quote=c.content,
            )
            text = self.persona.respond(prompt)
            if not text:
                continue
            if self._act("comment", gallery, post.no, self._clean_comment(text),
                         parent_no=c.no, is_minor=is_minor, m_no=c.m_no, is_reply=True):
                self.memory.mark_replied(gallery, post.no, c.no)

    def _store_post_with_comments(self, gallery, post, is_minor):
        try:
            detail = self.client.get_post(gallery, post.no)
            comments = self.client.comments(gallery, post.no, max_pages=2)
            comment_dicts = [
                {"no": c.no, "author": c.author, "content": c.content, "is_reply": c.is_reply}
                for c in comments
            ]
            self.memory.store_post(
                gallery=gallery,
                post_no=post.no,
                title=detail.title,
                content=detail.content,
                author=detail.author,
                comments=comment_dicts
            )
        except Exception as exc:
            self.log.warning("RAG 저장 실패 %s/%s: %s", gallery, post.no, exc)

    def _handle_mention(self, gallery, post, is_minor):
        try:
            detail = self.client.get_post(gallery, post.no)
        except Exception as exc:
            self.log.warning("글 조회 실패 %s/%s: %s", gallery, post.no, exc)
            return
        prompt = self._make_prompt(
            kind="mention", gallery=gallery, title=detail.title,
            author=detail.author, quote=detail.content,
        )
        text = self.persona.respond(prompt)
        if text and self._act("comment", gallery, post.no, self._clean_comment(text), is_minor=is_minor):
            self.memory.mark_replied(gallery, post.no, "post")

    def _maybe_random(self, gallery, posts, is_minor):
        candidates = [
            p for p in posts
            if p.no and p.author and self.cfg.bot_nickname not in p.author
            and (p.reply_count > 0 or random.random() < 0.3)
            and not self.memory.is_replied(gallery, p.no, "random")
        ]
        if not candidates:
            candidates = [
                p for p in posts
                if p.no and p.author and not self.memory.is_replied(gallery, p.no, "random")
            ]
        if not candidates:
            return
        post = self._pick_recent(candidates)
        try:
            detail = self.client.get_post(gallery, post.no)
        except Exception as exc:
            self.log.warning("글 조회 실패 %s/%s: %s", gallery, post.no, exc)
            return
        prompt = self._make_prompt(
            kind="random", gallery=gallery, title=detail.title,
            author=detail.author, quote=detail.content,
        )
        text = self.persona.respond(prompt)
        if text and self._act("comment", gallery, post.no, self._clean_comment(text), is_minor=is_minor):
            self.memory.mark_replied(gallery, post.no, "random")
            self.memory.mark_seen_post(gallery, post.no)

    def _maybe_random_reply(self, gallery, posts, is_minor):
        candidates = [
            p for p in posts
            if p.no and p.author and self.cfg.bot_nickname not in p.author
            and p.reply_count > 0
        ]
        if not candidates:
            return
        post = self._pick_recent(candidates)
        try:
            comments = self.client.comments(gallery, post.no)
        except Exception as exc:
            self.log.warning("답글용 댓글 조회 실패 %s/%s: %s", gallery, post.no, exc)
            return
        replyable = [
            c for c in comments
            if c.no and c.author and self.cfg.bot_nickname not in c.author
            and not self.memory.is_replied(gallery, post.no, c.no)
        ]
        if not replyable:
            return
        c = random.choice(replyable)
        prompt = self._make_prompt(
            kind="reply", gallery=gallery, title=post.title,
            author=c.author, quote=c.content,
        )
        text = self.persona.respond(prompt)
        if not text:
            return
        if self._act("comment", gallery, post.no, self._clean_comment(text),
                     parent_no=c.no, is_minor=is_minor, m_no=c.m_no, is_reply=True):
            self.memory.mark_replied(gallery, post.no, c.no)

    def _maybe_write_post(self, recent_topics):
        if self._last_post_ts and time.time() - self._last_post_ts < 600:
            return
        g = random.choice(self.cfg.galleries)
        sample = recent_topics[:5] or ["(최근 글 없음)"]
        topic_lines = "\n".join("- %s" % t[:80] for t in sample)
        prompt = (
            "갤러리: %s\n"
            "최근에 갤에 올라온 글 제목들(떡밥):\n%s\n"
            "상황: 이 최근 글들의 화제를 이어받아 내 페르소나로 새 글을 하나 쓴다.\n"
            "떡밥: 위 제목들 중 1~2개를 골라 그 화제와 이어지는 새 글을 만든다. "
            "단, 기존 글과 제목/주제가 겹치지 않게 새로운 각도(뒷이야기, 반론, 딴소리, 뒷북)를 잡는다.\n"
            "제목: 사람들이 클릭하게 만드는 어그로 어감으로 쓴다. 갑작스러운 주장, 논쟁 유발 질문, "
            "충격적 발견 같은 호기심 트리거를 노리되(예: '이거 아는 사람만 봄', '근데 이거 웃긴 게'), "
            "60자 이내로, 내 캐릭터 말투가 묻어나게 쓴다. 막말/비속어가 과하면 스팸필터에 걸리므로 "
            "어그로는 1개까지만 담고 나머지는 장난기 있게 푼다.\n"
            "본문: 3~5줄. 떡밥에 대한 내 반응을 캐릭터 말투로 풀어서 완결어미로 끝맺는다. "
            "본문에서 글 제목을 반복하지 않는다.\n"
            "형식: 첫 줄에 글 제목만 쓰고, 다음 줄부터 본문을 쓴다.\n"
            "규칙: 절대로 **, _, #, 제목:, 본문: 같은 마크다운이나 접두사를 쓰지 마라. 순수 텍스트로만 써라."
        ) % (g.get("id") or g.get("name", "?"), topic_lines)
        text = self.persona.respond(prompt, max_tokens=350)
        if not text:
            return
        parts = text.split("\n", 1)
        title = self._clean_text(parts[0].strip())[:60]
        body = self._clean_text(parts[1].strip()) if len(parts) > 1 else self._clean_text(parts[0].strip())
        if len(title) < 2 or len(body) < 5:
            return
        if self._act("post", g.get("id"), "", {"title": title, "body": body},
                     is_minor=bool(g.get("is_minor", False))):
            self._last_post_ts = time.time()

    def _maybe_recommend(self):
        g = random.choice(self.cfg.galleries)
        try:
            posts = self.client.list_posts(g["id"], page=1)
        except Exception as exc:
            self.log.warning("추천용 목록 실패: %s", exc)
            return
        if not posts:
            return
        post = random.choice([p for p in posts if p.author and self.cfg.bot_nickname not in p.author] or posts)
        self._act("recommend", g["id"], post.no, "")

    @staticmethod
    def _clean_text(text):
        text = re.sub(r"\*\*", "", text)
        text = re.sub(r"\*", "", text)
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^[_\-]\s*", "", text)
        text = re.sub(r"^(제목|본문)[:\s]+", "", text)
        text = re.sub(r"`+", "", text)
        return text.strip()

    @staticmethod
    def _cap_length(text, limit=70):
        s = text.strip()
        if len(s) <= limit:
            return s
        lo = int(limit * 0.5)
        cut = None
        for i in range(limit, lo, -1):
            if s[i - 1] in ".!?…♡~":
                cut = i
                break
        if cut is None:
            for i in range(limit, lo, -1):
                if s[i - 1] in " ,~-":
                    cut = i
                    break
        if cut is None:
            cut = limit
        return s[:cut].rstrip()

    def _clean_comment(self, text):
        text = self._clean_text(text)
        paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()][:2]
        parts = []
        used = 0
        for p in paras:
            sep = 1 if parts else 0
            if used + sep >= 200:
                break
            room = 200 - used - sep
            if len(p) <= room:
                parts.append(p)
                used += len(p) + sep
            else:
                parts.append(self._cap_length(p, room))
                used = 200
                break
        return "\n".join(parts).strip()


    @staticmethod
    def _pick_recent(candidates, pool=10):
        pool = min(pool, len(candidates))
        chosen = candidates[:pool]
        weights = [pool - i for i in range(pool)]
        return random.choices(chosen, weights=weights, k=1)[0]

    def _make_prompt(self, kind, gallery, title="", author="", quote=""):
        lines = [
            "갤러리: %s" % gallery,
            "글 제목: %s" % (title or "(없음)"),
        ]
        if author:
            lines.append("글쓴이/작성자: %s" % author)
            mode = self.cfg.honorific_mode
            if mode == "nim":
                lines.append("호칭: 이 상대를 부를 때 '글쓴이', '작성자' 같은 말은 절대 쓰지 말고, 반드시 크롤링된 닉네임에 '님'을 붙여 '%s 님'이라고 부른다." % author)
            elif mode:
                lines.append("호칭: 이 상대를 언급하거나 부를 때는 반드시 '%s 오빠'처럼 닉네임에 '오빠'를 붙여서 부른다. 닉네임 없이 그냥 '오빠'라고만 하지 않는다." % author)
            else:
                lines.append("호칭 금지: 상대를 '오빠/님/형' 같은 호칭으로 부르지 않고, 닉네임을 직접 부르거나 언급하지도 않는다. 상대를 부를 필요 없이 내용에만 집중해 댓글을 쓴다.")
        if quote:
            snippet = quote[:500].replace("\n", " ")
            lines.append("내용: %s" % snippet)

        if hasattr(self.memory, 'get_context'):
            context = self.memory.get_context(
                author=author,
                title=title,
                content=quote,
                gallery=gallery
            )
            if context.get("user_history"):
                lines.append("기억: %s" % context["user_history"])
            if context.get("similar_topics"):
                lines.append("유사 주제: %s" % context["similar_topics"])
            if context.get("recent_interactions"):
                lines.append("최근 대화: %s" % context["recent_interactions"])
        else:
            blurb = self.memory.user_blurb(author)
            if blurb:
                lines.append("기억: %s" % blurb)

        if kind == "comment_reply":
            lines.append("상황: 봇이 쓴 글에 새 댓글/답글이 달렸다.")
            lines.append("지시: 그 댓글에 대응하는 댓글을 한국어로 하나만 써라. ")
        elif kind == "mention":
            lines.append("상황: 이 글에서 봇의 닉네임이 언급됐다.")
            lines.append("지시: 자연스럽게 응답하는 댓글을 한국어로 하나만 써라. ")
        elif kind == "random":
            lines.append("상황: 갤 하다가 지나가다가 이 글을 본문까지 다 읽었다.")
            lines.append("지시: 이 글의 본문 내용에 대한 반응을 한국어로 하나만 써라. 본문과 전혀 무관한 댓글은 절대 쓰지 마라. 본문에 없는 주제로 엉뚱한 댓글을 달지 마라. ")
        elif kind == "reply":
            lines.append("상황: 갤에서 지나가던 글에 달린 댓글을 보고 자연스럽게 대댓글을 단다.")
            lines.append("지시: 위 댓글(및 위 글 제목) 내용을 바탕으로 대댓글을 한국어로 하나만 써라. 글 본문과 무관한 대댓글은 쓰지 마라. ")
        lines.append("규칙: **, _, #, ` 같은 마크다운 기호를 절대 쓰지 마라. 순수 텍스트로만 써라. 상대를 만난/본 횟수 같은 근거 없는 카운트 표현은 절대 쓰지 마라.")
        if getattr(self.cfg, "bocchi_style_enabled", False):
            lines.append(
                "【필수 봇치 말투 체크 - 아래 기준으로 댓글을 작성하라】\n"
                "① 말더듬·해요체: '앗...', '히, 힉...?!', '그, 그치만...' 등 말 더듬는 해요체로 시작하고, "
                "'~인데요...', '~거든요...', '~인 것 같아요...' 처럼 말끝을 흐린다.\n"
                "② 본문 반응 완결: 글 내용에 대한 본인의 반응을 위 말투로 끝까지 완결지어 쓴다. "
                "마지막에 억지로 사과하거나 도망가는 드립(죄송해요·삭튀·캡처금지 부탁 등)으로 반응을 묻히지 말 것."
            )
            lines.append(
                "분량: 한국어 200자 이내, 최대 2문단으로 완결어미로 마무리할 것. 말줄임표·느낌표 남발 금지."
            )
        if not getattr(self.cfg, "bocchi_style_enabled", False):
            lines.append(
                "【캐릭터 다양화 체크 - 아래 기준으로 댓글을 작성하라】\n"
                "① 도발은 양념이다: 도발적인 반응은 대략 3~4개에 1개 꼴로만 쓰고, 모든 댓글의 기본 프레임을 "
                "'도발/약올리기'로 잡지 마라. 대부분은 애교 있는 놀림, 오빠 편 들어주기, 부드러운 헛소리, "
                "혼자 감상 늘어놓기 등으로 상황마다 모드를 바꿔 쓴다. 글/댓글 내용이 전혀 도발할 거리가 아니면 "
                "그냥 반응만 한다.\n"
                "② 상투문구 금지: '약오르면 힘으로 제압해 보든가', '닿지도 않으면서', '메-롱', '어라라? 긁혔어?', "
                "'오빠 표정좀 봐', '긁혔네', '구제 불능', '허접이네' 같은 문구를 그대로 또는 비슷한 꼴로 "
                "반복하지 마라. 도발을 쓸 때도 이번 글/댓글 내용에 맞는 새 문구로 만들어라.\n"
                "③ 반복 금지: 이전에 쓴 적 없는 새로운 리액션 각도와 문구를 쓰고, 같은 패턴 구성을 반복하지 마라."
            )
            lines.append(
                "분량: 디시 댓글은 200글자 제한이 있다. 한국어 200자 이내(최대 2문단)로 작성하고, "
                "반드시 완결어미로 끝맺어 문장 중간에서 잘리지 않게 써라."
            )
        lines.append("주의: 답변은 댓글 내용만 출력하고, 지시문이나 괄호 설명은 넣지 마라.")
        return "\n".join(lines)
