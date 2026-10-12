from typing import Dict, List
from .sse_utils import push_to_session

# ---------------------------
# 内存态任务追踪（单进程）
# ---------------------------
# key: task_id
# value: 节点名列表（原始英文/节点ID）
_tasks_running_list: Dict[str, List[str]] = {}
_tasks_done_list: Dict[str, List[str]] = {}

# key: task_id
# value: status 字符串（如 pending/processing/completed/failed）
_tasks_status: Dict[str, str] = {}

# key: task_id
# value: 任务结果（例如 query 的 answer）
_tasks_result: Dict[str, Dict[str, str]] = {}

# key: task_id
# value: 该任务的阶段计划（中文阶段名，按执行顺序）；用于前端算真实进度
_tasks_steps: Dict[str, List[str]] = {}


TASK_STATUS_PENDING = "pending"
TASK_STATUS_PROCESSING = "processing"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"

# 节点名 -> 中文名映射（用于前端展示）
# 说明：这里的 key 应与 LangGraph 的 add_node("xxx", ...) 中的节点名一致。
_NODE_NAME_TO_CN: Dict[str, str] = {
    "upload_file": "开始上传文件",  
    "node_entry": "检查文件",
    "node_pdf_to_md": "PDF转Markdown",
    "node_md_img": "Markdown图片处理",
    "node_item_name_recognition": "主体名称识别",
    "node_document_split": "文档切分",
    "node_bge_embedding": "向量生成",
    "node_import_kg": "导入知识图谱",
    "node_import_milvus": "导入向量库",
    "__end__": "处理完成",
    "END": "处理完成",
    # --- Query 流程节点（kb/query_process/main_graph.py）---
    "node_item_name_confirm": "确认问题产品",
    "node_answer_output": "生成答案",
    "node_rerank": "重排序",
    "node_rrf": "倒排融合",
    "node_web_search_mcp": "网络搜索",
    "node_search_embedding": "切片搜索",
    "node_search_embedding_hyde": "切片搜索(假设性文档)",
    "node_multi_search": "多路搜索",
    "node_query_kg": "查询知识图谱",
    "node_join": "多路搜索合并",
}


def _ensure_task(task_id: str) -> None:
    """确保 task_id 对应的数据结构已初始化。"""
    if task_id not in _tasks_running_list:
        _tasks_running_list[task_id] = []
    if task_id not in _tasks_done_list:
        _tasks_done_list[task_id] = []
    if task_id not in _tasks_result:
        _tasks_result[task_id] = {}


def _to_cn(node_name: str) -> str:
    """将节点名转换为中文展示名；若无映射则返回原名。"""
    return _NODE_NAME_TO_CN.get(node_name, node_name)


# ---------------------------------------------------------------------------
# 导入流程的「阶段计划」
# ---------------------------------------------------------------------------
# 作用：让前端知道"这次导入一共要跑几个阶段、顺序是什么"。
# 只有知道总数，前端才能算出真实的完成百分比，并把"已完成 / 进行中 / 未开始"
# 三段完整地画出来，而不是自己编一个进度。
#
# ⚠️ 顺序必须与 processor/import_processor/main_graph.py 里的
#    add_node / add_edge 保持一致：
#    node_entry → node_pdf_to_md → node_md_img → node_document_split
#      → node_item_name_recognition → node_bge_embedding → node_import_milvus
_IMPORT_STAGE_ORDER: List[str] = [
    "upload_file",                    # 由 import_service 在上传接口里记录，不在图里
    "node_entry",
    "node_pdf_to_md",                 # 仅 PDF 文件会走这一步
    "node_md_img",
    "node_document_split",
    "node_item_name_recognition",
    "node_bge_embedding",
    "node_import_milvus",
]


def build_import_steps(is_pdf: bool) -> List[str]:
    """
    生成"本次导入实际会执行的阶段"中文名列表（顺序 = 执行顺序）。

    :param is_pdf: 上传的是不是 PDF
    :return: 中文阶段名列表

    说明：Markdown 文件不进 node_pdf_to_md（见 main_graph.route_after_entry 的分支），
         所以这里必须把它从计划里剔掉——否则前端会永远显示一个不会完成的阶段。
    """
    node_ids = _IMPORT_STAGE_ORDER if is_pdf else [
        n for n in _IMPORT_STAGE_ORDER if n != "node_pdf_to_md"
    ]
    return [_to_cn(n) for n in node_ids]


