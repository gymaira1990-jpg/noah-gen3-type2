# 工具模块自动加载
from tools.registry import TOOL_REGISTRY, register, get_tool, list_tools
from tools.feet import http_request, ssh_remote, git_clone
from tools.toolbox import schedule_task, start_scheduler, get_system_info
