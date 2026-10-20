# ADB 유지보수 Agent

ANReroll 실행 앱은 리소스를 불러올 때 아래 CustomAction을 직접 등록합니다. 같은 구현은 외부 MaaFramework Client가 사용할 수 있도록 독립 `AgentServer` 진입점도 제공합니다.

- `ResetAdvertisingId`: Google Play 서비스의 광고 설정 화면을 열고 `광고 ID 재설정` 또는 `새 광고 ID 받기`를 누릅니다. Android 12 이상에서 삭제/재발급 UI만 제공하면 광고 ID 삭제 후 새 ID를 발급합니다.
- `DeleteArknightsSharedPrefs`: `com.YoStarKR.Arknights`를 강제 종료한 다음 `/data/data/com.YoStarKR.Arknights/shared_prefs`를 삭제합니다.
- `CaptureArknightsOperators`: 파이프라인 인식에 사용한 최신 캐시 화면을 MaaFW 내장 `Screencap`으로 저장합니다. 성공 화면은 `assets/saved/`에 저장하고 백업 ID를 전달하며, 실패 기록은 `assets/failed/`에 저장하고 백업 설정을 변경하지 않습니다.
- `ExportArknightsSharedPrefs`: 앱을 강제 종료한 다음 위 디렉터리의 파일을 PC 로컬 시각 기준 `assets/saved/shared_prefs_YYYYMMDDHHMMSS/`로 추출합니다. 예: `shared_prefs_20261016045310`.
- `ImportArknightsSharedPrefs`: `assets/saved`의 백업 폴더를 복사하여 기기의 원래 `shared_prefs` 위치에 복원합니다. PC 원본 폴더와 파일은 수정·이동·삭제하지 않습니다.

삭제와 추출에는 ADB shell 자체의 root 권한 또는 `su`가 필요합니다. 권한이 없으면 액션은 실패하고 대상 파일을 변경하지 않습니다. 추출 액션에서 `custom_action_param: { "name": "완료이미지명" }`을 지정하면 현재 시각 대신 안전하게 정리된 이름을 사용합니다. 같은 이름의 저장 폴더가 이미 있으면 기존 파일을 보존하고 실패합니다.

## 오퍼레이터 촬영과 나중 계정 백업 연결

`Check_Success`의 다음 노드인 `Check_Operator_Capture`가 저장합니다. 회차ID는 `YYYYMMDDHHMMSS_<16자리 난수>`이며 매 저장마다 새로 생성되므로, 반복 실행과 여러 인스턴스에서도 고정 파일명을 공유하지 않습니다.

`CaptureArknightsOperators`의 `action.param.custom_action_param`으로 저장 경로와 백업 연동 여부를 지정합니다.

```json
{
    "save_dir": "saved",
    "link_backup": true
}
```

- `save_dir`: `assets` 기준 상대 폴더 경로입니다. 생략하면 기존 `assets/saved/`를 사용합니다. 절대 경로도 `assets` 내부만 허용하며 상위 경로나 링크를 통해 외부로 벗어나는 경로는 거부합니다.
- `link_backup`: 기본값은 `true`입니다. 성공 촬영은 `saved`에 저장하고 기존 shared_prefs 백업과 같은 ID로 연결합니다. 다른 폴더에 기록만 남길 때는 `false`로 지정합니다.
- `Check_Failed_Record`는 `{"save_dir": "failed", "link_backup": false}`로 호출합니다. `assets/failed/shared_prefs_<회차ID>.png`를 저장한 뒤 기존 `Start_Reset`으로 진행합니다. 백업 노드가 없어도 촬영할 수 있으며 성공 촬영의 백업 ID를 읽거나 덮어쓰지 않습니다.
- 두 출력 폴더 모두 필요할 때 자동 생성되며 Git 추적에서 제외됩니다.

파이프라인은 `next` 인식 전에 화면을 촬영하므로 별도 `post_screencap()`은 호출하지 않습니다. 내장 `Screencap`은 해당 컨트롤러의 최신 전체 화면 캐시를 PNG로 저장합니다. 성공 판정에 사용한 프레임 자체가 아니라 저장 노드 직전의 최신 프레임이며, 두 노드 사이에 화면을 이동하는 동작을 넣지 않아야 합니다. 파이프라인 밖에서 액션만 단독 호출한다면 호출자가 먼저 유효한 화면 캐시를 준비해야 합니다.

