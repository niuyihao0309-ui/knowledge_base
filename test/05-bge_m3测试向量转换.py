# test/05-bge_m3测试向量转换.py
# 2026-10-16 更新：向量化已从本地 BGE-M3 改为阿里云百炼 text-embedding-v4 API，
# 原来的 get_bge_m3_ef() 已下线，统一走 utils/embedding_utils.py 的 generate_embeddings()
from utils.embedding_utils import EMBEDDING_DIM, EMBEDDING_MODEL, generate_embeddings

# 一次调用同时返回稠密 + 稀疏两种向量，结构等价于原 BGE-M3 的 encode_documents
result = generate_embeddings(["测试", "test"])

dense = result["dense"]    # 定长稠密向量：[[float x EMBEDDING_DIM], ...]
sparse = result["sparse"]  # 变长稀疏向量：[{词ID: 权重}, ...]

print(f"模型: {EMBEDDING_MODEL}   维度: {EMBEDDING_DIM}")
print(f"稠密向量条数: {len(dense)}，第一条长度: {len(dense[0])}")
print(f"稀疏向量条数: {len(sparse)}，第一条词条数: {len(sparse[0])}")
print("稀疏向量示例（前 5 项 词ID:权重）:", dict(list(sparse[0].items())[:5]))

# 数据结构说明：
# 稠密向量 list[list[float]]，每条 EMBEDDING_DIM 维  → 入 Milvus dense_vector  (FLOAT_VECTOR)
# 稀疏向量 list[dict[int, float]]，键=词表ID、值=权重 → 入 Milvus sparse_vector (SPARSE_FLOAT_VECTOR)
