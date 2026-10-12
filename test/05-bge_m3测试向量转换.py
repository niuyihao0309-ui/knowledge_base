# test/bge_m3测试向量转换.py
from utils.embedding_utils import get_bge_m3_ef

model = get_bge_m3_ef()
# BGE-M3 向量模型中最核心的方法
#它的核心作用是：将输入的文本列表（字符串数组）批量转化为大模型能够理解的向量（Embedding）数据 。  因为 BGE-M3 是一个混合检索
#模型，所以 encode_documents 非常强悍，它调用一次会同时吐出“稠密向量（Dense）”和“稀疏向量（Sparse）”两种结果 。
result = model.encode_documents(["测试","test"])


print(result)
# 数据结构：
# 稠密向量：这是一个包含两个 array 的列表。每个 array 长度为 1024，数据类型是 float16（半精度）。
# 稀疏向量：这是一个 Compressed Sparse Row sparse array（压缩稀疏行矩阵），形状是 (2, 250002)，250002 代表模型词汇表的大小（大约有 25 万个可能的词），2表示当前是2个词的向量