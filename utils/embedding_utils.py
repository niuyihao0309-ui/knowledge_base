"""
文本向量化工具（2026-10-16 改造：本地 BGE-M3 → 阿里云百炼 text-embedding-v4 API）

改造原因：
    1. 本地 BGE-M3（flagembedding + torch）加载后常驻约 2.8G 内存，三项目共存时内存不够用；
    2. 百炼 text-embedding-v4 支持 output_type='dense&sparse'，一次调用同时返回
       稠密向量（dim 可设 1024）和稀疏向量 [{index, value, token}]，
       与本地 BGE-M3 的输出结构完全对齐，
       Milvus 的 dense_vector / sparse_vector 两个字段和 hybrid search 逻辑一行都不用改；
    3. 官方口径：dense&sparse 与只出 dense 同价（0.5 元/百万 token），不额外加钱。

对外契约（与改造前保持一致，调用方无需改动）：
    generate_embeddings(texts, text_type="document")
        -> {"dense": [[float, ...], ...], "sparse": [{词ID: 权重}, ...]}
    返回顺序与入参 texts 严格一一对应。
"""
import logging
import os
import time

from dotenv import load_dotenv

# 先加载 .env，再读取下面的环境变量（不依赖调用方的导入顺序）
load_dotenv(override=True)

import dashscope
from dashscope import TextEmbedding

from processor.import_processor.base import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
# 向量模型名。百炼同价可选 qwen3.7-text-embedding（稀疏向量效果 +8.4%，指令遵循 +16.4%）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4").strip().strip('"').strip("'")

# 向量维度。必须与 Milvus 集合 dense_vector 的 dim 一致（现网 1024）
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# API Key：优先用专用 key；为空则复用 rerank 在用的那个百炼 key（MCP_API_KEY）
EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY")
    or os.getenv("MCP_API_KEY")
    or os.getenv("OPENAI_API_KEY")
)
dashscope.api_key = EMBEDDING_API_KEY

# 单次请求最大文本条数。百炼 text-embedding-v4 / v3 上限 10 条；
# 若以后换成 qwen3.7-text-embedding，可调到 20
_MAX_BATCH = int(os.getenv("EMBEDDING_MAX_BATCH", "10"))

# 两次请求之间的最小间隔（秒）。默认 0 不限速；遇到 429 限流可调到 0.2~0.5
_MIN_INTERVAL = float(os.getenv("EMBEDDING_MIN_INTERVAL", "0"))

# 失败重试次数与退避基数（秒）。批量重导几千次请求，网络偶发抖动很正常，重试比整批失败划算
_MAX_RETRY = 3
_RETRY_BACKOFF = 1.0

# 上一次成功调用的时间戳，用于限流间隔计算
_last_call_ts = 0.0


def _call_api(texts, text_type):
    """
    调用一次百炼 embedding 接口（内部带限流间隔 + 指数退避重试）

    :param texts: 文本列表，长度不得超过 _MAX_BATCH
    :param text_type: "query" 检索词 / "document" 入库文本
    :return: dashscope 的响应对象（status_code == 200）
    :raises RuntimeError: 连续 _MAX_RETRY 次都失败
    """
    global _last_call_ts

    resp = None
    for attempt in range(1, _MAX_RETRY + 1):
        # 限流保护：与上次请求间隔不足 _MIN_INTERVAL 就先补个睡眠
        if _MIN_INTERVAL > 0:
            elapsed = time.time() - _last_call_ts
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)

        resp = TextEmbedding.call(
            model=EMBEDDING_MODEL,
            input=texts,
            dimension=EMBEDDING_DIM,
            output_type="dense&sparse",  # 关键：一次拿回稠密 + 稀疏，与只出稠密同价
            text_type=text_type,         # 非对称检索：查询词用 query，入库文本用 document
        )
        _last_call_ts = time.time()

        if resp.status_code == 200:
            return resp

        logger.warning(
            "Embedding 调用失败（第 %s/%s 次）: status=%s message=%s",
            attempt, _MAX_RETRY, resp.status_code, resp.message,
        )
        if attempt < _MAX_RETRY:
            time.sleep(_RETRY_BACKOFF * (2 ** (attempt - 1)))

    raise RuntimeError(
        f"Embedding API 连续 {_MAX_RETRY} 次调用失败: model={EMBEDDING_MODEL} "
        f"status={getattr(resp, 'status_code', None)} message={getattr(resp, 'message', None)}。"
        "请检查 EMBEDDING_API_KEY（或 MCP_API_KEY）是否具备百炼 text-embedding-v4 权限。"
    )


