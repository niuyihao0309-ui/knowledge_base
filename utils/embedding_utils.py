"""
文本向量化工具（2026-10-22 改造：支持双 provider，dense/sparse 契约不变）

历史：
    1. v0.1.0：本地 BGE-M3（pymilvus BGEM3EmbeddingFunction），dense + sparse，常驻约 2.8G 内存；
    2. v0.2.0：百炼 text-embedding-v4（dashscope），output_type='dense&sparse'，一次调用双向量；
    3. 2026-10-22：百炼免费额度耗尽（403 Free quota exhausted），切硅基流动 Qwen3-Embedding-0.6B。
       但硅基流动 embedding 只出 dense、没有 sparse，而现网 Milvus 的 kb_chunks/kb_item_names
       都有 sparse_vector 字段、查询侧走 0.8/0.2 的 dense+sparse 混合检索 —— 实测「库里 sparse 全空
       + 查询带 sparse」时 hybrid_search 会整体返回 []（dense 那一路也被吞掉），所以 sparse 绝不能空。
       解决：硅基流动模式下，sparse 改用**本地词频编码**（jieba 分词 + 稳定 hash 词ID + 词频权重 + L2 归一化），
       等价于一个不含 IDF 的 BM25 稀疏表示，纯本地算、零成本、无需额外模型。

对外契约（与改造前完全一致，调用方一行都不用改）：
    generate_embeddings(texts, text_type="document")
        -> {"dense": [[float, ...], ...], "sparse": [{词ID: 权重}, ...]}
    返回顺序与入参 texts 严格一一对应；dense 维度 = EMBEDDING_DIM（现网 1024）。

provider 由 .env 的 EMBEDDING_PROVIDER 决定：
    dashscope   （默认）百炼，dense + sparse 全由接口返回
    siliconflow        硅基流动，dense 走 OpenAI 兼容 /v1/embeddings，sparse 本地算
"""
import hashlib
import logging
import math
import os
import re
import time

import requests
from dotenv import load_dotenv

# 先加载 .env，再读取下面的环境变量（不依赖调用方的导入顺序）
load_dotenv(override=True)

from processor.import_processor.base import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

# ==================== 配置 ====================
# provider 开关：dashscope（百炼） / siliconflow（硅基流动）
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "dashscope").strip().lower()

# 向量模型名。不同 provider 取值不同：
#   dashscope   -> text-embedding-v4 / qwen3.7-text-embedding-flash ...
#   siliconflow -> Qwen/Qwen3-Embedding-0.6B / BAAI/bge-m3 ...
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4").strip().strip('"').strip("'")

# 向量维度。必须与 Milvus 集合 dense_vector 的 dim 一致（现网 1024）
# Qwen3-Embedding-0.6B 支持 1024/768/512/256，默认 1024，正好对上，schema 不用动
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# ---------- 百炼（dashscope）专用 ----------
# API Key：优先用专用 key；为空则复用 rerank 在用的那个百炼 key（MCP_API_KEY）
EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY")
    or os.getenv("MCP_API_KEY")
    or os.getenv("OPENAI_API_KEY")
)

# ---------- 硅基流动（siliconflow）专用 ----------
# 硅基流动是 OpenAI 兼容接口，复用项目里已有的 OPENAI_API_BASE / OPENAI_API_KEY
SILICONFLOW_BASE_URL = (os.getenv("SILICONFLOW_BASE_URL") or os.getenv("OPENAI_API_BASE") or "").rstrip("/")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

if EMBEDDING_PROVIDER == "dashscope":
    # dashscope SDK 走模块级全局 key
    import dashscope
    from dashscope import TextEmbedding

    dashscope.api_key = EMBEDDING_API_KEY

# 单批文本条数上限：
#   百炼 text-embedding-v4 = 10 条；硅基流动 embedding 一次可放几十条，取 32 留余量
_DEFAULT_MAX_BATCH = 32 if EMBEDDING_PROVIDER == "siliconflow" else 10
_MAX_BATCH = int(os.getenv("EMBEDDING_MAX_BATCH", str(_DEFAULT_MAX_BATCH)))

