export const ISSUE_TYPE_LABELS = {
  standard_replaced: "标准已替代",
  standard_name_mismatch: "标准名称不一致",
  standard_no_mismatch: "标准编号不一致",
  standard_not_found: "标准库未收录",
  clause_not_found: "强条条号未找到",
  body_reference_replaced_by_basis: "正文仍引用旧标准",
  body_standard_no_mismatch: "正文标准编号不一致",
  body_standard_name_mismatch: "正文标准名称不一致",
  basis_declared_but_unused: "依据未被正文使用",
  body_reference_not_in_basis: "正文引用未列入依据章节",
  template_year_not_matched: "模板年份未匹配",
  template_not_matched: "未匹配到模板",
  template_multiple_matched: "匹配到多个模板",
  missing_section: "疑似缺少章节",
  empty_section_body: "章节正文为空",
  placeholder_text_found: "正文存在占位符",
  template_key_section_missing: "模板缺少关键章节",
  key_section_missing: "关键章节缺失",
  key_section_similarity_low: "关键章节相似度不足",
  key_section_heading_no_changed: "子章节编号不同",
  key_section_content_missing: "模板内容缺失",
  key_section_content_modified: "章节内容不同",
  key_section_content_added: "章节新增内容",
};

export const SEVERITY_LABELS = { high: "高风险", warning: "警告", info: "提示" };
export const CHECK_SCOPE_LABELS = {
  basis_excel: "依据与标准库",
  body_basis: "正文与设计依据",
  completeness: "完整性检查",
};

export const issueTypeLabel = (value) => ISSUE_TYPE_LABELS[value] || value || "未知问题";
export const severityLabel = (value) => SEVERITY_LABELS[value] || value || "未知级别";
export const checkScopeLabel = (value) => CHECK_SCOPE_LABELS[value] || value || "未知分类";

export function translateDisplayText(value) {
  const replacements = { ...ISSUE_TYPE_LABELS, ...CHECK_SCOPE_LABELS, ...SEVERITY_LABELS };
  return Object.entries(replacements)
    .sort(([left], [right]) => right.length - left.length)
    .reduce((text, [source, target]) => text.split(source).join(target), value);
}
