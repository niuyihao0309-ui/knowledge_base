import json
import logging
from pathlib import Path
from processor.import_processor.base import BaseNode, setup_logging
from processor.import_processor.exceptions import StateFieldError, FileProcessingError, ValidationError
from processor.import_processor.state import ImportGraphState


class NodeEntry(BaseNode):
    """
    入口节点：任务分发
     1. 从 state（状态）中获取文件的绝对路径
     2. 判断路径是否为空
     3. 将文件路径变为文件对象（Path）
     4. 判断文件类型（".pdf" / ".md")
     5. 获取文件名 - 将文件名转变为标题
     if __name__ == "__main__":
     # 打印日志 -- 打印结果
     # 初始化图的状态 -- 传入文件的路径
     # 创建节点对象
     # 执行节点的单元测试

    """
    name = "node_entry"

    def process(self, state: ImportGraphState):
        # 1. 从 state 中获取文件的绝对路径
        import_file_path = state.get("import_file_path")
        # 判断路径是否为空 --- 调高代码的鲁棒性
        if not import_file_path:
            raise StateFieldError(
                field_name="import_file_path",
                message="文件路径不能为空",
                expected_type=str
            )
        # 2. 将 import_file_path 转换为Path对象
        import_file_path_obj = Path(import_file_path)
        if not import_file_path_obj.exists():
            raise FileProcessingError(
                message=f"文件{import_file_path_obj.name}不存在",
            )

        # 3. 判断文件类型
        if import_file_path_obj.suffix == ".pdf":
            state["is_pdf_read_enabled"] = True     # is_pdf_read_enabled：是否为 PDF 文件
            state["pdf_path"] = import_file_path
        elif import_file_path_obj.suffix == ".md":
            state["is_md_read_enabled"] = True
            state["md_path"] = import_file_path
        else:
            raise ValidationError(
                message=f"不支持的文件类型{import_file_path_obj.suffix}"
            )

        # 4. 获取文件名作为标题
        state["file_title"] = import_file_path_obj.stem

        return state


if __name__ == "__main__":
    # 激活日志   --- 打印
    setup_logging()

    # 初始化图状态
    init_state = {
        "import_file_path": r"D:\ke_cheng\kengcheng-centos\kejian\cs\H3C LA2608室内无线网关 用户手册-6W100-整本手册.pdf"
    }

    # 创建节点对象
    node_entry = NodeEntry()
    # 执行节点的单元测试
    result = node_entry(init_state)
    # 将返回的图状态进行json序列化
    json_state = json.dumps(result, ensure_ascii=False, indent=4)
    # 输出
    logging.getLogger().info(json_state)









