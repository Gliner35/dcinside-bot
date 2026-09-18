import argparse
import os
import sys
import time

from dcbot.activity import ActivityLog
from dcbot.config import Config
from dcbot.dca import DCClient
from dcbot.engine import Engine
from dcbot.memory_factory import create_memory
from dcbot.persona import PersonaEngine
from dcbot.utils import setup_logging


def build(args):
    cfg = Config(args.config)
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "dcbot.log")
    log = setup_logging(cfg.debug, log_file=log_file)
    client = DCClient(
        cookie_file=cfg.cookie_file,
        read_delay=(cfg.read_delay_min_sec, cfg.read_delay_max_sec),
    )
    persona = PersonaEngine(cfg)
    memory = create_memory(cfg)
    activity = ActivityLog(cfg.activity_file)
    engine = Engine(cfg, client, persona, memory, log, activity=activity)
    return cfg, log, client, engine, persona


def ensure_login(cfg, client, log):
    if cfg.cookie_file and os.path.exists(cfg.cookie_file):
        client.load_cookies()
        if client.whoami():
            client.anonymous = False
            log.info("저장된 쿠키로 로그인됨")
            return
        log.info("쿠키가 유효하지 않아 재로그인 시도")
    if cfg.dc_id and cfg.dc_pw:
        try:
            client.login(cfg.dc_id, cfg.dc_pw, extra=cfg.login_extra)
            client.anonymous = False
            log.info("로그인 성공 (봇 닉네임: %s)", client.whoami() or cfg.bot_nickname)
            return
        except Exception as exc:
            log.warning("최신 로그인 방식 실패, 구식 방식 시도: %s", exc)
        client.login_legacy(cfg.dc_id, cfg.dc_pw)
        client.anonymous = False
        log.info("로그인 성공 (legacy)")
        return
    client.anonymous = True
    client.comment_nick = cfg.dc_nickname
    client.comment_pw = cfg.dc_comment_pw
    log.info("비로그인(익명) 모드: 닉네임 '%s'로 동작", cfg.dc_nickname)
    if not cfg.dc_comment_pw:
        log.warning("DC_COMMENT_PW 미설정: 익명 댓글/글은 가능하지만 쓴 글 지우기는 불가")


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="ㅇㅇ봇 - dcinside 갤질 봇")
    ap.add_argument("--config", default=os.path.join(base, "config.json"))
    ap.add_argument("--once", action="store_true", help="한 사이클만 실행하고 종료")
    ap.add_argument("--verify", action="store_true", help="로그인/크롤링 검증 후 종료")
    args = ap.parse_args()

    cfg, log, client, engine, persona = build(args)
    if not cfg.galleries:
        log.error("config.json 에 galleries 를 설정하세요.")
        raise SystemExit(1)

    ensure_login(cfg, client, log)

    if persona.disabled:
        log.warning("LLM_API_KEY 미설정: 모든 생성형 동작(댓글/글)이 비활성화됩니다. 읽기 크롤링만 동작.")

    if args.verify:
        log.info("신원: %s (%s)", cfg.dc_nickname, "비로그인/익명" if client.anonymous else "로그인")
        for g in cfg.galleries:
            try:
                posts = client.list_posts(g["id"], page=1)
                first = posts[0] if posts else None
                log.info("갤 %s: 최근 글 %d개", g["id"], len(posts))
                if first:
                    log.info("  예시: %s | %s | 댓글%d", first.title, first.author, first.reply_count)
            except Exception as exc:
                log.error("갤 %s 크롤링 실패: %s", g.get("id"), exc)
        return

    if args.once:
        engine.run_once()
        log.info("한 사이클 종료")
        return

    log.info("===== %s 갤질 시작 =====", cfg.bot_nickname)
    while True:
        try:
            engine.run_once()
        except Exception as exc:
            log.error("사이클 오류: %s", exc)
        try:
            time.sleep(cfg.crawl_interval_sec)
        except KeyboardInterrupt:
            break
    log.info("봇 종료")


if __name__ == "__main__":
    main()