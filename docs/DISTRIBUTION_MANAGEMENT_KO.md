# 관리 서버를 연결해 배포하기

0.6.1 배포 ZIP을 만들려면 실제 관리 서버 URL과 그 서버의 RSA 공개 키를 정해야 합니다. 운영 도메인과 서버가 아직 없으면 로컬 시험 ZIP까지만 만들 수 있습니다. 로컬 시험 서버를 실행하고 검사한 결과는 외부 사용자에게 제공할 서버의 배포 완료를 의미하지 않습니다.

## 공개 프로필과 비밀 정보

`distribution/build.py --management-profile PATH`에 전달하는 JSON은 아래 세 필드만 포함해야 합니다.

| 필드 | 의미 |
| --- | --- |
| `service_url` | 경로·쿼리·사용자 정보가 없는 HTTPS 서버 주소 |
| `public_key_pem` | 서버가 생성한 RSA SPKI 공개 키 PEM. 3072~8192비트 |
| `allow_insecure_loopback` | 운영 배포는 `false`. 로컬 시험 HTTP만 `true` |

로컬 시험 HTTP 주소는 명시한 `localhost`, `127.0.0.1`, `::1`만 허용합니다. 배포 프로그램은 공개 프로필을 검증한 후 `management-server.json`으로 복사하고 그 SHA-256을 `bundle.json`에 기록합니다. 별도 필드에 비밀 정보를 넣으면 빌드를 거부합니다. **서명 개인 키, 관리자 비밀번호, 세션 쿠키, 설치 토큰을 공개 프로필이나 배포 ZIP에 넣지 마세요.** 공개 프로필은 사용자와 공유할 수 있습니다.

## 같은 PC에서 시험하기

저장소의 관리 서버 Python 의존성을 먼저 준비합니다. 관리 서버의 상세 운영 절차는 `management` 디렉터리의 문서를 따릅니다. 아래 경로는 사용자가 정하는 로컬 경로이며 운영 도메인을 대신하지 않습니다.

```powershell
python management/control_service.py --state 'C:\RhinoMCP-Operator\private' init
python management/control_service.py --state 'C:\RhinoMCP-Operator\private' export-profile --url 'http://127.0.0.1:8765' --allow-insecure-loopback --output 'C:\RhinoMCP-Operator\management-public.json'
python management/control_service.py --state 'C:\RhinoMCP-Operator\private' serve --host 127.0.0.1 --port 8765 --allow-insecure-loopback
```

서버를 실행한 상태에서 다른 터미널에서 빌드합니다.

```powershell
python distribution/build.py --management-profile 'C:\RhinoMCP-Operator\management-public.json' --yak 'C:\Program Files\Rhino 8\System\yak.exe'
```

이 ZIP의 `local_demo_only`는 `true`입니다. 다른 PC에서 설치하면 **그 PC 자신의** `127.0.0.1:8765`를 찾으므로 운영 배포용으로 사용할 수 없습니다. 같은 PC에서 실제 설치할 때도 Rhino 문서를 먼저 저장하고 종료해야 합니다.

## 운영 서버를 연결하기

운영자가 HTTPS 도메인과 서버를 준비하고 관리 서버의 `serve --public-url`에 실제 HTTPS 주소를 설정합니다. 같은 주소로 `export-profile --url ACTUAL_HTTPS_ORIGIN --output PUBLIC_JSON`을 실행하되 `--allow-insecure-loopback`은 사용하지 않습니다. 생성한 공개 프로필을 `--management-profile`로 빌드에 전달합니다. 공개 키와 서버 상태 디렉터리는 서로 일치해야 합니다.

설치 프로그램은 서버의 `POST /v1/enroll`에 클라이언트 버전과 운영체제만 전송합니다. 리다이렉트를 따르지 않고 표준 TLS 인증서 검증, 5초 네트워크 타임아웃과 응답 크기 제한을 적용합니다. 서버가 응답하지 않거나 잘못된 등록을 반환하면 Rhino 플러그인과 Codex 설정을 변경하기 전에 설치를 중지합니다. 설치 프로그램의 Python·uv 준비 파일은 이미 생성되어 있을 수 있습니다.

등록을 완료한 플러그인은 각 작업의 실행 직전에 서버에서 서명된 승인을 받고 검증합니다. 모델 파일과 실행 스크립트를 설치 등록에 보내지 않습니다. 작업 승인에서 전송하는 정확한 필드는 관리 서버 프로토콜 문서를 참고하세요. 관리자가 전체·버전·설치 단위로 중지하면 다음 작업 승인을 거부합니다. 이미 실행 중인 작업은 중지 대상에 포함되지 않습니다.

## 재설치, 진단과 통제 범위

재설치와 업데이트는 같은 서버·공개 키의 기존 등록을 재사용합니다. 서비스 변경은 명시적 설치 옵션이 필요합니다. 관리 등록을 다른 InstallRoot가 덮어쓰지 못하도록 설치 상태에 파일 경로와 해시를 기록하며, 상태 파일에 비밀 토큰을 복사하지 않습니다.

doctor는 비밀 토큰을 출력하지 않고 등록 상태와 플러그인의 마지막 승인 상태를 보고합니다. 이 결과는 이후 명령이 승인된다는 보장이 아닙니다. 인터넷, VPN, 핫스팟의 종류와 관계없이 작업 승인 서버에 접속하지 못하면 새 작업을 거부합니다.

사용자 PC의 코드와 등록 파일은 사용자가 변경할 수 있습니다. 공개 등록이 가능한 구조에서는 의도적으로 완전히 새 설치 등록을 만드는 사용자를 영구적으로 식별하는 기능까지 제공하지 않습니다. 전체·버전 정책은 새 등록에도 적용됩니다. 장치별 영구 차단이나 변조 방지를 보장하려면 별도의 계정·등록 승인 정책 또는 서버에서 수행하는 필수 기능이 필요하며, 이번 설치 기능에는 포함되지 않습니다.

## 배포 전 확인

```powershell
python -m unittest discover -s distribution/tests -v
```

자동 검사는 공개 프로필과 키 검증, ZIP의 공개 정보 포함과 체크섬, 네트워크 등록 실패 시 기존 설정 보존, 동일 설치 ID 재사용, 관리 서버 변경 승인 옵션, 관리 등록·Codex 설정·설치 상태 복구를 확인합니다. 모의 Rhino/Yak 검사와 실제 Windows/macOS Rhino 설치·모델링 검증 결과는 구분해 기록하세요.