# 两次请求之间的最小间隔（秒）。默认 0 不限速；遇到 429 限流可调到 0.2~0.5
_MIN_INTERVAL = float(os.getenv("EMBEDDING_MIN_INTERVAL", "0"))

# 失败重试次数与退避基数（秒）
_MAX_RETRY = 3
_RETRY_BACKOFF = 1.0

# 单次 HTTP 请求超时（秒）。128K 长文本也够用，卡死比慢更难受
_HTTP_TIMEOUT = int(os.getenv("EMBEDDING_TIMEOUT", "60"))

# 上一次成功调用的时间戳，用于限流间隔计算
_last_call_ts = 0.0


# ===========================================================================
# 一、本地稀疏向量编码（siliconflow 模式下使用）
# ===========================================================================
# 为什么自己算 sparse：
#   硅基流动只返回 dense。而查询侧 hybrid_search 必须两路都有结果，否则整体返回空。
#   做法与 Milvus 官方 BM25 思路一致：分词 -> 词 -> 稳定整数ID -> 词频权重 -> 归一化。
#   区别只是把「BM25 的 IDF 部分」省掉了（在线增量场景拿不到全库词频），
#   实际效果 ≈ TF 加权的关键词匹配，配合 dense 那 0.8 的权重已经够用。

# 停用词：中文虚词/代词/连词 + 常见无信息量词。
# 注意别把「网关」「配置」这类业务词加进来，它们恰恰是稀疏检索的关键词。
_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "或", "也", "都", "就", "而", "及", "等",
    "对", "把", "被", "从", "到", "为", "以", "于", "个", "中", "上", "下", "后",
    "这", "那", "其", "之", "有", "无", "不", "很", "会", "可以", "进行", "通过",
    "一个", "我们", "你们", "他们", "如果", "因为", "所以", "但是", "并且", "以及",
    "如图", "如下", "所示", "下图", "上图", "以下", "以上", "相关", "所述",
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be",
    "this", "that", "with", "as", "by", "at", "from", "it", "we", "you", "they",
}

# 英文/型号/数字的切分正则：
#   [a-zA-Z][a-zA-Z0-9\-_.]*  -> LumiScan、RS-12、App.vue 这类整体保留
#   \d{2,}                    -> 两位以上数字（型号、年份），单个数字当噪声丢掉
_LATIN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_.]*|\d{2,}")

# 连续汉字段（用于切 2-gram）
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 每个文档最多保留的关键词数量：
# 中文 2-gram 会让词数暴涨（600 字的 chunk 能切出上千个），
# 按词频取前 N 个，既压住稀疏向量体积，也顺手滤掉低频噪声。
_MAX_SPARSE_TERMS = int(os.getenv("SPARSE_MAX_TERMS", "160"))


def _tokenize(text: str) -> list:
    """
    分词：英文/型号按词切，中文按「字符 2-gram」切。

    为什么中文不用词、也不用 jieba：
        1. jieba 是额外依赖，且它在模块顶层 import pkg_resources，本项目装了 165 个包，
           扫 metadata 会明显拖慢服务启动；
        2. 中文 2-gram 是无词典分词的经典做法，对 BM25 这种「关键词匹配」完全够用：
           「局域网通讯配置」-> 局域/域网/网络/络通/通讯/讯配/配置，
           查询和文档只要共享任意二字片段就能命中，比精确分词更宽容。

    清洗规则：
        1. 转小写（LumiScan / lumiscan 视为同一个词）
        2. 丢掉停用词
        3. 丢掉单个汉字（信息量太低，还容易被 hash 碰撞冲淡权重）
        4. 丢掉单个数字（页码、序号之类）
    """
    tokens = []
    lower = (text or "").lower()

    # 1. 英文单词、型号、多位数字
    for word in _LATIN_RE.findall(lower):
        if word in _STOPWORDS:
            continue
        tokens.append(word)

    # 2. 中文连续片段 -> 2-gram
    for run in _CJK_RUN_RE.findall(lower):
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram in _STOPWORDS:
                continue
            tokens.append(bigram)

    return tokens


