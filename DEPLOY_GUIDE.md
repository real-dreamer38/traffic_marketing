# 🚀 traffic_marketing — Ubuntu 서버 배포 가이드

데스크탑 → AWS EC2 / 오라클 클라우드 (Ubuntu 22.04 LTS) 이전용 가이드.
처음부터 끝까지 순서대로 따라가면 매일 KST 08:00 에 텔레그램으로 순위 리포트가 자동 발송됩니다.

> **전제**: Ubuntu 22.04 LTS, 1 vCPU / 1GB RAM 이상, 22번 포트 SSH 접근 가능.

---

## 0. 사전 준비 — 로컬에서 1회만

### 0-1. GitHub 푸시 전 마지막 점검

```bash
# 로컬 PC 터미널 (프로젝트 폴더에서)
git status                          # 변경사항 확인
git add .                           # .gitignore 가 .env / marketing.db / auth_session/ 제외
git commit -m "chore: prepare for Ubuntu deployment"
git push origin main
```

⚠️ `.env`, `marketing.db`, `auth_session/` 가 git status 에 나타나면 **절대 푸시하지 마세요.** `.gitignore` 가 제대로 적용됐는지 다시 확인하세요.

### 0-2. 텔레그램 봇 토큰 / 챗 ID 메모

서버에서 `.env` 를 다시 만들어야 하므로 미리 복사해 두기:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

---

## 1. 서버 접속 & 시스템 패키지 설치

```bash
# SSH 접속 (AWS EC2 예시)
ssh -i ~/your-key.pem ubuntu@<EC2_PUBLIC_IP>

# 오라클 클라우드 / 일반 Ubuntu 서버
ssh ubuntu@<SERVER_IP>
```

```bash
# 시스템 업데이트 (5분 정도)
sudo apt update && sudo apt upgrade -y

# Python 3 + venv + pip + git 설치 (Ubuntu 22.04 는 Python 3.10 이 기본 포함)
sudo apt install -y python3 python3-pip python3-venv git tmux

# Python 버전 확인 (3.10+ 권장)
python3 --version
```

---

## 2. 코드 클론 & 가상환경 셋업

```bash
# 홈 디렉터리에서
cd ~

# GitHub 에서 코드 받기
git clone https://github.com/<YOUR_GITHUB_ID>/traffic_marketing.git
cd traffic_marketing

# 가상환경 생성 + 활성화 (이후 모든 pip/python 명령은 venv 안에서)
python3 -m venv venv
source venv/bin/activate

# 활성화되면 프롬프트가 (venv) 로 시작함
```

> 💡 다음 세션에서 다시 접속하면 항상 `cd ~/traffic_marketing && source venv/bin/activate` 먼저.

---

## 3. Python 의존성 + Playwright 브라우저 설치

```bash
# (venv 활성화 상태에서)
pip install --upgrade pip
pip install -r requirements.txt

# Playwright Chromium 브라우저 + 시스템 의존 라이브러리 설치
# (--with-deps 가 libnss3, libatk-bridge2.0-0 등 헤드리스 Chromium 에 필요한
#  apt 패키지까지 자동으로 깔아줌. sudo 권한 한 번 필요)
sudo $(which python) -m playwright install --with-deps chromium

# 또는 sudo 가 venv 를 못 찾으면 두 줄로 나누어 실행:
#   python -m playwright install chromium
#   sudo apt install -y libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgtk-3-0 libasound2
```

---

## 4. 환경변수 (.env) 작성

```bash
# 템플릿 복사
cp .env.example .env

# nano 또는 vim 으로 편집
nano .env
```

다음 두 값을 실제 값으로 채워 넣고 `Ctrl-O → Enter → Ctrl-X` 로 저장:

```env
TELEGRAM_BOT_TOKEN=8823068824:AAGGEZlkjq_FIy7C8E1nULLJqBU-dQ0M5o8
TELEGRAM_CHAT_ID=6554024624
REPORT_HOUR=8
REPORT_MINUTE=0
```

권한도 본인만 읽을 수 있게 잠가두기:

```bash
chmod 600 .env
```

---

## 5. DB 초기화 + (선택) 샘플 데이터

```bash
python database.py init        # 빈 marketing.db 생성
# python database.py seed      # 샘플 상품 4건 시드 — 필요 시
python database.py list        # 등록된 상품 확인
```

---

## 6. 네이버/쿠팡 사전 인증 (auth_session) — ⚠️ 1회 수동 작업

서버는 GUI 가 없으므로 캡차를 직접 풀 수 없습니다. 두 가지 방법 중 택1:

### 방법 A — 로컬에서 만든 `auth_session/` 폴더를 서버로 업로드 (권장)

```bash
# 로컬 PC (별도 터미널) — 프로젝트 폴더에서
# auth_session 폴더를 통째로 tar 로 묶어 전송
tar czf auth_session.tar.gz auth_session/
scp auth_session.tar.gz ubuntu@<SERVER_IP>:~/traffic_marketing/

# 서버
cd ~/traffic_marketing
tar xzf auth_session.tar.gz
rm auth_session.tar.gz
chmod -R 700 auth_session
```

### 방법 B — 서버에 X11 포워딩으로 직접 실행 (어렵습니다)

```bash
# SSH 접속 시 -X 옵션 + 서버에 xvfb 설치 필요. 비추.
ssh -X ubuntu@<SERVER_IP>
sudo apt install -y xvfb
python auth_setup.py
```

---

## 7. 동작 확인 — 일회성 실행

```bash
# (venv 활성화 + .env + auth_session 모두 준비된 상태에서)
python scheduler.py --now
```

성공하면:
- 콘솔에 `[📊 데일리 순위 모니터링 리포트] — YYYY-MM-DD` 로그
- 텔레그램으로 순위 리포트 메시지 도착
- `Telegram 메시지 전송 완료 (message_id=N)` 로그

