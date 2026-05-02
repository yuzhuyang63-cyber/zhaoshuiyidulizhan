from __future__ import annotations

if __package__ in {None, ""}:
    import logging
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from backend.app_context import AppContext
    from backend.chat_service import ChatService
    from backend.config import load_runtime_config
    from backend.http_server import ChatHTTPServer, ChatRequestHandler
    from backend.inquiry_service import InquiryService
    from backend.knowledge_base import LocalKnowledgeBase
    from backend.logging_setup import configure_logging, log_event
else:
    import logging

    from .app_context import AppContext
    from .chat_service import ChatService
    from .config import load_runtime_config
    from .http_server import ChatHTTPServer, ChatRequestHandler
    from .inquiry_service import InquiryService
    from .knowledge_base import LocalKnowledgeBase
    from .logging_setup import configure_logging, log_event


def create_app_context() -> AppContext:
    config = load_runtime_config()
    logger = configure_logging(config)
    knowledge_base = LocalKnowledgeBase(config)
    log_event(
        logger,
        logging.INFO,
        "knowledge_base_loaded",
        "knowledge base loaded",
        rag_ready=knowledge_base.is_ready,
        chunk_count=len(knowledge_base.chunks),
        product_count=len(knowledge_base.products),
        faq_seed_count=len(knowledge_base.faq_seeds),
        chunks_path=knowledge_base.chunks_path,
        catalog_path=knowledge_base.catalog_path,
        faq_path=knowledge_base.faq_path,
    )
    if not knowledge_base.is_ready:
        log_event(
            logger,
            logging.WARNING,
            "knowledge_base_not_ready",
            "knowledge base is not ready; chat retrieval will return no results",
        )

    return AppContext(
        config=config,
        logger=logger,
        knowledge_base=knowledge_base,
        chat_service=ChatService(config, knowledge_base),
        inquiry_service=InquiryService(config),
    )


def run() -> None:
    app_context = create_app_context()
    config = app_context.config
    logger = app_context.logger
    server = ChatHTTPServer((config.host, config.port), ChatRequestHandler, app_context)
    log_event(
        logger,
        logging.INFO,
        "server_started",
        "chat backend listening",
        host=config.host,
        port=config.port,
        rag_ready=app_context.knowledge_base.is_ready,
        chunk_count=len(app_context.knowledge_base.chunks),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event(
            logger,
            logging.INFO,
            "server_shutdown_requested",
            "chat backend shutdown requested by keyboard interrupt",
        )
    except Exception as exc:
        log_event(
            logger,
            logging.CRITICAL,
            "server_crashed",
            "chat backend crashed unexpectedly",
            exc_info=exc,
            host=config.host,
            port=config.port,
        )
        raise
    finally:
        server.server_close()
        log_event(logger, logging.INFO, "server_stopped", "chat backend stopped")


if __name__ == "__main__":
    run()