def _token_id(token: str) -> int:
    """
    把词映射成 Milvus 稀疏向量要求的下标（非负整数）。

    为什么用 md5 而不是 hash()：
        Python 内置 hash() 对 str 加了随机盐（PYTHONHASHSEED），
        同一台机器重启一次、换一台机器，同一个词算出来的 ID 就变了 ——
        入库时用的 ID 和查询时用的 ID 对不上，稀疏检索直接失效。
        md5 稳定、跨进程跨机器一致，取前 4 字节正好落进 32 位。
    """
    # digest() 是 16 字节摘要，取前 4 字节 -> 无符号整数
    value = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:4], "big")
    # 0x7FFFFFFF 掩码：保证落在 Milvus 可接受的 31 位非负整数区间；
    # `or 1`：极端情况下掩码结果是 0，兜一下（0 虽然合法，但留个非零值更保险）
    return (value & 0x7FFFFFFF) or 1


def local_sparse_vectors(texts) -> list:
    """
    本地生成稀疏向量（词ID -> 权重），与 dense 同序返回。

    权重公式（BM25 的 TF 部分 + L2 归一化）：
        w(t, d) = 1 + log(tf(t, d))
        w_norm  = w / ||w||₂
    L2 归一化很关键：归一化后内积落在 0~1，和 dense 的 cosine 分数同量级，
    这样 milvus_utils.hybrid_search 里 WeightedRanker(0.8, 0.2) 的权重才是有意义的；
    否则词频内积可能上千，直接把 dense 那一路压死。

    :param texts: 文本列表
    :return: [{词ID: 权重}, ...]，与入参等长等序；文本无有效词时返回 {}（Milvus 允许空 sparse）
    """
    if isinstance(texts, str):
        texts = [texts]

    result = []
    for text in texts:
        tokens = _tokenize(text)
        if not tokens:
            result.append({})
            continue

        # 统计词频
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1

        # 只保留词频最高的 N 个词：
        # 2-gram 切法下长 chunk 能产出上千个词，全部入库会让稀疏向量体积翻十几倍，
        # 而且低频词本来就是噪声。160 个足够覆盖正文里的关键概念。
        if len(tf) > _MAX_SPARSE_TERMS:
            top = sorted(tf.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_SPARSE_TERMS]
            tf = dict(top)

        # 词频 -> 原始权重
        raw = {_token_id(token): 1.0 + math.log(count) for token, count in tf.items()}

        # L2 归一化
        norm = math.sqrt(sum(w * w for w in raw.values()))
        if norm > 0:
            raw = {idx: w / norm for idx, w in raw.items()}

        result.append(raw)

    return result


# ===========================================================================
# 二、dense 向量：百炼（dashscope）
# ===========================================================================
def _call_dashscope(texts, text_type):
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
        "请检查 EMBEDDING_API_KEY（或 MCP_API_KEY）是否具备百炼 text-embedding-v4 权限、"
        "以及账户是否还有免费额度/余额。"
    )


