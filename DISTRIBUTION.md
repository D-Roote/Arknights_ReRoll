# 배포·업데이트 명령어

명령은 **Arknights_Reroll 저장소 루트**에서 실행합니다. 설치 상세 동작과 옵션은 [DEPLOYMENT.md](DEPLOYMENT.md), 사용자 안내는 [README.md](README.md)를 참고하세요. 이 운영 문서는 저장소에서 관리하며, 기존 설치 스크립트와의 리소스 ZIP 호환성을 위해 ZIP에는 추가하지 않습니다.

## 버전 규칙과 전환 시점

- 표시 버전·파일명·생성 도구의 `--version`은 `1.0.0`, `1.0.1`, `1.1.0`처럼 **`v` 없는 세 정수**로 지정합니다. `01.0.0` 같은 선행 0은 사용하지 않습니다.
- GitHub 태그는 **`v1.0.0`**, 릴리즈 제목은 **`Arknights_Reroll 1.0.0`** 형식입니다. 생성된 설치 파일의 기본 `ResourceTag`에는 자동으로 `v`가 붙습니다. ZIP manifest와 `assets/resources/interface.json`의 버전에는 붙이지 않습니다.
- MFWSide 태그는 독립적으로 관리합니다. 현재 대상은 `deployment/runtime.json`의 `app_tag: v1.0.0`이며 SDK는 MaaFW `5.12.3`입니다. 이후 앱 릴리즈가 바뀌면 실제 게시된 태그로 갱신하세요.
- 기존 `v1.0` 릴리즈를 `v1.0.0`으로 전환하되, 과거 Git 태그 `v1.0`과 저장소의 `Distribution/Setup_v1.0.*`는 이력으로 보존합니다. 현재 설치에는 `Setup_1.0.0.*`를 사용하며, 이전 첨부 다운로드 링크를 계속 제공하는 것은 아닙니다.

## 설치 파일 구분

| 파일 | 용도 |
|---|---|
| `Setup.ps1` | 저장소의 설치 원본. 기본 리소스는 최신 정식 릴리즈(`latest`) |
| `Distribution/Setup_<버전>.cmd` | 기본 설치용 단일 파일. 더블클릭하면 **그 파일이 있는 폴더**에 설치 |
| `Distribution/Setup_<버전>.ps1` | 설치 위치·버전·업데이트 등 추가 옵션을 지정할 때 사용 |
| 각 설치 파일의 `.sha256` | 다운로드·업로드 무결성 확인용. 설치 실행에 필수인 파일은 아님 |

예를 들어 `Setup_1.0.0.cmd`와 `Setup_1.0.0.ps1`은 기본 리소스 태그가 `v1.0.0`으로 고정됩니다. 파일명만 바꾸지 말고 생성 명령의 `--version`을 변경하세요. PS1에서는 `-ResourceTag`로 이 기본값을 덮어쓸 수 있습니다.

CMD에는 동일 버전의 PowerShell 설치 코드 전체가 평문으로 포함됩니다. 사용자는 **CMD 하나만** 받아 새 폴더에서 실행하면 됩니다. 별도 PS1을 내려받거나 임시 PS1을 만들지 않으며, 실행 앱·리소스·로컬 Python·Agent 의존성은 인터넷에서 자동 다운로드합니다. 추가 인수는 CMD에서 전달하지 않습니다. 사용자 설정이 필요하면 PS1을 사용하세요.

첫 설치 폴더에는 실행할 설치 파일 하나만 두세요. CMD와 PS1, 체크섬을 모두 같은 폴더에 넣으면 미관리 파일 보호 검사에서 중단됩니다. 브라우저의 다운로드 차단·Windows 보안 확인은 사용자가 정상 배포 파일인지 확인한 뒤 처리해야 합니다. 관리자 권한, 시스템 실행 정책 변경, 시스템 Python 설치는 요구하지 않습니다.

## 1. 사용자: 신규 설치

