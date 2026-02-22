# server.py
from flask import Flask, jsonify
import datetime
import os

from main import run_collection

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def collect():
    """수집 엔드포인트"""
    print("🌊 예보 수집 시작:", datetime.datetime.now().isoformat())
    
    try:
        result = run_collection()
        return jsonify({
            "success": True,
            "message": "완료",
            "result": result
        }), 200
    except Exception as e:
        print(f"❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """헬스체크 엔드포인트"""
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
