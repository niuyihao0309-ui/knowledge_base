# 更新日志（CHANGELOG）

记录 `knowledge_base` 知识库系统的版本迭代。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)，
日期为本地时间（GMT+8）。每个版本对应仓库里的一个 Git tag，可用文末的对比链接查看逐行差异。

---

## [v0.2.0] - 2026-10-16

向量化引擎替换、服务端口迁移、启动脚本与门户页重做。**这一版起，整套系统可以「一键起来」。**

### 变更 Changed

- **向量化：本地 BGE-M3 → 阿里云百炼 `TextEmbedding`（`text-embedding-v4`）**
  - 输出 dense 1024 维 + sparse 稀疏向量，Milvus 侧同步调整。
  - 统一契约：`generate_embeddings(texts, text_type) -> {dense, sparse}`；入库传 `document`，查询传 `query`。
  - 单批上限 10 条，超出自动分批。
  - `EMBEDDING_API_KEY` 未配置时回退读取 `MCP_API_KEY`。
  - 影响：不再需要本地跑 embedding 模型，16GB 内存机器的压力明显下降，也不再依赖本地显卡/算力。
- **文档导入服务端口 8001 → 8005**（8001 已被问数后端占用）。
  端口涉及 6 处配置，已在启动脚本与页面注释里逐条列明，避免漏改导致「页面能开、上传 502」。

### 新增 Added

- `start_all.bat` 重写为真正的一键启动：Docker 数据服务 → 文档导入 API → 知识问答 API → 页面就绪校验 → 自动打开门户页。
  - 判断「服务是否已在运行」改为发**真实 HTTP 请求**，不再只看端口有没有被占用。
  - 端口被占但服务不响应时，打印占用进程的命令行并给出处理选项；若确认是本项目上次的残留进程，自动清理。
  - 每个服务启动后等待其真正可响应，结束时汇总「新起 / 复用 / 失败」。
  - 知识问答服务未就绪时，浏览器降级打开文档导入门户，不会开出一个白页。

### 修复 Fixed

- **导入链路中断（一）**：`kb_chunks.parent_title` 在 Milvus 集合中没有默认值，写入 chunk 时若未显式带上该字段会抛
  `DataNotMatchException`，导致整批导入失败。已在 `node_document_split._step_4_refine_chunks()` 中加兜底。
- **导入链路中断（二）**：`node_md_img.process()` 提前 return 时没有回写 `state["md_content"]`，
  后续节点取到空内容。已修。
- **门户页「点卡片跳到旧端口」**：根因是浏览器还原了旧的渲染快照（bfcache），既不改 DOM 也不发请求，
  仅靠禁用缓存头拦不住。三层防御：后端返回 HTML 时带 `Cache-Control: no-store`
  ＋ 启动脚本打开页面时在地址后挂随机参数 ＋ 页脚显示**配置指纹**（对不上就 Ctrl+F5）。
- 图片访问地址从内网 IP 改为 `localhost`；前端统一由 `chat.html` 的 `MINIO_ORIGIN` 一处出口控制，换地址只改这里。
- `docker/docker-compose.yml`：移除已不用的 Attu 服务；容器重建必须加 `--remove-orphans`，否则旧容器继续占用端口。

### 界面 Changed

- 门户页 `web/page/index.html` 按新版式重排：顶栏 → Hero → 核心能力卡片 → 页脚。
  保留原有三项工程能力 —— `PORTAL_CONFIG` 单一配置源、`resolveHref()` 端口判定、配置指纹；
  图标仍全部使用内联 SVG，页面零图片资源。

---

## [v0.1.0] - 2026-10-12

首个版本：把整套知识库 RAG 链路跑通并入库。

### 包含 Included

- **数据服务**（Docker Desktop / WSL2 编排，`docker/docker-compose.yml`）：
  Milvus v2.5 + etcd + MinIO（向量库与对象存储）＋ MongoDB（会话历史）。
- **文档导入服务** `web/api/import_service.py`：上传 PDF / Markdown → 解析 → 切分 → 图片抽取并上传 MinIO → 向量化入库。
  导入流程由多个节点串联，进度通过 `utils/task_utils.build_import_steps()` 输出。
- **知识问答服务** `web/api/query_service.py`：向量检索 → 重排（远程 `qwen3-rerank`）→ LLM 生成答案，会话历史落 MongoDB。
- **前端页面** `web/page/`（由两个后端直接托管，无独立前端工程）：
  统一入口门户 `index.html`、文档导入 `import.html`、知识问答 `chat.html`。
- 初始向量化方案：本地 BGE-M3 模型。

---

## 版本对照

| 版本 | 日期 | 一句话 |
| --- | --- | --- |
| [v0.2.0][v0.2.0] | 2026-10-16 | 百炼向量化 ＋ 端口迁移 ＋ 一键启动 ＋ 门户改版 |
| [v0.1.0][v0.1.0] | 2026-10-12 | 初始版：Milvus/Mongo ＋ 两条 API ＋ 三张页面 |

逐行差异（GitHub）：

- v0.1.0 → v0.2.0：<https://github.com/niuyihao0309-ui/knowledge_base/compare/v0.1.0...v0.2.0>

[v0.2.0]: https://github.com/niuyihao0309-ui/knowledge_base/releases/tag/v0.2.0
[v0.1.0]: https://github.com/niuyihao0309-ui/knowledge_base/releases/tag/v0.1.0
