# RhinoMCP Studio 설치 안내

RhinoMCP Studio는 Rhino 8과 Grasshopper를 Codex에서 제어하는 로컬 MCP입니다. Windows x64와 macOS의 Intel/Apple Silicon을 대상으로 합니다. 플러그인 설치에는 Rhino 계정 로그인이 필요하지 않습니다. Rhino 본체의 유효한 라이선스와 설치된 Codex는 필요합니다.

Rhino 8.20 이상에서 .NET 8 모드를 사용하세요. Windows에서 오래된 플러그인 때문에 Rhino를 .NET Framework 모드로 실행한다면, Studio를 사용하기 전에 해당 플러그인의 .NET 8 호환성을 확인해야 합니다. 설치 프로그램이 Rhino의 런타임 설정을 임의로 바꾸지는 않습니다.

**0.6.0부터는 설치 등록과 MCP 작업 실행에 관리 서버가 필요합니다.** Rhino 플러그인이 각 작업을 실행하기 직전에 서버 승인을 확인합니다. 관리자가 전체·버전·설치별로 중지했거나 서버에 연결할 수 없으면 새 MCP 작업을 실행하지 않습니다. 인터넷·관리 서버 장애에도 같은 제한이 적용되며 오프라인 사용 유예는 없습니다. 실행을 시작한 작업을 강제로 종료하지 않으며 Rhino 수동 사용과 모델 저장은 계속 가능합니다. 관리 상태를 읽는 진단 요청은 연결 장애를 설명하기 위해 로컬에서 동작합니다.

무료 배포 ZIP에는 관리 서버 주소와 공개 서명 검증 키만 들어갑니다. 설치 시 개별 설치 ID와 비밀 토큰을 발급받습니다. 핫스팟이나 VPN으로 IP가 바뀌어도 이 설치 등록과 서버 정책으로 승인 여부를 판단합니다. 관리 기능이 없는 구버전은 0.6.0 이상으로 업데이트해야 적용됩니다. 사용자 PC의 코드 변조나 별도 클라이언트 제작까지 완전히 막는 기능은 아닙니다.

## Codex에 링크로 설치 요청하기

배포자가 운영하는 관리 서버가 설정된 **`rhinomcp-studio-0.6.1.zip`**을 사용합니다. GitHub의 `Code → Download ZIP`은 개발 소스이며 바로 설치하는 배포물이 아닙니다. 설치 스크립트가 실행될 때 Python과 서버 의존성을 처음 준비하므로 인터넷 연결이 필요합니다. 파일에 포함된 서버 wheel과 잠긴 의존성 버전을 사용하며, 실행할 때 원본 PyPI 최신 버전을 받지 않습니다. `bundle.json`의 `local_demo_only`가 `true`인 ZIP은 같은 컴퓨터의 시험 서버에만 연결하므로 일반 사용자에게 배포하는 운영 릴리스로 사용하면 안 됩니다.

Codex에 아래 문장을 전달하고 마지막 줄의 링크를 실제 저장소/Release 링크로 바꾸세요.

> 이 링크의 RhinoMCP Studio 릴리스를 설치해 주세요. INSTALL_KO.md와 설치 코드를 먼저 확인하고, 이 PC의 Windows/macOS 및 Rhino 8 환경을 진단하세요. 최신 검증 릴리스 ZIP과 SHA-256 파일을 받아 일치하는지 확인한 뒤, Rhino를 종료한 상태에서 운영체제에 맞는 install.ps1 또는 install.sh를 실행하세요. Codex MCP 이름은 rhino-studio입니다. 다른 MCP와 전역 Python 설정은 보존하세요. 원본 rhinomcp가 설치돼 있으면 충돌 내용을 먼저 보고하고, 사용자가 교체를 승인한 경우에만 ReplaceUpstream/replace-upstream 옵션을 쓰세요. 설치 후 Rhino를 열고 Codex MCP를 다시 연결한 뒤 doctor로 버전과 연결을 확인하세요. 실제 문서의 객체는 변경하지 마세요. 설치 링크: [여기에 실제 GitHub Release 링크]

