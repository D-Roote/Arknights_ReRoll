"""Standalone MaaFramework AgentServer entry point for ANReroll actions."""

from __future__ import annotations

import sys
from pathlib import Path

# Support direct script execution by Project Interface clients, as well as -m.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

from agent.actions import create_actions


ASSETS_DIR = Path(__file__).resolve().parent.parent
SAVED_DIR = ASSETS_DIR / "saved"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not argv[0].strip():
        print("사용법: python -m agent.main <Maa Agent identifier>", file=sys.stderr)
        return 2
    if not Toolkit.init_option(str(ASSETS_DIR / "user" / "agent")):
        print("MaaFW Toolkit 초기화에 실패했습니다.", file=sys.stderr)
        return 1
    for name, action in create_actions(SAVED_DIR):
        if not AgentServer.register_custom_action(name, action):
            print(f"Maa CustomAction 등록에 실패했습니다: {name}", file=sys.stderr)
            return 1
    if not AgentServer.start_up(argv[0]):
        print("Maa AgentServer 시작에 실패했습니다.", file=sys.stderr)
        return 1
    try:
        AgentServer.join()
    finally:
        AgentServer.shut_down()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