MaaFW 기본 저장 위치인 `log_dir/screencap/`에서 반환된 `filepath`를 읽고, Python 표준 라이브러리로 지정한 폴더에 배타적으로 생성·복사합니다. 기존 PNG를 덮어쓰지 않으며, 복사 또는 ID 전달 실패 시 이번에 만든 저장 PNG만 제거합니다. 내장 액션의 이번 임시 파일은 복사 후 정리하고, 이전 로그나 이미지에는 손대지 않습니다. Python OpenCV/Pillow는 사용하지 않습니다.

`link_backup: true`인 촬영 Agent는 `Context.override_pipeline()`으로 **현재 task에만** 아래 백업 매개변수를 설정합니다. 원본 JSON이나 다른 인스턴스의 설정을 수정하지 않습니다.

```json
{
    "name": "20261017153045_a81f32c59d06e72b",
    "screenshot_path": "C:/ANReroll/assets/saved/shared_prefs_20261017153045_a81f32c59d06e72b.png",
    "require_screenshot": true
}
```

이후 `SReset_SharedPrefs_Export`에 도달하면 해당 PNG와 같은 위치에 `shared_prefs_<회차ID>/`를 만듭니다. 백업 시점에 다시 촬영하거나 ID를 생성하지 않습니다. PNG는 추출 디렉터리 밖에 두어 복원할 shared_prefs 파일과 섞이지 않게 합니다.

- 성공은 `Check_Operator_Capture → Start_Saved_Reset`, 실패는 `Check_Failed → Check_Failed_Record → Start_Reset` 흐름입니다. 다른 파이프라인 흐름은 변경하지 않습니다.
- 촬영과 백업은 반드시 **같은 task의 next 흐름**으로 연결해야 합니다. 별도 task 시작이나 프로세스 재시작에는 전달 정보가 유지되지 않습니다.
- `saved_reset.json`은 `require_screenshot: true`로 설정되어, 촬영 누락·경로/이름 불일치·누락/빈 이미지일 때 백업 액션이 실패합니다. 기존 `on_error: []`로 삭제/초기화 단계에 넘어가지 않습니다. 앞선 `SReset_App_Stop`은 기존대로 실행될 수 있습니다.
- 촬영만 하고 백업에 도달하지 못하면 PNG만 남습니다. 백업 실패 시에도 이미 촬영한 PNG는 보존합니다.
- 별도 수동 추출에서는 `require_screenshot`을 생략하면 기존의 이미지 없는 백업과 초 단위 기본 이름을 계속 사용할 수 있습니다.

