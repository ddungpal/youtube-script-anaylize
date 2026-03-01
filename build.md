# 생각구독 분석 에이전시 — GitHub 연결 & 배포 가이드

---

## 목차

1. [GitHub 연결](#1-github-연결)
2. [Vercel 배포](#2-vercel-배포)
3. [Vercel 제약사항 및 대안](#3-vercel-제약사항-및-대안)

---

## 1. GitHub 연결

### 1-1. 로컬 Git 초기화

```bash
cd "/Users/dongwonchoi/Desktop/동원 백업/동원폴더/claude-code/유튜브 스크립트 분석/saenggak-agency"

# Git 초기화 (처음 한 번만)
git init
git add .
git commit -m "feat: 생각구독 분석 에이전시 v2 초기 커밋"
```

### 1-2. GitHub 리포지토리 생성

**방법 A — GitHub CLI (권장)**

```bash
# GitHub CLI 설치 (없으면)
brew install gh

# 로그인
gh auth login

# 리포지토리 생성 + 원격 연결 + 첫 Push (한 번에)
gh repo create saenggak-agency --private --source=. --remote=origin --push
```

**방법 B — 웹에서 수동 생성**

1. [github.com/new](https://github.com/new) 에서 `saenggak-agency` 리포지토리 생성
2. **"Add a README"** 체크 해제 (빈 리포 생성)
3. 아래 명령어 실행:

```bash
git remote add origin https://github.com/YOUR_USERNAME/saenggak-agency.git
git branch -M main
git push -u origin main
```

### 1-3. 이후 변경사항 Push

```bash
git add .
git commit -m "변경 내용 설명"
git push
```

### 확인 사항

- `.env` 파일은 `.gitignore`에 포함되어 **절대 커밋되지 않습니다.**
- `venv/` 및 DB 파일 (`database/saenggak.db`) 도 제외됩니다.
- `static/index.html`, `app.py`, `agents/` 등 소스 코드만 커밋됩니다.

---

## 2. Vercel 배포

### 2-1. 사전 준비

```bash
# Vercel CLI 설치
npm install -g vercel

# 또는 npx로 바로 사용 (설치 불필요)
npx vercel
```

### 2-2. 프로젝트 루트에서 배포

```bash
cd "/Users/dongwonchoi/Desktop/동원 백업/동원폴더/claude-code/유튜브 스크립트 분석/saenggak-agency"

# Vercel 로그인 + 배포 (첫 번째 실행)
vercel

# 또는 GitHub 리포와 연결 후 자동 배포 (권장)
vercel --prod
```

> **첫 실행 시 질문 응답 예시:**
> - Set up and deploy? → **Y**
> - Which scope? → 본인 계정 선택
> - Link to existing project? → **N** (신규)
> - Project name? → `saenggak-agency`
> - Directory? → `.` (현재 디렉터리)
> - Override settings? → **N**

### 2-3. 환경변수 설정 (필수)

Vercel 대시보드 → 프로젝트 → **Settings → Environment Variables** 에서 아래 변수를 추가합니다.

| 변수명 | 값 | 설명 |
|--------|-----|------|
| `OPENAI_API_KEY` | `sk-proj-...` | OpenAI API 키 (필수) |
| `DB_PATH` | `/tmp/saenggak.db` | Vercel 임시 디렉터리 사용 |
| `OPENAI_MODEL` | `gpt-4o` | 사용할 모델 (선택) |
| `OPENAI_TEMPERATURE` | `0` | 응답 일관성 (선택) |

또는 CLI로 설정:

```bash
vercel env add OPENAI_API_KEY
vercel env add DB_PATH
# 입력값: /tmp/saenggak.db
```

### 2-4. GitHub 연동 후 자동 배포

1. [vercel.com/dashboard](https://vercel.com/dashboard) → **Add New Project**
2. GitHub 리포지토리 `saenggak-agency` 선택
3. **Framework Preset** → `Other`
4. **Root Directory** → `.` (기본값)
5. **Build Command** → 비워 둠
6. **Output Directory** → 비워 둠
7. 환경변수 추가 (2-3 참고)
8. **Deploy** 클릭

이후 `main` 브랜치에 `git push` 하면 **자동으로 재배포**됩니다.

---

## 3. Vercel 제약사항 및 대안

### Vercel에서 동작하는 기능

| 기능 | 상태 | 비고 |
|------|------|------|
| 웹 UI (대시보드, 검색 등) | ✅ 정상 | |
| 신규 분석 (영상 1개) | ⚠️ 제한적 | 응답 시간 10~60초 초과 시 타임아웃 |
| DB 조회 (읽기) | ⚠️ 제한적 | Cold start마다 빈 DB에서 시작 |
| 트렌드 분석 / 심화 인사이트 | ❌ 미지원 | 백그라운드 스레드 미지원 |
| 리포트/차트 파일 저장 | ❌ 미지원 | 파일시스템 쓰기 불가 |

### Vercel 구조적 제약

Vercel은 **서버리스(Serverless)** 플랫폼이라 이 프로젝트와 구조적으로 맞지 않는 부분이 있습니다.

1. **파일시스템 비영속성**: DB와 리포트 파일이 `/tmp`에만 쓰여지며, Cold start마다 초기화됩니다.
2. **함수 타임아웃**: Hobby 플랜 10초, Pro 플랜 60초 — OpenAI API 호출(30초~)이 초과할 수 있습니다.
3. **백그라운드 스레드 미지원**: 트렌드/인사이트 분석처럼 응답 후 계속 실행되는 작업이 종료됩니다.

### 풀스택 배포 대안 (Railway — 권장)

SQLite + 장시간 프로세스를 지원하는 Railway가 이 프로젝트에 최적입니다.

```bash
# Railway CLI 설치
npm install -g @railway/cli

# 로그인 및 배포
railway login
railway init          # 프로젝트 초기화
railway up            # 배포
railway open          # 브라우저에서 열기
```

Railway 환경변수 설정:

```bash
railway variables set OPENAI_API_KEY=sk-proj-...
railway variables set OPENAI_MODEL=gpt-4o
railway variables set DB_PATH=database/saenggak.db
```

Railway 시작 명령 (`railway.json` 또는 설정 패널):

```json
{
  "deploy": {
    "startCommand": "uvicorn app:app --host 0.0.0.0 --port $PORT"
  }
}
```

### 플랫폼 비교

| 항목 | Vercel | Railway | Render |
|------|--------|---------|--------|
| SQLite 영속성 | ❌ | ✅ | ✅ |
| 장시간 작업 | ❌ | ✅ | ✅ |
| 무료 플랜 | ✅ | ✅ (Trial $5) | ✅ |
| 자동 재배포 (GitHub) | ✅ | ✅ | ✅ |
| Python FastAPI | ✅ (제한) | ✅ | ✅ |
| 이 프로젝트 적합도 | ⚠️ 데모용 | ✅ 프로덕션 | ✅ 프로덕션 |
