from copy import deepcopy
import ctypes
from pathlib import Path
import re


DEFAULT_PROGRAM_CONFIG = {
    "manual_path": "",
    "startup_wait_seconds": 60,
    "recognition_timeout_seconds": 180,
    "poll_interval_seconds": 1.0,
}


def normalize_program_config(raw_config):
    config = deepcopy(DEFAULT_PROGRAM_CONFIG)
    if not isinstance(raw_config, dict):
        return config

    manual_path = raw_config.get("manual_path")
    if isinstance(manual_path, str):
        config["manual_path"] = manual_path.strip()

    for key in ("startup_wait_seconds", "recognition_timeout_seconds"):
        value = raw_config.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            config[key] = int(value)

    poll_interval = raw_config.get("poll_interval_seconds")
    if (
        isinstance(poll_interval, (int, float))
        and not isinstance(poll_interval, bool)
        and poll_interval > 0
    ):
        config["poll_interval_seconds"] = float(poll_interval)
    return config


def resolve_manual_program_path(manual_path, executable_name=None):
    """An explicit executable, or an unambiguous legacy folder; never an auto fallback."""
    if not isinstance(manual_path, str) or not manual_path.strip():
        return None
    if any(character in manual_path for character in ("\0", "\r", "\n")):
        return None
    try:
        candidate = Path(manual_path.strip()).expanduser()
        if candidate.is_dir():
            executables = [path for path in candidate.iterdir()
                           if path.is_file() and path.suffix.casefold() == ".exe"]
            return executables[0].resolve() if len(executables) == 1 else None
        if candidate.is_file() and candidate.suffix.casefold() == ".exe":
            return candidate.resolve()  # Preserve previously saved unquoted file paths.
    except (OSError, ValueError):
        pass  # A command with arguments is not necessarily a valid filesystem path.
    try:
        return parse_manual_program_command(manual_path)[0]
    except (OSError, ValueError):
        return None


def parse_manual_program_command(command):
    """Parse a shortcut Target using Windows rules, never a command shell."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("실행 디바이스의 수동 경로를 입력하세요.")
    command = command.strip()
    if any(character in command for character in ("\0", "\r", "\n")):
        raise ValueError("실행 주소와 속성은 한 줄로 입력하세요.")
    quoted, slashes = False, 0
    for character in command:
        if character == '"' and slashes % 2 == 0:
            quoted = not quoted
        slashes = slashes + 1 if character == "\\" else 0
    if quoted:
        raise ValueError("실행 주소와 속성의 큰따옴표가 닫혔는지 확인하세요.")
    from ctypes import wintypes
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not argv:
        raise ValueError("실행 주소와 속성을 해석할 수 없습니다.")
    try:
        values = [argv[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))
    if not values:
        raise ValueError("실행 파일 경로가 없습니다.")
    executable = Path(values[0]).expanduser()
    if executable.suffix.casefold() != ".exe" or not executable.is_file():
        raise ValueError("실행할 EXE 파일을 확인할 수 없습니다. 경로와 큰따옴표를 확인하세요.")
    return executable.resolve(), values[1:]


def _controller_patterns(controller):
    if not isinstance(controller, dict) or controller.get("type") != "Win32":
        return None
    win32 = controller.get("win32") or {}
    if not isinstance(win32, dict):
        return None
    title, class_name = win32.get("window_regex", ""), win32.get("class_regex", "")
    if not isinstance(title, str) or not isinstance(class_name, str) or not (title or class_name):
        return None
    try:
        return re.compile(title, re.IGNORECASE), re.compile(class_name, re.IGNORECASE)
    except re.error:
        return None


def registered_steam_roots():
    """Read Steam's registration, not guesses about game folders or drive letters."""
    import winreg
    roots = set()
    for hive, key_name, value_name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            if (isinstance(value, str) and value and Path(value).is_absolute()
                    and (Path(value) / "steam.exe").is_file()):
                roots.add(Path(value).resolve())
        except (OSError, ValueError):
            pass
    return sorted(roots)