API 확인 기준: MaaFW 5.12.3의 [내장 Screencap 구현](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/source/MaaFramework/Task/Component/Actuator.cpp#L504-L547), [Context.run_action_direct/override_pipeline/get_node_data](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/source/binding/Python/maa/context.py), [JScreencap](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/source/binding/Python/maa/pipeline.py).

## 외부 Agent의 최소 설치

실행 앱을 Python·라이브러리 내장 형태로 빌드하더라도, 별도 Python 프로세스로 실행하는 Agent의 환경과는 구분합니다. 외부 Agent만 사용하려면 프로젝트 루트에서 다음 목록만 설치합니다. 앱 전체용 `requirements.txt`/`requirements-lock.txt`는 설치할 필요가 없습니다.

```powershell
python -m pip install -r assets/agent/requirements.txt
```

직접 지정하는 패키지는 호스트와 같은 `MaaFw==5.12.3` 하나입니다. MaaFW의 필수 의존성인 NumPy, StrEnum, MaaAgentBinary는 pip가 함께 설치하므로 `--no-deps`는 사용하지 않습니다. PySide6, `opencv-python`, Pillow는 Agent에 필요하지 않습니다. MaaFW 자체의 네이티브 이미지 처리 라이브러리는 계속 사용합니다. 현재 개발 기준 Python은 3.10입니다.

이 변경은 Agent 저장 방식과 의존성 분리만 다룹니다. 앱 빌드·Python 내장 및 외부 인터프리터 선택 방식은 변경하지 않습니다.

## 저장한 계정 불러오기

1. 사용할 `shared_prefs_<이름>/` 폴더를 `assets/saved/` 아래에 둡니다. PNG가 아니라 XML 등 원본 파일이 들어 있는 폴더입니다.
2. `계정 불러오기` task의 `파일 이름` 입력에 **폴더 이름만** 입력합니다. 예: `shared_prefs_20261017153045_a81f32c59d06e72b`.
3. 실행하면 `Load_Shared_Pref_Dir`의 `ImportArknightsSharedPrefs`가 기기 계정 데이터를 교체합니다. 이후 기존 Pipeline대로 광고 ID 초기화와 앱 재실행을 진행합니다.

input의 `{TargetDir}`는 `action.param.custom_action_param.source_dir`로 전달됩니다. 별도 UI/백엔드 변경은 필요 없습니다. 직접 CustomAction을 호출할 때도 `custom_action_param: {"source_dir": "shared_prefs_..."}`로 지정합니다.

- 비어 있거나 없는 폴더, 전체 경로/상위 경로, 하위 폴더, 심볼릭 링크/Windows junction, 안전하지 않은 파일명은 거부합니다. Agent 검증을 우회해 임의의 PC 경로를 읽거나 기기 경로를 지정할 수 없습니다.
- 패키지 설치, root/su, 앱 데이터의 실제 UID/GID, 필요한 기기 명령을 확인합니다. 기기 앱 데이터가 아직 없으면 먼저 게임을 한 번 실행해야 합니다.
- 앱을 종료하고, 임시 폴더에 분할 전송한 모든 파일의 SHA-256을 검증합니다. 파일은 600, 폴더는 700 및 앱 UID/GID로 설정합니다. SELinux 활성 기기는 `restorecon -RFD`로 컨텍스트도 복원합니다.
- 파일별 UID/GID/권한 검증은 임시 폴더에서 짧은 개별 명령으로 수행합니다. 교체 스크립트는 파일 수에 따라 커지지 않도록 하여 MuMu의 긴 shell 명령 `exit 255` 문제를 피합니다.
- 기존 기기 `shared_prefs`를 임시 보관한 뒤 새 폴더를 원래 이름 `shared_prefs`로 교체합니다. 검증에 성공하면 기존 기기 데이터만 삭제합니다. 정상적인 교체 실패에서는 기존 폴더를 되돌리고 task를 실패시킵니다.
- 같은 기기의 동시 복원은 잠금 디렉터리로 차단합니다. ADB 단절·강제 종료·재부팅에서는 자동 복구를 보장할 수 없습니다. 실패 로그에 `.anreroll_previous_*`, `.anreroll_restore_*`, `.anreroll_restore_lock`이 표시되면 게임을 시작하지 말고 해당 기기 경로의 복구 상태를 확인해야 합니다. 잠금은 임의로 지우지 않습니다.
- 현재 기기 계정은 교체되므로 필요하면 먼저 별도로 백업하세요. PC의 불러올 원본 백업은 성공/실패와 관계없이 유지됩니다.

확인 문서: [MaaFW Project Interface V2 input](https://github.com/MaaXYZ/MaaFramework/blob/v5.12.3/docs/en_us/3.3-ProjectInterfaceV2.md#input-type-option-example), [Android restorecon 옵션](https://android.googlesource.com/platform/external/toybox/+/b73f894/toys/android/restorecon.c).

Pipeline 호출 예:

```json
{
    "ResetAdId": {
        "recognition": "DirectHit",
        "action": "Custom",
        "custom_action": "ResetAdvertisingId"
    },
    "BackupPrefs": {
        "recognition": "DirectHit",
        "action": "Custom",
        "custom_action": "ExportArknightsSharedPrefs",
        "custom_action_param": { "name": "clear_complete" }
    },
    "DeletePrefs": {
        "recognition": "DirectHit",
        "action": "Custom",
        "custom_action": "DeleteArknightsSharedPrefs"
    }
}
```

독립 AgentServer 실행 명령은 다음과 같습니다. identifier는 MaaFramework Client가 생성해 전달해야 합니다.

```powershell
Set-Location assets
python -m agent.main <Maa Agent identifier>
```
