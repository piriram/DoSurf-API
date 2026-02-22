import os
import firebase_admin
from firebase_admin import credentials, firestore

_db = None

def get_db():
    """Firestore 클라이언트 반환 (Cloud Run용)"""
    global _db
    if _db is not None:
        return _db
    
    # Cloud Run 환경에서는 기본 인증 사용
    if os.environ.get('K_SERVICE'):  # Cloud Run 환경 감지
        print("🔧 Initializing Firebase with default credentials (Cloud Run)")
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        _db = firestore.client()
        return _db
    
    # 로컬 환경에서는 serviceAccountKey.json 사용
    root_dir = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))
    service_key_path = os.path.join(root_dir, "secrets", "serviceAccountKey.json")
    
    if os.path.exists(service_key_path):
        print(f"🔧 Initializing Firebase with service account key (Local)")
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_key_path)
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
        return _db
    
    # 둘 다 없으면 에러
    raise FileNotFoundError(
        "Firebase initialization failed. "
        "Running locally without serviceAccountKey.json, "
        "or running on Cloud Run without proper permissions."
    )


class _LazyFirestoreClient:
    """Lazy proxy for Firestore client to avoid import-time initialization."""

    def __getattr__(self, item):
        return getattr(get_db(), item)


db = _LazyFirestoreClient()
