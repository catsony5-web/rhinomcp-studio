# RhinoMCP Studio 0.6.1 — 관리형 배포

Rhino 8과 Grasshopper를 **Codex에서 조작하는 MCP**입니다. 모델링은 사용자 PC에서 실행하고, 새 Rhino 작업마다 운영자의 관리 서버에서 사용 승인을 확인합니다. 운영자는 전체·특정 버전을 일시 중지하거나 재개할 수 있습니다. 건축·인테리어 도구와 설치·진단·제거 스크립트를 포함합니다.

**관리 서버에 연결할 수 없거나 점검 중이면 새 MCP 작업은 실행되지 않습니다.** 이미 실행 중인 작업, Rhino 수동 편집과 저장은 유지됩니다. `describe_capabilities`, `get_management_status`와 로컬 문서 안내는 진단을 위해 이용할 수 있습니다.

**현재 공개 상태: 소스·운영 배포 구성 준비.** 운영 서버 연결과 외부 설치 검증을 마친 설치 ZIP은 [GitHub Releases](https://github.com/catsony5-web/rhinomcp-studio/releases)에 게시합니다. 아직 운영 설치 ZIP이 없는 경우 소스 ZIP이나 localhost 시험 ZIP으로 설치를 진행하지 마세요. [운영자 배포 절차](management/RENDER_KO.md)를 먼저 완료해야 합니다.

Rhino 플러그인과 전용 Python 서버를 하나의 배포 ZIP으로 설치합니다. 플러그인 다운로드·설치에는 Rhino 계정 로그인이 필요하지 않습니다. Rhino 본체의 유효한 라이선스는 별도로 필요합니다. [McNeel 패키지 설치 안내](https://developer.rhino3d.com/en/guides/yak/the-package-server/)

## 시작하기

필요한 환경은 **Rhino 8.20 이상(.NET 8), 설치된 Codex, 설치 및 MCP 사용 중 관리 서버에 연결 가능한 인터넷**입니다. Windows x64와 macOS Intel/Apple Silicon을 대상으로 합니다. 실제 검사 범위와 결과는 배포 ZIP과 함께 전달되는 `VALIDATION_KO.md`를 확인하세요. macOS 실제 실행 검증은 아직 완료하지 않았습니다.

Releases에 첨부된 `rhinomcp-studio-0.6.1.zip`과 `.zip.sha256`을 사용하세요. GitHub의 `Code → Download ZIP`과 릴리스의 자동 생성 `Source code`는 개발 소스입니다. 사용자는 관리 서버를 설치하거나 Rhino 계정으로 플러그인 다운로드에 로그인할 필요가 없습니다.

**Codex에 아래 내용을 붙여 넣고 마지막 줄을 실제 ZIP 경로나 배포 링크로 바꾸세요.**

```text
RhinoMCP Studio 배포 ZIP을 이 컴퓨터에 설치해 주세요.
먼저 포함된 INSTALL_KO.md와 설치 코드를 읽고 운영체제, Rhino 8 버전과 .NET 8 모드를 확인하세요.
ZIP과 함께 제공된 SHA-256을 확인한 뒤 압축을 풀어 주세요.
Rhino 작업을 저장하고 종료하도록 안내한 다음 Windows는 install.ps1, macOS는 install.sh를 실행하세요.
Codex MCP 이름은 rhino-studio로 등록하고 기존 다른 MCP와 전역 Python 설정을 보존하세요.
원본 rhinomcp가 설치돼 있으면 충돌을 설명하고, 교체가 승인된 경우에만 ReplaceUpstream/replace-upstream 옵션을 사용하세요.
설치 후 Rhino와 Codex MCP를 다시 연결하고 doctor로 실제 버전과 연결을 확인하세요.
설치 확인 중 기존 Rhino 문서의 객체는 변경하지 마세요. 확인하지 못한 항목은 별도로 알려 주세요.
배포 ZIP 경로 또는 실제 배포 링크: 여기에 입력
```

직접 설치하려면 압축을 푼 폴더에서 Rhino를 종료한 상태로 실행합니다.

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

```bash
# macOS
bash ./install.sh
```

Rhino와 Codex MCP를 다시 연결한 뒤 같은 폴더의 `doctor.ps1` 또는 `doctor.sh`를 실행하세요. 수동 시작은 Rhino 명령줄의 **`StudioMCPStart`**, 종료는 `StudioMCPStop`, 플러그인 버전 확인은 `StudioMCPVersion`입니다.

기존 `mcpstart`는 다른 Rhino MCP 플러그인의 명령일 수 있어 Studio 연결 확인에 사용하지 않습니다. **RhinoAiMCP는 별도 플러그인 ID를 사용하므로 설치된 상태로 유지할 수 있습니다.** Jingcheng Chen의 원본 `rhinomcp`는 Studio와 ID가 같아 동시에 설치할 수 없습니다. 구분과 교체 절차는 [설치 안내](docs/INSTALL_KO.md)를 확인하세요.

## 할 수 있는 작업

| 작업 | 도구와 범위 |
| --- | --- |
| 문서 확인 | 단위·공차·레이어·객체 조회, 치수·체적·유효성 검사, 뷰포트 캡처 |
| 벽 | `create_wall`: 수평 직선 중심선, 높이·두께, 사각형 문·창 개구부 |
| 바닥 | `create_floor_slab`: 수평 polygon 외곽과 관통 홀, 아래 방향 두께 |
| 일반 모델링 | 곡선·기본 형상, 돌출·로프트·스윕, Boolean, 이동·회전·속성 변경 |
| Grasshopper | 컴포넌트 검색, 입력·출력 확인, 연결·값 설정, 그래프 생성·수정, 해석 결과 조회 |

벽과 바닥은 Rhino의 닫힌 Brep입니다. BIM 타입, 재료층, 자동 벽 접합, 지속적인 매개변수 편집 이력은 제공하지 않습니다. 좌표·개구부 제약과 검증 예제는 [벽·바닥 안내](docs/ARCHITECTURE_KO.md)에 있습니다.

새 빈 문서에서 시작할 때 사용할 수 있는 요청 예시입니다.

> 문서 단위와 공차부터 확인해 줘. 밀리미터 기준 길이 6000, 높이 3000, 두께 200인 벽을 만들고 시작점에서 800 떨어진 곳에 폭 900, 높이 2100인 문을 뚫어 줘. 기존 객체를 보존하고 반환 GUID로 체적과 솔리드 상태, 문 위치를 확인해 줘.

> 현재 Grasshopper 정의를 읽고 기존 컴포넌트를 보존해 줘. 폭과 깊이 슬라이더로 조절하는 직사각형 그래프를 추가하고, 연결·출력값·경고를 확인해 줘.

서버에는 `get_modeling_guidance("architecture")`를 비롯한 모델링 가이드가 함께 들어 있습니다. 단위와 기존 상태를 먼저 읽고, 도구 성공 이후에도 치수·형상을 검증합니다. 시간 초과로 실행 결과가 불분명하면 상태를 확인하기 전 같은 변경을 다시 실행하지 않습니다.

## 배포와 출처

이 프로젝트는 Jingcheng Chen의 [rhinomcp](https://github.com/jingcheng-chen/rhinomcp)를 기반으로 수정한 **제3자 파생 프로젝트**입니다. McNeel이나 OpenAI의 공식 제품이 아닙니다. 원본 커밋과 변경 범위는 [PROVENANCE.md](PROVENANCE.md), 원본 저작권과 사용 조건은 [MIT 라이선스](LICENSE)를 확인하세요.

운영자는 [Render 배포 안내](management/RENDER_KO.md) 또는 [Docker/Caddy 안내](management/README_KO.md)로 HTTPS 관리 서버를 먼저 준비합니다. Render 구성은 유료 상시 서버와 1GB 영구 저장소를 사용하며, 계정·요금 확인 없이 생성하지 않습니다.

배포 ZIP 빌드 방법은 [설치 안내의 개발자 절차](docs/INSTALL_KO.md#개발자가-배포-zip-만들기)에 있습니다. Studio 배포 워크플로는 수동 실행으로 검사 후 GitHub Release 초안을 준비합니다. 운영 설치·연결 검사 후 초안을 공개하세요. PyPI나 Yak 레지스트리에는 자동 게시하지 않습니다. 실제 Windows/macOS 검증 결과를 구분해 기록합니다.
