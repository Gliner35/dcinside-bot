import json
import os
import random
import re
import time

import requests
from bs4 import BeautifulSoup

from .parser import parse_comments, parse_list, parse_page_meta, parse_post

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 10; SM-G973N Build/QP1A.190711.020; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36"
)
MOBILE_ROOT = "https://m.dcinside.com"
HOME_URL = "https://www.dcinside.com/"


class DCError(RuntimeError):
    pass


def _quote(text):
    out = ""
    for ch in text:
        cp = ord(ch)
        if cp >= 0x100:
            out += "%%u%04X" % cp
        else:
            out += "%%%02X" % cp
    return out


class DCClient:
    def __init__(self, cookie_file=None, timeout=25, read_delay=(0.0, 0.0),
                 comment_nick="", comment_pw=""):
        self.cookie_file = cookie_file
        self.timeout = timeout
        self.read_delay = tuple(read_delay)
        self.comment_nick = comment_nick
        self.comment_pw = comment_pw
        self.anonymous = True
        self.session = requests.Session()
        self.session.headers["User-Agent"] = MOBILE_UA
        self.session.headers["Accept-Language"] = "ko-KR,ko;q=0.8,en-US;q=0.5"

    def _throttle(self):
        time.sleep(random.uniform(self.read_delay[0], self.read_delay[1]))

    def _get(self, url, **kw):
        self._throttle()
        kw.setdefault("timeout", self.timeout)
        resp = self.session.get(url, **kw)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp

    def _post(self, url, **kw):
        self._throttle()
        kw.setdefault("timeout", self.timeout)
        resp = self.session.post(url, **kw)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp

    def save_cookies(self, path=None):
        path = path or self.cookie_file
        if not path:
            return
        data = requests.utils.dict_from_cookiejar(self.session.cookies)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def load_cookies(self, path=None):
        path = path or self.cookie_file
        if not path or not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.session.cookies.update(requests.utils.cookiejar_from_dict(data))
        return True

    def whoami(self):
        resp = self._get(HOME_URL, headers={"Referer": "https://sign.dcinside.com/"})
        soup = BeautifulSoup(resp.text, "html.parser")
        for selector in (
            "#login_box .user_name strong",
            "#login_box div.user_name strong",
            ".user_name.otp_width strong",
        ):
            tag = soup.select_one(selector)
            if tag:
                return tag.get_text(" ", strip=True)
        return None

    def login(self, user_id, pw, extra=None):
        headers = {"Referer": HOME_URL}
        self._get(HOME_URL, headers=headers)
        resp = self._get(HOME_URL, headers=headers)
        soup = BeautifulSoup(resp.text, "html.parser")
        payload = dict(extra or {})
        for tag in soup.select("#login_process input[type=hidden]"):
            name = tag.get("name")
            if name:
                payload.setdefault(name, tag.get("value", ""))
        payload.setdefault("s_url", "//www.dcinside.com/")
        payload.setdefault("ssl", "y")
        payload["user_id"] = user_id
        payload["pw"] = pw
        self._post("https://sign.dcinside.com/login/member_check", headers=headers, data=payload)
        if not self.whoami():
            raise DCError("sign.dcinside.com 로그인 실패")
        self.save_cookies()
        return True

    def login_legacy(self, user_id, user_pw):
        self._get("https://dcid.dcinside.com/join/popup_login.php",
                  headers={"Referer": "https://dcid.dcinside.com/"})
        resp = self._post(
            "https://dcid.dcinside.com/join/login.php",
            data={"user_id": user_id, "user_pw": user_pw},
            headers={"Referer": "https://dcid.dcinside.com/join/popup_login.php"},
        )
        try:
            data = resp.json()
        except ValueError:
            raise DCError("legacy 로그인 응답이 JSON 아님: %s" % resp.text[:200])
        if data.get("result") != "ok":
            raise DCError("legacy 로그인 실패: %s" % data.get("err_msg"))
        self.save_cookies()
        return True

    def list_posts(self, board_id, page=1):
        resp = self._get("%s/board/%s" % (MOBILE_ROOT, board_id), params={"page": page})
        return parse_list(resp.text)

    def get_post(self, board_id, no):
        resp = self._get("%s/board/%s/%s" % (MOBILE_ROOT, board_id, no))
        return parse_post(resp.text, no=no)

    def comments(self, board_id, no, max_pages=3):
        url = "%s/ajax/response-comment" % MOBILE_ROOT
        out = []
        for page in range(1, max_pages + 1):
            data = {"id": board_id, "no": str(no), "cpage": page,
                    "managerskill": "", "del_scope": "1", "csort": ""}
            resp = self._post(url, headers={"X-Requested-With": "XMLHttpRequest"}, data=data)
            frag = parse_comments(resp.text)
            if not frag:
                break
            out.extend(frag)
        seen = set()
        unique = []
        for cm in out:
            key = (cm.no, cm.content)
            if key in seen:
                continue
            seen.add(key)
            unique.append(cm)
        return unique

    def _con_key(self, token_verify, referer, csrf):
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf,
            "Referer": referer,
        }
        resp = self._post("%s/ajax/access" % MOBILE_ROOT, headers=headers,
                          data={"token_verify": token_verify})
        try:
            data = resp.json()
        except ValueError:
            raise DCError("access 토큰 응답이 JSON 아님: %s" % resp.text[:200])
        key = data.get("Block_key", "")
        if not key:
            raise DCError("Block_key 획득 실패: %s" % resp.text[:200])
        return key

    def write_comment(self, board_id, no, content, parent_no="", is_minor=False, m_no="", is_reply_mode=False):
        # DC 모바일 댓글 200자 제한 하드컷
        _MAX_CHARS = 200
        if len(content) > _MAX_CHARS:
            content = content[:_MAX_CHARS].rstrip()
        post_url = "%s/board/%s/%s" % (MOBILE_ROOT, board_id, no)
        meta = parse_page_meta(self._get(post_url).text)
        csrf = meta["csrf"]
        hide = meta["hide_robot"]
        con_key = self._con_key("com_submit", post_url, csrf)
        if not con_key:
            con_key = meta["csrf"]
        self.session.cookies.set("cmtw_chk", con_key, domain="m.dcinside.com", path="/")
        self.session.cookies.set("cmtw_chk", con_key, domain=".dcinside.com", path="/")
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf,
            "Referer": post_url,
            "Origin": MOBILE_ROOT,
        }
        cookies = {"m_dcinside_%s" % board_id: board_id}
        payload = {
            "comment_memo": content,
            "comment_nick": self.comment_nick if self.anonymous else "",
            "comment_pw": self.comment_pw if self.anonymous else "",
            "mode": "com_reple" if is_reply_mode else "com_write",
            "comment_no": str(parent_no or ""),
            "id": board_id,
            "no": str(no),
            "best_chk": "",
            "subject": meta["title"],
            "board_id": "",
            "reple_id": str(m_no or ""),
            "cpage": "1",
            "con_key": con_key,
            "use_gall_nickname": "1",
        }
        if hide:
            payload[hide] = "1"
        resp = self._post("%s/ajax/comment-write" % MOBILE_ROOT,
                          headers=headers, data=payload, cookies=cookies)
        try:
            data = resp.json()
        except ValueError:
            raise DCError("댓글 작성 응답이 JSON 아님: %s" % resp.text[:200])
        if "data" not in data:
            raise DCError("댓글 작성 실패: %s" % json.dumps(data, ensure_ascii=False)[:200])
        return str(data["data"])

    def write_post(self, board_id, title, content, is_minor=False):
        write_url = "%s/write/%s" % (MOBILE_ROOT, board_id)
        resp = self._get(write_url)
        meta = parse_page_meta(resp.text)
        csrf = meta["csrf"]
        hide = meta["hide_robot"]
        code = meta["code"]
        user_id = meta["user_id"]
        mobile_key = meta["mobile_key"]
        con_key = self._con_key("dc_check2", write_url, csrf)
        if not con_key:
            con_key = csrf
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf,
            "Referer": write_url,
            "Origin": MOBILE_ROOT,
        }
        wf = {
            "subject": title,
            "memo": content,
            "id": board_id,
            "captcha_code": "",
            "rand_code": code,
            "mode": "write",
            "is_mini": "1" if is_minor else "0",
            "is_person": "0",
        }
        if self.anonymous:
            wf["nickname"] = self.comment_nick
        res = None
        try:
            resp_f = self._post("%s/ajax/w_filter" % MOBILE_ROOT, headers=headers, data=wf)
            res = resp_f.json()
        except (ValueError, requests.RequestException):
            pass
        if isinstance(res, dict) and res.get("result") is False:
            raise DCError("글 필터 실패: %s" % res.get("cause", resp_f.text)[:200])

        payload = {
            "subject": title,
            "memo": content,
            "Block_key": con_key,
        }
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.select_one("form#writeForm") or soup.select_one("form")
        for inp in form.find_all("input"):
            if inp.get("type", "").lower() != "hidden":
                continue
            nm = inp.get("name")
            if not nm or nm in payload:
                continue
            payload[nm] = inp.get("value", "")
        if "imgSize" in payload and not payload["imgSize"]:
            payload["imgSize"] = "850"
        for f in ("adult_certified", "adult_contents", "not_allowed_pum"):
            if f in payload:
                payload[f] = "0"
        if soup.find("input", attrs={"id": "is_minor"}):
            payload["is_minor"] = "1"
        if hide:
            payload[hide] = "1"
            payload["GEY3JWF"] = hide
        if user_id:
            payload["user_id"] = user_id
        if self.anonymous:
            payload["name"] = self.comment_nick
            payload["password"] = self.comment_pw

        cookies = {
            "m_dcinside_%s" % board_id: board_id,
            "m_dcinside_lately": _quote(board_id + "|" + (meta["board_name"] or board_id) + ","),
        }
        uplink = "https://mupload.dcinside.com/write_new.php"
        headers_up = {
            "User-Agent": MOBILE_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": write_url,
            "Host": "mupload.dcinside.com",
        }
        resp = self._post(uplink, headers=headers_up, data=payload, cookies=cookies,
                          allow_redirects=False)
        text = resp.text or ""
        parts = text.split("||")
        if len(parts) > 1 and parts[1].strip().isdigit():
            return parts[1].strip()
        loc = resp.headers.get("location") or ""
        if "/board/%s/" % board_id in loc or "/board/%s" % board_id in loc.split("?")[0] or \
                'http-equiv="refresh"' in text.lower() or "/board/%s" % board_id in text:
            no = self._find_no_by_title(board_id, title)
            if no:
                return no
            raise DCError("글 작성 성공했으나 새 글 번호 확인 실패")
        try:
            return self._write_post_playwright(board_id, title, content, is_minor)
        except DCError:
            raise
        except Exception as exc:
            raise DCError("글 작성 실패(HTTP/브라우저 둘 다): %r" % exc) from exc

    def delete_post(self, board_id, no, password=""):
        conf_url = "%s/confirmpw/%s/%s/%s/?mode=del" % (MOBILE_ROOT, "board", board_id, no)
        try:
            html = self._get(conf_url).text
        except DCError:
            return False
        soup = BeautifulSoup(html, "html.parser")
        csrf = parse_page_meta(html)["csrf"]
        con_key = self._con_key("board_Del", conf_url, csrf or "")
        if not con_key:
            con_key = csrf
        data = {
            "_token": csrf or "",
            "id": board_id,
            "no": no,
            "mode": "del",
            "route_id": board_id,
            "board_pw": password or self.comment_pw,
            "con_key": con_key or "",
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf or "",
            "Referer": conf_url,
            "Origin": MOBILE_ROOT,
        }
        resp = self._post("%s/del/board" % MOBILE_ROOT, headers=headers, data=data)
        try:
            j = resp.json()
            return j.get("result") == 1
        except ValueError:
            return False

    def _find_no_by_title(self, board_id, title):
        target = re.sub(r"\s*\[[\d,]+\]\s*$", "", title)
        try:
            for p in self.list_posts(board_id, 1):
                if p.title == target:
                    return p.no
        except (DCError, requests.RequestException):
            pass
        return ""

    def _write_post_playwright(self, board_id, title, content, is_minor=False):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise DCError("글 작성 실패: playwright 미설치. `python -m pip install playwright && python -m playwright install chromium` 필요")
        write_url = "%s/write/%s" % (MOBILE_ROOT, board_id)
        result = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                user_agent=MOBILE_UA,
                viewport={"width": 390, "height": 844},
                is_mobile=False,
                device_scale_factor=1,
                locale="ko-KR",
            )
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "navigator.plugins=[{name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}];"
                "window.chrome={runtime:{}};"
            )
            page = context.new_page()
            page.on("dialog", lambda d: result.setdefault("dialog", d.message) or d.dismiss())
            page.goto(write_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("form#writeForm", timeout=60000)
            page.fill("#subject", title)
            page.evaluate("(v)=>{var el=document.getElementById('name'); if(el){el.disabled=false; el.value=v;}}", self.comment_nick)
            if self.anonymous:
                page.evaluate("(v)=>{var el=document.getElementById('password'); if(el){el.disabled=false; el.value=v;}}", self.comment_pw)
            page.wait_for_function("typeof $ !== 'undefined' && !!$('#textbox').summernote")
            page.evaluate(
                "(v)=>{ $('#textbox').summernote('code', v); }", content)
            if page.locator("#dcblock").count():
                raise DCError("글 작성 실패: 자동입력방지코드(캡차)가 요구됩니다.")
            page.evaluate("window.write_submit ? write_submit() : (function(){ $('#writeForm').submit(); })()")
            page.wait_for_timeout(14000)
            final_url = page.url
            body = page.content()
            browser.close()
        m = re.search(r"/board/%s/(\d+)" % re.escape(board_id), final_url)
        if m:
            return m.group(1)
        parts = (body or "").split("||")
        if len(parts) > 1 and parts[1].strip().isdigit():
            return parts[1].strip()
        if "/board/%s" % board_id in final_url or 'http-equiv="refresh"' in (body or "").lower():
            no = self._find_no_by_title(board_id, title)
            if no:
                return no
            raise DCError("글 작성 성공했으나 새 글 번호 확인 실패")
        msg = result.get("dialog") or ""
        if body:
            soup = BeautifulSoup(body, "html.parser")
            p_el = soup.select_one("p.txt")
            if p_el:
                msg = p_el.get_text(" ", strip=True)
        raise DCError("글 작성 실패(브라우저): %s" % (msg or body)[:200])

    def delete_comment(self, board_id, no, comment_no):
        post_url = "%s/board/%s/%s" % (MOBILE_ROOT, board_id, no)
        meta = parse_page_meta(self._get(post_url).text)
        csrf = meta["csrf"]
        con_key = self._con_key("com_submitDel", post_url, csrf)
        if not con_key:
            con_key = meta["csrf"]
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf,
            "Referer": post_url,
            "Origin": MOBILE_ROOT,
        }
        payload = {
            "_token": csrf,
            "commentDel_pw": self.comment_pw if self.anonymous else "",
            "comment_no": str(comment_no),
            "id": board_id,
            "no": str(no),
            "best_chk": "",
            "board_id": "",
            "con_key": con_key,
        }
        resp = self._post("%s/del/comment" % MOBILE_ROOT, headers=headers, data=payload)
        try:
            data = resp.json()
        except ValueError:
            raise DCError("댓글 삭제 응답이 JSON 아님: %s" % resp.text[:200])
        if data.get("result") is False:
            raise DCError("댓글 삭제 실패: %s" % json.dumps(data, ensure_ascii=False)[:200])
        return True

    def recommend(self, board_id, no, down=False):
        cookie = "%s%s_Firstcheck" % (board_id, no)
        self.session.cookies[cookie] = "Y"
        url = "https://gall.dcinside.com/forms/recommend_vote_%s" % ("down" if down else "up")
        data = {"ci_t": "", "id": board_id, "no": str(no), "recommend": "0",
                "vote": "vote", "user_id": ""}
        resp = self._post(url, headers={"X-Requested-With": "XMLHttpRequest"}, data=data)
        return "error" not in (resp.text or "").lower()