
# uv run uvicorn demo:app --reload --port 8001
# 启动程序

# 进入单个程序的网页
# 127.0.0.1:8001 + ""

# 进入客服端 - 可查看全部的程序
# http://127.0.0.1:8001/docs


# 1.3.1 测试1
from fastapi import FastAPI
from langgraph_sdk.schema import Item

# 创建一个 FastAPI 应用实例
app = FastAPI()

@app.get("/", summary="第一个测试")
async def read_root():
    return {"Hello": "World"}




# 访问 http://127.0.0.1:8000/items/5?q=somequery
# item_id: 路径参数 (自动转为 int)
# q: 查询参数 (可选，默认 None)
@app.get("/items/{item_id}", summary="获取指定参数")
async def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}


# 接收? skip=? & limit = ?
@app.get("/items", summary="分页")
async def read_item(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}






# Pydantic 数据模型
from pydantic import BaseModel, Field, ValidationError

# pydantic 能够帮你做的事情
class Student(BaseModel):
    name: str = Field(..., description="姓名")  # 必填
    age: int = Field(..., description="年龄")  # 必填
    score: float = Field(default=0.0, description="成绩")  # 选填，默认0.0


# 1. 正常创建
s1 = Student(name="张三", age=18, score=95.5)
print(s1)
# name='张三' age=18 score=95.5 email=None

# 2. 转成字典
print(s1.model_dump())
# {'name': '张三', 'age': 18, 'score': 95.5}

# 3. 转成 JSON 字符串
print(s1.model_dump_json())
# {"name":"张三","age":18,"score":95.5,"email":null}

# 4. 自动类型转换：字符串 "20" → int 20---------- 转换类型，年龄为str ，输出为 int
s2 = Student(name="李四", age="20")
print(s2.age, type(s2.age))  # 20  <class 'int'>

# 5. 类型校验失败：直接报错 ---------------------- 完全转换不了 - 会报错
try:
    Student(name="王五", age="不是数字")
except ValidationError as e:
    print(e)  # age - Input should be a valid integer

# 6. 缺少必填字段 ───
try:
    s4 = Student(age=18)  # 缺少必填的 name
except ValidationError as e:
    print(e)
    # name - Field required

# 7. 多余字段自动丢弃
s3 = Student(name="赵六", age=22, hobby="篮球")
print(s3.model_dump())
# {'name': '赵六', 'age': 22, 'score': 0.0}   ← hobby 被丢弃了

# 8. 从字典创建
data = {"name": "孙七", "age": 19, "score": 85, "email": "sun7@test.com"}
s6 = Student(**data)  # ** 解包字典，等价于 Student(name="孙七", age=19, ...)
print(s6)





# 1.3.3 测试3：类型检查和错误提示
from pydantic import BaseModel

# 定义数据模型
class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = None

# POST 请求接收 JSON 数据
@app.post("/items/", summary="类型检查")
async def create_item(item: Item):
    # item 已经是验证过的 Item 对象
    # 如果客户端传来的 price 是字符串 "abc"，FastAPI 会自动报错
    return {"name": item.name, "price": item.price, "is_offer": item.is_offer}






#### 1.3.4 测试4：响应JSON数据
##### 常见的响应形式
# 1、路由处理函数返回一个 Pydantic 模型实例，FastAPI 将自动将其转换为 JSON 格式，并作为响应发送给客户端：
@app.post("/items/return", summary="返回 Pydantic 模型实例")
async def create_item(item: Item):
    return item

#2、使用 HTTPException 抛出异常，返回自定义的状态码和详细信息。
#以下实例在 item_id 为 42 会返回 404 状态码：
from fastapi import HTTPException

@app.delete("/items/{item_id}", summary="抛出异常")
async def read_item(item_id: int):
    if item_id == 42:
        raise HTTPException(status_code=404, detail="Item 找不到")
    return {"item_id": item_id}






# JSONResponse（最常用） -- JSON格式输出
from fastapi.responses import JSONResponse

@app.get("/api/user")
async def get_user():
    # 等价于直接 return {"name": "张三", "age": 20}（FastAPI 自动转 JSONResponse）
    return JSONResponse(
        content={"name": "张三", "age": 20},
        status_code=200,  # 可选，默认 200
        headers={"X-Custom-Header": "custom-value"}  # 可选，自定义响应头
    )







# FileResponse（文件专用） --- 文件下载弹窗
from fastapi.responses import FileResponse

@app.get("/download/excel")
async def download_excel():
    excel_path = "D:/test.xls"
    # 返回文件并指定下载文件名
    return FileResponse(
        path=excel_path,
        filename="月度报表.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )






# HTMLResponse -- HTML网页
from fastapi.responses import HTMLResponse

@app.get("/hello")
async def hello(name: str = "游客"):
    html_content = f"""
    <html>
        <body>
            <h1>你好，{name}！</h1>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)







# PlainTextResponse -- 纯文本
from fastapi.responses import PlainTextResponse

@app.get("/text")
async def get_text():
    return PlainTextResponse(content="这是纯文本响应", status_code=200)







# RedirectResponse -- 旧转新
# test/fastapi/demo.py

from fastapi.responses import RedirectResponse

@app.get("/old-path")
async def redirect_old_path():
    # 重定向到 /new-path，状态码 307 表示临时重定向
    return RedirectResponse(url="/new-path", status_code=307)

@app.get("/new-path")
async def new_path():
    return {"message": "这是新接口"}







# StreamingResponse（流式响应）
# test/fastapi/demo.py

from fastapi.responses import StreamingResponse
import asyncio

async def generate_stream():
    # 模拟流式输出（逐字返回）
    words = ["你", "好", "，", "这", "是", "流", "式", "响", "应"]
    for word in words:
        await asyncio.sleep(0.5)
        yield word.encode("utf-8")  # 流式输出需返回字节流

@app.get("/stream")
async def stream_response():
    return StreamingResponse(generate_stream(), media_type="text/event-stream")













