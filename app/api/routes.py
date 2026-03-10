import datetime
import hmac
import json
import logging
import os

from flask import Flask, jsonify, request

from app.clients.alerts import send_telegram_alert
from app.services.collection import run_collection

logger = logging.getLogger(__name__)


def _log(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False))


def _is_production() -> bool:
    env = (os.environ.get("ENV") or os.environ.get("FLASK_ENV") or "").lower()
    return env in {"prod", "production"}


def _is_collect_authorized(req) -> bool:
    """Collect endpoint token auth (X-Job-Token)."""
    expected_token = os.environ.get("COLLECT_JOB_TOKEN")

    # 운영 환경에서는 토큰 미설정 시 차단
    if not expected_token:
        return not _is_production()

    provided_token = req.headers.get("X-Job-Token", "")
    return hmac.compare_digest(provided_token, expected_token)


def _is_monitoring_webhook_authorized(req) -> bool:
    """Cloud Monitoring webhook basic auth 검증"""
    expected_user = os.environ.get("MONITORING_WEBHOOK_USER")
    expected_pass = os.environ.get("MONITORING_WEBHOOK_PASS")

    # 운영 환경에서는 인증정보 미설정 시 차단
    if not expected_user and not expected_pass:
        return not _is_production()

    auth = req.authorization
    if not auth:
        return False

    return hmac.compare_digest(auth.username or "", expected_user or "") and hmac.compare_digest(
        auth.password or "", expected_pass or ""
    )


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/", methods=["POST"])
    def collect():
        """수집 엔드포인트"""
        if not _is_collect_authorized(request):
            _log("collect.unauthorized", remote_addr=request.remote_addr)
            return jsonify({"success": False, "error": "unauthorized"}), 401

        _log("collect.start", at=datetime.datetime.now().isoformat())

        try:
            result = run_collection()

            # 전체 위치가 실패하면 HTTP 500으로 처리 (Scheduler/Monitoring이 즉시 감지하도록)
            total = int(result.get("total", 0)) if isinstance(result, dict) else 0
            failed = int(result.get("failed", 0)) if isinstance(result, dict) else 0
            if total > 0 and failed >= total:
                _log("collect.complete", ok=False, total=total, failed=failed)
                return (
                    jsonify({"success": False, "message": "전체 실패", "result": result}),
                    500,
                )

            _log("collect.complete", ok=True, total=total, failed=failed)
            return jsonify({"success": True, "message": "완료", "result": result}), 200
        except Exception as e:
            logger.exception("collect.exception")

            alert_result = send_telegram_alert(
                message=f"서버 collect 엔드포인트 예외 발생: {e}",
                level="CRITICAL",
                source="server.collect",
            )
            if alert_result.get("sent"):
                print("📩 Telegram 장애 알림 전송 완료")
            else:
                print(f"ℹ️ Telegram 알림 미전송: {alert_result.get('reason')}")

            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/monitoring-alert", methods=["POST"])
    def monitoring_alert():
        """Cloud Monitoring Webhook 수신 -> Telegram 포워딩"""
        if not _is_monitoring_webhook_authorized(request):
            _log("monitoring_alert.unauthorized", remote_addr=request.remote_addr)
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        incident = payload.get("incident", {}) if isinstance(payload, dict) else {}

        state = str(incident.get("state", "UNKNOWN")).upper()
        policy_name = incident.get("policy_name") or incident.get("policy_display_name") or "(unknown_policy)"
        summary = incident.get("summary") or "(no summary)"
        url = incident.get("url")

        message_lines = [
            f"Cloud Monitoring incident: {state}",
            f"policy: {policy_name}",
            f"summary: {summary}",
        ]
        if url:
            message_lines.append(f"url: {url}")

        level = "CRITICAL" if state == "OPEN" else "INFO"
        alert_result = send_telegram_alert(
            message="\n".join(message_lines),
            level=level,
            source="cloud-monitoring",
        )

        sent = alert_result.get("sent", False)
        status_code = 200 if sent else 502
        _log("monitoring_alert.forward", sent=sent, state=state, policy=policy_name)
        return jsonify({"ok": sent, "sent": sent, "reason": alert_result.get("reason")}), status_code

    @app.route("/health", methods=["GET"])
    def health():
        """헬스체크 엔드포인트"""
        return jsonify({"status": "healthy"}), 200

    return app
