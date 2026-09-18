import logging


def create_memory(config):
    log = logging.getLogger("dcbot")

    if config.memory_backend == "rag":
        if not config.gemini_api_key:
            log.warning("GEMINI_API_KEY 미설정: simple 모드로 동작")
        else:
            try:
                from .memory_rag import RagMemory
                memory = RagMemory(config)
                log.info("RAG 메모리 백엔드 초기화 완료")
                return memory
            except Exception as e:
                log.warning("RAG 초기화 실패, simple로 폴백: %s", e)

    from .memory import MemoryStore, DEFAULT_ANONYMOUS_AUTHORS
    anonymous = list(DEFAULT_ANONYMOUS_AUTHORS) + list(config.anonymous_authors)
    memory = MemoryStore(config.memory_file, anonymous_authors=anonymous)
    log.info("Simple 메모리 백엔드 사용 (익명 닉 %d개 제외)", len(anonymous))
    return memory
