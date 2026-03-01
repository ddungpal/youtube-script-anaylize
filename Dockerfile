FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (yt-dlp, matplotlib 빌드용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (레이어 캐싱 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 출력 디렉터리 생성
RUN mkdir -p outputs/reports outputs/trends outputs/charts data

EXPOSE 8000
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
