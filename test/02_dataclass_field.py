from dataclasses import dataclass, field

@dataclass
# 自动帮我们补全 init方法 和 str方法；可以快速创建一个类
class User:
    # 1. 必需字段：没有默认值，创建实例时必须提供
    username: str
    # 2. 简单默认值：适用于不可变类型 (str, int, float等)
    age: int = 18
    # 3. 动态默认值：适用于可变类型 (list, dict等)，防止实例间共享状态
    tags: list = field(default_factory=list)
    # default_factory，每个实例都有自己独立的列表

# --- 开始测试 ---
print("--- 测试 1: 只提供必需字段 ---")
user1 = User("zhangsan")
print(f"user1: {user1}")    # 输出: user1: User(username='Alice', age=18, tags=[])

print("\n--- 测试 2: 提供所有字段 ---")
user2 = User("lisi", 25, ["developer", "pythonist"])
print(f"user2: {user2}")
# 输出: user2: User(username='Bob', age=25, tags=['developer', 'pythonist'])

print("\n--- 测试 3: 验证可变默认值的独立性 ---")
# 这是使用 field(default_factory=list) 的关键原因
user3 = User("wangwu")
user4 = User("zhaoliu")

# 修改 user3 的 tags 列表
user3.tags.append("new_tag")

print(f"user3.tags: {user3.tags}")
print(f"user4.tags: {user4.tags}")
# 如果这里使用的是 tags: list = []，那么 user4.tags 也会包含 'new_tag'
# 但因为使用了 default_factory，每个实例都有自己独立的列表
# 输出:
# user3.tags: ['new_tag']
# user4.tags: []



#不可变类型（如 `str`, `int`, `float`, `bool`, `tuple`）的静态默认值。
# name: str = "zhangsan"
# #等同于
# name: str = field(default="zhangsan")

#动态默认值 (`default_factory`)
#这是 `field()` 最重要的用途之一，专门用于处理**可变类型**（如 `list`, `dict`, `set`）的默认值
# items: list = field(default_factory=list)
