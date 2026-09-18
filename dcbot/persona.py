from .keypool import KeyPool


class PersonaEngine:
    def __init__(self, cfg):
        self.model = cfg.llm_model
        self.gemini_model = getattr(cfg, "gemini_model", "")
        self.max_tokens = cfg.llm_max_tokens
        self.temperature = cfg.llm_temperature
        self.persona = cfg.persona
        self.base_url = cfg.llm_base_url or None

        self.gemini_pool = KeyPool(getattr(cfg, "gemini_api_keys", None))
        self.openai_pool = KeyPool(getattr(cfg, "llm_api_keys", None))
        self._genai = None
        self._openai_cls = None
        self._gemini_clients = {}
        self._openai_clients = {}

        if not self.gemini_pool.empty:
            try:
                from google import genai
                self._genai = genai
            except Exception:
                self.gemini_pool = KeyPool([])

        if not self.openai_pool.empty:
            try:
                from openai import OpenAI
                self._openai_cls = OpenAI
            except Exception:
                self.openai_pool = KeyPool([])

        self.disabled = not (self._genai and not self.gemini_pool.empty) \
            and not (self._openai_cls and not self.openai_pool.empty)

    def _gemini_client(self, key):
        if key not in self._gemini_clients:
            self._gemini_clients[key] = self._genai.Client(api_key=key)
        return self._gemini_clients[key]

    def _openai_client(self, key):
        if key not in self._openai_clients:
            kwargs = {"api_key": key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._openai_clients[key] = self._openai_cls(**kwargs)
        return self._openai_clients[key]

    def respond(self, prompt, max_tokens=None):
        if self.disabled:
            return ""
        mt = max_tokens or self.max_tokens

        if self._genai is not None and not self.gemini_pool.empty:
            for _ in range(len(self.gemini_pool)):
                key = self.gemini_pool.get()
                try:
                    response = self._gemini_client(key).models.generate_content(
                        model=self.gemini_model,
                        contents=prompt,
                        config=self._genai.types.GenerateContentConfig(
                            system_instruction=self.persona,
                            max_output_tokens=mt,
                            temperature=self.temperature,
                        )
                    )
                    return (response.text or "").strip()
                except Exception:
                    continue
            if self.openai_pool.empty:
                return ""

        return self._respond_openai(prompt, mt)

    def _respond_openai(self, prompt, max_tokens=None):
        if self.openai_pool.empty:
            return ""
        mt = max_tokens or self.max_tokens
        for _ in range(len(self.openai_pool)):
            key = self.openai_pool.get()
            try:
                resp = self._openai_client(key).chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.persona},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=mt,
                    temperature=self.temperature,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception:
                continue
        return ""