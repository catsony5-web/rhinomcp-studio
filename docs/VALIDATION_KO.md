# RhinoMCP Studio 0.6.1 배포 준비와 0.6.0 실기 검증 기록

0.6.1 준비 날짜: 2026-09-12. 공개 운영 서버는 계정·비용 확인 전이며, 아직 다른 PC에 전달할 운영 설치 ZIP을 공개하지 않았습니다.

- 0.6.1 .NET 플러그인 Release 빌드: 경고 0, 오류 0.
- Python 서버 검사 351개 통과. 설치기에 기록하는 실제 실행 명령으로 stdio 연결·도구 검색·로컬 안내 실행을 검사하는 회귀 검사를 포함합니다. 기존 `python -m rhinomcp.server`에서 도구가 비는 문제를 `python -m rhinomcp` 패키지 진입점으로 수정했습니다. 실제 0.6.1 wheel을 별도 환경에 설치한 stdio·도구·스키마·안내 검사도 통과했습니다.
- 관리 서버·Render 초기화 검사 24개, 실제 C# 승인 검증 49개 통과. Render 구성은 공식 JSON Schema 검사도 통과했습니다.
- 설치·릴리스 검사 57개 중 56개 통과, Windows 심볼릭 링크 권한 관련 1개 제외. 공개 HTTPS 주소, 전체/내부 체크섬, wheel·Yak 버전과 승인 서명 형식을 검사합니다. localhost 시험 ZIP은 공개 릴리스 검사에서 거부됩니다. 실제 운영 HTTPS 승인 검사는 서버 배포 후 수행합니다.
- 일괄 수정은 활성 객체를 열거해 Undo에 남은 삭제 객체를 제외하도록 보완했고, Boolean 복원 검사에서 Extrusion을 잘못 Brep으로 변환하던 부분을 수정했습니다. 이 수정의 0.6.1 실제 Rhino 재검증은 설치 후 수행해야 합니다.
- 2026-09-12 배포 준비 중 읽기 전용 조회로 확인한 현재 실행 Rhino는 8.34.26223.11001입니다. 아래 0.6.0 기록을 0.6.1 실기 결과로 간주하지 않습니다.

## 이전 0.6.0 검증 결과

검증 날짜: 2026-09-12. 이번 버전의 검증 대상은 관리 서버, 온라인 승인, 설치·진단과 실제 Rhino에서의 중지·재개입니다. 자동 테스트와 실제 앱 실행 결과를 구분합니다.

| 항목 | 결과 |
| --- | --- |
| Python MCP 서버 | 350개 자동 테스트 통과. 기존 jsonschema.RefResolver deprecation 경고 2개 |
| 설치기 | 37개 검사 중 36개 통과, Windows symlink 권한 관련 1개 제외 |
| 관리 서버 | 실제 HTTP·인증·CSRF·정책 테스트 14개 통과 |
| 플러그인의 승인 검증 | 실제 C# 클라이언트를 연결한 .NET 검사 49개 통과: 서명 변조·난수·명령·시간·설정 불일치, 연결 실패 등 |
| 실제 관리 HTTP + C# 클라이언트 | 12개 통과: 전체·버전·설치별 중지/재개, 최소 버전, 중지 중 새 등록, 서버 연결 불가·설정 없음 거부 |
| 명령 계약 | 68개 명령의 JSON Schema·Python·C# 일치, 유효/잘못된 요청 검사 통과 |
| .NET Release 빌드 | 플러그인과 승인 검사 프로그램 모두 경고 0, 오류 0 |
| Windows 실제 설치 | 배포 ZIP에서 0.6.0 플러그인·전용 Python·Codex 설정·관리 등록 설치 완료 |
| 설치된 MCP 실행 | 소스 경로 주입 없이 stdio 초기화, MCP 도구 73개, 플러그인 명령 68개 확인 |
| Windows 실제 Rhino | 아래 7개 검사 통과. 설치된 Rhino 8.29와 로컬 관리 서버 사용 |
| macOS | 설치 진입점·경로 처리·공통 .NET 코드 준비. 실제 Mac 설치·Rhino 실행 미검증 |
| Docker / 공개 HTTPS | 배포 파일 준비. Docker 실행 및 실제 도메인의 TLS 발급·외부 PC 연결은 미검증 |

