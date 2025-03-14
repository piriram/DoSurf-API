# firebase_utils.py
import os
import firebase_admin
from firebase_admin import credentials, firestore

# 프로젝트 루트 디렉토리 위치를 계산 (현재 파일의 상위 폴더 기준)
ROOT_DIR = os.path.dirname(os.path.abspath(os.path.join(__file__, os.pardir)))

# Firebase 서비스 키 파일 경로 (루트 디렉토리에 있는 serviceAccountKey.json)
SERVICE_KEY_PATH = os.path.join(ROOT_DIR, "secrets" , "serviceAccountKey.json")

# 모듈 내부에서만 관리되는 Firestore 인스턴스 (싱글톤 캐시용)
_db = None

def get_db():
    """
    Firestore 클라이언트를 싱글톤으로 리턴.
    - 이미 생성되어 있으면 기존 객체를 그대로 반환
    - 없으면 새로 초기화해서 반환
    - serviceAccountKey.json 경로가 잘못되면 FileNotFoundError 발생
    """
    global _db  # 함수 안에서 전역 변수 _db를 사용하겠다고 명시

    # 이미 클라이언트가 만들어져 있으면 그대로 반환
    if _db is not None:
        return _db

    # 서비스 키 파일이 없으면 에러 발생 (초보자가 에러 위치를 알기 쉽게)
    if not os.path.exists(SERVICE_KEY_PATH):
        raise FileNotFoundError(f"serviceAccountKey.json not found at: {SERVICE_KEY_PATH}")

    # firebase_admin 앱이 아직 초기화되지 않았다면 초기화
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_KEY_PATH)  # 서비스 계정 키 로드
        firebase_admin.initialize_app(cred)              # Firebase 앱 초기화

    # Firestore 클라이언트 생성
    _db = firestore.client()
    return _db

# 외부에서 바로 사용 가능하도록 db라는 이름으로 초기화
db = get_db()

# 이 모듈에서 외부로 내보낼 공개 심볼 지정 (db와 get_db만 import 가능)
__all__ = ["db", "get_db"]
