# Render에 운영 관리 서버 배포

이 안내는 `catsony5-web/rhinomcp-studio`의 관리 서버를 Render 한 대에서 운영하는 절차입니다. 저장소에 설정을 올리는 것만으로 서버가 만들어지거나 비용이 청구되지는 않습니다. **Render 계정에서 아래 유료 리소스를 검토하고 배포를 실행해야 합니다.** 클라이언트 배포 ZIP은 운영 서버 확인 후 별도로 빌드합니다.

## 준비된 구성과 예상 비용

| 항목 | 설정 |
|---|---|
| GitHub | `https://github.com/catsony5-web/rhinomcp-studio` |
| 서비스 | `rhinomcp-studio-control`, Python 3.12.10, Singapore |
| 컴퓨팅 | `0.5c-512mb`: 0.5 CPU / 512 MB, 월 US$7 |
| 영속 디스크 | `/var/data`에 1 GB, 월 US$0.25 |
| 기본 합계 | **월 약 US$7.25**. 세금·환율·트래픽 초과 사용량 등은 별도 |
| 공개 주소 | Render가 배정하는 `https://…onrender.com` |
| 시작 명령 | `python render_start.py` |
| 자동 배포·미리보기 | 끔. 운영자가 업데이트 시점을 선택 |
| 인스턴스 | 1개. SQLite와 서명키를 같은 영속 디스크에 보관 |

