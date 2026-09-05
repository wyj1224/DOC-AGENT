<template>
  <aside v-if="open" class="result-panel">
    <div class="result-panel-overview">
      <header class="result-header">
        <div><span>{{ panelTitle }}</span><strong>{{ panelCount }}</strong></div>
        <button class="icon-action" type="button" title="收起结果面板" @click="$emit('toggle')"><PanelRightClose :size="19" /></button>
      </header>

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
    </div>

    <div class="result-panel-scroll">
      <div v-if="editResult" class="edit-result-block">
          <div class="edit-result-card">
            <div>
              <span>{{ editResult.output_document_id ? "Word 修订副本" : "Word 修改结果" }}</span>
              <strong v-if="editResult.output_file_name">{{ editResult.output_file_name }}</strong>
              <small>{{ editResult.message }}</small>
              <small>已修改 {{ editResult.applied_count }} 处{{ editStatusText }}</small>
              <small>{{ taskSummary }}<template v-if="editResult.attempt_count"> · 修订 {{ editResult.attempt_count }} 轮</template></small>
            </div>
            <button v-if="editResult.output_document_id" type="button" @click="$emit('download-edit', editResult)"><Download :size="16" />下载副本</button>
          </div>
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

      <details v-if="trajectorySteps.length" class="edit-agent-trace task-trajectory">
        <summary>查看 Agent 执行轨迹（{{ trajectorySteps.length }} Step）</summary>
        <ol>
          <li v-for="step in trajectorySteps" :key="step.step_id">
            <span class="trace-actor" :class="step.status === 'completed' ? 'tool' : 'llm'">{{ step.step_index }}</span>
            <div>
              <strong>{{ stepTitle(step) }}</strong>
              <p>{{ stepDescription(step) }}</p>
            </div>
          </li>
        </ol>
      </details>
    </div>
  </aside>
</template>

<script>
import { ChevronDown, Download, PanelRightClose } from "lucide-vue";

import { checkScopeLabel, issueTypeLabel, severityLabel } from "../lib/labels";
import EmptyState from "./EmptyState.vue";

export default {
  name: "ResultPanel",
  components: { ChevronDown, Download, EmptyState, PanelRightClose },
  props: {
    open: Boolean,
    totals: { type: Object, required: true },
    activeScope: { type: String, required: true },
    basisIssues: { type: Object, default: null },
    bodyIssues: { type: Object, default: null },
    completenessIssues: { type: Object, default: null },
    currentIssues: { type: Object, default: null },
    agentTask: { type: Object, default: null },
    editResult: { type: Object, default: null },
  },
  computed: {
    panelTitle() {
      return "校核结果";
    },
    panelCount() {
      return `${this.totals.total} 个问题`;
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
    trajectorySteps() {
      const episodes = (this.agentTask && this.agentTask.episodes) || [];
      return episodes.flatMap((episode) => episode.steps || []);
    },
    taskSummary() {
      if (!this.agentTask) return "等待 Agent 运行";
      const episodeCount = (this.agentTask.episodes || []).length;
      return `${statusLabel(this.agentTask.status)} · ${episodeCount} Episode · ${this.trajectorySteps.length} Step`;
    },
  },
  methods: {
    issueTypeLabel,
    severityLabel,
    stepTitle(step) {
      if (step.action && step.action.action === "call_tool") return step.action.tool || "调用工具";
      return statusLabel((step.action && step.action.action) || step.status);
    },
    stepDescription(step) {
      if (step.error_message) return step.error_message;
      const reason = step.action && step.action.reason_summary;
      return reason || `耗时 ${step.duration_ms || 0} ms`;
    },
  },
};

function statusLabel(status) {
  return {
    success: "成功",
    completed: "已完成",
    manual_review: "需人工复核",
    terminal_failure: "执行失败",
    retryable_failure: "准备重试",
    finish: "完成任务",
  }[status] || status || "未知状态";
}
</script>
