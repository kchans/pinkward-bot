# STEP 1 — 개발 환경 세팅 체크리스트

목표: 코드 한 줄도 짜지 않는다. 오늘은 **"준비물 챙기기"만** 한다.
예상 소요: 60~90분

기술 스택 확정
- 언어: Python 3.12
- 봇 라이브러리: discord.py 2.x
- DB: Supabase (무료 클라우드 PostgreSQL)
- 에디터: VS Code

---

## 1. Python 3.12 설치 (약 10분)

1. https://www.python.org/downloads/release/python-3128/ 접속
2. 페이지 맨 아래 **Windows installer (64-bit)** 다운로드
3. 실행 후 **⚠️ 첫 화면 맨 아래 "Add python.exe to PATH" 체크박스를 반드시 체크** → Install Now
   - 이거 안 하면 나중에 `python` 명령어가 안 먹힌다. 가장 흔한 초보 실수.
4. 확인: 시작 메뉴 → `cmd` 실행 → 아래 입력

```
python --version
```

`Python 3.12.x` 가 나오면 성공. Microsoft Store가 열리면 PATH 체크를 놓친 것이니 재설치.

> Python 3.13 말고 3.12를 쓰는 이유: 일부 라이브러리가 최신 버전에서 아직 삐걱거린다. 안정성 우선.

---

## 2. VS Code 설치 (약 5분)

1. https://code.visualstudio.com/ → Download for Windows → 설치
2. 설치 옵션에서 "Add to PATH" / "Open with Code" 항목 전부 체크
3. VS Code 실행 → 왼쪽 확장(Extensions, `Ctrl+Shift+X`) 아이콘 → 아래 2개 설치
   - `Python` (Microsoft)
   - `Korean Language Pack` (선택, 한글 UI 원하면)

---

## 3. Git 설치 (선택이지만 권장, 약 5분)

https://git-scm.com/download/win → 다운로드 → 옵션 전부 기본값으로 Next

당장은 안 써도 되지만, 나중에 코드 백업/서버 배포할 때 필수다.

---

## 4. 디스코드 봇 생성 + 토큰 발급 (약 15분)

1. https://discord.com/developers/applications 접속 → 본인 디스코드 계정 로그인
2. 우상단 **New Application** → 이름 입력 (예: `LoL 명예의전당`) → 약관 동의 → Create
3. 왼쪽 메뉴 **Bot** 클릭
4. **Reset Token** 버튼 → Yes, do it! → 나타나는 문자열을 **즉시 복사해 메모장에 저장**
   - ⚠️ 이 토큰은 이 화면을 벗어나면 다시 볼 수 없다. 잃어버리면 Reset 다시.
   - ⚠️ 이 토큰은 봇의 비밀번호다. 절대 남에게 보여주거나 GitHub에 올리지 말 것.
5. 같은 Bot 페이지를 아래로 스크롤 → **Privileged Gateway Intents** 섹션
   - `SERVER MEMBERS INTENT` → **켜기** (서버 멤버 목록을 읽어야 명예의전당이 가능)
   - `MESSAGE CONTENT INTENT` → **켜기** (지금은 안 써도 나중 확장 대비)
   - 아래 **Save Changes** 꼭 누르기

### 봇을 내 서버에 초대하기

6. 왼쪽 메뉴 **OAuth2** → **URL Generator**
7. SCOPES 에서 체크:
   - `bot`
   - `applications.commands`
8. 아래 BOT PERMISSIONS 에서 체크:
   - Send Messages
   - Embed Links
   - Read Message History
   - Attach Files
   - Move Members  *(나중에 내전 팀 나눌 때 음성채널 이동용)*
   - Manage Roles  *(나중에 티어 역할 자동 부여용)*
9. 맨 아래 생성된 URL 복사 → 브라우저 주소창에 붙여넣기 → **내가 관리자인 테스트용 서버** 선택 → 승인
   - 테스트 서버가 없다면 디스코드에서 새 서버를 하나 만들어라 (본인 혼자만 있는 서버).
10. 서버 멤버 목록에 봇이 회색(오프라인)으로 보이면 성공.

---

## 5. 라이엇 API 키 발급 (약 10분)

1. https://developer.riotgames.com/ 접속 → 우상단 **LOGIN** → 라이엇 계정 로그인
2. 로그인하면 대시보드에 **DEVELOPMENT API KEY** 가 보인다 (`RGAPI-` 로 시작)
3. **REGENERATE API KEY** 눌러 발급 → 복사해서 메모장에 저장

### ⚠️ 반드시 알아야 할 제약

| 항목 | 개발용 키 (지금) | 개인용 승인 키 (나중) |
|---|---|---|
| 유효기간 | **24시간마다 만료** | 무기한 |
| 요청 한도 | 20회 / 1초, 100회 / 2분 | 훨씬 넉넉 |

- 개발용 키는 **매일 재발급**받아 `.env` 파일에 갈아끼워야 한다. 정상이다, 고장난 게 아니다.
- 24시간 만료 때문에라도, 그리고 저 100회/2분 한도 때문에라도 **DB 캐싱이 필수**다. 이게 STEP 3의 핵심 주제가 된다.
- 봇이 어느 정도 돌아가기 시작하면 같은 사이트에서 **REGISTER PRODUCT → Personal API Key** 를 신청한다. 승인에 보통 며칠~2주 걸리니, 개발이 어느 정도 진행되면 미리 넣어두는 게 좋다.

---

## 6. Supabase 무료 DB 생성 (약 15분)

