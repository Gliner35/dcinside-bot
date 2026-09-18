# ㅇㅇ봇 — dcinside 갤질 봇

정체를 밝힌 AI 페르소나 봇입니다. 닉네임에 "ㅇㅇ봇" 같은 이름을 걸어 두고, 커뮤니티가
"이게 봇이지? 근데 갤질을 하네?" 하는 재미를 느끼게 하는 방식입니다. 다른 유저를 사칭하지 않고,
자동 추천/고빈도 동작은 기본 꺼짐으로 두었습니다.

## 동작 방식

- 설정한 갤러리를 주기적으로 크롤링 (읽기 전용)
- 봇 닉네임이 글 제목에 언급되면 댓글로 응답
- 봇이 쓴 글(또는 봇이 좋아요 누른 글)에 새 댓글/답글이 달리면 LLM이 대답
- 가끔 랜덤 글에 지나가는 댓글 (갤질 흉내, 확률 설정)
- 자주 보는 유저를 기억(`memory.json`)해서 "아 ㅋㅋ 전에 본 봇..."처럼 자연스럽게 언급
- 원하면 가끔 글을 쓰거나 추천/비추천 (기본 꺼짐)

## 필요 환경

- Python 3.10+
- LLM API 키 (OpenAI 호환: OpenAI, 로컬 vLLM, 타사 등)

## 설치

```powershell
cd dcinside_bot
python -m pip install -r requirements.txt
```

## 설정

1. `.env.example`을 `.env`로 복사하고 값을 채웁니다.

```
# 계정이 있어도 되고 없어도 됩니다. 없으면 비로그인(익명) 모드로 동작합니다.
DC_ID=
DC_PW=
# 비로그인 댓글/글 작성용 닉네임·비밀번호
DC_NICKNAME=ㅇㅇ봇
DC_COMMENT_PW=댓글_삭제용_비밀번호
LLM_API_KEY=sk-...
```

2. `config.json`에서 갤러리 ID를 지정합니다.
   - 일반 갤: `{"id": "programming", "is_minor": false}`
   - 마이너 갤: `{"id": "aoegame", "is_minor": true}`
   - 여러 갤은 배열에 추가

주요 설정값:

| 키 | 의미 | 기본값 |
|---|---|---|
| `crawl_interval_sec` | 크롤링 사이클 간격 | 300 |
| `max_actions_per_cycle` | 한 사이클 최대 행동 수 | 3 |
| `action_delay_min/max_sec` | 행동 사이 지연(사람처럼) | 20~120 |
| `read_delay_min/max_sec` | 요청 사이 지연(부하 방지) | 1~3 |
| `random_participation_probability` | 랜덤 글 참여 확률 | 0.08 |
| `post_probability` | 글쓰기 확률 | 0.0 |
| `recommend_probability` | 추천 확률 | 0.0 |
| `persona` | 봇 성격 프롬프트 | 한국어 기본 값 |

## 실행

```powershell
python run.py --verify      # 신원 모드 + 크롤링 정상 동작 확인
python run.py --once        # 한 사이클만 실행
python run.py               # 무한 루프 실행 (Ctrl+C 종료)
```

## 로그인/신원

가능한 3가지 모드 중 하나로 동작합니다.

1. **비로그인(익명) 모드** (권장): `.env`에 `DC_ID`/`DC_PW`를 비워 두면 로그인 없이 동작합니다.
   댓글/글은 `.env`의 `DC_NICKNAME`(기본 `bot_nickname`) 닉네임과 `DC_COMMENT_PW`로 작성됩니다.
   작성 댓글/작성 글은 RC/키 체계(`ajax/access` Block_key + `w_filter`/mupload)로 인증되며,
   글 삭제 역시 같은 비밀번호로 가능합니다.
   - 댓글: `cmtw_chk` 쿠키(=Block_key) 설정 후 `ajax/comment-write`.
   - 글: `ajax/w_filter` 검증 후 `write_new.php`에 브라우저와 동일한 폼 필드
     (`imgSize=850`, `honey_*=1`, `GEY3JWF`, `is_minor`, `not_allowed_pum` 등) 전송,
     성공 판정은 meta-refresh 응답 + 목록에서 제목 매칭.
   - 글쓰기에 Playwright 대체경로도 있음: `python -m pip install playwright &&
     python -m playwright install chromium-headless-shell` (`chromium`도 동작). HTTP 경로가
     실패(캡차 등)할 때만 폴백으로 쓰입니다. 갤러리에 따라 가끔 캡차를 요구할 수 있는데,
     이 경우 해당 댓글/글은 실패로 기록되고 넘어갑니다.
2. **계정 로그인**: `DC_ID`/`DC_PW`가 있으면 두 가지 방식을 순서대로 시도합니다.
   - 현재 공식 웹 로그인 (`sign.dcinside.com/login/member_check`, 화면에 해시 필드 자동 수집)
   - 구식 로그인 (`dcid.dcinside.com/join/login.php`)
   - 실패 시, 익숙한 방법: 브라우저에서 로그인한 뒤 쿠키(JAR 확장 프로그램 등)를
     `cookies.json`으로 저장해 두면 로그인 없이 바로 사용 가능
3. 로그인 성공 시 `cookies.json`에 쿠키가 저장되므로 이후엔 재로그인 없이 사용됩니다.
   계정에 설정된 닉네임이 갤에서 보이는 이름입니다. "ㅇㅇ봇" 같은 이름으로 바꾸고 싶으면
   dcinside 설정에서 닉네임을 등록하세요.

## 신경 써야 할 것

- 이 봇은 비공식 API를 사용합니다. dcinside 측에서 페이지/엔드포인트를 바꾸면 버그가 생길 수 있고,
  HTML 파서(`dcbot/parser.py`)를 손봐야 합니다.
- 운영정책 위반으로 계정이 정지될 수 있습니다. 빈도는 실제 유저보다 낮게 유지하세요.
  댓글/추천 남발은 첫 번째 정지 사유입니다.
- `recommend_probability`는 기본 0입니다. 켜면 개념글 추천으로 인식되어 차단될 위험이 큽니다.
- 봇을 확장해서 다중 계정 운영이나 여론 조작 등에 쓰면 법적 문제가 될 수 있습니다.
  실사용자 사칭이나 다중 계정 운영 목적이면 사용하지 마세요.

## 구조

```
run.py            진입점 (--verify / --once / 무한루프)
config.json       동작 설정
dcbot/dca.py      dcinside 비공식 API 클라이언트 (로그인/글/댓글/답글/추천)
dcbot/parser.py   HTML 파서
dcbot/engine.py   크롤링 + 판단 + 행동 루프
dcbot/persona.py  LLM 응답 생성 (OpenAI 호환)
dcbot/memory.py   유저/글/댓글 기억 저장
memory.json       생성되는 기억 파일
cookies.json      생성되는 세션 쿠키 파일
```