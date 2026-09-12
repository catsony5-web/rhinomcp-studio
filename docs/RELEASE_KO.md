# RhinoMCP Studio 관리형 배포

Windows와 macOS의 Rhino 8용 Codex MCP 설치 ZIP입니다. 실제 실행 검증 환경과 남은 제약은 ZIP의 `docs/VALIDATION_KO.md`에 기록되어 있습니다.

## 설치받는 분

1. 이 릴리스의 `rhinomcp-studio-버전.zip`과 `.zip.sha256`을 다운로드합니다. GitHub가 자동 제공하는 **Source code ZIP은 설치 파일이 아닙니다.**
2. 다운로드한 파일을 Codex에 전달하고 아래와 같이 요청합니다.

   > 이 RhinoMCP Studio 배포 ZIP의 SHA-256을 첨부 체크섬과 확인하고 압축을 풀어 INSTALL_KO.md를 읽어 주세요. 내 운영체제에 맞춰 설치·Codex 연결·doctor 진단을 수행해 주세요. 설치 파일에는 운영 관리 서버 주소와 공개키가 들어 있습니다. Rhino 문서 저장과 종료가 필요하면 알려 주세요.

3. 설치 후 Rhino 8에서 `StudioMCPStart`를 실행하고 Codex에서 연결을 확인합니다.

처음 설치에는 인터넷이 필요합니다. 이후에도 각 MCP 명령은 관리 서버의 온라인 승인을 받아야 합니다. 점검·지원 종료·관리 서버 장애 중에는 새 MCP 명령이 거부됩니다. Rhino 자체 모델링과 문서 저장은 계속 사용할 수 있습니다. Rhino를 사용할 수 있는 라이선스가 필요하며, MCP 설치를 위한 별도 Rhino 계정 로그인 절차는 없습니다.

## 배포 관리자가 공개하기 전 확인할 사항

- HTTPS 운영 서버를 배포하고 데이터베이스와 서명키의 영속 저장·백업을 확인합니다. `management/README_KO.md`에 운영 구성이 있습니다.
- 서버에서 내보낸 **공개 프로필** JSON을 GitHub 저장소 변수 `RHINO_MCP_MANAGEMENT_PROFILE`에 넣습니다. 관리자 암호, 개인 서명키, 설치 토큰은 넣지 않습니다.
- Actions의 **Studio distribution**을 수동 실행합니다. `create_draft`의 기본값은 꺼짐이며, 켜면 검사 통과 후 다운로드 파일이 첨부된 초안 릴리스를 만듭니다. 작업은 릴리스를 자동 공개하지 않습니다.
- 검사기는 ZIP 전체와 내부 체크섬, 필수 설치 문서, wheel·Yak 버전, 공개 서버 주소, 실제 HTTPS 등록 및 RSA-PSS 서명 승인을 확인합니다. 이 온라인 검사는 관리 서버에 시험 설치 기록을 생성하지만 등록 토큰을 로그나 배포 파일에 저장하지 않습니다.
- `public-release` GitHub Environment에 필요한 승인 규칙을 설정할 수 있습니다. 쓰기 권한은 초안 생성 작업에만 부여합니다.
- 운영 주소가 들어간 다운로드 파일로 새 PC 설치와 Rhino 연결, 중지·재개를 검증한 뒤 초안의 검증 결과·지원 범위를 확인하고 공개합니다. **이 자동 검사는 실제 Rhino 모델링 시험을 대신하지 않습니다.**
- 이미 같은 버전의 릴리스가 있으면 생성이 실패합니다. 기존 공개 파일을 덮어쓰지 않고 패치 버전을 올려 다시 배포합니다.

localhost·사설 주소의 시험 ZIP은 다른 사람에게 전달할 운영 배포본이 아닙니다. 기존 0.5.x 비관리형 설치는 업데이트가 필요합니다. 수정된 클라이언트의 통제 우회나 재등록을 통한 설치별 중지 해제까지 영구 차단하는 제품은 아닙니다.

워크플로 구현은 [GitHub CLI release create](https://cli.github.com/manual/gh_release_create)와 [GitHub 수동 워크플로 실행](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) 문서를 따릅니다.
