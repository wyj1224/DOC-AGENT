from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase.ttfonts import TTFont


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT_DIR / "通信工程设计说明强制性条文引用一致性校核第一阶段报告.pdf"

CN_FONT = "STHeiti"
pdfmetrics.registerFont(TTFont(CN_FONT, "/System/Library/Fonts/STHeiti Medium.ttc"))


def make_styles():
    base = getSampleStyleSheet()
    styles = {}
    styles["Title"] = ParagraphStyle(
        "CNTitle",
        parent=base["Title"],
        fontName=CN_FONT,
        fontSize=22,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1F3A5F"),
        spaceAfter=18,
    )
    styles["Subtitle"] = ParagraphStyle(
        "CNSubtitle",
        parent=base["Normal"],
        fontName=CN_FONT,
        fontSize=11,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#52657A"),
        spaceAfter=8,
    )
    styles["H1"] = ParagraphStyle(
        "CNH1",
        parent=base["Heading1"],
        fontName=CN_FONT,
        fontSize=16,
        leading=22,
        textColor=colors.HexColor("#1F3A5F"),
        spaceBefore=14,
        spaceAfter=8,
    )
    styles["H2"] = ParagraphStyle(
        "CNH2",
        parent=base["Heading2"],
        fontName=CN_FONT,
        fontSize=12.5,
        leading=18,
        textColor=colors.HexColor("#24527A"),
        spaceBefore=10,
        spaceAfter=6,
    )
    styles["Body"] = ParagraphStyle(
        "CNBody",
        parent=base["BodyText"],
        fontName=CN_FONT,
        fontSize=9.6,
        leading=15,
        firstLineIndent=18,
        spaceAfter=5,
    )
    styles["Small"] = ParagraphStyle(
        "CNSmall",
        parent=base["BodyText"],
        fontName=CN_FONT,
        fontSize=8.4,
        leading=12,
        spaceAfter=3,
    )
    styles["Cell"] = ParagraphStyle(
        "CNCell",
        parent=base["BodyText"],
        fontName=CN_FONT,
        fontSize=8.2,
        leading=11.5,
        spaceAfter=0,
    )
    styles["CellSmall"] = ParagraphStyle(
        "CNCellSmall",
        parent=base["BodyText"],
        fontName=CN_FONT,
        fontSize=7.5,
        leading=10.2,
        spaceAfter=0,
    )
    styles["Code"] = ParagraphStyle(
        "CNCode",
        parent=base["Code"],
        fontName=CN_FONT,
        fontSize=7.8,
        leading=10.5,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=6,
        backColor=colors.HexColor("#F5F7FA"),
    )
    styles["Callout"] = ParagraphStyle(
        "CNCallout",
        parent=base["BodyText"],
        fontName=CN_FONT,
        fontSize=9.3,
        leading=14,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=4,
        spaceAfter=4,
        textColor=colors.HexColor("#27384A"),
    )
    return styles


STYLES = make_styles()


def p(text: str, style: str = "Body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def bullet(text: str) -> Paragraph:
    return Paragraph("• " + text, STYLES["Body"])


def cell(text: str, small: bool = False) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), STYLES["CellSmall" if small else "Cell"])


def table(data, widths, header=True, small=False):
    converted = []
    for row in data:
        converted.append([cell(str(item), small=small) for item in row])
    t = LongTable(converted, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7DEE8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFD")]),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBFA")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#9AB7D5")),
            ]
        )
    t.setStyle(TableStyle(style))
    return t


