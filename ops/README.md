# 24시간 로컬 자율운용 서비스

`com.kis-paper-trading.backend.plist`는 macOS 로그인 세션에서 백엔드를 자동 시작하고,
프로세스 종료 시 재시작한다. `caffeinate -is`로 실행되어 자율운용 중 유휴 절전을 막는다.

상태 확인:

```bash
curl http://127.0.0.1:8000/health
launchctl print gui/$(id -u)/com.kis-paper-trading.backend
```

로그는 `backend/logs/`에 기록된다. 앱을 업데이트한 뒤에는 서비스를 재시작해야 새 환경변수가 적용된다.