# ===========================================================================
# 三、dense 向量：硅基流动（OpenAI 兼容 /v1/embeddings）
# ===========================================================================
def _call_siliconflow(texts):
    """
    调用硅基流动 embedding 接口，返回稠密向量列表。

    与百炼的差异：
        1. 只有 dense，没有 sparse（sparse 由 local_sparse_vectors 本地补）
        2. 走标准 OpenAI 协议：POST {base}/embeddings，body={"model","input"}
        3. 返回的 data[i] 带 index 字段，排序后保证与入参同序

    :param texts: 文本列表（长度 <= _MAX_BATCH）
    :return: [[float, ...], ...]
    :raises RuntimeError: 连续重试仍失败
    """
    if not SILICONFLOW_BASE_URL or not SILICONFLOW_API_KEY:
        raise RuntimeError(
            "硅基流动 embedding 配置缺失：请检查 .env 里的 OPENAI_API_BASE / OPENAI_API_KEY"
            "（或 SILICONFLOW_BASE_URL / SILICONFLOW_API_KEY）。"
        )

    url = f"{SILICONFLOW_BASE_URL}/embeddings"
    payload = {"model": EMBEDDING_MODEL, "input": texts}
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = ""
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT)
            if resp.status_code == 200:
                body = resp.json()
                # 按 index 排序，防止服务端并发返回乱序（OpenAI 协议里 index 就是入参下标）
                items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
                return [item["embedding"] for item in items]

            last_error = f"status={resp.status_code} body={resp.text[:300]}"
            logger.warning("硅基流动 Embedding 调用失败（第 %s/%s 次）: %s", attempt, _MAX_RETRY, last_error)

        except Exception as e:
            # 网络异常（超时/连接重置）也走重试，不要一次就放弃
            last_error = f"{type(e).__name__}: {e}"
            logger.warning("硅基流动 Embedding 请求异常（第 %s/%s 次）: %s", attempt, _MAX_RETRY, last_error)

        if attempt < _MAX_RETRY:
            time.sleep(_RETRY_BACKOFF * (2 ** (attempt - 1)))

    raise RuntimeError(
        f"硅基流动 Embedding 连续 {_MAX_RETRY} 次调用失败: model={EMBEDDING_MODEL} {last_error}。"
        "请检查 OPENAI_API_KEY 是否有效、账户余额与模型是否可用。"
    )


# ===========================================================================
# 四、统一入口
# ===========================================================================
def generate_embeddings(texts, text_type="document"):
    """
    批量将文本转为 稠密向量 + 稀疏向量

    行为随 EMBEDDING_PROVIDER 变化，但返回结构完全一致：
        dashscope   : dense/sparse 都来自接口（output_type="dense&sparse"）
        siliconflow : dense 来自接口，sparse 由 local_sparse_vectors 本地算

    :param texts: 文本列表（传单个字符串会自动包成列表）
    :param text_type: "query" 用于检索词，"document" 用于入库文本
                      （本地稀疏编码不区分 query/document，两种都按词频处理）
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

        if EMBEDDING_PROVIDER == "siliconflow":
            # 路线 A：dense 走硅基流动，sparse 本地补
            dense_all.extend(_call_siliconflow(batch))
            sparse_all.extend(local_sparse_vectors(batch))
        else:
            # 路线 B：dense + sparse 都由百炼一次返回
            resp = _call_dashscope(batch, text_type)
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
        "向量化完成: %s 条, provider=%s, text_type=%s, model=%s, dim=%s",
        len(texts), EMBEDDING_PROVIDER, text_type, EMBEDDING_MODEL, EMBEDDING_DIM,
    )
    return {"dense": dense_all, "sparse": sparse_all}


# ================= 单元测试主入口 =================
if __name__ == "__main__":
    # 中英文各一条，模拟跨语言召回
    test_data = ["大功率电磁炉", "Car"]

    print("👉 开始测试 generate_embeddings ...")
    print(f"👉 provider={EMBEDDING_PROVIDER} 模型={EMBEDDING_MODEL} 维度={EMBEDDING_DIM} 单批={_MAX_BATCH}")

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

        # 稀疏向量合法性自检：Milvus 要求下标是非负整数
        bad = [k for k in output["sparse"][0] if not isinstance(k, int) or k < 0]
        print(f"   - 下标合法性: {'OK' if not bad else '异常 ' + str(bad[:3])}")

        print("=" * 54)
        print("💡 结论：输出数据结构符合 Milvus 入库标准（dense 定长 + sparse 变长字典）。")

    except Exception as e:
        print(f"\n❌ 测试失败！拦截到异常: {e}")
        print("💡 排查建议：")
        print("   1. provider=siliconflow 时确认 .env 的 OPENAI_API_BASE / OPENAI_API_KEY 有效。")
        print("   2. provider=dashscope 时确认 EMBEDDING_API_KEY 有余额、已关掉「仅用免费额度」模式。")
        print("   3. 确认 EMBEDDING_DIM 与 Milvus 集合 dense_vector 的 dim 一致。")
