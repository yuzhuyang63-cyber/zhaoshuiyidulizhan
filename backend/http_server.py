from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import perf_counter
from urllib.parse import urlparse
from uuid import uuid4

from .app_context import AppContext
from .inquiry_service import clean_form_text
from .logging_setup import log_event


class ChatHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, request_handler_class, app_context: AppContext):
        super().__init__(server_address, request_handler_class)
        self.app_context = app_context

    def handle_error(self, request, client_address):
        log_event(
            self.app_context.logger,
            logging.ERROR,
            "unhandled_http_server_error",
            "unhandled exception escaped request handler",
            exc_info=True,
            remote_addr=client_address[0] if client_address else "-",
        )


class ChatRequestHandler(BaseHTTPRequestHandler):
    server_version = "AquaScanInquiry/1.0"

    @property
    def app_context(self) -> AppContext:
        return self.server.app_context

    @property
    def logger(self):
        return self.app_context.logger

    def log_message(self, format, *args):
        return

    def log_error(self, format, *args):
        log_event(
            self.logger,
            logging.ERROR,
            "http_server_error",
            "http server error",
            request_id=self.ensure_request_id(),
            remote_addr=self.client_address[0] if self.client_address else "-",
            detail=format % args,
        )

    def ensure_request_id(self) -> str:
        if not hasattr(self, "_request_id"):
            headers = getattr(self, "headers", None)
            header_value = clean_form_text(headers.get("X-Request-ID", "") if headers else "", limit=80)
            self._request_id = header_value or uuid4().hex[:12]
        if not hasattr(self, "_request_started_at"):
            self._request_started_at = perf_counter()
        return self._request_id

    def log_request_summary(self, status: int, response_bytes: int):
        request_id = self.ensure_request_id()
        duration_ms = max(int((perf_counter() - self._request_started_at) * 1000), 0)
        log_event(
            self.logger,
            logging.INFO,
            "http_request_complete",
            "request complete",
            request_id=request_id,
            method=self.command,
            path=urlparse(self.path).path,
            status=status,
            duration_ms=duration_ms,
            remote_addr=self.client_address[0] if self.client_address else "-",
            response_bytes=response_bytes,
        )

    def send_json(self, payload, status=200):
        request_id = self.ensure_request_id()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", request_id)
        self.send_cors_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            log_event(
                self.logger,
                logging.WARNING,
                "http_response_write_failed",
                "failed to write response to client",
                exc_info=exc,
                request_id=request_id,
                path=urlparse(self.path).path,
                status=status,
                remote_addr=self.client_address[0] if self.client_address else "-",
            )
            return
        self.log_request_summary(status, len(body))

    def request_origin(self) -> str:
        return clean_form_text(self.headers.get("Origin", ""), limit=300)

    def same_origin(self) -> str:
        host = clean_form_text(self.headers.get("Host", ""), limit=300)
        if not host:
            return ""
        scheme = clean_form_text(self.headers.get("X-Forwarded-Proto", ""), limit=20) or "http"
        return f"{scheme}://{host}"

    def is_cors_origin_allowed(self) -> bool:
        origin = self.request_origin()
        if not origin:
            return True
        if origin == self.same_origin():
            return True
        allowed_origins = self.app_context.config.inquiry_allowed_origins
        return "*" in allowed_origins or origin in allowed_origins

    def send_cors_headers(self) -> None:
        origin = self.request_origin()
        if not origin or not self.is_cors_origin_allowed():
            return
        if "*" in self.app_context.config.inquiry_allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _handle_unexpected_exception(self, exc: Exception):
        request_id = self.ensure_request_id()
        path = urlparse(self.path).path if getattr(self, "path", None) else "-"
        log_event(
            self.logger,
            logging.ERROR,
            "unhandled_request_exception",
            "unhandled exception while processing request",
            exc_info=exc,
            request_id=request_id,
            method=getattr(self, "command", "-"),
            path=path,
            remote_addr=self.client_address[0] if self.client_address else "-",
            error_type=type(exc).__name__,
        )

        try:
            self.send_json(
                {
                    "error": "Internal server error",
                    "request_id": request_id,
                },
                status=500,
            )
        except Exception:
            log_event(
                self.logger,
                logging.ERROR,
                "internal_error_response_failed",
                "failed to send internal server error response",
                exc_info=True,
                request_id=request_id,
                path=path,
            )

    def do_OPTIONS(self):
        try:
            request_id = self.ensure_request_id()
            if not self.is_cors_origin_allowed():
                self.send_json({"error": "CORS origin not allowed"}, status=403)
                return
            self.send_response(204)
            self.send_header("X-Request-ID", request_id)
            self.send_cors_headers()
            self.end_headers()
            self.log_request_summary(204, 0)
        except Exception as exc:
            self._handle_unexpected_exception(exc)

    def do_GET(self):
        try:
            self.ensure_request_id()
            path = urlparse(self.path).path
            if path == "/api/health":
                self.send_json(
                    {
                        "status": "ok",
                        "inquiry_ready": True,
                        "email_configured": self.app_context.inquiry_service.email_is_configured(),
                        "feishu_configured": self.app_context.feishu_service.is_configured(),
                    }
                )
                return

            self.send_json({"error": "Not found"}, status=404)
        except Exception as exc:
            self._handle_unexpected_exception(exc)

    def do_POST(self):
        try:
            request_id = self.ensure_request_id()
            path = urlparse(self.path).path
            if not self.is_cors_origin_allowed():
                self.send_json({"error": "CORS origin not allowed"}, status=403)
                return
            if path != "/api/inquiry":
                self.send_json({"error": "Not found"}, status=404)
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)

            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "invalid_json_body",
                    "invalid json body",
                    request_id=request_id,
                    path=path,
                    remote_addr=self.client_address[0] if self.client_address else "-",
                    content_length=content_length,
                )
                self.send_json({"error": "Invalid JSON body"}, status=400)
                return

            if path == "/api/inquiry":
                email_sent = False
                email_error = ""
                feishu_synced = False
                feishu_error = ""
                try:
                    validated = self.app_context.inquiry_service.validate_payload(payload)
                    inquiry = self.app_context.inquiry_service.persist(validated, self)
                except ValueError as exc:
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "inquiry_validation_failed",
                        "inquiry validation failed",
                        request_id=request_id,
                        path=path,
                        error=str(exc),
                    )
                    self.send_json({"error": str(exc)}, status=400)
                    return
                except Exception as exc:
                    log_event(
                        self.logger,
                        logging.ERROR,
                        "inquiry_submission_failed",
                        "inquiry submission failed",
                        exc_info=exc,
                        request_id=request_id,
                        path=path,
                        error_type=type(exc).__name__,
                    )
                    self.send_json(
                        {
                            "error": "Inquiry submission failed",
                            "details": str(exc),
                        },
                        status=502,
                    )
                    return

                try:
                    email_sent = self.app_context.inquiry_service.send_email_notification(inquiry)
                except Exception as exc:
                    email_error = str(exc)
                    log_event(
                        self.logger,
                        logging.ERROR,
                        "inquiry_email_failed",
                        "inquiry was saved but email notification failed",
                        exc_info=exc,
                        request_id=request_id,
                        path=path,
                        inquiry_id=inquiry["id"],
                        error_type=type(exc).__name__,
                    )

                try:
                    feishu_result = self.app_context.feishu_service.create_customer_record(inquiry)
                    feishu_synced = not bool(feishu_result.get("skipped"))
                except Exception as exc:
                    feishu_error = str(exc)
                    log_event(
                        self.logger,
                        logging.ERROR,
                        "inquiry_feishu_sync_failed",
                        "inquiry was saved but Feishu sync failed",
                        exc_info=exc,
                        request_id=request_id,
                        path=path,
                        inquiry_id=inquiry["id"],
                        error_type=type(exc).__name__,
                    )

                log_event(
                    self.logger,
                    logging.INFO,
                    "inquiry_submitted",
                    "inquiry submitted successfully",
                    request_id=request_id,
                    inquiry_id=inquiry["id"],
                    country=inquiry.get("country", ""),
                    email_sent=email_sent,
                    feishu_synced=feishu_synced,
                )
                response_payload = {
                    "status": "ok",
                    "message": "Inquiry submitted successfully",
                    "inquiry_id": inquiry["id"],
                    "email_sent": email_sent,
                    "email_configured": self.app_context.inquiry_service.email_is_configured(),
                    "feishu_synced": feishu_synced,
                    "feishu_configured": self.app_context.feishu_service.is_configured(),
                }
                if email_error:
                    response_payload["email_error"] = email_error
                if feishu_error:
                    response_payload["feishu_error"] = feishu_error
                self.send_json(response_payload, status=201)
                return
        except Exception as exc:
            self._handle_unexpected_exception(exc)
