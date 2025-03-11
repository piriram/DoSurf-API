import os
import firebase_admin
from firebase_admin import credentials, firestore

# 프로젝트 루트: .../do-surf-functions
ROOT_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))
SERVICE_KEY_PATH = os.path.join(ROOT_DIR, "serviceAccountKey.json")

_db = None

def get_db():
    """
    Firestore 클라이언트를 싱글톤으로 리턴.
    serviceAccountKey.json 경로가 틀리면 여기서 명확히 에러를 던져줍니다.
    """
    global _db
    if _db is not None:
        return _db

    if not os.path.exists(SERVICE_KEY_PATH):
        raise FileNotFoundError(f"serviceAccountKey.json not found at: {SERVICE_KEY_PATH}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_KEY_PATH)
        firebase_admin.initialize_app(cred)

    _db = firestore.client()
    return _db

# 외부에 바로 쓰라고 export
db = get_db()

__all__ = ["db", "get_db"]
