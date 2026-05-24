"""Base Command class — 所有子命令继承自此"""
import sys


class Command:
    name = ""
    help = ""
    _output_mode = "human"

    def run(self, args: list) -> int:
        raise NotImplementedError

    def parse_args(self, args: list):
        """统一参数解析: --json / -q / -h"""
        self._output_mode = "human"
        filtered = []
        for a in args:
            if a == "--json":
                self._output_mode = "json"
            elif a == "-q":
                self._output_mode = "quiet"
            elif a in ("-h", "--help"):
                self.print_help()
                sys.exit(0)
            else:
                filtered.append(a)
        return filtered

    def print_help(self):
        print(f"tool {self.name} [参数]")
        print()
        print(f"  {self.help}")
        print()
        print("参数:")
        print("  --json      JSON 输出")
        print("  -q          安静模式")
        print("  -h, --help  此帮助")

    def output(self, data):
        """统一输出"""
        from core.display import format_output
        print(format_output(data, mode=self._output_mode))
