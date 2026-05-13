"""
auth_setup.py — 사전 인증(Pre-warming) 세션 부트스트랩

전략
----
자동화로 네이버·쿠팡의 봇 탐지/캡차를 뚫는 대신, 사용자가 직접 한 번 캡차를 풀고
필요하면 로그인까지 마친 뒤 그 세션(쿠키·로컬스토리지)을 디스크에 저장한다.
이후 scraper.py 는 이 세션을 그대로 재사용해 봇 의심 점수가 낮은 상태로 크롤링한다.

저장 위치
---------
./auth_session  ← 실제 Chrome 의 User Data 형식이 그대로 들어가는 디렉터리.

실행
----
    python auth_setup.py

브라우저 창이 뜨면 네이버 쇼핑/쿠팡 두 탭에서 캡차 해제·(원하면) 로그인을 마치고
터미널로 돌아와 Enter 를 누른다 → 브라우저가 안전하게 종료되며 쿠키가 저장된다.
"""

import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

# Windows cp949 콘솔에서 박스 문자 출력이 터지지 않도록 UTF-8 재구성
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

AUTH_SESSION_DIR = pathlib.Path(__file__).parent / "auth_session"

NAVER_HOME   = "https://shopping.naver.com/"
COUPANG_HOME = "https://www.coupang.com/"

INSTRUCTIONS = """
═══════════════════════════════════════════════════════════════════
  사전 인증(Pre-warming) 세션 설정
═══════════════════════════════════════════════════════════════════
  열려있는 브라우저에서 다음 작업을 수행해 주세요.

    1) 네이버 쇼핑 탭
       - 캡차가 뜨면 직접 해제
       - (선택) 우측 상단에서 로그인까지 마치면 신뢰도 ↑
       - 검색창에 아무 키워드나 한 번 검색해서 정상 결과 페이지를 띄워두면 좋음

    2) 쿠팡 탭
       - 동일하게 캡차 해제 / (선택) 로그인 / 1회 검색

  모든 작업이 끝나면 이 터미널로 돌아와 Enter 를 누르세요.
  쿠키와 세션이 ./auth_session 에 저장됩니다.

  주의:
    - 이 창을 X 버튼으로 닫지 마세요. 반드시 터미널에서 Enter 로 종료해야
      Playwright 가 쿠키를 안전하게 디스크에 flush 합니다.
═══════════════════════════════════════════════════════════════════
"""


async def main() -> None:
    AUTH_SESSION_DIR.mkdir(exist_ok=True)
    print(INSTRUCTIONS)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(AUTH_SESSION_DIR),
            channel="chrome",            # 설치된 실제 Google Chrome
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            no_viewport=True,            # 사용자 화면 크기 그대로 사용
        )

        # 네이버 쇼핑 — 최초 페이지 재사용
        naver_page = context.pages[0] if context.pages else await context.new_page()
        try:
            await naver_page.goto(NAVER_HOME, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            print(f"[경고] 네이버 홈 로드 실패(계속 진행): {e}")

        # 쿠팡 — 새 탭으로 열기
        coupang_page = await context.new_page()
        try:
            await coupang_page.goto(COUPANG_HOME, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            print(f"[경고] 쿠팡 홈 로드 실패(계속 진행): {e}")

        # 사용자 작업 대기 — input() 은 블로킹이므로 별도 스레드에서 호출
        await asyncio.to_thread(
            input,
            "\n>>> 위 안내대로 작업을 마친 뒤, 여기서 Enter 키를 누르세요: ",
        )

        print("\n세션 저장 중... 브라우저를 안전하게 종료합니다.")
        try:
            await context.close()
        except Exception as e:
            print(f"[경고] 컨텍스트 종료 중 예외(무시): {e}")

    print(f"✅ 세션이 저장되었습니다: {AUTH_SESSION_DIR}")
    print("   이제 'python scraper.py <platform> <keyword> <id>' 로 크롤링을 시작하세요.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n중단됨 — 세션이 저장되지 않았을 수 있습니다.")
