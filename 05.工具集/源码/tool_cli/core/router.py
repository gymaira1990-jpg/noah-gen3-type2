"""子命令路由 — 自动发现 actions/ 下的命令模块"""
import importlib, inspect, os, sys
from pathlib import Path

TOOL_HOME = os.getenv("TOOL_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_commands = None


def discover_commands() -> dict:
    """扫描 actions/ 目录发现所有子命令"""
    cmds = {}
    actions_dir = Path(TOOL_HOME) / "actions"
    for f in sorted(actions_dir.glob("*.py")):
        if f.stem.startswith("__"):
            continue
        try:
            # 相对导入
            spec = importlib.util.spec_from_file_location(
                f"actions.{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"actions.{f.stem}"] = mod
            spec.loader.exec_module(mod)

            for name, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != f"actions.{f.stem}":
                    continue
                if hasattr(cls, "name") and hasattr(cls, "run") and cls.name:
                    cmds[cls.name] = cls
                    break
        except Exception as e:
            print(f"⚠️  加载命令 {f.stem} 失败: {e}", file=sys.stderr)
    return cmds


def get_commands() -> dict:
    global _commands
    if _commands is None:
        _commands = discover_commands()
    return _commands


def dispatch(args: list) -> int:
    """分发子命令"""
    cmds = get_commands()
    if not args or args[0] in ("-h", "--help"):
        _show_help(cmds)
        return 0

    cmd_name = args[0]
    if cmd_name not in cmds:
        print(f"未知命令: {cmd_name}")
        print(f"可用命令: {', '.join(sorted(cmds.keys()))}")
        return 1

    try:
        return cmds[cmd_name]().run(args[1:])
    except Exception as e:
        print(f"❌ {cmd_name} 执行失败: {e}", file=sys.stderr)
        return 1


def _show_help(cmds: dict):
    print("USAGE: tool <子命令> [参数]")
    print()
    print("子命令:")
    for name in sorted(cmds.keys()):
        cmd = cmds[name]
        desc = getattr(cmd, "help", "")
        print(f"  {name:20s}  {desc}")
    print()
    print("工具管理: tool registry list|add|remove")
    print("更多: tool <子命令> -h")