def _read_keyvalues(path):
    """Parse quoted/bare KeyValues tokens, nested blocks, escapes and line comments."""
    try:
        source = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}
    tokens, index = [], 0
    while index < len(source):
        if source[index].isspace():
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end + 1
        elif source[index] in "{}":
            tokens.append((source[index], True))
            index += 1
        elif source[index] == '"':
            index += 1
            value = []
            while index < len(source) and source[index] != '"':
                if source[index] == "\\" and index + 1 < len(source) and source[index + 1] in ('"', "\\"):
                    index += 1
                value.append(source[index])
                index += 1
            if index == len(source):
                return {}
            tokens.append(("".join(value), False))
            index += 1
        else:
            end = index + 1
            while end < len(source) and not source[end].isspace() and source[end] not in '{}"':
                end += 1
            tokens.append((source[index:end], False))
            index = end
    position = 0

    def block(nested=False, depth=0):
        nonlocal position
        if depth > 32:
            raise ValueError("KeyValues nesting too deep")
        result = {}
        while position < len(tokens):
            key, structural = tokens[position]
            position += 1
            if structural:
                if key == "}" and nested:
                    return result
                raise ValueError("Unexpected brace")
            if position == len(tokens):
                raise ValueError("Missing value")
            value, structural = tokens[position]
            position += 1
            if structural:
                if value != "{":
                    raise ValueError("Missing value")
                value = block(True, depth + 1)
            result[key.casefold()] = value
        if nested:
            raise ValueError("Unclosed block")
        return result
    try:
        return block()
    except (ValueError, RecursionError):
        return {}


def steam_installations(steam_roots=None):
    installations = {}
    for root in registered_steam_roots() if steam_roots is None else steam_roots:
        try:
            root = Path(root).resolve()
            launcher = root / "steam.exe"
            available = launcher.is_file()
        except (OSError, ValueError):
            continue
        if not available:
            continue
        libraries = {root}
        folders = _read_keyvalues(root / "steamapps/libraryfolders.vdf").get("libraryfolders", {})
        if isinstance(folders, dict):
            for key, value in folders.items():
                if key.isdecimal():
                    path = value.get("path") if isinstance(value, dict) else value
                    if isinstance(path, str) and path and Path(path).is_absolute():
                        try:
                            libraries.add(Path(path).resolve())
                        except (OSError, ValueError):
                            continue
        for library in sorted(libraries):
            steamapps = library / "steamapps"
            for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
                state = _read_keyvalues(manifest).get("appstate", {})
                if not isinstance(state, dict):
                    continue
                app_id, name, directory = state.get("appid"), state.get("name"), state.get("installdir")
                if (not isinstance(app_id, str) or not app_id.isascii() or not app_id.isdecimal() or int(app_id) <= 0
                        or manifest.stem != f"appmanifest_{app_id}" or not isinstance(name, str)
                        or not isinstance(directory, str) or not directory):
                    continue
                try:
                    common = (steamapps / "common").resolve()
                    installed = (common / directory).resolve()
                    available = installed.is_relative_to(common) and installed != common and installed.is_dir()
                except (OSError, ValueError):
                    continue
                if not available:
                    continue
                installations[(app_id, str(installed).casefold())] = {
                    "app_id": app_id, "name": name, "directory": installed, "launcher": launcher,
                }
    return list(installations.values())


def _literal_window_title(pattern):
    """Do not treat arbitrary regexes, class names, or project labels as Steam IDs."""
    text = pattern.removeprefix("^").removesuffix("$")
    result, index = [], 0
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 1
            if index == len(text) or text[index].isalnum():
                return None
            result.append(text[index])
        elif character in ".*+?[](){}|^$":
            return None
        else:
            result.append(character)
        index += 1
    title = "".join(result)
    return title if title.strip() else None


