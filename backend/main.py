from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from backend.app_context import AppContext
    from backend.config import load_runtime_config
    from backend.feishu_service import FeishuService
    from backend.http_server import ChatHTTPServer, ChatRequestHandler
    from backend.inquiry_service import InquiryService
    from backend.logging_setup import configure_logging, log_event
else:
    from .app_context import AppContext
    from .config import load_runtime_config
    from .feishu_service import FeishuService
    from .http_server import ChatHTTPServer, ChatRequestHandler
    from .inquiry_service import InquiryService
    from .logging_setup import configure_logging, log_event


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai") if ZoneInfo else None


def create_app_context() -> AppContext:
    config = load_runtime_config()
    logger = configure_logging(config)

    return AppContext(
        config=config,
        logger=logger,
        inquiry_service=InquiryService(config),
        feishu_service=FeishuService(config),
    )


def next_daily_report_time(hour: int, minute: int) -> datetime:
    now = datetime.now(LOCAL_TIMEZONE) if LOCAL_TIMEZONE else datetime.now().astimezone()
    hour = min(max(hour, 0), 23)
    minute = min(max(minute, 0), 59)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def start_daily_report_scheduler(app_context: AppContext) -> threading.Event:
    stop_event = threading.Event()
    config = app_context.config
    logger = app_context.logger

    def run_scheduler() -> None:
        while not stop_event.is_set():
            target = next_daily_report_time(config.inquiry_daily_report_hour, config.inquiry_daily_report_minute)
            sleep_seconds = max((target - datetime.now(target.tzinfo)).total_seconds(), 0)
            log_event(
                logger,
                logging.INFO,
                "scheduled_inquiry_statistics_waiting",
                "scheduled inquiry statistics report waiting",
                scheduled_at=target.isoformat(),
            )

            while sleep_seconds > 0 and not stop_event.is_set():
                chunk = min(sleep_seconds, 60)
                stop_event.wait(chunk)
                sleep_seconds -= chunk

            if stop_event.is_set():
                break

            try:
                app_context.inquiry_service.send_statistics_report_email()
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "scheduled_inquiry_statistics_failed",
                    "scheduled inquiry statistics report failed",
                    exc_info=exc,
                )
            time.sleep(1)

    thread = threading.Thread(target=run_scheduler, name="daily-inquiry-report", daemon=True)
    thread.start()
    return stop_event


def run() -> None:
    app_context = create_app_context()
    config = app_context.config
    logger = app_context.logger
    server = ChatHTTPServer((config.host, config.port), ChatRequestHandler, app_context)
    report_scheduler_stop = start_daily_report_scheduler(app_context)
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
        report_scheduler_stop.set()
        server.server_close()
        log_event(logger, logging.INFO, "server_stopped", "inquiry backend stopped")


if __name__ == "__main__":
    run()
