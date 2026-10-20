# Arknights_ReRoll

명일방주 한국 서버 리세마라 자동화 리소스입니다. [MFWSide](https://github.com/D-Roote/MFWSide) 실행 앱과 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)를 사용하며, 오퍼레이터 화면 저장과 게스트 계정 백업·복원을 지원합니다.

## 설치

Windows x64 환경에서 사용합니다. 별도로 Python을 설치하거나 관리자 권한으로 실행할 필요는 없습니다.

1. [릴리즈](https://github.com/D-Roote/Arknights_ReRoll/releases)에서 `setup.ps1`을 내려받습니다.
2. 다운로드한 폴더에서 PowerShell을 열고 실행합니다.

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

3. 설치 완료 후 설치 폴더의 `Start-ANReroll.cmd`를 더블클릭합니다.

설치 스크립트가 실행 앱·리소스·현재 OCR 모델·로컬 Python·Agent용 venv와 의존성을 구성합니다. 기본 설치 위치는 `%LOCALAPPDATA%\Arknights_ReRoll`이며 시스템 Python·PATH는 변경하지 않습니다. `setup.ps1` 자체는 더블클릭 대신 위 명령으로 실행하세요.

설치 위치 변경, 업데이트, 배포물 생성은 [상세 설치·배포 안내](DEPLOYMENT.md)를 참고하세요.

## MuMu Player 설정

| 항목 | 설정값 |
|---|---|
| CPU | 1코어 |
| 메모리 | 4~5 GB |
| 해상도 | 1280×720 |
| DPI | 240 |
| 프레임 | 60 FPS |
| Root 권한 | 활성화 |
| ADB | 연결 허용 |

설정을 적용한 뒤 앱에서 `MuMuPlayer` 컨트롤러와 실제 ADB 실행 파일·인스턴스 주소를 선택합니다. 리세마라 방식, 현재 화면, 저장/종료 조건과 뽑기 옵션을 확인한 후 실행하세요. 다중 실행 중 로딩·입력이 지연되면 동시 실행 수를 줄이세요.

## 결과 확인 및 주의사항

- `assets/saved/`: 성공한 계정의 오퍼레이터 사진과 `shared_prefs` 백업을 저장합니다.
- `assets/failed/`: 실패로 판정한 오퍼레이터 사진을 저장합니다. 실행 후 주기적으로 확인하세요.
- 필터로 제외될 결과 외에 **조건을 만족하는 사진이 `failed`에 저장되어 있다면**, `저장/종료 조건 (6성 개수)`를 **`0개 이상 (고려 안 함)`(0명)**으로 바꿔 인원수 필터를 해제하세요. 특정 6성 오퍼레이터 조건은 별도로 적용됩니다.
- 오퍼레이터 목록이 아닌 화면이 저장됐다면 연결·정렬·화면 전환 상태도 확인하세요.
- 기존 게스트 계정 삭제와 게임 재화 사용이 포함됩니다. 보관할 계정은 먼저 백업하고, 계정 불러오기와 리세마라를 동시에 실행하지 마세요. 백업에는 계정 정보가 있으므로 외부에 공개하지 마세요.

## 오픈소스 및 출처

- [MaaReroll](https://github.com/CookieHCl/MaaReroll)의 파이프라인과 이미지 리소스를 기반으로 재구성·수정했습니다.
- 전투 관련 파이프라인에는 이 프로젝트 작성자가 이전에 MaaReroll 포크에서 작업·기여한 내용이 포함되어 있습니다.
- MaaReroll의 원본 저작권 고지와 MIT 라이선스는 [LICENSE.MaaReroll](LICENSE.MaaReroll)에 보존했습니다.
- 실행 앱은 [MFWSide](https://github.com/D-Roote/MFWSide), 자동화 엔진은 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)를 사용합니다.
