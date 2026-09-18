import re

from bs4 import BeautifulSoup
from dataclasses import dataclass


def _has_class(node, token):
    cls = node.get("class") or []
    if isinstance(cls, str):
        cls = cls.split()
    return token in cls


def _text(el):
    return el.get_text(" ", strip=True) if el else ""


def _num(text):
    m = re.search(r"[\d,]+", text or "")
    if not m:
        return 0
    return int(m.group().replace(",", ""))


@dataclass
class Post:
    no: str = ""
    title: str = ""
    author: str = ""
    reply_count: int = 0
    view_count: int = 0
    vote_up: int = 0
    created_at: str = ""


@dataclass
class PostDetail:
    no: str = ""
    title: str = ""
    author: str = ""
    content: str = ""


@dataclass
class Comment:
    no: str = ""
    parent_no: str = ""
    m_no: str = ""
    author: str = ""
    content: str = ""
    is_reply: bool = False
    created_at: str = ""


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("ul.gall-detail-lst > li"):
        if _has_class(li, "ad"):
            continue
        link = li.select_one("a.lt")
        if not link:
            continue
        href = link.get("href") or ""
        m = re.search(r"/(\d+)(?:[#?]|$)", href)
        if not m:
            continue
        no = m.group(1)

        title_el = li.select_one(".subjectin")
        title = _text(title_el) if title_el else _text(link)
        title = re.sub(r"\s*\[[\d,]+\]\s*$", "", title)

        author = ""
        block = li.select_one(".blockInfo")
        if block and block.get("data-name"):
            author = block["data-name"].strip()
        if not author:
            nick = li.select_one("li.list-nick")
            if nick:
                author = nick.get_text(strip=True)

        reply_count = 0
        ct_el = li.select_one("a.rt > span")
        if ct_el:
            reply_count = _num(_text(ct_el))

        created_at = ""
        view_count = 0
        vote_up = 0
        for gi in li.select("ul.ginfo > li"):
            txt = gi.get_text(" ", strip=True)
            if _has_class(gi, "list-nick"):
                continue
            if not created_at and (":" in txt or "." in txt):
                created_at = txt
            elif txt.startswith("조회"):
                view_count = _num(txt)
            elif txt.startswith("추천"):
                vote_up = _num(txt)

        out.append(Post(no=no, title=title, author=author, reply_count=reply_count,
                        view_count=view_count, vote_up=vote_up, created_at=created_at))
    return out


def parse_post(html, no=""):
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("div.gallview-tit-box span.tit") or soup.select_one("span.tit")
    title = _text(title_el) if title_el else ""
    if not title:
        title = _text(soup.select_one(".gallview_tit") or soup.select_one("h2"))

    content = ""
    content_el = soup.select_one("div.thum-txtin") or soup.select_one("div.view_content")
    if content_el:
        for adv in content_el.select("div.adv-groupin, div.adv-groupno, div.ad, script"):
            adv.decompose()
        content = content_el.get_text("\n", strip=True)

    author = ""
    nick = soup.select_one("div.gallview-tit-box .ginfo2 button.nick, div.gallview-tit-box button.nick")
    if nick:
        author = nick.get_text(strip=True)
    else:
        nick = soup.select_one("span.nickname")
        if nick:
            author = nick.get_text(strip=True)
        else:
            strong = soup.select_one("#login_box .user_name strong")
            if strong:
                author = strong.get_text(strip=True)

    return PostDetail(no=str(no), title=title, author=author, content=content[:2000])


def parse_comments(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("ul.all-comment-lst li.comment, ul.all-comment-lst li.comment-add")
    if not items:
        for container in soup.select("ol, ul.coments, .coments, #comment_list, div.ub-comment-list"):
            items.extend(container.find_all("li"))
    if not items:
        items = soup.select("li.ub-content, li.comment, div.ub-content")

    out = []
    seen = set()
    last_root_no = ""
    for li in items:
        no = li.get("no") or li.get("data-no") or ""
        if not no or no in seen:
            continue
        seen.add(no)
        is_reply = _has_class(li, "comment-add") or _has_class(li, "reple") \
            or bool(li.get("data-parent-id") or li.get("parent_no")) \
            or bool(li.find_parent("ul", class_="reple-lst"))
        if is_reply:
            parent_no = li.get("data-parent-id") or li.get("parent_no") or last_root_no
        else:
            parent_no = li.get("data-parent-id") or li.get("parent_no") or ""
            last_root_no = no

        author = ""
        nick = li.select_one(".ginfo-area button.nick, button.nick, span.nickname, .reply_nickname, .ub-writer span")
        if nick:
            author = nick.get_text(" ", strip=True)
        if not author:
            first = li.find("span")
            if first:
                author = first.get_text(" ", strip=True)

        content = ""
        body = li.select_one("div.rbox h2, p.comment_content, div.comment_content, .content, p.txt")
        if not body:
            body = li.select_one("p")
        if body:
            content = body.get_text("\n", strip=True)

        date_el = li.select_one(".ub-date, span.date")
        created_at = _text(date_el)

        out.append(Comment(no=no, parent_no=parent_no, m_no=str(li.get("m_no") or ""),
                           author=author, content=content[:500],
                           is_reply=is_reply, created_at=created_at))
    return out


def parse_page_meta(html):
    soup = BeautifulSoup(html, "html.parser")

    def value(selector):
        el = soup.select_one(selector)
        return el.get("value", "") if el else ""

    csrf = soup.find("meta", attrs={"name": "csrf-token"})
    hide = soup.find("input", class_="hide-robot")
    code = soup.find("input", attrs={"name": "code"})
    user_id = soup.find("input", attrs={"name": "user_id"})
    mobile_key = soup.find("input", attrs={"id": "mobile_key"})
    ci_t = soup.find("input", attrs={"name": "ci_t"})
    tit = soup.select_one("span.tit")
    board = soup.select_one("a.gall-tit-lnk")

    meta = {
        "csrf": csrf.get("content", "") if csrf else "",
        "hide_robot": hide.get("name", "") if hide else "",
        "code": code.get("value", "") if code else "",
        "user_id": user_id.get("value", "") if user_id else "",
        "mobile_key": mobile_key.get("value", "") if mobile_key else "",
        "ci_t": ci_t.get("value", "") if ci_t else "",
        "title": tit.get_text(" ", strip=True) if tit else "",
        "board_name": board.get_text(" ", strip=True) if board else "",
    }
    return meta