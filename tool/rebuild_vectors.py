"""
向量全库重建脚本（换 embedding 模型 / 换 provider 后必须跑一次）

背景：
    稠密向量是「特定模型」的产物，换了模型（比如 text-embedding-v4 -> Qwen3-Embedding-0.6B）
    之后新旧向量不在同一个向量空间里，混在一起检索会明显掉准。所以换模型 = 全库重算。

做法：
    不重跑 PDF 解析（那要 MinerU + 图片理解，几十个文档跑一晚上），
    而是把库里已有的 chunk 正文读出来，用新模型重新算 dense/sparse，再写回去。
    chunk 的正文/标题/商品名这些元数据原样保留，只有两个向量字段是新的。

安全设计：
    1. 删数据前先把全量数据导出成 JSON 备份（默认落在 DATA_BASED_ROOT_DIR 下）；
    2. 支持 --from-backup 从备份 JSON 恢复，脚本可重入（中途挂了重跑即可）。

用法：
    全流程重建：
        PYTHONPATH=. .venv/Scripts/python.exe -m tool.rebuild_vectors
    只备份不重建：
        PYTHONPATH=. .venv/Scripts/python.exe -m tool.rebuild_vectors --backup-only
    从备份 JSON 重建（Milvus 里数据已删或想反复重算）：
        PYTHONPATH=. .venv/Scripts/python.exe -m tool.rebuild_vectors --from-backup <json路径>
"""
import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from pymilvus import MilvusClient

from config.milvus_config import milvus_config
from utils.embedding_utils import generate_embeddings, EMBEDDING_MODEL, EMBEDDING_PROVIDER

# 写库批大小：比 embedding 单批（32）小一点，避免单次 insert 报文过大
_INSERT_BATCH = 20

# chunk 集合要保留的业务字段（向量字段由脚本重算，不导出）
_CHUNK_FIELDS = ["chunk_id", "content", "title", "parent_title", "part", "file_title", "item_name"]
_ITEM_FIELDS = ["pk", "file_title", "item_name"]


def _backup_dir() -> Path:
    """备份目录：优先用 .env 的 DATA_BASED_ROOT_DIR，退化到当前工作目录。"""
    root = os.getenv("DATA_BASED_ROOT_DIR") or "."
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_collection(client: MilvusClient, name: str, fields: list, pk_field: str) -> list:
    """
    把集合里的业务字段全量导出为 JSON 备份，并把行数据返回给调用方。

    :param client: Milvus 客户端
    :param name: 集合名
    :param fields: 要导出的字段
    :param pk_field: 主键字段名（query 需要一个恒真过滤条件）
    :return: 行数据列表（备份文件路径在日志里打印）
    """
    client.load_collection(name)
    # limit 给到 16384（Milvus 单次 query 的默认上限），当前库只有几百条，一次拿完
    rows = client.query(collection_name=name, filter=f"{pk_field} >= 0", output_fields=fields, limit=16384)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _backup_dir() / f"_vector_backup_{name}_{stamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"[备份] {name}: {len(rows)} 条 -> {path}")
    return rows


