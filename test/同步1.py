# import time
#
# def download_file(name):
#     print(f"开始下载：{name}")
#     time.sleep(2)  # 模拟下载耗时 2 秒（整个程序卡住2秒，阻塞）
#     print(f"下载完成：{name}")
#
# download_file("文件 1")





# 异步
# import asyncio
#
# async def download_file(name):
#     print(f"开始下载：{name}")
#     await asyncio.sleep(2)  # 模拟下载耗时 2 秒（让出控制权2秒，非阻塞）
#     print(f"下载完成：{name}")
#
# asyncio.run(download_file("文件 1"))




# 并发下载 3 个文件
# test/fastapi/同步1.py

# import time
#
# def download_file(name):
#     print(f"开始下载：{name}")
#     time.sleep(2)  # 模拟下载耗时 2 秒
#     print(f"下载完成：{name}")
#
# # 逐个下载
# time_begin = time.time()
# download_file("文件 1")
# download_file("文件 2")
# download_file("文件 3")
# time_end = time.time()
#
# # 总耗时：6 秒（2+2+2） ---- 总耗时：6.002439260482788 秒
# print(f"总耗时：{time_end - time_begin} 秒")

# 异步方式：  任务同时进行 -- 一起开始、完成后打印
import asyncio
import time

async def download_file(name):
    print(f"开始下载：{name}")
    await asyncio.sleep(2)  # 模拟下载耗时 2 秒
    print(f"下载完成：{name}")

async def main():
    # 三个任务同时开始！
    await asyncio.gather(
        download_file("文件 1"),
        download_file("文件 2"),
        download_file("文件 3")
    )

time_begin = time.time()
asyncio.run(main())
time_end = time.time()

# 总耗时：约 2 秒（同时进行）
print(f"总耗时：{time_end - time_begin} 秒")


# 协程对象和运行协程：
import asyncio

# 1. 定义【异步函数】
async def my_task():
    await asyncio.sleep(1) #
    return "完成"

# 2. 调用异步函数时，返回的是【协程对象】
coroutine = my_task()  # 这是一个协程（还没执行）

# 3. 用 asyncio 来【运行协程】
asyncio.run(coroutine)  # 启动协程，得到结果








