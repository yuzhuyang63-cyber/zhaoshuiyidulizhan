from __future__ import annotations

import logging

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from backend.app_context import AppContext
    from backend.config import load_runtime_config
    from backend.http_server import ChatHTTPServer, ChatRequestHandler
    from backend.inquiry_service import InquiryService
    from backend.logging_setup import configure_logging, log_event
else:
    from .app_context import AppContext
    from .config import load_runtime_config
    from .http_server import ChatHTTPServer, ChatRequestHandler
    from .inquiry_service import InquiryService
    from .logging_setup import configure_logging, log_event


def create_app_context() -> AppContext:
    config = load_runtime_config()
    logger = configure_logging(config)

    return AppContext(
        config=config,
        logger=logger,
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
        "inquiry backend listening",
        host=config.host,
        port=config.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event(
            logger,
            logging.INFO,
            "server_shutdown_requested",
            "inquiry backend shutdown requested by keyboard interrupt",
        )
    except Exception as exc:
        log_event(
            logger,
            logging.CRITICAL,
            "server_crashed",
            "inquiry backend crashed unexpectedly",
            exc_info=exc,
            host=config.host,
            port=config.port,
        )
        raise
    finally:
        server.server_close()
        log_event(logger, logging.INFO, "server_stopped", "inquiry backend stopped")


if __name__ == "__main__":
    run()
