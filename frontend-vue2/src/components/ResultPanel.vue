<template>
  <aside v-if="open" class="result-panel">
    <div class="result-panel-overview">
      <header class="result-header">
        <div><span>{{ panelTitle }}</span><strong>{{ panelCount }}</strong></div>
        <button class="icon-action" type="button" title="收起结果面板" @click="$emit('toggle')"><PanelRightClose :size="19" /></button>
      </header>

      <template v-if="mode === 'check'">
        <div class="result-summary">
          <div class="result-stat high"><span>高风险</span><strong>{{ totals.high }}</strong></div>
          <div class="result-stat warning"><span>警告</span><strong>{{ totals.warning }}</strong></div>
          <div class="result-stat info"><span>提示</span><strong>{{ totals.info }}</strong></div>
        </div>
        <div class="result-toolbar">
          <div class="result-tabs">
            <button
              v-for="scope in scopes"
              :key="scope.value"
              :class="{ active: activeScope === scope.value }"
              type="button"
              @click="$emit('scope-change', scope.value)"
            ><span>{{ scope.label }}</span><em>{{ scope.count }}</em></button>
          </div>
        </div>
      </template>
    </div>

    <div class="result-panel-scroll">
      <template v-if="mode === 'knowledge'">
        <div v-if="sources.length" class="source-list">
          <article v-for="source in sources" :key="`${source.document_id}-${source.chunk_index}`" class="source-item">
            <div><strong>[{{ source.rank }}] {{ source.source_file }}</strong><span>第 {{ source.page_no }} 页 · 相关度 {{ Number(source.score).toFixed(3) }}</span></div>
            <p>{{ source.text }}</p>
          </article>
        </div>
        <EmptyState v-else title="暂无引用" text="知识库回答生成后会展示命中的材料。" />
      </template>

      <template v-else-if="mode === 'clause_extract'">
        <div v-if="clauseExtractionResult" class="clause-extraction-result">
          <div class="clause-extraction-summary">
            <ScanText :size="20" />
            <div>
              <span>{{ mandatoryStatusLabel(clauseExtractionResult.mandatory_status) }}</span>
              <strong>{{ clauseExtractionResult.file_name }}</strong>
              <small>{{ clauseExtractionResult.message }}</small>
              <small>{{ clauseExtractionResult.page_count }} 页 · LLM 决策 {{ clauseExtractionResult.llm_decision_count }} 次 · 工具调用 {{ clauseExtractionResult.tool_call_count }} 次</small>
            </div>
          </div>
          <div class="clause-methods">
            <span v-for="method in clauseExtractionResult.detection_methods" :key="method">{{ detectionMethodLabel(method) }}</span>
          </div>
          <div v-if="clauseExtractionResult.warnings.length" class="clause-warnings">
            <p v-for="warning in clauseExtractionResult.warnings" :key="warning">{{ warning }}</p>
          </div>
          <details v-if="clauseExtractionResult.agent_trace.length" class="edit-agent-trace">
            <summary>查看强条抽取 Agent Loop</summary>
            <ol><li v-for="step in clauseExtractionResult.agent_trace" :key="step.step">
              <span class="trace-actor" :class="step.actor">{{ step.actor === "llm" ? "LLM" : "工具" }}</span>
              <div><strong>{{ step.phase }}</strong><p>{{ step.summary }}</p></div>
            </li></ol>
          </details>
          <div class="clause-list">
            <article
              v-for="clause in clauseExtractionResult.clauses"
              :key="`${clause.reference || clause.clause_no}-${clause.page_no}`"
              class="clause-item"
            >
              <div><strong>{{ clause.reference || clause.clause_no }}</strong><span>PDF 第 {{ clause.page_no }} 页 · {{ detectionMethodLabel(clause.evidence_type) }}</span></div>
              <p>{{ clause.clause_text }}</p>
            </article>
            <EmptyState
              v-if="!clauseExtractionResult.clauses.length"
              title="未识别到强条"
              text="请结合识别状态和原始 PDF 复核，系统不会把未识别到等同于确定没有。"
            />
          </div>
        </div>
        <EmptyState v-else title="等待抽取" text="上传 PDF 后，Agent 会自动识别公告、粗体和正文条文。" />
      </template>

      <template v-else>
        <div v-if="editResult" class="edit-result-block">
          <div class="edit-result-card">
            <div>
              <span>{{ editResult.output_document_id ? "Word 修订副本" : "Word 修改结果" }}</span>
              <strong v-if="editResult.output_file_name">{{ editResult.output_file_name }}</strong>
              <small>{{ editResult.message }}</small>
              <small>已修改 {{ editResult.applied_count }} 处{{ editStatusText }}</small>
              <small>LLM 决策 {{ editResult.llm_decision_count }} 次 · 工具调用 {{ editResult.tool_call_count }} 次 · 修订 {{ editResult.attempt_count }} 轮</small>
            </div>
            <button v-if="editResult.output_document_id" type="button" @click="$emit('download-edit', editResult)"><Download :size="16" />下载副本</button>
          </div>
          <details v-if="editResult.agent_trace && editResult.agent_trace.length" class="edit-agent-trace">
            <summary>查看 Agent 执行循环</summary>
            <ol><li v-for="step in editResult.agent_trace" :key="step.step">
              <span class="trace-actor" :class="step.actor">{{ step.actor === "llm" ? "LLM" : "工具" }}</span>
              <div><strong>{{ step.phase }}</strong><p>{{ step.summary }}</p></div>
            </li></ol>
          </details>
        </div>

        <div v-if="currentIssues && currentIssues.issues.length" class="result-issue-list">
          <article
            v-for="(issue, index) in currentIssues.issues"
            :key="`${issue.issue_id || index}-${issue.issue_type}`"
            class="result-issue"
            :class="`severity-${issue.severity}`"
          >
            <div class="result-issue-title"><strong>{{ issueTypeLabel(issue.issue_type) }}</strong><span>{{ severityLabel(issue.severity) }}</span></div>
            <div class="result-issue-meta"><span>{{ issue.section_title || "未识别章节" }}</span><span>段落 {{ issue.paragraph_index }}</span></div>
            <p>{{ issue.reason }}</p>
            <p v-if="issue.suggestion" class="result-suggestion">{{ issue.suggestion }}</p>
            <details v-if="issue.original_text"><summary><ChevronDown :size="14" />查看原文</summary><div>{{ issue.original_text }}</div></details>
          </article>
        </div>
        <EmptyState v-else-if="!currentIssues" title="等待校核" text="完成文档校核后，问题会显示在这里。" />
        <EmptyState v-else title="未发现问题" text="当前分类没有返回问题。" />

        <details v-if="agentResult" class="trace-details">
          <summary>查看工具执行详情</summary>
          <pre>{{ traceJson }}</pre>
        </details>
      </template>
    </div>
  </aside>