def set_task_steps(task_id: str, steps: List[str]) -> None:
    """记录某个任务的阶段计划（由上传接口调用）。"""
    _tasks_steps[task_id] = list(steps)


def get_task_steps(task_id: str) -> List[str]:
    """读取某个任务的阶段计划；未设置过则返回空列表。"""
    return _tasks_steps.get(task_id, [])


def add_running_task(task_id: str, node_name: str, is_stream:bool = False) -> None:
    """
    添加“正在运行”的节点任务。

    参数：
    - task_id: 任务ID
    - node_name: 节点名称(节点ID)
    """
    _ensure_task(task_id)
    running = _tasks_running_list[task_id]
    # 避免重复追加
    if node_name not in running:
        running.append(node_name)

    if is_stream:
        task_push_queue(task_id)


def add_done_task(task_id: str, node_name: str, is_stream:bool = False) -> None:
    """
    添加“已完成”的节点任务。

    注意：添加已完成任务时，会把同名的“正在运行”任务删除。

    参数：
    - task_id: 任务ID
    - node_name: 节点名称(节点ID)
    """
    _ensure_task(task_id)

    # 1) 从 running 中移除同名节点（可能出现重复，移除所有）
    running = _tasks_running_list[task_id]
    _tasks_running_list[task_id] = [n for n in running if n != node_name]

    # 2) 追加到 done（保持完成顺序），避免重复
    done = _tasks_done_list[task_id]
    if node_name not in done:
        done.append(node_name)

    if is_stream:
        task_push_queue(task_id)





def set_task_result(task_id: str, key: str, value: str) -> None:
    """
    存储任务结果字段（如 answer / error）。
    """
    _ensure_task(task_id)
    _tasks_result[task_id][key] = value


def get_task_result(task_id: str, key: str, default: str = "") -> str:
    """
    获取任务结果字段（如 answer / error）。
    """
    _ensure_task(task_id)
    return _tasks_result.get(task_id, {}).get(key, default)


def get_task_status(task_id: str ) -> str:
    """
    获取当前任务状态。

    参数：
    - task_id: 任务ID

    返回：
    - str: 状态名称；如果未设置过则返回空字符串
    """
    return _tasks_status.get(task_id, "")



def get_done_task_list(task_id: str) -> List[str]:
    """
    获取已完成节点列表（中文展示）。

 
    """
    _ensure_task(task_id)
    done = _tasks_done_list.get(task_id, [])
    return [ _to_cn(n)  for n in done]


def get_running_task_list(task_id: str) -> List[str]:
    """
    获取正在运行节点列表（中文展示）。
 
    """
    _ensure_task(task_id)
    running = _tasks_running_list.get(task_id, [])
    return [ _to_cn(n)  for n in running]



def update_task_status(task_id: str, status_name: str, push_queue:bool = False) -> None:
    """
    更新任务状态。

    参数：
    - task_id: 任务ID
    - status_name: 状态名称（字符串）
    """
    _tasks_status[task_id] = status_name
    if push_queue:
        task_push_queue(task_id)

def task_push_queue(task_id: str):
    push_to_session(task_id, "progress", {
        "status": get_task_status(task_id),
        "done_list": get_done_task_list(task_id),
        "running_list": get_running_task_list(task_id),
    })
#
def clear_progress(task_id: str) -> None:
    """
    清空指定任务的进度列表（running / done），但保留 status 与 result。

    用途：每轮查询开始时重置进度。进度列表是按 session_id 维度、在内存中
    长期保留的，若不重置，同一会话的多轮提问会把上一轮的节点累积进来，
    导致前端进度出现重复项、顺序错乱。

    参数：
    - task_id: 任务ID（查询流程中即 session_id）
    """
    _tasks_running_list.pop(task_id, None)
    _tasks_done_list.pop(task_id, None)


def clear_task(task_id: str):
    _tasks_running_list.pop(task_id, None)
    _tasks_done_list.pop(task_id, None)
    _tasks_status.pop(task_id, None)
    _tasks_result.pop(task_id, None)
    _tasks_steps.pop(task_id, None)