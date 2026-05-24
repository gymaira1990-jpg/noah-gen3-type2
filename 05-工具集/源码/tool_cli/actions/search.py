"""
tool search — 统一搜索入口

通过注册表自动路由到可用的搜索引擎。
支持：taivly API / Edge CDP 真实浏览器 / 自建引擎

用法:
  tool search "关键词"                # 智能路由
  tool search "关键词" --engine baidu  # 指定引擎
  tool search "关键词" --json          # JSON 输出
"""
from core.base import Command
import sys, json, urllib.request, urllib.parse


def _is_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)


class SearchCommand(Command):
    name = "search"
    help = "统一搜索 — tool search <query> [--engine baidu|google|bing] [--json]"

    def run(self, args):
        args = self.parse_args(args)
        if not args:
            self.print_help()
            return 0

        query = args[0]
        engine = None
        i = 1
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = args[i + 1]
                i += 2
            else:
                i += 1

        # 通过注册表找搜索工具
        from core.registry import best_tool
        search_tool = best_tool("web_search")
        if not search_tool:
            print("❌ 无可用搜索工具。请注册一个搜索引擎。")
            print("   tool registry add my-search --type edge_cdp")
            return 1

        tool = search_tool["tool"]
        search_cmd = tool.get("actions", {}).get("search", "")
        if not search_cmd:
            print("❌ 工具的 actions.search 为空")
            return 1

        # 替换占位符
        import subprocess
        cmd = search_cmd.replace("{query}", query)
        if engine:
            cmd = cmd.replace("{engine}", engine)

        try:
            proc = subprocess.run(
                cmd.split(), capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                print(f"❌ 搜索失败: {proc.stderr[:100]}")
                return 1

            result = json.loads(proc.stdout)
            links = result.get("links", [])
            if self._output_mode == "json":
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"🔍 {query}  ({len(links)}条)")
                for i, l in enumerate(links[:10]):
                    title = l.get("title", l.get("url", "?"))[:70]
                    url = l.get("url", "")
                    print(f"  [{i+1}] {title}")
                    print(f"      {url}")
                    print()
            return 0
        except subprocess.TimeoutExpired:
            print(f"❌ 搜索超时 (30s)")
            return 1
        except Exception as e:
            print(f"❌ 搜索失败: {e}")
            return 1
