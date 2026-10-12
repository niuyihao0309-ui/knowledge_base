# config/bailian_mcp_config.py

# 导入核心依赖：数据类、环境变量读取、路径处理
from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


# 定义mcp的服务配置
@dataclass
class McpConfig:
    mcp_base_url: str
    api_key : str

mcp_config = McpConfig(
    mcp_base_url=os.getenv("MCP_DASHSCOPE_BASE_URL"),
    # 【修复】只使用百炼 MCP 专用 key（MCP_API_KEY），不再回退 OPENAI_API_KEY。
    # 原因：本项目 OPENAI_API_BASE 指向硅基流动（https://api.siliconflow.cn/v1），
    # 拿硅基流动的 key 去请求 dashscope 的 MCP，只会得到一个同样是 401、
    # 但原因更难判断的报错，掩盖「MCP_API_KEY 未配置/已失效」这个真实问题。
    api_key=os.getenv("MCP_API_KEY")
)