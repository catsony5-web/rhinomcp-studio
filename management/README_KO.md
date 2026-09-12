# RhinoMCP Studio 관리 서버

이미 설치된 **관리형 배포본**의 다음 MCP 요청을 전체·정확한 버전·설치 등록별로 중지하거나 재개합니다. 한국어 관리자 화면은 `/admin`입니다. 관리자 비밀번호를 입력하는 사람은 운영자뿐이며 사용자 설치 등록에는 로그인이 필요 없습니다.

서버 소스와 배포 구성을 준비한 상태입니다. [Render 배포 안내](RENDER_KO.md)는 별도 도메인 구매 없이 HTTPS 운영 주소를 만드는 절차이며, 서버 비용이 발생합니다. 실제 운영 서버를 배포하기 전에는 다른 사람의 PC를 인터넷으로 관리할 수 없습니다. `0.5.1` 등 관리 기능이 없는 과거 설치본에는 이 정책이 적용되지 않으며 관리형 버전으로 업데이트해야 합니다.

## 동작과 한계

- 관리형 플러그인은 새 Rhino 명령마다 서버에 온라인 승인을 요청합니다. 서버 응답이 없거나 검증에 실패하면 요청을 실행하지 않는 구성을 사용합니다. 인터넷 연결·서버 운영·인증서·정상 시각이 필요합니다.
- 서버는 매 요청에서 현재 정책을 읽습니다. 전체 중지, 설치 중지, 정확한 버전 중지, 최소 지원 버전 순서로 판단합니다. 응답의 명령·설치 ID·버전·일회성 난수·만료 시각을 RSA-PSS 서명으로 묶습니다.
- 정책 저장 이후 시작하는 승인 요청에 적용됩니다. 이미 승인되어 실행 중인 Rhino 작업을 종료하거나 모델을 변경하지 않습니다. 서버 정책 응답은 30초 이내에만 유효하며, 플러그인은 응답을 다른 요청에 재사용하지 않아야 합니다.
- 핫스팟·VPN 변경은 전체·버전 정책을 해제하지 않습니다. 관리 서버만 차단해도 정상 배포본은 새 승인을 얻지 못합니다.
- 사용자 로그인 없이 공개 등록하므로 **개별 설치 중지는 사람·PC의 영구 차단이 아닙니다**. 재설치로 새 등록을 만들 수 있습니다. 전체·버전 정책은 새 등록에도 적용됩니다.
- 로컬 코드 변조나 독립적인 포크까지 완전히 통제하는 DRM은 아닙니다. 클라이언트에 있는 검사를 제거할 수 있다는 한계는 유지됩니다.

## 로컬에서 실행

### 초기화한 Windows 로컬 서버 다시 시작

공개 저장소와 배포 파일에는 운영자의 초기화한 상태·서명 개인키·관리자 비밀번호·Python 가상 환경이 포함되지 않습니다. 먼저 아래의 새 로컬 환경 초기화 절차를 수행합니다. 다시 시작할 때 아래 도우미에 **본인이 초기화한 상태 폴더와 Python 환경 경로**를 지정합니다. 도우미는 비밀번호를 읽거나 표시하지 않습니다.

저장소 루트에서 다음 명령으로 창 없이 관리 서버를 실행할 수 있습니다.

```powershell
& .\management\Start-LocalManagement.ps1 -StateDirectory "$PWD\management\.state" -PythonPath "$PWD\management\.venv\Scripts\python.exe"
```

다른 초기화된 상태 폴더·Python 환경을 사용하려면 다음처럼 지정합니다.

```powershell
& .\management\Start-LocalManagement.ps1 -StateDirectory 'C:\OwnerData\RhinoMCP\state' -PythonPath 'C:\OwnerData\Python\python.exe'
```

도우미는 상태 DB·서명키가 이미 있는지 확인하고, 정상 서버가 실행 중이면 관리자 URL만 안내합니다. 다른 프로그램이 포트를 사용하면 중단하며 어떤 프로세스도 종료하지 않습니다. 새로 실행할 때 출력·오류 로그는 상태 폴더의 상위 폴더에 별도 파일로 저장합니다. 초기화·정책 변경·사용자 PC 설치·Windows 자동 시작 등록은 수행하지 않습니다. 포트를 변경할 경우 `-Port`를 지정하고 클라이언트 프로필 주소도 함께 맞춰야 합니다.

**`http://127.0.0.1:8765/admin`은 현재 PC에서만 열리는 루프백 데모입니다.** 이 PC가 재시작되면 도우미를 다시 실행해야 합니다. 다른 사람의 PC에서 사용하는 배포본을 관리하려면 아래 HTTPS 서버 배포 절차로 공개 운영 주소를 마련해야 합니다.

### 새 로컬 환경 초기화

