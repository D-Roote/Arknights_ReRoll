# ANReroll

MaaReroll에서 이식한 명일방주 한국 서버 리세마라 리소스입니다. 배포판은 범용 실행 앱 [MFWSide](https://github.com/D-Roote/MFWSide)와 별도 Python Agent를 함께 구성합니다.

## 배포판 자동 설치

[릴리즈](https://github.com/D-Roote/Arknights_ReRoll/releases)에서 `setup.ps1`을 내려받아 내용을 확인한 뒤 Windows x64 PowerShell에서 실행합니다. 관리자 권한은 필요하지 않습니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

기본 설치 위치는 `%LOCALAPPDATA%\Arknights_ReRoll`입니다. MFWSide 앱 ZIP과 이 프로젝트의 리소스 ZIP을 받아 현재 한국어 OCR 모델, 로컬 Python, `.venv`, Agent 최소 의존성을 구성합니다. 시스템 Python·PATH는 변경하지 않으며 PySide6·OpenCV·Pillow를 Agent 환경에 추가하지 않습니다.

설치 후 `Start-ANReroll.cmd`를 실행합니다. 설치 스크립트는 기본적으로 앱·앱플레이어·게임 작업을 시작하지 않습니다. 설치 위치 변경·버전 지정·업데이트·배포물 생성 방법은 [설치·배포 안내](DEPLOYMENT.md)를 참고하세요.

## 소스 실행 (개발용)

```powershell
cd C:\Users\RTE\Desktop\DEVELOP\ANReroll
.\.venv\Scripts\python.exe .\assets\main.py
```

가상환경을 다시 만들 때는 Python 3.10을 준비한 뒤 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

`requirements.txt`는 실행 앱의 직접 의존성 목록이고, `requirements-lock.txt`는 설치 패키지 버전을 고정한 목록입니다. 가상환경은 MAABA와 공유하지 않습니다. 외부 Agent만 실행할 때는 전체 앱 의존성 대신 `assets/agent/requirements.txt`를 사용합니다. [Agent 최소 설치 안내](assets/agent/README.md#외부-agent의-최소-설치)를 참고하세요.

## 사용 전 확인

1. 앱플레이어의 해상도를 1280×720, DPI를 180으로 설정하고 ADB 및 리소스에서 요구하는 root 권한을 확인합니다.
2. 설정 또는 모니터링의 연결 영역에서 MuMuPlayer ADB 프리셋과 실제 ADB 실행 파일·기기 주소를 선택합니다. 프리셋 이름만으로 ADB 주소나 실행 인스턴스를 자동 결정하지 않습니다.
3. 자동 실행을 사용하려면 설정의 수동 경로에 앱플레이어 바로가기의 전체 대상 문자열을 입력합니다. 앱플레이어 자동 실행 후에는 60초 대기하며, 게임 앱 실행은 파이프라인의 책임입니다.
4. 작업 목록에서 리세마라를 체크하고 현재 화면, 종료 조건, 뽑기 옵션을 확인한 뒤 시작합니다. 현재 앱은 원본의 `check` 대신 `default_check`를 읽으므로 이식한 작업은 기본 미선택입니다. 파이프라인 옵션은 원본 그대로 유지했습니다. 리소스는 기존 계정을 삭제하거나 게임 재화를 사용할 수 있으므로 작업을 시작하기 전에 내용을 확인하세요.

연결·캡처·실제 게임 작업은 사용자 환경에서 확인해야 합니다. 이식 검증은 게임을 실행하거나 입력하지 않습니다.

## 디렉터리와 수정 범위

- `assets/main.py`, `assets/app/`: MAABA의 실행 앱 원본. 여기서 UI/백엔드를 독자 수정하지 않습니다.
- `assets/resources/interface.json`: 작업·옵션·ADB 프리셋 선언. 리소스 경로는 이 파일의 위치 기준 `./`입니다.
- `assets/resources/pipeline/`, `image/`, `default_pipeline.json`: MaaReroll의 파이프라인과 이미지.
- `assets/resources/model/ocr/ko/`: 현재 사용 중인 한국어 OCR 모델. Git에는 포함하지 않지만, 배포 ZIP에는 `det.onnx`, `rec.onnx`, `keys.txt` 세 파일을 예외로 포함합니다. 다른 모델로 자동 대체하지 않습니다.
- `assets/user/`: ANReroll 전용 설정·로그·세션. MAABA의 사용자 데이터는 복사하지 않았습니다.

MAABA의 `.git`, `.cache`, `build`, 단위테스트, 사용자 설정, Blue Archive 파이프라인은 복사하지 않았습니다. MaaReroll의 예제 Agent 대신 현재 리소스에 필요한 ADB 유지보수·오퍼레이터 화면 저장·계정 백업/복원 Agent를 `assets/agent/`에서 제공합니다. 실행 앱 내부 등록과 외부 `AgentServer` 실행을 지원하며, 자세한 사용법은 [Agent 안내](assets/agent/README.md)를 참고하세요.

## 앱 업데이트 반영

UI/백엔드 수정은 MAABA에서 수행하고 검증한 뒤 다음 경로만 ANReroll에 반영합니다.

```powershell
Copy-Item -LiteralPath ..\MAABA\assets\main.py -Destination .\assets\main.py -Force
robocopy ..\MAABA\assets\app .\assets\app /E /XD __pycache__ /XF *.pyc
Copy-Item -LiteralPath ..\MAABA\requirements.txt -Destination .\requirements.txt -Force
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`robocopy`의 종료 코드 0~7은 성공/변경 상태입니다. 위 명령은 삭제된 앱 파일을 제거하지 않으므로 상위 앱에서 파일 삭제·이동이 있었다면 해당 파일만 별도 검토합니다. `assets/resources`와 `assets/user`를 MAABA 버전으로 덮어쓰지 마세요. 의존성 변경 후에는 lock 목록도 갱신합니다.

## 출처

- 초기 앱 이식: 로컬 MAABA `404f4878f216a328dae893a02c37ce5c6d8dfe15` 작업 트리. 현재 공통 앱은 MAABA `15fc8a4` 기준으로 동기화했습니다.
- 리소스: 로컬 `.cache/MaaReroll` 작업 트리(기준 `ad1d207`, v1.4.3). 이전 최적화·이미지 재구성 변경을 포함합니다.
- MaaFramework: `5.12.3`, PySide6: `6.11.1`.
- MaaReroll의 MIT 라이선스는 [LICENSE.MaaReroll](LICENSE.MaaReroll)에 보존했습니다.
- 파이프라인 작성법은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요. 원본 MAABA 문서이므로 Blue Archive 전용 TODO는 ANReroll 작업 범위에 해당하지 않습니다.
- 공식 [Project Interface V2](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/docs/en_us/3.3-ProjectInterfaceV2.md)와 [Pipeline Protocol](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/docs/en_us/3.1-PipelineProtocol.md)을 기준으로 버전별 필드를 확인합니다.

## 공통 앱 업데이트 / 2026-10-14

- MAABA `d95da91`: 게임별 EXE/설치 경로 하드코딩 제거, 공식 컨트롤러 창 조건과 Steam 설치 정보를 이용한 경로 인식 및 일반 EXE·인수 지원. ANReroll의 ADB 수동 실행 정책은 유지합니다.
- MAABA `15fc8a4`: MuMu ADB 장치의 uint64 입력 마스크가 Qt 드롭다운 변환에서 오버플로를 일으켜 카드 생성/자동 연결이 중단되던 문제 수정. Qt에는 대상 ID만 넣고 원본 장치 정보는 Python에서 보관합니다.
- MAABA 전체 테스트 465개 통과. ANReroll 복사본에서 임시 설정·모의 장치로 단일 연결과 다중 자동 연결/카드 생성·마스크 보존을 검증했습니다. 실제 게임/ADB 입력은 수행하지 않았습니다.
- 앱 파일만 동기화했으며 리소스와 개인 설정은 덮어쓰지 않았고 단위테스트는 복사하지 않았습니다. 실행 중이던 앱은 종료 후 다시 실행해야 새 코드가 적용됩니다.
