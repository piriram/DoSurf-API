# server.py
from flask import Flask, jsonify, request
import datetime
import hmac
import os

from main import run_collection
from scripts.alerts import send_telegram_alert

app = Flask(__name__)


def _is_monitoring_webhook_authorized(req) -> bool:
    """Cloud Monitoring webhook basic auth 검증"""
    expected_user = os.environ.get("MONITORING_WEBHOOK_USER")
    expected_pass = os.environ.get("MONITORING_WEBHOOK_PASS")

    # 미설정이면 인증 우회 (초기 설정 편의)
    if not expected_user and not expected_pass:
        return True

    auth = req.authorization
    if not auth:
        return False

    return (
        hmac.compare_digest(auth.username or "", expected_user or "")
        and hmac.compare_digest(auth.password or "", expected_pass or "")
    )


@app.route('/', methods=['GET', 'POST'])
def collect():
    """수집 엔드포인트"""
    print("🌊 예보 수집 시작:", datetime.datetime.now().isoformat())
    
    try:
        result = run_collection()

        # 전체 위치가 실패하면 HTTP 500으로 처리 (Scheduler/Monitoring이 즉시 감지하도록)
        total = int(result.get("total", 0)) if isinstance(result, dict) else 0
        failed = int(result.get("failed", 0)) if isinstance(result, dict) else 0
        if total > 0 and failed >= total:
            print("❌ 수집 결과 전체 실패 -> HTTP 500 반환")
            return jsonify({
                "success": False,
                "message": "전체 실패",
                "result": result
            }), 500

        return jsonify({
            "success": True,
            "message": "완료",
            "result": result
        }), 200
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()

        alert_result = send_telegram_alert(
            message=f"서버 collect 엔드포인트 예외 발생: {e}",
            level="CRITICAL",
            source="server.collect",
        )
        if alert_result.get("sent"):
            print("📩 Telegram 장애 알림 전송 완료")
        else:
            print(f"ℹ️ Telegram 알림 미전송: {alert_result.get('reason')}")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/monitoring-alert', methods=['POST'])
def monitoring_alert():
    """Cloud Monitoring Webhook 수신 -> Telegram 포워딩"""
    if not _is_monitoring_webhook_authorized(request):
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

    return jsonify({
        "ok": True,
        "sent": alert_result.get("sent", False),
        "reason": alert_result.get("reason"),
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """헬스체크 엔드포인트"""
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