Python 3.12 이상을 사용합니다. 아래 명령은 `management` 디렉터리에서 실행합니다. 서버 실행 터미널은 검증하는 동안 유지합니다.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe control_service.py --state .state init
.\.venv\Scripts\python.exe control_service.py --state .state serve --host 127.0.0.1 --port 8765 --allow-insecure-loopback
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python control_service.py --state .state init
.venv/bin/python control_service.py --state .state serve --host 127.0.0.1 --port 8765 --allow-insecure-loopback
```

초기화 과정에서 관리자 비밀번호를 두 번 입력합니다. 비밀번호는 14~1024자이며 명령줄 인수나 출력에 노출되지 않습니다. 자동화에는 `init --password-file OWNER_ONLY_FILE`을 사용할 수 있으며 해당 임시 파일은 운영자가 별도로 보호·처리해야 합니다. `.state`는 비어 있을 때만 초기화할 수 있습니다. 기존 키·설정은 덮어쓰지 않습니다.

`http://127.0.0.1:8765/admin`에서 로그인합니다. 개발 모드는 정확한 루프백 주소에서만 동작합니다. 동일 서버라도 `localhost`와 `127.0.0.1`을 섞어 사용하지 않고 안내한 주소로 접속합니다.

별도 터미널에서 공개 클라이언트 프로필을 생성합니다.

```powershell
.\.venv\Scripts\python.exe control_service.py --state .state export-profile --url http://127.0.0.1:8765 --allow-insecure-loopback --output public-profile.json
```

이 JSON에는 공개 URL·RSA 공개키·개발 모드 여부만 있습니다. 클라이언트 배포 빌드에 전달할 수 있습니다. `.state/signing-key.pem`, `.state/control.sqlite3`, 관리자 비밀번호·세션·백업은 클라이언트 ZIP이나 공개 Git 저장소에 넣지 않습니다. 개발 프로필은 해당 PC의 루프백 검증용이며 다른 사람에게 배포하는 운영 프로필로 사용하지 않습니다.

## HTTPS 서버 배포

Render를 사용하려면 [Render 배포 안내](RENDER_KO.md)를 따릅니다. 아래 구성은 **Docker Compose가 실행되는 Linux 서버 1대와 영속 저장소 1개**를 전제로 합니다. SQLite DB를 여러 컨테이너나 서버가 공유하는 형태로 확장하지 않습니다.

1. 운영 도메인의 A/AAAA 레코드를 서버에 연결합니다. 공개 인바운드는 80·443만 열고 관리 API의 8765 포트는 공개하지 않습니다.
2. `.env.example`을 `.env`로 복사하고 실제 `MCP_DOMAIN`, `ACME_EMAIL`을 입력합니다. 도메인은 `https://`나 경로를 제외한 이름입니다.
3. 아래 명령으로 초기화하고 실행합니다.

```sh
docker compose build control
docker compose run --rm control init
docker compose up -d
```

브라우저에서 `https://실제도메인/admin`, 연결 상태 확인은 `https://실제도메인/healthz`를 사용합니다. Caddy가 HTTPS를 제공하고 내부 Docker 네트워크에서만 관리 서버에 연결합니다. 서버의 `--public-url`이 Host·Origin 검증 기준이므로 도메인 변경 시 설정과 배포 프로필을 함께 갱신해야 합니다.

제공된 Compose는 공개 클라이언트 IP에 따른 로그인·등록 속도 제한을 위해 `--trust-proxy-headers`를 지정합니다. 이는 **8765가 외부에 노출되지 않고 Caddy만 요청을 전달하는 배포에서만** 사용합니다. 로컬 개발에서는 이 옵션을 사용할 수 없습니다. Caddy 앞에 다른 프록시를 추가하면 해당 프록시의 신뢰 범위를 별도로 검토해야 합니다.

공개 운영 프로필 생성 예시:

```sh
docker compose exec control python control_service.py --state /state export-profile --url https://실제도메인 --output /tmp/public-profile.json
docker compose cp control:/tmp/public-profile.json ./public-profile.json
```

같은 출력 경로는 덮어쓰지 않습니다. 이미 파일이 있다면 새 파일명을 사용합니다. `public-profile.json`으로 새 관리형 클라이언트 ZIP을 빌드한 후 사용자에게 전달합니다. 서버의 개인 서명키는 컨테이너의 `control-state` 볼륨에만 보관합니다.

관리 UI에는 전체 일시 중지·재개, 정확한 버전별 중지·재개, 최소 지원 버전, 최근 접속 설치 100개와 설치별 중지, 최근 관리 기록 100개가 표시됩니다. 중지 사유를 입력해야 정책을 저장할 수 있습니다.

## 운영 데이터와 복구

| 항목 | 보관 내용 |
|---|---|
| 설치 등록 | 무작위 설치 ID, 설치 토큰의 SHA-256 해시, 버전, OS, 최초·최근 승인 시각, 중지 상태 |
| 관리자 | scrypt 비밀번호 해시·솔트, 만료되는 세션 토큰 해시, CSRF 값 |
| 운영 정책·기록 | 전체·버전·설치 정책, 관리자 로그인·로그아웃·정책 변경 시각·사유 |
| 속도 제한 | 요청 IP의 SHA-256 값과 시각. 최대 1시간 범위의 기록을 다음 제한 요청에서 정리 |

