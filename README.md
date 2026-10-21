# Arknights_ReRoll

명일방주 한국 서버 리세마라 자동화 리소스입니다. [MFWSide](https://github.com/D-Roote/MFWSide) 실행 앱과 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)를 사용하며, 오퍼레이터 화면 저장과 게스트 계정 백업·복원을 지원합니다.

## 설치

이 문서는 **차기 `1.0.0` 배포 기준**입니다. ANReroll 리소스와 MFWSide의 `1.0.0` 릴리즈가 모두 게시된 후 아래 새 설치 파일을 사용하세요. 현재 공개된 `v1.0`과 이전 `Setup_v1.0.*` 파일은 기존 설치용으로 유지합니다.

Windows x64 환경에서 사용합니다. 별도로 Python을 설치하거나 관리자 권한으로 실행할 필요는 없습니다.

1. [릴리즈](https://github.com/D-Roote/Arknights_ReRoll/releases)에서 **`Setup_1.0.0.cmd` 하나만** 내려받습니다.
2. 설치할 새 폴더에 CMD 파일만 넣고 더블클릭합니다. 필요한 실행 앱·리소스·Python·Agent 환경을 자동으로 구성합니다.
3. 설치 완료 후 같은 폴더의 `Start-ANReroll.cmd` 또는 `MFWSide.exe`를 실행합니다.

설치 위치 변경·업데이트 등 추가 옵션이 필요할 때는 CMD 대신 `Setup_1.0.0.ps1`을 받아 PowerShell에서 실행합니다.

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll
   ```

기본 설치 위치는 **CMD 파일이 있는 폴더**, PS1로 실행할 때는 **PowerShell의 현재 폴더**입니다. 첫 설치는 빈 폴더 또는 실행할 설치 파일 하나만 있는 폴더에서 진행하세요. 두 설치 파일을 모두 받을 필요는 없습니다. 버전별 설치 파일은 해당 리소스 릴리즈를 기본값으로 사용하며, 시스템 Python·PATH는 변경하지 않습니다. 다운로드 차단이나 Windows 보안 확인이 표시되면 출처를 확인하세요.

설치 상세는 [DEPLOYMENT.md](DEPLOYMENT.md), 파이프라인·MFWSide 업데이트 및 배포 명령은 [DISTRIBUTION.md](https://github.com/D-Roote/Arknights_ReRoll/blob/main/DISTRIBUTION.md)를 참고하세요.

## MuMu Player 설정

| 항목 | 설정값 |
|---|---|
| CPU | 1코어 |
| 메모리 | 4~5 GB |
| 해상도 | 1280×720 |
| DPI | 240 |
| 프레임 | 30 FPS |
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
- MaaReroll의 원본 저작권 고지와 MIT 라이선스는 [LICENSE.MaaReroll](LICENSE.MaaReroll)에 보존했습니다.
- 실행 앱은 [MFWSide](https://github.com/D-Roote/MFWSide), 자동화 엔진은 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)를 사용합니다.