def generate_embeddings(texts, text_type="document"):
    """
    批量将文本转为 稠密向量 + 稀疏向量

    :param texts: 文本列表（传单个字符串会自动包成列表）
    :param text_type: "query" 用于检索词，"document" 用于入库文本
    :return: {
        "dense":  [[float, ...], ...],   # 与 texts 等长、等序，每条 EMBEDDING_DIM 维
        "sparse": [{词ID: 权重}, ...],     # 与 texts 等长、等序，直接可入 Milvus
    }
    """
    # 容错：允许调用方直接传裸字符串
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return {"dense": [], "sparse": []}

    dense_all, sparse_all = [], []

    # 按接口上限切批（调用方可能一次塞几百条）
    for start in range(0, len(texts), _MAX_BATCH):
        batch = texts[start:start + _MAX_BATCH]
        resp = _call_api(batch, text_type)

        # text_index 标记该结果对应本批次里的第几条，排序后保证与入参顺序严格一致
        items = sorted(resp.output["embeddings"], key=lambda item: item["text_index"])

        for item in items:
            dense_all.append(item["embedding"])
            # 百炼返回 [{"index": 7149, "value": 0.829, "token": "风"}, ...]
            # Milvus 的 SPARSE_FLOAT_VECTOR 要的是 {词ID: 权重}，这里做一次格式转换
            sparse_all.append(
                {int(p["index"]): float(p["value"]) for p in (item.get("sparse_embedding") or [])}
            )

    logger.debug(
        "向量化完成: %s 条, text_type=%s, model=%s, dim=%s",
        len(texts), text_type, EMBEDDING_MODEL, EMBEDDING_DIM,
    )
    return {"dense": dense_all, "sparse": sparse_all}


# ================= 单元测试主入口 =================
if __name__ == "__main__":
    # 中英文各一条，模拟跨语言召回
    test_data = ["大功率电磁炉", "Car"]

    print("👉 开始测试 generate_embeddings（百炼 API 版）...")
    print(f"👉 模型={EMBEDDING_MODEL} 维度={EMBEDDING_DIM} Key尾号={str(EMBEDDING_API_KEY)[-4:]}")
    print(f"👉 测试文本: {test_data}\n")

    try:
        output = generate_embeddings(test_data)

        print("\n" + "=" * 20 + " 🎉 测试结果 🎉 " + "=" * 20)

        print("【稠密向量 (Dense)】")
        print(f"   - 生成数量: {len(output['dense'])} 条")
        print(f"   - 第一条维度: {len(output['dense'][0])} 维（应为 {EMBEDDING_DIM}）")
        print(f"   - 前 5 维: {output['dense'][0][:5]} ...")

        print("\n【稀疏向量 (Sparse)】")
        print(f"   - 生成数量: {len(output['sparse'])} 条")
        print(f"   - 第一条关键词字典 (词ID : 权重) 前 5 项:")
        print(f"     {dict(list(output['sparse'][0].items())[:5])}")

        print("=" * 54)
        print("💡 结论：输出数据结构符合 Milvus 入库标准（dense 定长 + sparse 变长字典）。")

    except Exception as e:
        print(f"\n❌ 测试失败！拦截到异常: {e}")
        print("💡 排查建议：")
        print("   1. 确认 .env 里 MCP_API_KEY / EMBEDDING_API_KEY 是有效的百炼 key。")
        print("   2. 确认该 key 已开通 text-embedding-v4（百炼控制台 → 模型服务）。")
        print("   3. 确认 EMBEDDING_DIM 是 64/128/256/512/768/1024/1536/2048 之一。")