</template>

<script>
import { ChevronDown, Download, PanelRightClose, ScanText } from "lucide-vue";

import { checkScopeLabel, issueTypeLabel, severityLabel } from "../lib/labels";
import EmptyState from "./EmptyState.vue";

export default {
  name: "ResultPanel",
  components: { ChevronDown, Download, EmptyState, PanelRightClose, ScanText },
  props: {
    open: Boolean,
    mode: { type: String, required: true },
    totals: { type: Object, required: true },
    activeScope: { type: String, required: true },
    basisIssues: { type: Object, default: null },
    bodyIssues: { type: Object, default: null },
    completenessIssues: { type: Object, default: null },
    currentIssues: { type: Object, default: null },
    sources: { type: Array, default: () => [] },
    agentResult: { type: Object, default: null },
    editResult: { type: Object, default: null },
    clauseExtractionResult: { type: Object, default: null },
  },
  computed: {
    panelTitle() {
      return this.mode === "check" ? "校核结果" : this.mode === "clause_extract" ? "强条抽取" : "引用来源";
    },
    panelCount() {
      if (this.mode === "check") return `${this.totals.total} 个问题`;
      if (this.mode === "clause_extract") return `${this.clauseExtractionResult ? this.clauseExtractionResult.clause_count : 0} 条强条`;
      return `${this.sources.length} 条材料`;
    },
    scopes() {
      return [
        { value: "basis_excel", label: checkScopeLabel("basis_excel"), count: this.basisIssues ? this.basisIssues.issue_count : 0 },
        { value: "body_basis", label: checkScopeLabel("body_basis"), count: this.bodyIssues ? this.bodyIssues.issue_count : 0 },
        { value: "completeness", label: checkScopeLabel("completeness"), count: this.completenessIssues ? this.completenessIssues.issue_count : 0 },
      ];
    },
    editStatusText() {
      if (!this.editResult) return "";
      if (this.editResult.status === "completed") return "，复检通过";
      if (this.editResult.remaining_issue_count > 0) return `，仍有 ${this.editResult.remaining_issue_count} 个问题`;
      return "，需人工确认";
    },
    traceJson() {
      return JSON.stringify({ tool_plan: this.agentResult.tool_plan, tool_results: this.agentResult.tool_results }, null, 2);
    },
  },
  methods: {
    issueTypeLabel,
    severityLabel,
    mandatoryStatusLabel(status) {
      return { present: "识别到强制性条文", confirmed_none: "PDF 明确说明无强条", none_detected: "未识别到强条", needs_review: "需要人工复核" }[status];
    },
    detectionMethodLabel(method) {
      return {
        announcement_list: "公告列出",
        bold_rule: "PDF 声明黑体标识",
        vision_announcement: "视觉识别公告条号",
        vision_bold_rule: "视觉识别黑体规则",
        vision_bold_body: "视觉确认黑体正文",
        vision_explicit_none: "视觉确认无强条声明",
        vision_no_evidence: "全页视觉扫描未发现证据",
        body_high_accuracy: "正文页高精度复识别",
        body_native_text: "PDF 原生文字层回查",
        body_cache: "复用同文件有效正文缓存",
        explicit_none: "明确无强条",
        no_evidence: "未发现明确证据",
        announcement_and_body: "公告 + 正文",
        announcement_and_body_ocr_recovered: "公告 + 正文（条号纠偏）",
        announcement_and_bold_body: "公告 + 黑体正文",
        vision_bold_body_and_ocr: "视觉黑体 + 正文 OCR",
      }[method] || method;
    },
  },
};
</script>