실패 패턴별 대응:
| 증상 | 원인 | 해결 |
|---|---|---|
| `auth_session 이 비어 있거나 없습니다` | 6번 단계 누락 | 로컬에서 auth_session 만든 뒤 scp 로 업로드 |
| `TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 비어 있습니다` | `.env` 미작성 또는 로드 실패 | `cat .env` 로 값 확인 |
| Playwright `Executable doesn't exist` | 브라우저 미설치 | `python -m playwright install chromium` 재실행 |
| `libnss3.so: cannot open shared object` | 시스템 라이브러리 부족 | `sudo apt install -y libnss3 libnspr4 libatk-bridge2.0-0` |

---

## 8. 24시간 백그라운드 실행 — 3가지 방식 중 택1

### 🥇 방식 A — tmux (가장 간단, 추천)

```bash
# 세션 시작
tmux new -s rank-bot

# 안에서 스케줄러 실행
cd ~/traffic_marketing
source venv/bin/activate
python scheduler.py --schedule

# 세션 detach (스케줄러는 계속 동작): Ctrl-B 누르고 D
# SSH 끊고 다시 들어와서 다시 보려면:
tmux attach -t rank-bot

# 세션 목록 확인
tmux ls

# 세션 종료 (스케줄러 영구 정지)
tmux kill-session -t rank-bot
```

### 🥈 방식 B — nohup (가장 가볍게)

```bash
cd ~/traffic_marketing
source venv/bin/activate

# 백그라운드로 실행, 로그는 scheduler.log 로 리다이렉트
nohup python scheduler.py --schedule > scheduler.log 2>&1 &

# 프로세스 확인
ps aux | grep scheduler.py

# 실시간 로그 확인
tail -f scheduler.log

# 정지 (PID 확인 후)
ps aux | grep scheduler.py | grep -v grep | awk '{print $2}' | xargs kill
```

### 🥉 방식 C — systemd (서버 재부팅에도 자동 부활, 운영용)

```bash
sudo nano /etc/systemd/system/rank-bot.service
```

다음 내용 붙여넣기 (`ubuntu` 부분은 본인 계정명으로):

```ini
[Unit]
Description=Traffic Marketing — Daily Rank Report Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/traffic_marketing
EnvironmentFile=/home/ubuntu/traffic_marketing/.env
ExecStart=/home/ubuntu/traffic_marketing/venv/bin/python scheduler.py --schedule
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/traffic_marketing/scheduler.log
StandardError=append:/home/ubuntu/traffic_marketing/scheduler.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rank-bot     # 부팅 시 자동 시작
sudo systemctl start rank-bot
sudo systemctl status rank-bot     # 동작 상태 확인
journalctl -u rank-bot -f          # 실시간 로그
```

---

## 9. (선택) 대시보드를 외부에서 보기

서버에서 Streamlit 대시보드를 8501 포트로 띄우려면:

```bash
# 방화벽 / 보안그룹에서 8501 포트 열어두기 (AWS 콘솔에서 설정)

# tmux 안에서
tmux new -s dashboard
cd ~/traffic_marketing && source venv/bin/activate
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0
# Ctrl-B D 로 detach

# 브라우저에서: http://<SERVER_IP>:8501
```

⚠️ 보안: 공개 IP 로 노출 시 누구나 접근 가능합니다. Nginx + Basic Auth 또는 SSH 포트포워딩(`ssh -L 8501:localhost:8501 ubuntu@<IP>`) 권장.

---

## 10. 운영 체크리스트

매주 1번씩 확인하면 좋은 것들:

```bash
# 1. 스케줄러가 살아있는가?
sudo systemctl status rank-bot       # systemd 방식
# 또는
tmux ls                              # tmux 방식

# 2. 최근 로그에 에러 있는가?
tail -100 scheduler.log
journalctl -u rank-bot --since "1 day ago"

# 3. DB 가 정상적으로 쌓이는가?
python database.py list
sqlite3 marketing.db "SELECT rank_date, COUNT(*) FROM rank_history GROUP BY rank_date ORDER BY rank_date DESC LIMIT 7;"

# 4. auth_session 만료 (캡차 다시 떠서 스크랩 실패) 알림이 텔레그램으로 오면:
#    → 로컬에서 auth_setup.py 다시 돌려 새 auth_session/ 만든 뒤 scp 로 업로드
```

---

## 11. 코드 업데이트 절차

로컬에서 코드를 고친 뒤 서버에 반영하는 워크플로우:

```bash
# 로컬 PC
git add . && git commit -m "feat: ..." && git push

# 서버
cd ~/traffic_marketing
git pull
source venv/bin/activate
pip install -r requirements.txt    # 의존성 변경 시에만

# 스케줄러 재시작
sudo systemctl restart rank-bot    # systemd
# 또는 tmux 라면 attach 해서 Ctrl-C 후 다시 실행
```

---

## 부록 — 빠른 reference

| 작업 | 명령어 |
|---|---|
| venv 활성화 | `source ~/traffic_marketing/venv/bin/activate` |
| 일회성 실행 | `python scheduler.py --now` |
| 메시지 미리보기 (전송 X) | `python scheduler.py --dry-run` |
| 스케줄러 데몬 | `python scheduler.py --schedule` |
| 시각 변경 | `python scheduler.py --schedule --hour 9 --minute 30` |
| DB 초기화 | `python database.py init` |
| DB 시드 | `python database.py seed` |
| 대시보드 | `streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0` |
| 통합 테스트 | `python test_integration.py` |

배포 끝났으면 텔레그램에 "🎉 서버 배포 완료" 한 줄만 보내져도 성공입니다. 🚀
