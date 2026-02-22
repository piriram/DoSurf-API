# private/

Git에 올리면 안 되는 **민감 정보 전용 폴더**입니다.

## 저장 대상 (예시)
- Firebase 서비스 계정 키 (`serviceAccountKey.json`)
- API 키/토큰 파일
- 배포용 비공개 설정 파일

## 권장 구조

```text
private/
├── README.md                # 이 파일(커밋됨)
└── keys/                    # 실제 키 파일들(커밋 금지)
    └── serviceAccountKey.json
```

## 규칙
- `private/README.md`만 Git에 포함
- `private/` 하위 실제 파일은 `.gitignore`로 전부 제외
- 키 파일을 메신저/이슈/PR에 첨부하지 않기

## Firebase 로컬 실행
`scripts/firebase_utils.py`는 아래 순서로 키를 찾습니다.
1. `private/keys/serviceAccountKey.json` (권장)
2. `private/serviceAccountKey.json`
3. `secrets/serviceAccountKey.json` (레거시 호환)