1. https://supabase.com/ → **Start your project** → GitHub 또는 이메일로 가입
2. **New project** 클릭
   - Name: `lol-hof-bot`
   - Database Password: **강한 비밀번호 생성 후 반드시 메모장에 저장** (다시 못 본다)
   - Region: **Northeast Asia (Seoul)** 선택 (한국에서 가장 빠름)
   - Plan: Free
3. 생성에 2~3분 걸린다. 커피 한 잔.
4. 완료되면 좌측 하단 **Project Settings**(톱니바퀴) → **Database** 메뉴
5. **Connection string** 섹션에서 탭을 **Session pooler** 로 선택 → URI 복사
   - 형태: `postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres`
   - `[YOUR-PASSWORD]` 부분을 3번에서 저장한 실제 비밀번호로 바꿔서 메모장에 저장
   - ⚠️ **Transaction pooler(6543 포트)는 고르지 마라.** 우리가 쓸 asyncpg 라이브러리와 궁합이 나쁘다.

---

## 7. 프로젝트 폴더 + 가상환경 만들기 (약 15분)

### 7-1. 폴더 생성

`C:\dev\lol-hof-bot` 처럼 **경로에 한글이나 띄어쓰기가 없는** 위치에 폴더를 만든다.
(바탕화면이나 `내 문서`는 한글 경로 문제로 나중에 골치 아플 수 있다)

### 7-2. VS Code로 열기

VS Code → File → Open Folder → 방금 만든 `lol-hof-bot` 폴더 선택

### 7-3. 터미널 열고 가상환경 생성

VS Code 상단 메뉴 → Terminal → New Terminal (`Ctrl + Shift + \``)
아래를 **한 줄씩** 입력한다.

```powershell
py -3.12 -m venv .venv
```

```powershell
.venv\Scripts\activate
```

> 실행 정책 오류(`이 시스템에서 스크립트를 실행할 수 없으므로`)가 나면 아래를 한 번 실행하고 다시 activate:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

프롬프트 맨 앞에 `(.venv)` 가 붙으면 성공이다. **앞으로 터미널을 새로 열 때마다 이 activate를 해줘야 한다.**

### 7-4. 라이브러리 설치

```powershell
pip install "discord.py[speed]" asyncpg aiohttp python-dotenv
```

| 패키지 | 역할 |
|---|---|
| discord.py | 디스코드 봇 본체 |
| asyncpg | PostgreSQL 비동기 드라이버 (빠름) |
| aiohttp | 라이엇 API 비동기 호출 |
| python-dotenv | 비밀키를 `.env` 파일에서 안전하게 읽기 |

---

## 8. 폴더 구조 만들기

VS Code 탐색기에서 아래 구조대로 폴더와 **빈 파일**을 만든다. (내용은 STEP 2부터 채운다)

```
lol-hof-bot/
├── .venv/                  ← 자동 생성됨. 건드리지 말 것
├── .env                    ← 비밀키 보관 (절대 공유 금지)
├── .gitignore              ← 깃에 올리면 안 되는 것 목록
├── requirements.txt        ← 설치한 패키지 목록
├── bot.py                  ← 봇 실행 진입점
├── core/                   ← 공용 엔진
│   ├── __init__.py
│   ├── config.py           ← .env 값 로딩
│   ├── db.py               ← DB 연결 풀
│   └── riot.py             ← 라이엇 API 클라이언트 (Rate Limit 처리)
├── cogs/                   ← 기능별 명령어 모음
│   └── __init__.py
└── sql/                    ← 테이블 생성 SQL 스크립트
```

> `cogs`는 discord.py 용어로 "기능 묶음"이다. 명예의전당, 내전, 밴픽을 각각 별도 파일로 분리해 관리하기 위한 구조다. 처음부터 이렇게 잡아두면 나중에 기능이 20개가 돼도 안 무너진다.

### 8-1. `.env` 파일 내용

```
DISCORD_TOKEN=여기에_4번에서_받은_봇_토큰
RIOT_API_KEY=여기에_5번에서_받은_RGAPI로_시작하는_키
DATABASE_URL=여기에_6번에서_만든_postgresql로_시작하는_주소
```

- 값에 따옴표를 붙이지 않는다.
- `=` 앞뒤에 공백을 넣지 않는다.

### 8-2. `.gitignore` 파일 내용

```
.venv/
.env
__pycache__/
*.pyc
logs/
```

### 8-3. `requirements.txt` 자동 생성

```powershell
pip freeze > requirements.txt
```

---

## ✅ STEP 1 완료 확인

터미널에 `(.venv)` 가 붙은 상태에서:

```powershell
python -c "import discord, asyncpg, aiohttp, dotenv; print('OK', discord.__version__)"
```

`OK 2.x.x` 가 출력되면 STEP 1 완료.

---

## 완료 후 나에게 보고할 것

1. 위 확인 명령어 출력 결과 (또는 발생한 에러 메시지 전문)
2. 디스코드 테스트 서버에 봇이 초대되었는지 (예/아니오)
3. Supabase 프로젝트 생성 완료 여부 (예/아니오)

**절대 토큰, API 키, DB 비밀번호 자체는 나에게 붙여넣지 마라.** "발급 완료"라고만 하면 된다.

---

## 다음 단계 예고

- **STEP 2**: 봇을 실제로 켜서 디스코드에 온라인으로 띄우고, `/핑` 슬래시 명령어 하나 만들기
- **STEP 3**: DB 테이블 설계 + 라이엇 API 캐싱 아키텍처 (여기서 설계도를 먼저 그리고 동의를 구할 예정)
- **STEP 4**: `/등록` 명령어 — 디스코드 유저와 롤 계정 연결