가격·플랜 이름은 2026-09-12에 [Render 요금표](https://render.com/pricing)와 [Blueprint 공식 명세](https://render.com/docs/blueprint-spec)에서 확인했습니다. 계정 생성과 별개로 유료 컴퓨팅·디스크가 청구됩니다. 무료 웹 서비스의 절전 시작과 임시 파일 시스템은 매 명령 승인 및 키 보존 요건에 맞지 않아 이 구성에 사용하지 않습니다. [Render 무료 서비스 제한](https://render.com/docs/free)

## 1. 운영자가 처음 배포하기

1. Render에 로그인하고 GitHub의 `catsony5-web/rhinomcp-studio` 접근을 연결합니다.
2. [이 저장소로 Blueprint 만들기](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fcatsony5-web%2Frhinomcp-studio)를 열거나 대시보드의 **New → Blueprint**에서 저장소를 선택합니다. 루트의 `render.yaml`을 사용합니다.
3. 리소스 목록에서 웹 서비스 1개와 1 GB 디스크, 선택한 가격을 확인합니다. 별도 Postgres·Redis·프리뷰 서비스는 필요하지 않습니다.
4. `RHINOMCP_BOOTSTRAP_PASSWORD`에 운영자용 비밀번호를 넣습니다. 14~1024자를 허용하며, 비밀번호 관리 도구로 생성한 긴 무작위 값을 권장합니다. 이 값은 Render의 비밀 환경 변수에만 입력하고 GitHub·대화·설치 ZIP에는 넣지 않습니다.
5. 배포를 실행합니다. 상태 폴더가 완전히 비어 있을 때만 서명키와 관리자 비밀번호 해시를 생성합니다. 앱이 실행된 뒤 Render 화면에 나타나는 **실제 HTTPS 주소**를 기록합니다. 저장소나 서비스 이름만으로 주소를 추측하지 않습니다.
6. 해당 주소의 `/healthz`가 `{"status":"ok","protocol":1}`을 반환하고 `/admin`에서 비밀번호로 로그인되는지 확인합니다.
7. 비밀번호 관리 도구에 비밀번호를 보관한 뒤 Render 서비스의 Environment에서 `RHINOMCP_BOOTSTRAP_PASSWORD`를 제거하고 수동 재배포합니다. 관리자 로그인과 `/v1/profile`의 공개키가 그대로인지 확인합니다.

초기 비밀번호는 재시작할 때 덮어쓰지 않습니다. 환경 변수에 다른 비밀번호를 넣어도 기존 관리자 비밀번호·키·등록·중지 정책을 바꾸지 않습니다. 앱은 읽은 초기 비밀번호를 자신의 프로세스 환경에서도 제거합니다. Render 대시보드에 저장된 값은 운영자가 7번 단계에서 직접 제거해야 합니다.

디스크에 키나 DB 한쪽만 있거나 DB가 불완전하면 서버는 시작을 거부합니다. 재초기화하거나 새로운 키로 자동 교체하지 않습니다. 초기 비밀번호 제거 후 영속 디스크가 사라졌다면 빈 상태를 재생성하지 않고 시작을 거부합니다.

## 2. 운영 주소를 클라이언트 ZIP에 고정하기

1. **자신의 Render 대시보드에서 확인한 HTTPS 주소**의 `/v1/profile`을 열어 공개 프로필을 내려받습니다. 필드는 `service_url`, `public_key_pem`, `allow_insecure_loopback` 세 개이고 마지막 값은 `false`여야 합니다.
2. `/admin`에서 전체 중지 상태가 해제돼 있는지 확인합니다.
3. 저장소의 [릴리스 안내](../docs/RELEASE_KO.md)에 따라 공개 프로필을 `RHINO_MCP_MANAGEMENT_PROFILE` 저장소 변수에 저장하고 빌드·온라인 승인 검증·릴리스를 수행합니다. 프로필에는 공개키만 있으므로 GitHub 변수로 전달할 수 있습니다. **서명 개인키나 DB는 올리지 않습니다.**
4. 다른 PC의 Codex에 전달할 링크는 검증한 클라이언트 ZIP이 있는 GitHub Release 또는 해당 ZIP입니다. `/admin` 주소나 관리자 비밀번호를 사용자에게 설치 정보로 전달하지 않습니다.

공개 프로필 엔드포인트는 릴리스 제작자가 공개키를 고정하는 데 사용합니다. 배포 이후 클라이언트는 설치된 공개키로 승인 서명을 검증하며, 서버에서 공개키를 자동 교체해 받지 않습니다. 키를 변경하면 기존 배포본이 거부하므로 키 변경을 일반적인 비밀번호 변경처럼 처리하면 안 됩니다.

## 3. HTTPS 주소·상태 경로·프록시

`render_start.py`는 `RENDER_EXTERNAL_URL`을 운영 URL로 사용하고 `PORT`(기본 10000)에 `0.0.0.0`으로 바인딩합니다. 운영 URL은 HTTPS origin만 허용하며 경로·쿼리·사용자 정보·공백은 거부합니다. 상태는 `RHINOMCP_STATE_DIR`의 절대 경로, 기본 `/var/data/rhinomcp`에만 저장합니다. Render의 자동 환경 변수는 [공식 환경 변수 문서](https://render.com/docs/environment-variables)를 따릅니다.

TLS 인증서와 HTTP→HTTPS 처리는 Render의 앞단에서 수행하고 앱에는 내부 HTTP를 전달합니다. 관리자 쿠키는 앱의 운영 모드에서 항상 Secure이며 Host·Origin 검증은 설정된 HTTPS 주소 기준입니다. [Render 웹 서비스의 TLS 처리](https://render.com/tutorials/web-service-vs-static-site/web-services)

기본 `onrender.com` 주소를 유지하는 구성이 가장 간단합니다. 자신이 확보한 도메인을 붙일 때만 `RHINOMCP_PUBLIC_URL=https://실제도메인`을 지정합니다. 이 값이 자동 URL보다 우선합니다. Render는 등록한 사용자 도메인이 있으면 그중 하나를 health check의 Host로 사용하므로, 이 구성에는 **관리 서버의 정규 주소와 같은 사용자 도메인 하나만** 연결합니다. 도메인 변경은 클라이언트 프로필과 배포본 업데이트도 필요합니다. 검사를 통과시키려고 모든 Host를 허용하지 않습니다. [Render health check의 Host 규칙](https://render.com/docs/health-checks)

시작 코드는 Render가 Python 환경에 기본 제공하는 `FORWARDED_ALLOW_IPS=*`를 사용하지 않고 Uvicorn의 `proxy_headers=False`를 명시합니다. 일부 프록시 경로에서 사용자가 보낸 `X-Forwarded-For` 값이 보존될 수 있기 때문입니다. 따라서 이 기본 배포의 로그인·등록 IP별 속도 제한은 **앱과 접속한 Render 프록시 주소를 함께 사용하는 요청들에 합산**될 수 있습니다. 한 프록시 기준 등록 30회/시간을 넘는 대량 배포는 다음 시간대에 나누어 진행합니다. 전체 제한과 관리 인증 검사는 그대로 적용됩니다. 클라이언트 승인 API에는 이 등록 횟수 제한이 적용되지 않습니다. [Render의 프록시 헤더 주의사항](https://render.com/articles/host-pocketbase-on-render)

## 4. 업데이트·비밀번호 재설정·복구

코드 업데이트는 GitHub에 반영한 뒤 Render에서 수동 배포합니다. **같은 서비스와 같은 디스크**를 유지합니다. 시작 과정은 기존 서명키·DB·관리자 비밀번호·설치 등록·정책을 그대로 사용합니다. `/var/data` 밖의 파일은 재배포 후 사라질 수 있고, 디스크를 연결한 서비스는 여러 인스턴스로 확장할 수 없습니다. 배포 시 잠깐 중단될 수 있으며 해당 시간에 새 Rhino MCP 요청은 승인을 받지 못합니다. [Render 영속 디스크 수명과 제약](https://render.com/docs/disks)

비밀번호를 잊은 운영자는 Render 서비스의 Shell에서 다음 명령을 실행합니다. 비밀번호를 명령줄 인수로 넣지 않고 두 번 입력합니다.

```sh
python control_service.py --state /var/data/rhinomcp reset-password
```

관리자 세션은 모두 무효화되며 설치 등록·정책·서명키는 바뀌지 않습니다. 초기 비밀번호 환경 변수를 다시 넣어 재설정하지 않습니다.

Render 디스크 스냅샷은 플랫폼의 보존 정책을 확인하고 사용합니다. 별도로 보관할 경우 운영 서버를 정상 중지한 시점의 **DB와 서명 개인키를 함께** 운영자 전용 암호화 저장소에 백업합니다. 서비스 삭제나 디스크 삭제 전에는 복구할 수 있는 백업이 있어야 합니다. 공개 프로필만으로 개인키나 설치 등록을 복구할 수는 없습니다. 복원 후에는 기존 프로필과 공개키가 같은지, 관리자 로그인·시험 설치의 승인이 되는지 확인합니다.

## 검증 범위

로컬 테스트는 새 디스크 초기화, 재시작의 키·비밀번호·정책·등록 유지, 누락/불완전 상태 거부, 잘못된 URL·포트·경로 거부, 프로세스 환경에서 초기 비밀번호 제거, 공개 프로필의 민감값 제외 및 Host/HTTP method 제한을 검사합니다. 기존 관리 API의 등록·서명·중지·재개·CSRF 테스트도 함께 실행합니다. 관리 테스트 24개와 Ruff 검사를 통과했고, `render.yaml`은 [Render 공식 JSON Schema](https://render.com/schema/render.yaml.json)로 검증했습니다.

```sh
python -m unittest discover -s management/tests -v
```

실제 Render 계정의 리소스 생성, 인증서·인터넷 연결, 재배포 후 영속 디스크 유지, 다른 PC 설치는 **운영 계정에서 배포한 뒤 확인해야 하는 단계**입니다. 소스에 배포 설정이 있다는 사실만으로 이 단계들이 완료된 것은 아닙니다.
