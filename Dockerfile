FROM python:3.11-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY . .

# 환경변수
ENV PORT=8080

# Flask 서버 실행
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 server:app