def load_backup(path: str) -> list:
    """读取备份 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"[载入] {path}: {len(rows)} 条")
    return rows


def rebuild_chunks(client: MilvusClient, rows: list) -> int:
    """
    重算 chunk 的 dense/sparse 并写回 kb_chunks。

    向量化文本与导入时保持一致："{item_name}\n{content}"（见 node_bge_embedding），
    这样新库和查询侧的口径完全一致，不会出现「入库用 A 格式、检索用 B 格式」的偏差。

    :return: 写入条数
    """
    name = milvus_config.chunks_collection

    # 1. 先删干净（auto_id 主键无法 upsert 覆盖，只能删了重插）
    print(f"[重建] {name}: 删除旧数据 ...")
    client.delete(collection_name=name, filter="chunk_id >= 0")
    client.flush(name)

    # 2. 分批算向量 + 插入
    written = 0
    total = len(rows)
    for start in range(0, total, _INSERT_BATCH):
        batch = rows[start:start + _INSERT_BATCH]
        texts = [f"{(r.get('item_name') or r.get('file_title') or '')}\n{r.get('content') or ''}" for r in batch]
        vectors = generate_embeddings(texts, text_type="document")

        records = []
        for i, row in enumerate(batch):
            records.append({
                "content": row.get("content") or "",
                "title": (row.get("title") or "")[:100],
                "parent_title": (row.get("parent_title") or "")[:100],
                "part": int(row.get("part") or 0),
                "file_title": (row.get("file_title") or "")[:100],
                "item_name": (row.get("item_name") or "")[:100],
                "dense_vector": vectors["dense"][i],
                "sparse_vector": vectors["sparse"][i],
            })

        client.insert(collection_name=name, data=records)
        written += len(records)
        print(f"  进度 {written}/{total}")

    client.flush(name)
    return written


def rebuild_item_names(client: MilvusClient, rows: list) -> int:
    """重算商品名向量并写回 kb_item_names（文本就是 item_name 本身）。"""
    name = milvus_config.item_name_collection

    print(f"[重建] {name}: 删除旧数据 ...")
    client.delete(collection_name=name, filter="pk >= 0")
    client.flush(name)

    written = 0
    total = len(rows)
    for start in range(0, total, _INSERT_BATCH):
        batch = rows[start:start + _INSERT_BATCH]
        texts = [r.get("item_name") or "" for r in batch]
        vectors = generate_embeddings(texts, text_type="document")

        records = []
        for i, row in enumerate(batch):
            records.append({
                "file_title": (row.get("file_title") or "")[:100],
                "item_name": (row.get("item_name") or "")[:100],
                "dense_vector": vectors["dense"][i],
                "sparse_vector": vectors["sparse"][i],
            })
        client.insert(collection_name=name, data=records)
        written += len(records)
        print(f"  进度 {written}/{total}")

    client.flush(name)
    return written


def count_rows(client: MilvusClient, name: str, pk_field: str) -> int:
    """统计集合行数（flush 之后才准）。"""
    client.load_collection(name)
    res = client.query(collection_name=name, filter=f"{pk_field} >= 0", output_fields=["count(*)"])
    return int(res[0]["count(*)"])


def main():
    parser = argparse.ArgumentParser(description="向量全库重建")
    parser.add_argument("--backup-only", action="store_true", help="只导出备份，不改库")
    parser.add_argument("--from-backup", type=str, default="", help="从备份 JSON 重建（chunk 备份路径）")
    parser.add_argument("--skip-items", action="store_true", help="跳过 kb_item_names（只重建 chunk）")
    args = parser.parse_args()

    print(f"provider={EMBEDDING_PROVIDER} model={EMBEDDING_MODEL}")
    client = MilvusClient(milvus_config.milvus_url)
    chunks_name = milvus_config.chunks_collection
    items_name = milvus_config.item_name_collection

    # ---------- 1. 拿到源数据 ----------
    if args.from_backup:
        chunk_rows = load_backup(args.from_backup)
        # 商品名集合从 chunk 里按 (file_title,item_name) 去重推导，避免还要找第二个备份
        seen, item_rows = set(), []
        for row in chunk_rows:
            key = (row.get("file_title"), row.get("item_name"))
            if key[1] and key not in seen:
                seen.add(key)
                item_rows.append({"file_title": key[0], "item_name": key[1]})
    else:
        chunk_rows = dump_collection(client, chunks_name, _CHUNK_FIELDS, "chunk_id")
        item_rows = [] if args.skip_items else dump_collection(client, items_name, _ITEM_FIELDS, "pk")

    if args.backup_only:
        print("只备份，不改库。结束。")
        return

    # ---------- 2. 重建 ----------
    t0 = time.time()
    n_chunks = rebuild_chunks(client, chunk_rows)
    n_items = 0 if args.skip_items else rebuild_item_names(client, item_rows)

    # ---------- 3. 校验 ----------
    time.sleep(1)
    actual_chunks = count_rows(client, chunks_name, "chunk_id")
    actual_items = 0 if args.skip_items else count_rows(client, items_name, "pk")

    print("\n================ 重建结果 ================")
    print(f"kb_chunks     : 写入 {n_chunks} / 库内 {actual_chunks}  {'OK' if n_chunks == actual_chunks else '⚠️ 不一致'}")
    if not args.skip_items:
        print(f"kb_item_names : 写入 {n_items} / 库内 {actual_items}  {'OK' if n_items == actual_items else '⚠️ 不一致'}")
    print(f"耗时 {time.time() - t0:.1f}s，模型 {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()