def callout(title: str, body: str):
    t = Table(
        [[p(f"<b>{title}</b><br/>{body}", "Callout")]],
        colWidths=[16.2 * cm],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FB")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#AFC4DC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(CN_FONT, 8)
    canvas.setFillColor(colors.HexColor("#6D7F91"))
    canvas.drawString(2 * cm, 1.05 * cm, "通信工程设计说明强制性条文引用一致性校核 - 第一阶段报告")
    canvas.drawRightString(19 * cm, 1.05 * cm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_story():
    story = []
    story.append(Spacer(1, 2.4 * cm))
    story.append(p("通信工程设计说明强制性条文引用一致性校核", "Title"))
    story.append(p("第一阶段技术报告", "Title"))
    story.append(Spacer(1, 0.5 * cm))
    story.append(p("报告日期：2026-07-08", "Subtitle"))
    story.append(p("范围：Word 解析、引用记录抽取、设计依据与标准库校核、正文与设计依据校核、测试集验证与问题修复闭环", "Subtitle"))
    story.append(Spacer(1, 1.0 * cm))
    story.append(
        callout(
            "阶段结论",
            "第一阶段已经形成从 Word 设计说明上传、段落/表格解析、标准引用抽取、设计依据与标准库比对、正文与 1.2 设计依据比对、问题分类输出的闭环。核心判断尽量采用结构化规则和数据库精确匹配，大模型只作为后续解释与报告生成补充，不作为第一阶段一致性判断的唯一依据。",
        )
    )
    story.append(PageBreak())

    story.append(p("1. 项目定位与第一阶段目标", "H1"))
    story.append(
        p(
            "本项目面向通信工程设计说明中的强制性条文和标准引用校核。第一阶段重点解决“引用是否存在明显一致性问题”，包括设计依据与标准库是否一致、正文引用是否与 1.2 设计依据一致、是否仍引用旧标准或废止标准等。"
        )
    )
    story.append(
        p(
            "第一阶段不是替代设计人员判断工程方案，也不完全覆盖项目适用性、强条正文语义一致性和遗漏强条识别；这些内容更适合作为第二阶段、第三阶段继续扩展。"
        )
    )
    story.append(
        table(
            [
                ["模块", "第一阶段完成内容", "主要产物"],
                ["标准知识库", "读取强条表与清单表，形成强条库和标准有效性库", "强制性条文表、标准有效性表"],
                ["Word 解析", "读取 docx 段落、标题路径和表格文本，生成文本块", "Word 文档表、章节表"],
                ["引用记录抽取", "抽取标准号、标准名称、文件号、条号、上下文", "标准引用记录表"],
                ["一致性校核", "设计依据与标准库校核、正文与设计依据校核，输出风险等级、原因和建议", "问题记录表"],
                ["前端展示", "问题列表、分类页签、中文化问题类型与严重等级", "Word 校核工作台"],
            ],
            [3.0 * cm, 8.0 * cm, 5.2 * cm],
        )
    )

    story.append(p("2. 总体工作流", "H1"))
    story.append(p("系统采用“结构化知识库 + 确定性规则校核”的主线。Excel 文件先离线入库，Word 每次上传后解析成引用记录，再由校核模块读取数据库记录生成问题。"))
    story.append(
        p(
            "Excel 文件 → 标准知识入库 → 强制性条文表 / 标准有效性表\n"
            "Word 文档 → 文档解析 → 文本块 → 引用记录抽取 → 标准引用记录表\n"
            "标准引用记录 + 标准知识库 → 一致性校核 → 问题记录表 → 前端问题列表",
            "Code",
        )
    )
    story.append(
        table(
            [
                ["入口", "关键函数/文件", "作用"],
                ["POST /excel/ingest", "backend/app/main.py -> ingest_excel_to_postgres", "保存 Excel 文件，解析强条与新旧标准关系，写入数据库"],
                ["POST /word/upload", "parse_word_tool -> parse_docx_file -> extract_references", "保存 Word 文档，解析章节、段落、表格并抽取引用"],
                ["POST /word/check", "word_check_tool -> check_word_document", "按请求执行设计依据与标准库校核、正文与设计依据校核或全部校核"],
                ["GET /word/issues", "get_issues_tool", "按文档、范围、类型、严重等级查询问题"],
            ],
            [3.2 * cm, 6.2 * cm, 6.8 * cm],
        )
    )

    story.append(p("3. Word 解析过程", "H1"))
    story.append(p("Word 解析位于 backend/app/word_loader.py，使用 python-docx 本地读取 docx，不依赖外部解析额度。解析过程分为三层：标题路径、正文段落、表格文本。"))
    story.append(
        table(
            [
                ["步骤", "处理逻辑", "输出字段"],
                ["识别标题", "读取段落 style，支持 Heading 与中文“标题”样式，维护 section_stack", "metadata.section_title"],
                ["正文切块", "跳过空段落，将普通段落转成文本块", "正文文本、来源文件、段落序号"],
                ["表格切块", "按行提取非空单元格，用竖线拼接为表格文本块", "表格文本块"],
                ["章节定位", "每个文本块保留当前标题路径，后续用于区分 1.2 设计依据与正文", "章节标题路径"],
            ],
            [2.8 * cm, 8.2 * cm, 5.2 * cm],
        )
    )
    story.append(p("这一步的关键价值是把 Word 里的自然语言内容转成可追踪的结构化文本块。每个文本块都有段落序号和章节路径，因此最终问题能够回指到“设计说明 / 某章节 / 段落 N”。"))

    story.append(p("4. 引用记录抽取过程", "H1"))
    story.append(p("引用记录抽取位于 backend/app/services/word_references.py。其目标是把文本块进一步转换成标准引用记录，也就是数据库中的一条标准引用。"))
    story.append(
        table(
            [
                ["对象", "识别方式", "说明"],
                ["标准号", "STANDARD_NO_RE", "支持 GB/T、GB、YD/T、YD/、YD、JGJ/T、JGJ、CECS、HJ/T、QB-A、QB-J、MH、JJ、B 等前缀，并支持三位或四位年份错误写法"],
                ["标准名", "《...》", "仅把像“标准、规范、规程、规定、图集、办法、通知”等内容作为正文标准名；设计依据章节允许更宽松抽取"],
                ["文件号", "DOCUMENT_NO_RE", "支持工信部通信〔年份〕号、工信部令、计通、川移计等文件号"],
                ["条号", "CLAUSE_NO_RE", "从引用上下文中抽取第 x.x.x 条等条款号"],
            ],
            [2.6 * cm, 4.5 * cm, 9.1 * cm],
            small=True,
        )
    )
    story.append(p("最重要的改进是多引用拆分和标准号-标准名配对。早期逻辑容易把一整段里的多个标准揉成一条引用，导致后续问题被掩盖。当前逻辑先找所有编号和所有《标准名》，再按明确绑定关系配对。"))
    story.append(
        p(
            "优先级 1: 《标准名》（标准号）\n"
            "优先级 2: 标准号《标准名》\n"
            "优先级 3: 很短分隔符下的保守兜底配对\n"
            "未配对的标准名仍作为“名称引用”保留，未配对的标准号也会单独保留。",
            "Code",
        )
    )

    story.append(p("5. 引用一致性校核过程", "H1"))
    story.append(p("校核逻辑位于 backend/app/services/word_check.py。系统先把标准引用记录分成两组：章节标题中包含“设计依据”的记录进入设计依据引用集合，其余进入正文引用集合。"))
    story.append(p("5.1 设计依据与标准库校核", "H2"))
    story.append(
        table(
            [
                ["优先级", "问题类型", "判断逻辑"],
                ["1", "标准已替代", "先检查是否命中标准有效性库中的旧标准。若 Word 已命中新标准，则不报替代；若命中旧标准，则提示采用新标准。"],
                ["2", "标准库未收录", "有标准号但在强条库和名称匹配中均找不到时，提示标准库未收录或 Word 引用写错。"],
                ["3", "标准名称不一致", "标准号能在标准库中找到，但 Word 标准名与标准库名称归一化后不一致。"],
                ["4", "标准编号不一致", "标准名能在标准库中找到，但 Word 标准号与标准库编号不一致。"],
            ],
            [2.0 * cm, 4.0 * cm, 10.2 * cm],
        )
    )
    story.append(p("5.2 正文与设计依据校核", "H2"))
    story.append(
        table(
            [
                ["优先级", "问题类型", "判断逻辑"],
                ["1", "正文仍引用旧标准", "正文明确引用旧标准，且 1.2 设计依据已列对应新标准时，优先报旧标准问题。"],
                ["2", "正文标准编号不一致", "正文标准名能与 1.2 对上，且正文写了标准号，但标准号不同。正文只写标准名时不乱报编号不一致。"],
                ["3", "正文标准名称不一致", "正文标准号能与 1.2 对上，但正文标准名不同。"],
                ["4", "正文引用未列入设计依据", "正文编号和名称都无法与 1.2 对上时，提示正文引用未列入设计依据。"],
                ["5", "设计依据未被正文使用", "1.2 设计依据列了某依据，但正文没有发现明确引用，作为提示项而非高风险错误。"],
            ],
            [2.0 * cm, 4.6 * cm, 9.6 * cm],
            small=True,
        )
    )
    story.append(p("归一化规则包括标准号大小写和空格清理、中文/英文括号统一、年份版文字处理、数值范围符号统一、去除“中华人民共和国国家标准”等前缀噪声。"))

    story.append(PageBreak())
    story.append(p("6. 测试集设计与测试笔记整理", "H1"))
    story.append(p("测试笔记来自项目外部测试资料。笔记将测试分为“设计依据与标准库校核”和“正文与设计依据校核”两大类，覆盖替代标准、标准号不一致、标准名称不一致、正文旧标准引用等场景。"))
    story.append(
        table(
            [
                ["测试范围", "构造数量", "测试意图", "笔记记录"],
                ["设计依据与标准库校核", "25", "设计依据与标准库对比", "标准替代 5 个；标准编号错误 10 个；标准名称错误 10 个"],
                ["标准替代", "5", "设计依据引用旧标准或替代标准", "黄色标记，全部通过"],
                ["标准编号错误", "10", "标准名称正确但编号错误", "蓝色标记，最初只找到 9 个，原因是部分前缀没有匹配"],
                ["标准名称错误", "10", "标准号正确但名称错误", "绿色标记，全部通过"],
                ["正文与设计依据校核", "27", "正文与 1.2 设计依据对比", "正文旧标准引用 7 个；正文标准编号错误 10 个；正文标准名称错误 10 个"],
                ["正文旧标准引用", "7", "正文只写过期标准名或旧标准引用", "红色标记，全部通过"],
                ["正文标准编号错误", "10", "正文标准名正确但编号错误", "粉色标记，早期命中率低，后续通过拆分与正则扩展提升"],
                ["正文标准名称错误", "10", "正文标准号正确但名称错误", "灰色标记，早期 8/10，修复字串包含问题后通过"],
            ],
            [3.0 * cm, 2.0 * cm, 5.0 * cm, 6.2 * cm],
            small=True,
        )
    )
    story.append(
        callout(
            "测试笔记中的阶段性结论",
            "测试一文档应出现“警告”和“高风险”共 35 个，测试二文档应出现报错 17 个，合计应出现 52 个报错。笔记记录当时最后找到 50 个，剩余 2 个主要来自正则匹配边界。后续修复继续覆盖了 B 前缀、YD/ 缺 T、JJ 前缀、三位年份、同段多引用拆分和配对错位等问题。",
        )
    )

    story.append(p("7. 过程问题与修复闭环", "H1"))
    story.append(
        table(
            [
                ["问题", "表现", "原因", "修复方式"],
                ["正文只写标准名被误报", "正文没有标准号但系统仍报编号或替代错误", "旧规则默认要求正文编号与 1.2 完整一致", "允许正文只写标准名；只有正文明确写了编号才报编号不一致"],
                ["同名新旧标准误报替代", "如安全生产管理规定，新旧名称相同但文件号不同，正文只写名称被报旧标准", "名称-only 匹配没有区分同名替代", "只有名称命中旧名且不命中新名时才报替代；同名时不乱报"],
                ["文件号识别漏空格", "工信部通信〔2015〕406 号等无法稳定识别", "DOCUMENT_NO_RE 未允许数字与“号”之间的空格", "放宽文件号正则，允许空格"],
                ["数值范围导致名称不一致", "3000~5000MHz 与 3000－5000MHz 被当成不同名称", "名称归一化未统一范围符号", "统一 ~、～、-、－、–、—、至 等范围连接符"],
                ["字串包含造成漏检", "电源设备安装工程验收规范 vs 通信电源设备安装工程验收规范", "过度使用包含匹配，把不同名称当成等价", "名称不一致判断改为归一化后的严格等价"],
                ["一段多个标准漏检", "YD/T 5060-2019 等名称/编号不一致只找到一部分", "抽取层把整段多个标准聚合成一条引用记录", "按每个《标准名》和标准号拆分成多条标准引用记录"],
                ["异常编号格式漏抽", "YD/ 5026-2021、YD/T 5060-209、JJ 8-2016 等未识别", "标准号正则覆盖范围不足", "扩展前缀与年份匹配，支持 YD/、JJ、B、三位年份等"],
                ["同段引用互相污染", "替代判断读取整段上下文，把其他标准号混入当前引用", "替代判断从上下文中抓取所有编号", "替代判断只使用当前引用自身的标准号和标准名"],
                ["标准名和编号配对错位", "GB 51456-2023 被配到信息通信建筑工程设计规范，GB 55037-2022 被配到移动通信基础设施标准", "最近距离贪心配对抢走后续括号编号", "先识别《名称》（编号）和 编号《名称》明确绑定，再保守兜底"],
                ["前端英文问题类型", "用户看到标准编号不一致等内部英文枚举", "后端问题类型为枚举值，前端直接展示", "前端增加中文名称映射，严重等级也改为中文"],
            ],
            [3.0 * cm, 3.7 * cm, 4.6 * cm, 4.9 * cm],
            small=True,
        )
    )

    story.append(p("8. 当前验证结果", "H1"))
    story.append(p("本报告生成前，对当前代码执行了语法编译和本地解析回归。由于该验证不连接数据库，正文与设计依据校核统计不包含标准有效性库中的替代关系，只用于确认 Word 解析、引用记录抽取和正文一致性规则没有明显退化。"))
    story.append(
        table(
            [
                ["验证项", "结果"],
                ["语法编译", "引用记录抽取模块与一致性校核模块通过 Python 语法编译"],
                ["测试集1本地解析", "文本块 1505 个，引用记录 196 条，其中设计依据引用 62 条、正文引用 134 条"],
                ["测试集2本地解析", "文本块 1818 个，引用记录 206 条，其中设计依据引用 62 条、正文引用 144 条"],
                ["目标漏检回归", "YD 508-2005、YD 5059-205、YD/ 5026-2021、YD/T 506-2019、YD/T 5060-209、JJ 8-2016 均可拆出并进入编号不一致判断"],
                ["消防安全误报回归", "段落 1368 中 GB 51456-2023 与 GB 55037-2022 已正确配对，完整正文与设计依据校核中不再出现这两条误报"],
            ],
            [4.2 * cm, 12.0 * cm],
        )
    )
    story.append(
        callout(
            "使用注意",
            "抽取规则变化后，不能只点击“开始检查”。必须重启后端并重新上传/重新解析 Word 文档，否则数据库中的旧标准引用记录仍会保留旧的聚合或错配结果。",
        )
    )

    story.append(p("9. 当前边界与第二阶段建议", "H1"))
    story.append(bullet("继续补充标准号前缀白名单，尤其是测试笔记里提到的极端单字母前缀或录入错误。"))
    story.append(bullet("将目前通过人工测试发现的问题固化为自动化单元测试，至少覆盖设计依据与标准库校核、正文与设计依据校核、标准号与标准名配对三类。"))
    story.append(bullet("引入标准别名表，避免仅依靠字串归一化处理所有名称差异。"))
    story.append(bullet("第二阶段可扩展强条条号与正文内容一致性校核，优先按标准号+条号精确匹配，再用相似召回辅助。"))
    story.append(bullet("第三阶段再考虑项目适用性、遗漏强条和专业边界判断，避免第一阶段规则过度复杂。"))

    story.append(PageBreak())
    story.append(p("附录 A：关键代码文件", "H1"))
    story.append(
        table(
            [
                ["文件", "职责"],
                ["backend/app/main.py", "后端接口入口，负责文件上传、检查请求、问题查询"],
                ["backend/app/agent/tools.py", "把 Word 解析、检查和问题查询包装为可复用工具函数"],
                ["backend/app/word_loader.py", "本地解析 docx，生成文本块"],
                ["backend/app/services/word_references.py", "从文本块抽取标准号、标准名、文件号、条号并生成标准引用记录"],
                ["backend/app/services/word_check.py", "执行设计依据与标准库、正文与设计依据一致性检查，生成问题记录"],
                ["backend/app/services/excel_ingest.py", "读取 Excel 强条库和标准有效性清单，写入数据库"],
                ["backend/app/db/models.py", "定义强制性条文、标准有效性、标准引用记录、问题记录等表"],
                ["frontend-vue2/src/components/ResultPanel.vue", "Vue 2 公共工作台的问题列表、中文问题类型与严重等级展示"],
            ],
            [6.0 * cm, 10.2 * cm],
            small=True,
        )
    )

    story.append(p("附录 B：测试笔记原文摘录", "H1"))
    notes = [
        "测试集构建：",
        "设计依据与标准库校核：25个",
        "标准替代：5个 黄色标记 全部通过",
        "标准编号错误：10个 蓝色标记，只找到9个：中华人民共和国国家标准《混凝土结构加固设计规范》（B 5067-2013）；未发现原因是因为前缀没有匹配，所以标准号没有抽取到。",
        "标准名称错误：10个 绿色标记 全部通过",
        "正文与设计依据校核：27个",
        "正文旧标准引用：7个 红色标记 全部通过：不写标准号只写过期标准名被识别",
        "正文标准编号错误：10个 粉色标记，十个中只发现了3个，成功率低。修改后发现九个，唯一一个没找到是因为开头为Y正则没匹配到条号。",
        "正文标准名称错误：10个 灰色标记，十个通过八个，两个没找到是因为字串包含问题，已进行修改。修改后已完全通过。",
        "其中测试一文档应出现警告和高风险 35 个，测试二文档应出现报错 17 个，共计应出现 52 个报错。",
        "观察到细节：如果 1.2 设计依据跟标准库标准号不一样，不仅设计依据与标准库校核会报错，正文与设计依据校核也会报错，因为前后标准号也不一样；设计依据中标准名和标准库不一样同理。",
    ]
    for item in notes:
        story.append(p(item, "Small"))

    return story


def build_pdf():
    doc = BaseDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.8 * cm,
        title="通信工程设计说明强制性条文引用一致性校核第一阶段报告",
        author="Codex",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    template = PageTemplate(id="main", frames=[frame], onPage=header_footer)
    doc.addPageTemplates([template])
    doc.build(build_story())


if __name__ == "__main__":
    build_pdf()
    print(PDF_PATH)
