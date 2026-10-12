"""
导入功能的主流程图
"""
from langgraph.constants import END
from langgraph.graph import StateGraph
from processor.import_processor.nodes.node_bge_embedding import NodeBGEEmbedding
from processor.import_processor.nodes.node_document_split import NodeDocumentSplit
from processor.import_processor.nodes.node_entry import NodeEntry
from processor.import_processor.nodes.node_import_milvus import NodeImportMilvus
from processor.import_processor.nodes.node_item_name_recognition import NodeItemNameRecognition
from processor.import_processor.nodes.node_md_img import NodeMDImg
from processor.import_processor.nodes.node_pdf_to_md import NodePDFToMD
from processor.import_processor.state import ImportGraphState


class KBImportWorkflow:

    def __init__(self):
        """
        初始化工作流对象
        """
        self._compiled_graph = None
        print(self._compiled_graph)


    @property
    def graph(self):
        """
        延迟加载（懒加载）：只在第一次使用工作流对象的时候编译图
        :return:
        """

        if self._compiled_graph is None:
            self._compiled_graph = self.build_graph()
        return self._compiled_graph


    def build_graph(self):

        # 1.初始化图（工作流）
        graph = StateGraph (ImportGraphState)

        # 2.在图中注册节点
        graph.add_node("node_entry", NodeEntry())
        graph.add_node("node_pdf_to_md", NodePDFToMD())
        graph.add_node("node_md_img", NodeMDImg())
        graph.add_node("node_document_split", NodeDocumentSplit())
        graph.add_node("node_item_name_recognition", NodeItemNameRecognition())
        graph.add_node("node_bge_embedding", NodeBGEEmbedding())
        graph.add_node("node_import_milvus", NodeImportMilvus())

        # 3. 设置入口节点
        graph.set_entry_point("node_entry")
        # 4. 注册条件边
        graph.add_conditional_edges(
            "node_entry",
            self.route_after_entry,
            {
                "node_md_img": "node_md_img",
                "node_pdf_to_md": "node_pdf_to_md",
                END: END
            }
        )

        # 5.注册顺序边
        graph.add_edge("node_pdf_to_md", "node_md_img")
        graph.add_edge("node_md_img", "node_document_split")
        graph.add_edge("node_document_split", "node_item_name_recognition")
        graph.add_edge("node_item_name_recognition", "node_bge_embedding")
        graph.add_edge("node_bge_embedding", "node_import_milvus")
        graph.add_edge("node_import_milvus", END)

        # 6. 编译工作流
        return graph.compile()

    @staticmethod
    def route_after_entry(state: ImportGraphState) -> str:

        if state.get("is_pdf_read_enabled"):
            return "node_pdf_to_md"

        elif state.get("is_md_read_enabled"):
            return "node_md_img"

        else:
            return END

    # def run(self, state: ImportGraphState, stream: bool = False):
    #
    #     # 打印编译后的图结构
    #     self.graph.get_graph().print_ascii()
    #
    #     if stream:
    #         return self.graph.stream(state, stream_mode="values")
    #     else:
    #         return self.graph.invoke(state)

    # processor/import_processor/main_graph.py  替换原来的run方法

    def run(self, state: ImportGraphState, stream: bool = False):

        if stream:
            # return self.graph.stream(state, stream_mode="values")
            return self.graph.stream(state)
        else:
            return self.graph.invoke(state)

if __name__ == "__main__":
    from processor.import_processor.state import ImportGraphState


    init_state = {"import_file_path": "D:\ke_cheng\kengcheng-centos\kejian\cs\H3C LA2608室内无线网关 用户手册-6W100-整本手册.pdf",
                  "file_dir":r"D:\ke_cheng\kengcheng-centos\kejian\cs"}
    workflow = KBImportWorkflow()
    final_state = workflow.run(init_state)


    print(final_state)