모델 파일·형상·객체 이름·실행 코드·명령 인수·명령 이름·일회성 난수·원문 설치 토큰은 DB에 저장하지 않습니다. 원문 설치 토큰은 등록 응답으로 한 번 전달됩니다. 요청별 접근 로그는 기본 비활성화되어 있습니다. 서버·프록시에 별도 로깅을 추가할 때 Authorization 헤더·응답 토큰을 기록하지 않습니다.

관리자 세션은 8시간 후 만료되고 로그아웃하면 즉시 폐기됩니다. 쿠키는 HttpOnly·SameSite=Strict이며 운영에서는 Secure입니다. 모든 관리자 변경·로그아웃에 CSRF 확인을 적용하고 Host·Origin을 검증합니다. 로그인은 IP별 15분에 5회·전체 30회, 등록은 IP별 시간당 30회·전체 3,000회로 제한됩니다.

비밀번호를 잊으면 서버 소유자가 로컬에서 아래 명령을 실행합니다. 기존 관리자 세션은 모두 폐기됩니다.

```sh
docker compose run --rm control reset-password
```

백업 시에는 관리 서버를 정상 중지한 뒤 `control-state` 볼륨 전체를 운영자 전용 위치로 백업하고 재시작합니다. DB와 서명키를 함께 복구해야 기존 설치 등록이 유지됩니다. 서버 중단 기간에는 클라이언트가 새 승인을 받지 못합니다. 키를 잃거나 새로 초기화하면 기존 배포본의 고정 공개키와 맞지 않으므로 새 프로필로 업데이트가 필요합니다.

파일 모드는 Unix에서 상태 폴더 0700, 개인키·DB 0600으로 생성합니다. Windows에서 `chmod`는 사용자별 ACL을 보장하지 않으므로 운영자 개인 폴더의 Windows 접근 권한으로 상태 폴더·비밀번호 파일·백업을 보호합니다. Docker 운영은 UID 10001의 비루트 사용자로 실행됩니다.

## 프로토콜 1

공개 배포 프로필:

```text
GET /v1/profile
200 {"service_url":"https://운영주소", "public_key_pem":"PEM public key", "allow_insecure_loopback":false}
```

프로필은 로그인 없이 읽을 수 있고 기존 Host·Origin 검증을 적용합니다. 관리자 비밀번호·서명 개인키·설치 토큰은 반환하지 않습니다. 운영자가 HTTPS와 공개키를 확인해 릴리스 빌드에 고정하는 용도이며, 설치된 클라이언트가 요청마다 공개키를 새로 신뢰하는 용도가 아닙니다.

등록:

```text
POST /v1/enroll
Content-Type: application/json
{"client_version":"0.6.0","platform":"windows"}

201 {"installation_id":"UUID","installation_token":"64 hex characters"}
```

승인:

```text
POST /v1/authorize
Authorization: Bearer INSTALLATION_TOKEN
Content-Type: application/json
{"installation_id":"UUID","version":"0.6.0","command":"create_object","nonce":"64 hex characters"}

200 {"payload":"base64 UTF-8 compact JSON","signature":"base64 RSA-PSS signature"}
```

서명 대상 JSON은 `protocol`, `installation_id`, `version`, `command`, `nonce`, `allowed`, `code`, `reason`, `issued_at`, `expires_at`의 정확한 11개 필드입니다. 서명은 RSA 3072비트 이상·PSS·SHA-256·MGF1 SHA-256·솔트 32바이트를 사용하며, JSON을 다시 직렬화한 데이터가 아닌 **반환된 payload의 원본 디코딩 바이트**로 검증합니다. `expires_at`은 `issued_at + 30`입니다.

정책 거부도 정상 서명된 200 응답으로 전달합니다. `code`는 `allowed`, `maintenance`, `version_paused`, `installation_paused`, `update_required` 중 하나입니다. 잘못된 설치 인증은 401, 형식 오류는 400, 과도한 요청은 429입니다. 버전은 선행 0 없는 숫자 3부분 `x.y.z`이며 prerelease 표기는 이번 배포에서 지원하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

실제 로컬 HTTP 서버로 등록·전체/버전/설치 중지·재개·최소 버전·서명과 요청 결합·관리자/설치 인증 분리·CSRF·로그인 제한·HTML 이스케이프·민감값 미보관·프로필·운영 쿠키 설정을 확인합니다. 인터넷 공개 배포·실제 도메인의 인증서 발급은 운영 환경을 마련한 뒤 별도로 확인해야 합니다.

설계에 참고한 공식 문서: [cryptography RSA 서명](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/), [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