def find_auto_program_executable(program_config, drive_roots=None):
    """Return a verified running EXE or a unique Steam install root (no EXE guessing)."""
    controller = (program_config or {}).get("controller")
    patterns = _controller_patterns(controller)
    if patterns is None:
        return None
    from maa.toolkit import Toolkit
    from app.monitoring import window_process_info
    title, class_name = patterns
    try:
        matches = [window for window in (Toolkit.find_desktop_windows() or [])
                   if title.search(window.window_name or "") and class_name.search(window.class_name or "")]
        paths = set()
        for window in matches:
            hwnd = getattr(window.hwnd, "value", window.hwnd)
            pid, path = window_process_info(hwnd)
            if not pid or not path or not Path(path).is_file() or Path(path).suffix.casefold() != ".exe":
                return None  # Do not substitute another installation on a permissions failure.
            paths.add(Path(path).resolve())
        if matches:
            return next(iter(paths)) if len(paths) == 1 else None
    except (OSError, RuntimeError):
        return None
    literal_title = _literal_window_title(controller["win32"].get("window_regex", ""))
    if not literal_title:
        return None
    candidates = [installation["directory"] for installation in steam_installations(drive_roots)
                  if installation["name"].casefold() == literal_title.casefold()]
    return candidates[0] if len(candidates) == 1 else None


def find_program_executable(program_config, drive_roots=None):
    config = normalize_program_config(program_config)
    manual = resolve_manual_program_path(
        config["manual_path"]
    )
    if config["manual_path"]:
        return manual
    return find_auto_program_executable(program_config, drive_roots)


def find_steam_launch(executable_path):
    """Return the Steam launcher and app URL for an executable in a Steam library."""
    executable = Path(executable_path).resolve()
    parents = list(executable.parents)
    steamapps_dir = next(
        (parent for parent in parents if parent.name.casefold() == "steamapps"),
        None,
    )
    if steamapps_dir is None:
        return None

    common_dir = steamapps_dir / "common"
    try:
        executable.relative_to(common_dir)
    except ValueError:
        return None

    candidates = []
    for manifest_path in sorted(steamapps_dir.glob("appmanifest_*.acf")):
        state = _read_keyvalues(manifest_path).get("appstate", {})
        if not isinstance(state, dict):
            continue
        app_id, install_dir = state.get("appid"), state.get("installdir")
        if (not isinstance(app_id, str) or not app_id.isascii() or not app_id.isdecimal() or int(app_id) <= 0
                or manifest_path.stem != f"appmanifest_{app_id}" or not isinstance(install_dir, str)):
            continue
        try:
            installed_root = (common_dir / install_dir).resolve()
        except (OSError, ValueError):
            continue
        if not installed_root.is_relative_to(common_dir.resolve()) or installed_root == common_dir.resolve():
            continue
        try:
            executable.relative_to(installed_root)
        except ValueError:
            continue

        launchers = []
        registered_launcher = steamapps_dir.parent / "steam.exe"
        if registered_launcher.is_file():
            launchers.append(registered_launcher)
        launchers.extend(root / "steam.exe" for root in registered_steam_roots())
        launcher_path = state.get("launcherpath")
        if isinstance(launcher_path, str) and Path(launcher_path).name.casefold() == "steam.exe":
            launchers.append(Path(launcher_path))
        launcher = next((path.resolve() for path in launchers if path.is_file()), None)
        if launcher is None:
            continue
        candidates.append((launcher, f"steam://run/{app_id}"))
    return candidates[0] if len(candidates) == 1 else None


def build_program_launch_command(executable_path, arguments=None):
    executable = Path(executable_path).resolve()
    if arguments:
        return [str(executable), *arguments], executable.parent
    steam_launch = find_steam_launch(executable)
    if steam_launch is not None:
        launcher, app_url = steam_launch
        return [str(launcher), app_url], launcher.parent
    return [str(executable)], executable.parent
