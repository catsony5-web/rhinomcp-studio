# RhinoMCP Studio 출처

RhinoMCP Studio 0.6.1은 Jingcheng Chen의 RhinoMCP를 기반으로 수정한 파생 프로젝트입니다. 원본 프로젝트나 제작자가 이 파생 배포물을 검증·보증한다는 의미는 아닙니다.

- 원본 저장소: [jingcheng-chen/rhinomcp](https://github.com/jingcheng-chen/rhinomcp)
- 기준 커밋: [`ddc6cfdaaca3a1dc7b8930b409d0c2fce28ec33a`](https://github.com/jingcheng-chen/rhinomcp/commit/ddc6cfdaaca3a1dc7b8930b409d0c2fce28ec33a)
- 원본 저작권: `Copyright (c) 2026 Jingcheng Chen`
- 원본 라이선스: [MIT](LICENSE). 원본 저작권 고지와 라이선스 전문을 보존합니다.

Studio는 로컬 Codex 연결을 위한 버전 고정 ZIP 설치·진단·제거, Python 서버와 플러그인 버전 일치 검사, 모델 변경 검증, 좌표 기반 벽·개구부·슬래브 도구, 한국어 사용 안내와 패키지 내 건축 모델링 가이드를 추가합니다. 기존 Rhino/Grasshopper 연결과 일반 도구는 원본 구현을 기반으로 합니다.

0.6.0은 운영자의 관리 서버, 로그인 없는 설치 등록, 작업별 온라인 승인, 전체·버전별 일시 중지·재개를 추가합니다. 관리 기능과 그로 인한 서비스 연결 의존성은 이 파생 프로젝트가 추가한 사항이며 원본 RhinoMCP의 요구사항이 아닙니다. 사용자 PC의 코드를 수정하거나 구버전을 별도로 사용하는 행위까지 완전히 통제하는 구조는 아닙니다.

사용자에게 표시하는 배포 이름은 **RhinoMCP Studio**, Codex MCP 이름은 `rhino-studio`, Yak 패키지 이름은 `rhinomcp-studio`입니다. Python 배포/모듈 이름 `rhinomcp`와 Rhino 플러그인 GUID는 호환성을 위해 유지합니다. 따라서 Jingcheng Chen의 원본 `rhinomcp` 플러그인과 동시에 설치할 수 없습니다.

Rhino 명령은 원본의 일반 이름 대신 `StudioMCPStart`, `StudioMCPStop`, `StudioMCPVersion`, `StudioMCPTest`로 분리합니다. RhinoPort의 별도 제품 **RhinoAiMCP**가 설치된 환경에서 일반 `mcpstart`가 다른 서버를 시작하는 충돌을 확인했기 때문입니다. RhinoAiMCP는 Studio와 GUID가 다르므로 설치된 상태로 유지할 수 있으며 자동 제거 대상이 아닙니다. 전용 명령 분리와 `127.0.0.1:1999`의 버전 진단은 의도한 플러그인을 구분하기 위한 것이고, 두 제품의 전체 동시 동작을 보증하지 않습니다.

배포 ZIP은 이 저장소에서 빌드한 wheel을 포함합니다. 원본 PyPI의 `rhinomcp@latest`를 Studio 설치물로 안내하지 않습니다. 원본 이름으로 자동 게시하던 `mcp-server-publish.yml`, `rhino-plugin-publish.yml` 워크플로는 이 파생 프로젝트에서 제거했습니다. Studio의 수동 배포 워크플로는 산출물만 만들며 외부 패키지 레지스트리에 게시하지 않습니다.

McNeel/Rhino, OpenAI/Codex 및 Grasshopper와 연결되는 제3자 도구이며, 해당 회사의 공식 제품 또는 공식 지원 배포물이 아닙니다. 플랫폼별 실제 검증 결과와 남은 제한은 릴리스 기록에 별도로 기재해야 합니다.
