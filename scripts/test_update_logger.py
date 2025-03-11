import datetime
from google.cloud import firestore
from flask import Flask, request

app = Flask(__name__)
db = firestore.Client()

@app.route("/", methods=["POST"])
def log_update_time():
    now = datetime.datetime.now()
    doc_id = now.strftime("%Y%m%d%H%M%S")
    ref = db.collection("meta_updates").document(doc_id)
    ref.set({
        "timestamp": now,
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "Cloud Scheduler test update"
    })
    print(f"✅ meta_updates/{doc_id} 기록 완료")
    return ("OK", 200)