기본 설치는 [릴리즈](https://github.com/D-Roote/Arknights_ReRoll/releases)에서 `Setup_1.0.0.cmd` 하나를 새 설치 폴더로 내려받아 더블클릭합니다. 완료 후 `Start-ANReroll.cmd` 또는 `MFWSide.exe`로 실행합니다. 설치 자체는 앱·앱플레이어·게임 작업을 실행하지 않습니다.

옵션이 필요하면 CMD 대신 PS1만 받고 실행합니다.

```powershell
# 현재 PowerShell 폴더에 기본 옵션으로 설치
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1

# 설치 위치를 별도로 지정
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll

# 설치 후 앱도 실행: 기존 앱의 자동 시작 설정에 주의
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll -Launch
```

PS1은 스크립트 위치가 아니라 **PowerShell의 현재 폴더**가 기본 설치 위치입니다. CMD는 실행 중 파일의 폴더로 이동한 뒤 같은 설치 코드를 실행합니다. PS1의 일반 더블클릭 실행은 Windows에서 보장되지 않습니다. [PowerShell 스크립트 실행 안내](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_scripts?view=powershell-5.1)

## 2. 사용자: 파이프라인·리소스 업데이트

MFWSide와 실행 중인 작업을 모두 종료한 뒤, 사용할 릴리즈의 PS1을 받아 실행합니다. 다음의 `1.1.0`은 **해당 릴리즈가 실제 게시되었을 때** 사용하는 예시입니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.1.0.ps1 -InstallDir C:\Games\ANReroll -Update

# 같은 태그의 리소스 ZIP만 교체된 경우
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll -Update
```

`-Update` 없이 재실행하면 완료된 설치의 파일을 교체하지 않습니다. 최신 버전이라는 이유만으로 CMD가 기존 설치를 자동 업데이트하지도 않습니다.

- `assets/user`, `assets/saved`, `assets/failed`는 유지합니다.
- 기존 관리 파일은 `.setup-backups/`로 이동하고, 교체 실패 시 되돌립니다.
- 같은 ZIP 파일명이라도 릴리즈 digest가 바뀌면 캐시를 다시 검증·다운로드합니다.
- 다른 MaaFW SDK·Agent 패키지가 필요한 경우 기존 venv를 강제 변경하지 않고 중단합니다. **새 폴더에 설치**하고 설정·백업은 별도로 옮기세요.

## 3. 사용자: MFWSide 릴리즈만 업데이트

### 같은 MFWSide 태그의 첨부 ZIP이 교체된 경우

리소스가 지정한 앱 태그가 그대로라면 일반 업데이트로 새 앱 ZIP도 확인합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll -Update
```

### 새로운 MFWSide 태그를 직접 선택하는 경우

```powershell
# MFWSide 1.1.0이 게시되었고 현재 리소스와 SDK가 호환될 때의 예시
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup_1.0.0.ps1 -InstallDir C:\Games\ANReroll -Update -AppTag v1.1.0
```

이 명령은 관리되는 앱·리소스를 함께 재설치합니다. 앱만 따로 교체하는 전용 스위치는 없습니다. 기본 앱 버전은 리소스 ZIP의 `deployment/runtime.json`에 있는 `app_tag`이며, **자동으로 MFWSide의 최신 버전을 선택하지 않습니다.** `BUILD-INFO.json`의 MaaFW 버전이 맞지 않으면 중단합니다.

## 4. 배포자: 무엇이 바뀌면 무엇을 배포하나

| 변경 사항 | 필요한 작업 |
|---|---|
| 파이프라인·이미지·interface·기본 설정 | 리소스 ZIP과 체크섬 재생성·업로드 |
| Agent 코드 | 리소스 ZIP과 체크섬 재생성·업로드 |
| 설치 원본 `Setup.ps1` | 버전별 PS1·CMD·체크섬 재생성·업로드 |
| MFWSide 동일 태그의 앱 ZIP만 교체, SDK 동일 | ANReroll 리소스 재생성 불필요. 사용자에게 `-Update` 안내 |
| 기본 MFWSide 태그 변경 | `deployment/runtime.json`의 `app_tag` 수정 후 리소스 재배포 |
| MaaFW·Agent 의존성 변경 | 앱 빌드·명세·의존성·설치 검사를 함께 맞춘 뒤 새 폴더 설치 검증 |

버전이 바뀌는 신규 배포는 설치 파일도 새 버전으로 생성합니다. 기존 태그 안에서 파이프라인만 고쳤다면 설치 코드가 동일한 한 설치 파일을 다시 업로드할 필요는 없습니다.

### 공통 준비

패키징에는 Python 3.10 이상과 Git이 필요합니다. 아래 게시 명령은 [GitHub CLI](https://cli.github.com/manual/gh_release)를 설치하고 저장소 쓰기 권한으로 로그인한 환경을 전제로 합니다. CLI 없이 GitHub 릴리즈 화면에서 같은 파일을 첨부해도 됩니다.

```powershell
gh auth login
git status --short
```

리소스·문서 변경을 검토하고 커밋한 뒤 생성하세요. ZIP의 `source_commit`에는 생성 당시 HEAD가 기록됩니다. 사용자 데이터·실행 로그·개인 백업을 스테이징하지 마세요.

### 새 버전의 전체 배포물 생성

```powershell
$Version = '1.0.0'
python .\tools\package_release.py --version $Version --installers-only
git add -- Distribution
git commit -m "Chore: $Version 설치 파일 생성"
# 설치 파일까지 커밋한 뒤 ZIP을 생성해야 source_commit이 배포 소스와 일치
python .\tools\package_release.py --version $Version
```

생성 결과:

```text
dist/
  ANReroll-resources-1.0.0.zip
  ANReroll-resources-1.0.0.zip.sha256
Distribution/
  Setup_1.0.0.ps1
  Setup_1.0.0.ps1.sha256
  Setup_1.0.0.cmd
  Setup_1.0.0.cmd.sha256
```

`Distribution`의 작은 설치 파일들은 버전별로 Git에 보관하며, 리소스 ZIP은 Git 대신 릴리즈에 첨부합니다. 설치 파일의 바이트와 체크섬을 유지하도록 `.gitattributes`에서 줄바꿈 변환을 방지합니다.

### 설치 파일만 생성·수정

```powershell
# 리소스 ZIP은 건드리지 않음
python .\tools\package_release.py --version 1.0.0 --installers-only

# 같은 버전의 설치 원본을 의도적으로 수정한 경우에만
python .\tools\package_release.py --version 1.0.0 --installers-only --replace-installers
```

같은 내용의 재생성은 허용하지만 변경된 설치 파일을 같은 이름으로 덮어쓰는 것은 명시적 옵션이 필요합니다. 다른 버전의 파일은 바꾸지 않습니다.

### 새 GitHub 릴리즈 게시

```powershell
$Version = '1.0.0'
$Tag = "v$Version"
$Repository = 'D-Roote/Arknights_Reroll'
$Artifacts = @(
    ".\dist\ANReroll-resources-$Version.zip",
    ".\dist\ANReroll-resources-$Version.zip.sha256",
    ".\Distribution\Setup_$Version.cmd",
    ".\Distribution\Setup_$Version.cmd.sha256",
    ".\Distribution\Setup_$Version.ps1",
    ".\Distribution\Setup_$Version.ps1.sha256"
)
# 앞 단계에서 설치 파일을 커밋하고 ZIP을 생성한 상태에서 실행
git push origin main
git tag -a $Tag -m "Arknights_Reroll $Version"
git push origin $Tag
gh release create $Tag @Artifacts --repo $Repository --verify-tag --title "Arknights_Reroll $Version" --notes "기본 설치는 Setup_$Version.cmd 하나를 새 폴더에서 실행하세요. 추가 옵션과 업데이트는 Setup_$Version.ps1을 사용하세요."
```

`--version`에는 `1.0.0`처럼 숫자 버전을 넣습니다. `1.0`이나 `v1.0.0`은 생성 단계에서 거부하며, GitHub 명령에는 `v1.0.0` 태그를 사용합니다. MFWSide 태그와 같을 필요는 없습니다. 자동 생성된 `Source code.zip`을 리소스 ZIP 대신 올리지 마세요. 패키징 도구 자체는 커밋·푸시·태그 생성·업로드를 하지 않습니다. 기존 릴리즈 교체를 설명하는 아래 명령은 해당 태그가 이미 게시된 경우의 예시입니다. 이미 존재하는 태그를 강제로 이동하지 마세요.

### 기존 릴리즈의 리소스만 교체

먼저 기존 첨부를 별도 폴더에 내려받아 보관합니다. `--clobber`는 기존 동명 첨부를 제거하고 업로드하므로 **실패 시 백업으로 다시 업로드해야 할 수 있습니다.** 릴리즈 버전·태그를 지우거나 강제 이동할 필요는 없습니다.

```powershell
$Version = '1.0.0'
$Tag = "v$Version"
$Repository = 'D-Roote/Arknights_Reroll'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Output = ".\dist\repack-$Version-$Stamp"
gh release download $Tag --repo $Repository --dir ".\.cache\release-backup-$Version-$Stamp" --pattern "ANReroll-resources-$Version.zip*"
python .\tools\package_release.py --version $Version --output-dir $Output
gh release upload $Tag "$Output\ANReroll-resources-$Version.zip" "$Output\ANReroll-resources-$Version.zip.sha256" --repo $Repository --clobber
```

설치 코드도 바뀌었다면 위 생성 명령에 `--replace-installers`를 추가하고, 아래 설치 파일 교체도 수행하세요. 생성에 실패했다면 업로드하지 마세요. 게시 후에는 첨부 digest와 체크섬, 새 폴더에서의 설치를 다시 확인합니다.

### 기존 릴리즈에 버전별 설치 파일 첨부·교체

```powershell
$Version = '1.0.0'
$Tag = "v$Version"
$Repository = 'D-Roote/Arknights_Reroll'
python .\tools\package_release.py --version $Version --installers-only
gh release upload $Tag ".\Distribution\Setup_$Version.cmd" ".\Distribution\Setup_$Version.cmd.sha256" ".\Distribution\Setup_$Version.ps1" ".\Distribution\Setup_$Version.ps1.sha256" --repo $Repository
```

처음 첨부할 때는 `--clobber`가 필요 없습니다. 기존 설치 파일도 교체하려면 먼저 `gh release download`로 해당 파일들을 보관하고, 생성에는 `--replace-installers`, 업로드에는 `--clobber`를 명시하세요. 릴리즈 본문의 설치 안내도 새 파일명과 맞춥니다. 기존 무버전 `setup.ps1` 첨부는 이전 링크 호환용으로 남길 수 있습니다.

## 5. 검증·문제 확인

```powershell
# 게시된 파일명·크기·서버 digest 확인
gh release view v1.0.0 --repo D-Roote/Arknights_Reroll --json tagName,assets

# 로컬 설치 파일의 해시 확인
Get-FileHash .\Distribution\Setup_1.0.0.ps1 -Algorithm SHA256
Get-Content .\Distribution\Setup_1.0.0.ps1.sha256

# 로컬 배포 ZIP으로 별도 폴더에 실제 설치 검증: 앱·게임 작업은 실행하지 않음
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -InstallDir C:\Temp\ANReroll-verify -ResourceArchive .\dist\ANReroll-resources-1.0.0.zip -AppArchive C:\Downloads\MFWSide-1.0.0-windows-x64.zip
```

로컬 ZIP 옆에는 동일 이름의 `.zip.sha256` 파일이 필요합니다. 설치 검증은 네이티브 MaaFW·OCR 모델·Agent 등록까지 확인하며, 게임 로그인·ADB/root 권한·다중 실행 안정성을 보장하지는 않습니다. 명령이 실패하면 다음 업로드·실행 단계로 넘어가지 말고 먼저 오류를 확인하세요.