## 실제 Rhino에서 확인한 동작

1. 설치된 Python 서버와 플러그인이 모두 0.6.0이며 빈 문서인지 확인했습니다.
2. 온라인 승인을 받은 MCP 요청으로 실제 박스를 생성했습니다.
3. 관리자가 전체 중지한 후의 생성 요청이 거부되고 관리 상태 조회는 가능했습니다.
4. 재개 후 다시 연결되며 중지 중 생성 요청이 문서에 객체를 추가하지 않았습니다.
5. 정확한 버전 `0.6.0`의 중지·재개가 실제 플러그인에 적용됐습니다.
6. 이미 실행 중인 C# 작업은 중간에 종료되지 않았고, 다음 요청은 중지 정책에 따라 거부됐습니다.
7. 검사에서 만든 객체만 삭제하여 원래 빈 문서로 복원했습니다. 정책은 정상 운영 상태로 복원했습니다.

원본 보고서는 `artifacts/management-native-rhino.json`과 `artifacts/management-live-http.json`입니다. 전달 자료에는 두 보고서의 사본을 포함합니다. 인터넷 차단은 별도 C# 클라이언트에서 접속 불가 서버로 검사했으며, 실제 Rhino 시험 중 PC 네트워크나 핫스팟을 전환하지는 않았습니다.

## 검증의 범위

중지는 정책 저장 이후의 새 승인 요청부터 적용됩니다. 이미 발급되어 유효한 승인이나 실행 중인 작업을 강제 종료하는 기능은 아닙니다. 승인 유효기간은 최대 30초이며 요청 간 재사용하지 않습니다. 관리 상태 조회는 마지막 상태를 보여 주므로 다음 작업의 온라인 승인을 보장하지 않습니다.

0.6.0에서는 모든 모델링·Grasshopper 명령을 실제 Rhino로 다시 검사하지 않았습니다. 기존 0.5.1 통합 검사의 Boolean 부분 삭제 복원 검사와 일괄 변환 검사는 위에서 설명한 원인을 0.6.1 소스에서 보완했습니다. 모든 모델링 회귀 검사 통과 또는 Windows/macOS 양쪽의 운영 검증 완료를 주장하지 않습니다.

현재 PC의 관리 주소는 `http://127.0.0.1:8765`입니다. 이 설정이 들어간 ZIP은 같은 PC의 로컬 시험용입니다. 다른 PC에 전달하려면 HTTPS 운영 서버와 그 공개 프로필로 다시 빌드해야 합니다. 0.5.1 등 관리 기능 없는 기존 설치본은 먼저 관리형 버전으로 업데이트해야 합니다.

## 재현

저장소 루트에서 자동 검사를 실행합니다.

```powershell
server\.venv\Scripts\python.exe -m pytest server/tests -q
server\.venv\Scripts\python.exe -m unittest discover -s distribution/tests -v
server\.venv\Scripts\python.exe -m unittest discover -s management/tests -v
server\.venv\Scripts\python.exe contracts/test_schemas.py
dotnet run --project management-client-tests --configuration Release
```

실제 HTTP·Rhino 재현에는 실행 중인 로컬 관리 서버, 운영자 전용 비밀번호 파일과 검사 전용 빈 Rhino 문서가 필요합니다. `scripts/verify_management.py --help`와 `scripts/verify_management_rhino.py --help`로 필요한 경로를 확인합니다. 이 검사는 정책을 바꾸므로 다른 사용자가 이용 중인 운영 서버를 대상으로 실행하지 않습니다. 관리자 비밀번호·개인키·등록 토큰은 검사 보고서나 배포 ZIP에 포함하지 않습니다.

