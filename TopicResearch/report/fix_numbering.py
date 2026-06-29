"""
修复章节编号：将 1.1.6 资本市场 改为 1.1.7
"""
import os
from lxml import etree
from docx import Document

BASE_DIR = os.path.expanduser("~/llmwikify/TopicResearch/report")
V29_PATH = os.path.join(BASE_DIR, "复盘2005–2007年有色金属超级周期与当前AI板块投资的结构性比较 v2.9.docx")
OUT_PATH = os.path.join(BASE_DIR, "复盘2005–2007年有色金属超级周期与当前AI板块投资的结构性比较 v2.9.docx")

nsmap = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def get_element_text(elem):
    """获取元素的文本内容"""
    text = ''
    if elem.text:
        text += elem.text
    for child in elem:
        if child.text:
            text += child.text
        if child.tail:
            text += child.tail
    return text


def set_element_text(elem, new_text):
    """设置元素的文本内容"""
    # 清除所有 run
    for r in elem.findall(f'{{{nsmap["w"]}}}r'):
        elem.remove(r)
    
    # 创建新的 run
    r = etree.SubElement(elem, f'{{{nsmap["w"]}}}r')
    rPr = etree.SubElement(r, f'{{{nsmap["w"]}}}rPr')
    rFonts = etree.SubElement(rPr, f'{{{nsmap["w"]}}}rFonts')
    rFonts.set(f'{{{nsmap["w"]}}}ascii', '微软雅黑')
    rFonts.set(f'{{{nsmap["w"]}}}hAnsi', '微软雅黑')
    sz = etree.SubElement(rPr, f'{{{nsmap["w"]}}}sz')
    sz.set(f'{{{nsmap["w"]}}}val', '20')  # 10pt
    b = etree.SubElement(rPr, f'{{{nsmap["w"]}}}b')
    t = etree.SubElement(r, f'{{{nsmap["w"]}}}t')
    t.text = new_text
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def main():
    print("Loading v2.9 document...")
    doc = Document(V29_PATH)
    print(f"  段落数: {len(doc.paragraphs)}")
    
    body = doc.element.body
    
    # 找到所有需要重编号的段落
    renumber_map = {
        "1.1.6 资本市场：涨幅反映经济结构差异": "1.1.7 资本市场：涨幅反映经济结构差异",
    }
    
    changes = 0
    for i, elem in enumerate(body):
        if elem.tag == f'{{{nsmap["w"]}}}p':
            text = get_element_text(elem)
            for old, new in renumber_map.items():
                if old in text:
                    set_element_text(elem, new)
                    changes += 1
                    print(f"  [{i}] Renumbered: {old} → {new}")
    
    print(f"\nTotal changes: {changes}")
    
    # 保存
    print(f"Saving to {OUT_PATH}...")
    doc.save(OUT_PATH)
    
    print("✅ Done!")


if __name__ == "__main__":
    main()
