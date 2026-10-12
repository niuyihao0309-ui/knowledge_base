##### 单例模式 `get_config()`
# - 避免重复创建配置对象
# - 全局共享同一份配置
# 单例模式：确保我们整个程序运行过程中，只有一个对象，无论你实例化多少次，调用多少次
# 都是同一个对象，通常单例模式用于设计，我们要全局访问的内容
"""
单例模式 (Singleton Pattern) 介绍：
确保一个类在整个程序运行期间“有且仅有一个实例”，并提供一个全局访问点。
在 Python 中，通过【全局变量 + 检查实例化状态】可以最直接地实现单例，
既避免了重复创建对象造成的资源浪费，又保证了全局数据的状态一致性。
"""

from dataclasses import dataclass, field
from typing import Optional
import datetime


@dataclass
class SimpleLogger:
    """日志记录器类"""
    # 简单默认值
    log_level: str = "INFO"

    # 动态默认值：每次实例化时动态获取当前时间
    init_time: str = field(
        default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def log(self, message: str):
        print(f"[{self.init_time}] [{self.log_level}] {message}")


# ==================== 单例核心实现 ====================
# 1. 定义一个私有的全局变量，初始为 None，用来存放唯一的实例
_logger_instance: Optional[SimpleLogger] = None


def get_logger() -> SimpleLogger:
    """
    获取日志记录器的单例对象。
    与 config_base.py 中的 get_config() 逻辑完全一致。
    """
    global _logger_instance

    # 2. 只有在第一次调用时，才会真正创建对象（懒加载）
    if _logger_instance is None:
        _logger_instance = SimpleLogger()

    # 3. 后续调用直接返回已经创建好的唯一对象
    return _logger_instance


# ==================== 验证测试 ====================
if __name__ == "__main__":
    print("--- 第一次获取 Logger ---")
    logger1 = get_logger()
    logger1.log("这是第一条日志。")

    # 故意延迟一下，验证 init_time 是否会变
    import time

    time.sleep(1)

    print("\n--- 第二次获取 Logger ---")
    logger2 = get_logger()
    logger2.log("这是第二条日志。")

    print("\n--- 验证唯一性 ---")
    # 检查两个变量指向的是否是内存中的同一个对象
    is_same = logger1 is logger2
    print(f"logger1 和 logger2 是同一个实例吗？ {is_same}")
    # 输出: True













