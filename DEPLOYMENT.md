# 설치·배포 자동화

## 사용자 설치

Windows x64와 Windows PowerShell 5.1 이상이 필요합니다. 기본 설치용 단일 파일은 `Setup_v1.0.cmd`, 추가 옵션용은 `Setup_v1.0.ps1`입니다. CMD는 **그 파일이 있는 폴더**, PS1은 **PowerShell의 현재 폴더**에 설치하며 `-InstallDir`로 다른 위치를 지정할 수 있습니다. 첫 설치는 쓰기 가능한 빈 로컬 폴더 또는 실행할 설치 파일 하나만 있는 폴더에서 진행하세요. Git, 관리자 권한, 시스템 Python 설치는 필요하지 않습니다.

1. [Arknights_ReRoll 릴리즈](https://github.com/D-Roote/Arknights_ReRoll/releases)에서 `Setup_v1.0.cmd` 하나만 내려받아 새 폴더에서 더블클릭합니다. CMD에는 설치 코드가 포함되어 별도 PS1이 필요 없습니다.
2. 추가 옵션을 지정하려면 CMD 대신 `Setup_v1.0.ps1`을 받고 PowerShell에서 실행합니다.

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_v1.0.ps1
   ```

3. 완료 메시지가 표시되면 설치 폴더의 `Start-ANReroll.cmd`를 실행합니다.
4. MuMu Player를 CPU 1코어·RAM 4~5 GB·해상도 1280×720·DPI 240·30 FPS로 설정하고, ADB와 root 권한을 활성화합니다. 앱에서 연결 대상과 작업을 설정하고, 기존 계정 삭제·재화 사용을 포함하므로 실행 전 옵션을 확인하세요.

실행 정책 우회는 위 PowerShell 프로세스에만 적용됩니다. 스크립트는 시스템 실행 정책·PATH·파일 연결·레지스트리를 변경하지 않습니다. 인터넷에서 받은 스크립트를 `iex`로 바로 실행하지 마세요.

설치 스크립트는 다음을 자동 수행합니다.

- GitHub API에서 지정한 리소스 릴리즈의 ZIP을 다운로드합니다. 저장소 원본 `Setup.ps1`의 기본값은 `latest`, 생성된 `Setup_<버전>.ps1`과 CMD의 기본값은 해당 버전입니다.
- 리소스가 지정한 MFWSide 릴리즈를 다운로드합니다. 현재 검증 기준은 `v1.0`, MaaFW `5.12.3`입니다. 무조건 최신 앱으로 바꾸지 않으며, 앱의 `BUILD-INFO.json`과 리소스 SDK 버전이 다르면 설치를 중단합니다.
- GitHub의 SHA-256 digest 또는 릴리즈의 `.sha256` 파일로 ZIP을 검증하고 안전하게 압축 해제합니다. 경로 이탈·심볼릭 링크·중복 파일·Windows 특수 파일명은 거부합니다.
- 리소스 ZIP에 동봉한 **기존 한국어 OCR 모델 세 파일을 그대로** 설치하고 해시를 확인합니다. MaaCommonAssets의 다른 모델로 대체하지 않습니다.
- 공식 Python NuGet 배포본 `3.13.10`을 설치 폴더에 풀어 `.venv`를 만듭니다. 이것은 `venv`와 `ensurepip`를 포함하는 Python 배포본이며, pip 설치가 제한되는 embeddable ZIP이 아닙니다. 별도 `nuget.exe`도 필요하지 않습니다.
- Agent용 `MaaFw==5.12.3`, `MaaAgentBinary==1.0.1`, `numpy==2.2.6`, `StrEnum==0.4.15`만 설치합니다. MFWSide에 내장된 Python 3.10과 외부 Agent의 Python 버전은 달라도 되지만 MaaFW SDK 버전은 일치시킵니다.
- 네이티브 리소스·OCR 모델 로드, task entry 존재 여부와 CustomAction 등록을 검사합니다. ADB 연결이나 계정 초기화·촬영·게임 작업은 실행하지 않습니다.

Python NuGet 배포 방식은 [Python 공식 문서](https://docs.python.org/3.13/using/windows.html#the-nuget-org-packages)를 따릅니다. 고정 버전과 모델 해시는 `deployment/runtime.json`, Agent 의존성은 `deployment/agent-requirements.txt`에서 관리합니다.

## 설치 위치와 실행 경로

```text
ANReroll/
├─ MFWSide.exe
├─ _internal/                  # 앱의 내장 Python·라이브러리
├─ licenses/
├─ Start-ANReroll.cmd
├─ runtime/python-3.13.10/     # 외부 Agent용 로컬 Python
├─ .venv/Scripts/python.exe
├─ assets/
│  ├─ resources/
│  │  ├─ interface.json
│  │  ├─ default_pipeline.json
│  │  ├─ pipeline/
│  │  ├─ image/
│  │  └─ model/ocr/ko/         # 현재 det.onnx·rec.onnx·keys.txt
│  ├─ agent/
│  ├─ user/                    # 앱 설정·로그, 실행 시 생성
│  ├─ saved/                   # 성공 화면·계정 백업, 실행 시 생성
│  └─ failed/                  # 실패 화면, 실행 시 생성
└─ .anreroll-install.json
```

`interface.json`의 `agent.child_exec: ../../.venv/Scripts/python.exe`와 `child_args: [-X, utf8, -u, ../agent/main.py]`가 그대로 해석되는 구조입니다. 설치 시 Agent 실행 문자열을 임의로 치환하지 않습니다. Agent identifier는 MFWSide가 실행마다 생성하므로 고정 값을 넣지 마세요.

앱에 포함된 `_internal/`은 EXE와 함께 유지해야 합니다. 설치 폴더를 다른 위치로 옮기면 venv의 Python 기준 경로가 달라질 수 있으므로 새 위치에서 다시 설치하세요.

## 옵션과 재실행

```powershell
# 리소스 버전 고정
.\Setup_v1.0.ps1 -InstallDir C:\Games\ANReroll -ResourceTag v1.0

# 설치된 x64 Python 3.10~3.13 사용: 로컬 Python 다운로드 생략
.\Setup_v1.0.ps1 -InstallDir C:\Games\ANReroll -PythonExe C:\Python313\python.exe

# 설치 확인 후 앱도 실행 (기본값은 실행하지 않음)
.\Setup_v1.0.ps1 -InstallDir C:\Games\ANReroll -Launch

# 앱을 닫은 뒤 리소스·앱의 관리 대상 파일 업데이트
.\Setup_v1.0.ps1 -InstallDir C:\Games\ANReroll -Update
```

`-AppTag`로 다른 MFWSide 릴리즈를 지정할 수 있지만 SDK 버전이 맞아야 합니다. ZIP이 여러 개라 자동 선택이 불가능하면 `-ResourceAsset ANReroll-resources-v1.0.zip`으로 정확한 파일명을 지정합니다. CMD는 기본 설치용이며 추가 옵션은 전달하지 않습니다.

이미 설치가 완료된 폴더에서 `-Update` 없이 재실행하면 기존 파일을 교체하지 않습니다. 업데이트는 이 스크립트가 만든 설치 폴더에만 허용하며 소스 저장소나 다른 파일·폴더가 있는 미관리 폴더에는 설치하지 않습니다. 예외는 실행 중인 PS1 또는 CMD 파일 하나뿐입니다. PS1을 다른 폴더에서 절대 경로로 실행해도 스크립트 위치가 아니라 PowerShell의 현재 폴더에 설치합니다. 소스 저장소에서 테스트할 때는 별도의 `-InstallDir`를 지정하세요.

이전 기본 경로인 `%LOCALAPPDATA%\Arknights_ReRoll`의 설치본은 자동으로 옮기거나 삭제하지 않습니다. 그 위치에서 계속 사용하려면 해당 폴더를 `-InstallDir`로 지정하세요. 새 위치에 설치하려면 새 폴더에서 다시 설치하고, 필요한 계정 백업·설정은 별도로 보관하세요.

업데이트 전에 새 리소스 검사를 수행하고 기존 관리 파일은 `.setup-backups/`에 보존합니다. 교체 도중 실패하면 기존 파일을 되돌립니다. `assets/user`, `assets/saved`, `assets/failed`는 교체하지 않습니다. 기존 venv의 SDK·의존성이 다른 경우에는 자동 변경하지 않고 새 폴더에 설치하도록 안내합니다.

`.setup-cache/`에는 검증된 다운로드 파일을 보관합니다. `.setup-backups/`는 되돌리기용이므로 내용 확인 전 삭제하지 마세요. `-Launch`는 기존 앱 설정에 따라 자동 시작 기능이 동작할 수 있으므로 업데이트 시에는 특히 주의하세요.

## 릴리즈 생성

현재 리소스 ZIP 규격은 단순히 `resources/` 폴더만 압축한 파일과 다릅니다. 외부 Agent와 버전·해시 정보도 있어야 새 PC에서 자동 설치할 수 있습니다.

저장소 루트에서 실행합니다. 패키징에는 Python 3.10 이상과 Git만 필요하고 MaaFW·PySide6를 설치할 필요는 없습니다.

```powershell
python .\tools\package_release.py --version v1.0
```

`dist/`에 리소스 ZIP·체크섬이, `Distribution/`에 버전별 설치 파일·체크섬이 생성됩니다.

- `dist/ANReroll-resources-v1.0.zip`
- `dist/ANReroll-resources-v1.0.zip.sha256`
- `Distribution/Setup_v1.0.ps1`, `Setup_v1.0.ps1.sha256`
- `Distribution/Setup_v1.0.cmd`, `Setup_v1.0.cmd.sha256`

설치 파일만 생성하려면 `--installers-only`를 추가합니다. 수정된 설치 원본으로 같은 버전을 재생성할 때는 `--replace-installers`를 명시합니다. 기본값은 기존 설치 파일을 보존합니다.

ZIP에는 `assets/resources`, `assets/agent`, 설치 검증 도구, 의존성·런타임 명세, README와 MaaReroll 라이선스가 포함됩니다. `.gitignore`는 이미 추적된 파일에도 적용하며 사용자 설정·로그·백업·실패 화면·캐시·앱 소스는 제외합니다.

**모델만 명시적인 예외**입니다. Git에서 무시하더라도 현재 `assets/resources/model/ocr/ko/{det.onnx,rec.onnx,keys.txt}` 세 파일은 ZIP에 포함합니다. 다른 모델·임시 파일은 제외합니다. 세 파일이 없거나 `deployment/runtime.json`의 해시와 다르면 불완전한 릴리즈 생성을 거부합니다. 모델을 의도적으로 교체할 때만 해시와 호환성 검증 결과를 함께 갱신하세요.

현재 작업 트리의 파일을 패키징하므로 공개 전 변경 내용과 포함 파일을 확인하세요. `ANREROLL-RESOURCE.json`에는 기준 커밋과 배포한 각 파일의 해시가 기록됩니다. 기존 ZIP이나 체크섬은 덮어쓰지 않습니다.

1. `D-Roote/Arknights_ReRoll`에서 해당 버전의 정식 GitHub Release를 준비합니다.
2. 위 리소스 ZIP·체크섬과 `Distribution/Setup_<버전>.{cmd,ps1}`·각 체크섬을 첨부합니다.
3. 공개한 뒤 빈 설치 폴더에서 해당 `-ResourceTag`를 지정해 확인합니다.

GitHub의 자동 생성 `Source code.zip`은 모델과 패키지 명세가 없으므로 설치 파일로 사용하지 않습니다. 이 스크립트들은 Git push·태그 생성·릴리즈 게시를 자동 수행하지 않습니다. 신규 게시, 기존 첨부 교체, 파이프라인·MFWSide 업데이트별 명령은 [DISTRIBUTION.md](https://github.com/D-Roote/Arknights_ReRoll/blob/main/DISTRIBUTION.md)에 정리되어 있습니다.

## 로컬 ZIP과 오류 확인

릴리즈 게시 전에는 로컬 ZIP으로 같은 설치 과정을 검증할 수 있습니다. 각 ZIP 옆에 `.zip.sha256` 파일이 있어야 합니다.

```powershell
.\Setup.ps1 -InstallDir C:\Temp\ANReroll-test `
  -ResourceArchive .\dist\ANReroll-resources-v1.0.zip `
  -AppArchive C:\Downloads\MFWSide-v1.0-windows-x64.zip
```

- `-PythonPackage`에 미리 받은 동일 버전 Python `.nupkg`를 지정할 수 있습니다. `runtime.json`의 해시와 일치해야 합니다.
- `-Wheelhouse`를 지정하면 pip도 `--no-index --find-links`로 로컬 wheel만 사용합니다. OS·Python 버전에 맞는 네 패키지의 wheel을 모두 준비해야 합니다.
- GitHub 404: 저장소 공개 여부, 정식 릴리즈·첨부 파일 존재 여부와 태그를 확인합니다. 비공개 저장소·API 제한에는 읽기 권한이 있는 `GITHUB_TOKEN` 환경 변수를 사용할 수 있으며 스크립트에 토큰을 저장하지 않습니다.
- SHA-256 불일치: 해당 파일을 실행하지 말고 원본 릴리즈를 확인합니다. 캐시의 불일치 파일은 `.invalid-*` 이름으로 보존됩니다.
- 네이티브 라이브러리 로드 실패: Windows x64인지와 VC++ 런타임 등 OS 필수 구성요소를 확인합니다. 설치 검증이 성공하지 않으면 기존 앱·리소스는 교체하지 않습니다.
- 모델 로드·Agent 등록 성공은 실제 게임 화면 인식·root 권한·다중 실행 안정성을 보장하지 않습니다. 이 부분은 사용 환경에서 별도로 확인합니다.