## Windows

1. Rhino 작업을 저장하고 Rhino를 종료합니다.
2. ZIP 압축을 풉니다. 경로에 공백이나 한글이 있어도 됩니다.
3. 압축을 푼 폴더에서 PowerShell을 열어 실행합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

이 명령의 실행 정책 옵션은 해당 프로세스에만 적용됩니다. 회사의 그룹 정책이 스크립트 실행을 금지하면 그 정책을 변경하지 말고 회사 IT 담당자에게 설치 허용을 요청하세요.

설치가 끝나면 Rhino를 열고 Codex를 재시작하거나 MCP 연결을 다시 시작합니다. Rhino 플러그인은 시작할 때 자동으로 연결을 준비합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\doctor.ps1
```

기본 설치 위치는 `%LOCALAPPDATA%\RhinoMCPStudio`입니다. 설치 경로 또는 Rhino 설치 위치가 다르면 다음 옵션을 사용합니다. `CodexConfig`는 생략하면 현재 `CODEX_HOME/config.toml`, `CODEX_HOME`이 없으면 `~/.codex/config.toml`을 사용합니다.

관리 등록은 `InstallRoot` 옵션과 관계없이 `%LOCALAPPDATA%\RhinoMCPStudio\management.json`에 저장합니다. 이 파일의 `installation_token`은 외부에 공유하지 마세요. 같은 사용자 계정에 서로 다른 InstallRoot로 중복 설치하여 기존 등록을 덮어쓰는 것은 거부합니다.

```powershell
.\install.ps1 -InstallRoot 'D:\Tools\RhinoMCPStudio' -RhinoPath 'C:\Program Files\Rhino 8' -CodexConfig 'C:\Users\사용자\.codex\config.toml'
```

## macOS

Rhino를 종료하고 압축을 푼 폴더에서 실행합니다.

```bash
bash ./install.sh
```

Rhino와 Codex를 다시 연 뒤 확인합니다.

```bash
bash ./doctor.sh
```

기본 설치 위치는 `~/Library/Application Support/RhinoMCPStudio`입니다. Rhino가 다른 위치에 있으면 다음처럼 지정합니다.

관리 등록은 설치 위치를 바꾸더라도 `~/Library/Application Support/RhinoMCPStudio/management.json`에 저장합니다. 설치 프로그램은 이 파일을 해당 사용자만 읽고 쓸 수 있는 `0600` 권한으로 만듭니다.

```bash
bash ./install.sh --rhino-path '/Applications/Rhino 8.app'
```

macOS의 Gatekeeper나 회사 보안 정책이 플러그인을 차단할 경우 차단된 항목과 배포 출처를 확인하세요. 설치 스크립트는 시스템 보안 설정을 끄거나 다른 플러그인의 격리 속성을 제거하지 않습니다.

## 기존 RhinoMCP와 함께 설치된 경우

**Jingcheng Chen의 원본 `rhinomcp`**와 Studio는 플러그인 ID가 같아 동시에 설치할 수 없습니다. 설치 프로그램이 원본 Yak 패키지를 찾으면 변경 전에 중지합니다. 교체하기로 결정했다면 다음 옵션을 사용합니다. 원본 패키지는 제거하고 Studio로 교체하며, 다른 Codex MCP 항목은 남습니다. 그 항목이 원본 서버를 실행한다면 Codex에서 사용 중지해야 합니다.

```powershell
.\install.ps1 -ReplaceUpstream
```

```bash
bash ./install.sh --replace-upstream
```

`.rhp`를 직접 끌어넣어 설치한 원본은 Rhino의 `PlugInManager`에서 먼저 제거/비활성화하세요. 설치 프로그램은 수동 설치 경로를 임의로 삭제하지 않습니다.

**RhinoPort의 RhinoAiMCP는 별도 제품이며 플러그인 ID도 다릅니다.** 이를 설치된 상태로 유지할 수 있고 Studio 설치 프로그램은 제거하지 않습니다. 다만 서로 다른 플러그인이 `mcpstart` 같은 명령 이름을 공유하면 예상과 다른 서버가 시작될 수 있습니다. 실제 확인에서도 `mcpstart`가 기존 플러그인의 서버를 시작했고 Studio가 로드되었다는 증거가 되지 않았습니다. Studio는 이 충돌을 피하도록 `StudioMCPStart` 등 전용 명령을 사용합니다. 다른 플러그인의 정상 시작 메시지만 보고 Studio 설치가 성공했다고 판단하지 마세요.

Studio의 연결 대상은 `127.0.0.1:1999`입니다. `StudioMCPVersion`과 doctor로 실제 Studio 버전·연결을 확인하세요. 명령 이름 분리는 두 제품의 전체 동작 호환성을 검증한 결과가 아닙니다. Windows 실제 설치·동시 구동 검증은 진행 중이며 macOS 실제 실행은 미검증입니다.

## 진단과 모델링 확인

doctor는 설치 버전, Codex 등록, Python 서버 import, Yak 패키지 버전, `127.0.0.1:1999`의 실제 Rhino 플러그인 버전, 관리 등록 파일과 플러그인의 마지막 관리 상태를 확인합니다. 비밀 토큰은 출력하지 않습니다. `management_registered`는 로컬 등록이 존재한다는 뜻이며 현재 서버의 사용 승인을 보증하지 않습니다. `not_checked`는 아직 작업 승인을 확인하지 않았다는 뜻이고, 진단 시점 이후에도 관리자가 정책을 바꿀 수 있으므로 실제 작업마다 다시 확인합니다. 문서의 형상은 변경하지 않습니다. Rhino가 닫혀 있으면 연결 검증은 실패하는 것이 정상입니다. 자동 시작을 끈 환경에서는 Rhino 명령줄의 `StudioMCPStart`로 시작하고 `StudioMCPStop`으로 종료합니다.

| Rhino 명령 | 용도 |
| --- | --- |
| `StudioMCPStart` | Studio 로컬 서버 시작 |
| `StudioMCPStop` | Studio 로컬 서버 종료 |
| `StudioMCPVersion` | 로드된 Studio 플러그인 버전 확인 |
| `StudioMCPTest` | 개발용 기능 테스트. 테스트 객체를 만들 수 있으므로 새 빈 문서에서만 실행 |

`StudioMCPStart`나 `StudioMCPVersion`을 Rhino가 찾지 못하면 Studio 플러그인이 로드되었는지 `PlugInManager`에서 확인하세요. 대체 명령으로 일반 `mcpstart`를 실행해 연결을 우회하지 마세요.

정상 연결 뒤에는 **새 빈 문서**에서 작은 예제로 확인합니다. 예: “문서 단위와 공차를 확인하고, 3000 × 4000 mm 직사각형을 높이 2800 mm로 돌출한 매스를 새 레이어에 만들고, 실제 치수와 솔리드 유효성을 확인해 줘.” 이후 Undo로 생성물을 되돌릴 수 있는지 확인합니다. 설치 성공만으로 모든 건축·Grasshopper 모델링이 검증된 것은 아닙니다.

Studio는 loopback으로만 연결합니다. 포트를 외부 네트워크에 공개하지 마세요. Python/C# 실행 도구는 Rhino에서 코드를 실행하므로 신뢰할 수 있는 작업 지시와 파일에 사용하세요.

## 업데이트와 제거

업데이트는 새 릴리스 ZIP을 내려받아 기존과 같은 InstallRoot로 설치합니다. Rhino를 먼저 종료해야 합니다. 서버와 플러그인이 같은 버전으로 함께 업데이트되며, 다른 버전의 플러그인에는 형상을 수정하는 요청을 거부합니다. 같은 ZIP 재설치는 중복 MCP 항목을 만들지 않습니다. 설치된 동일 버전의 내용을 바꿔 덮어쓰지 않고 새 버전으로 배포합니다.

같은 관리 서버와 공개 키를 사용하는 업데이트·재설치는 기존 설치 ID와 토큰을 재사용합니다. 서버가 사용을 중지했거나 등록 파일이 없어졌다고 새 ID를 자동 발급받지 않습니다. 등록 파일을 수정하거나 분실했다면 원래 파일을 복구해야 합니다. 배포자의 관리 서버 주소 또는 공개 키가 변경된 경우에는 새 운영자 정보를 확인한 뒤 Windows의 `-ChangeManagementService` 또는 macOS의 `--change-management-service`를 명시해야 새 서버에 등록합니다.

설정 변경 전 원본 Codex 설정은 설치 폴더의 `backups`에 보관됩니다. 비밀 토큰은 이 백업이나 `state.json`에 복제하지 않습니다. 설치 실패 시 기존 Codex 설정, 관리 등록, 설치 상태와 이전 플러그인의 복구를 시도하고, 복구 실패는 명확한 오류로 표시합니다. 이전 서버 릴리스도 설치 폴더에 남습니다. 수동으로 수정한 `rhino-studio` 설정이나 다른 설치가 소유한 관리 등록이 발견되면 이를 덮어쓰거나 삭제하지 않고 중지합니다.

제거 전 Rhino를 종료하고, 설치에 사용한 ZIP 폴더의 제거 스크립트를 실행합니다. 경로를 지정해 설치했다면 같은 경로를 넘기세요.

```powershell
.\uninstall.ps1
```

```bash
bash ./uninstall.sh
```

Studio의 Yak 패키지와 Codex MCP 항목, 이 설치가 소유한 관리 등록, 전용 Python·uv·캐시·백업 파일을 제거합니다. 전역 Python/uv, 다른 MCP 설정, Rhino 모델 파일은 삭제하지 않습니다. 최초 설치에 사용했던 원본 RhinoMCP 패키지를 자동으로 다시 설치하지는 않습니다. 서버의 설치 기록은 로컬 제거와 별개로 남습니다.

## 개발자가 배포 ZIP 만들기

Python 3.11 이상, uv 0.11.28, .NET 8 SDK, Yak CLI와 운영자의 공개 관리 프로필이 필요합니다. 프로필이 없으면 빌드를 중지합니다. 운영 서버 배포와 로컬 시험 프로필 준비는 [관리 서버를 연결해 배포하기](DISTRIBUTION_MANAGEMENT_KO.md)를 참고하세요. 저장소 루트에서 다음을 실행합니다.

```powershell
python -m unittest discover -s distribution/tests -v
python distribution/build.py --yak 'C:\Program Files\Rhino 8\System\yak.exe' --management-profile 'C:\release-config\management-public.json'
```

이미 만든 `.whl`과 `.yak`로 묶을 수도 있습니다.

```bash
python distribution/build.py --wheel /path/to/rhinomcp-0.6.1-py3-none-any.whl --plugin /path/to/rhinomcp-studio-0.6.1-rh8-any.yak --management-profile /path/to/management-public.json
```

출력은 `dist/rhinomcp-studio-<version>.zip`과 `.zip.sha256`입니다. GitHub Actions의 **Studio distribution → Run workflow**로 같은 배포물을 만들 수 있습니다. 워크플로는 GitHub Release나 PyPI/Yak에 자동 공개하지 않습니다. ZIP과 SHA-256을 함께 Release에 첨부하고, 실제 Windows와 macOS Rhino에서 검증한 결과를 릴리스 설명에 남기세요. 테스트에서 모의 명령을 통과한 것과 실제 Rhino에서 로드·모델링을 통과한 것은 구분해서 기록해야 합니다.

