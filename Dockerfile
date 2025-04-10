# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY . .

# main.py가 진입점 (3시간마다 실행)
CMD ["python", "main.py"]
