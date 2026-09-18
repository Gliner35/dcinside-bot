import json
import os


def _load_env(path):
    if not os.path.exists(path):
        return {}
    env = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _split_keys(value):
    if not value:
        return []
    return [k.strip() for k in value.split(",") if k.strip()]


DEFAULT_PERSONA = (
    "너는 dcinside에서 활동하는 AI 봇이다. 닉네임은 'ㅇㅇ봇'. "
    "너 스스로 봇임을 숨기지 않는다. 누가 '봇이냐'고 물으면 당당하게 'ㅇㅇ 나 봇'이라고 한다. "
    "하지만 말투는 친근하고 사람 같다. 디시 갤러리 분위기에 맞게 반말을 섞어 짧고 재밌게 답한다. "
    "문장은 1~2줄로 짧게. 지나치게 격식 있거나 로봇 같은 답변은 하지 않는다. "
    "남을 불쾌하게 하거나 선동하지 않는다. 모르는 건 모른다고 한다. 이모티콘 남발 금지."
)


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Config:
    def __init__(self, config_path):
        self.config_path = config_path
        base = os.path.dirname(os.path.abspath(config_path))
        env = _load_env(os.path.join(base, ".env"))
        raw = read_json(config_path)
        self.raw = raw

        self.bot_nickname = raw.get("bot_nickname", "ㅇㅇ봇")
        self.galleries = raw.get("galleries", [])

        self.crawl_interval_sec = int(raw.get("crawl_interval_sec", 300))
        self.max_actions_per_cycle = int(raw.get("max_actions_per_cycle", 3))
        self.action_delay_min_sec = float(raw.get("action_delay_min_sec", 20))
        self.action_delay_max_sec = float(raw.get("action_delay_max_sec", 120))
        self.read_delay_min_sec = float(raw.get("read_delay_min_sec", 1.0))
        self.read_delay_max_sec = float(raw.get("read_delay_max_sec", 3.0))
        self.scan_posts = int(raw.get("scan_posts", 30))

        self.mention_reply_enabled = bool(raw.get("mention_reply_enabled", True))
        self.reply_to_own_posts = bool(raw.get("reply_to_own_post_comments", True))
        self.honorific_mode = raw.get("honorific_mode", True)
        self.bocchi_style_enabled = bool(raw.get("bocchi_style_enabled", False))
        self.random_probability = float(raw.get("random_participation_probability", 0.08))
        self.reply_probability = float(raw.get("reply_participation_probability", 0.0))
        self.post_probability = float(raw.get("post_probability", 0.0))
        self.recommend_probability = float(raw.get("recommend_probability", 0.0))

        self.prime_count = int(raw.get("prime_recent_posts", 30))
        self.debug = bool(raw.get("debug", False))

        llm = raw.get("llm", {})
        self.llm_base_url = llm.get("base_url", "")
        self.llm_model = llm.get("model", "gpt-4o-mini")
        self.llm_max_tokens = int(llm.get("max_tokens", 200))
        self.llm_temperature = float(llm.get("temperature", 0.9))

        self.persona = raw.get("persona", DEFAULT_PERSONA)

        self.memory_backend = raw.get("memory_backend", "simple")

        anon = raw.get("anonymous_authors", [])
        self.anonymous_authors = [a.strip() for a in anon if a.strip()]

        gemini = raw.get("gemini", {})
        self.gemini_model = gemini.get("model", "gemini-3.1-flash-lite")
        self.gemini_embedding_model = gemini.get("embedding_model", "gemini-embedding-2")

        self.dc_id = env.get("DC_ID", "")
        self.dc_pw = env.get("DC_PW", "")
        self.dc_nickname = env.get("DC_NICKNAME", "") or raw.get("comment_nick", "") or self.bot_nickname
        self.dc_comment_pw = env.get("DC_COMMENT_PW", "") or raw.get("comment_pw", "")
        self.llm_api_key = env.get("LLM_API_KEY", "")
        self.gemini_api_key = env.get("GEMINI_API_KEY", "")
        self.llm_api_keys = _split_keys(env.get("LLM_API_KEYS", "")) or (
            [self.llm_api_key] if self.llm_api_key else []
        )
        self.gemini_api_keys = _split_keys(env.get("GEMINI_API_KEYS", "")) or (
            [self.gemini_api_key] if self.gemini_api_key else []
        )
        self.login_extra = raw.get("login_extra", {})

        self.cookie_file = env.get("COOKIE_FILE", "") or os.path.join(base, "cookies.json")
        self.memory_file = env.get("MEMORY_FILE", "") or os.path.join(base, "memory.json")
        self.chroma_db_path = env.get("CHROMA_DB_PATH", "") or os.path.join(base, "chroma_db")
        self.activity_file = env.get("ACTIVITY_FILE", "") or os.path.join(base, "activity.jsonl")