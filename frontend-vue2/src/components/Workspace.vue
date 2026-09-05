<template>
  <div class="doc-agent-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'results-open': resultPanelOpen }">
    <AppSidebar
      :collapsed="sidebarCollapsed"
      :sessions="sessions"
      :selected-session-id="activeSessionId"
      :loading="loading.sessions || loading.sessionDetail"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
      @new-chat="startNewChat"
      @open-session="openSession"
      @delete-session="sessionToDelete = $event"
      @open-admin="$emit('open-admin')"
    />

    <ChatWorkspace
      :title="taskTitle"
      :messages="messages"
      :draft="draft"
      :attached-file="wordFile"
      :word-upload="wordUpload"
      :sending="sending"
      :result-panel-open="resultPanelOpen"
      @draft-change="draft = $event"
      @file-change="changeFile"
      @send="sendMessage"
      @stop="stopResponse"
      @quick-prompt="draft = $event"
      @open-results="resultPanelOpen = true"
    />

    <ResultPanel
      :open="resultPanelOpen"
      :totals="totals"
      :active-scope="activeIssueScope"
      :basis-issues="basisIssues"
      :body-issues="bodyIssues"
      :completeness-issues="completenessIssues"
      :current-issues="currentIssues"
      :agent-task="agentTask"
      :edit-result="editResult"
      @toggle="resultPanelOpen = !resultPanelOpen"
      @scope-change="activeIssueScope = $event"
      @download-edit="downloadEdit"
    />

    <div v-if="toast" class="toast" :class="`toast-${toast.type}`" role="status">
      <CheckCircle2 v-if="toast.type === 'success'" :size="18" /><AlertCircle v-else :size="18" /><span>{{ toast.text }}</span>
    </div>

    <div v-if="sessionToDelete" class="confirm-layer">
      <button class="confirm-backdrop" type="button" aria-label="关闭确认框" @click="!deletingSession && (sessionToDelete = null)" />
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
        <div class="confirm-dialog-heading">
          <span class="confirm-dialog-icon"><Trash2 :size="18" /></span>
          <div><h2 id="confirm-dialog-title">确认删除对话？</h2><p>删除“{{ sessionToDelete.title }}”后，这条历史对话将无法恢复。已上传文档和校核问题不会被删除。</p></div>
        </div>
        <div class="confirm-dialog-actions">
          <button class="button button-secondary" type="button" :disabled="deletingSession" @click="sessionToDelete = null">取消</button>
          <button class="button button-danger" type="button" :disabled="deletingSession" @click="deleteSession"><Loader2 v-if="deletingSession" class="spin" :size="17" />删除对话</button>
        </div>
      </section>
    </div>

  </div>
</template>

<script>
import { AlertCircle, CheckCircle2, Loader2, Trash2 } from "lucide-vue";

import { downloadWordDocument, errorMessage, request, streamAgentCheck } from "../lib/api";
import AppSidebar from "./AppSidebar.vue";
import ChatWorkspace from "./ChatWorkspace.vue";
import ResultPanel from "./ResultPanel.vue";

const initialLoading = () => ({
  uploadWord: false,
  check: false,
  issues: false,
  sessions: false,
  sessionDetail: false,
});

export default {
  name: "Workspace",
  components: { AlertCircle, AppSidebar, ChatWorkspace, CheckCircle2, Loader2, ResultPanel, Trash2 },
  data() {
    return {
      sidebarCollapsed: false,
      resultPanelOpen: true,
      taskTitle: "新对话",
      messages: [],
      draft: "",
      toast: null,
      toastTimer: null,
      loading: initialLoading(),
      activeController: null,
      wordFile: null,
      wordUpload: null,
      documentId: "",
      agentResult: null,
      agentTask: null,
      editResult: null,
      basisIssues: null,
      bodyIssues: null,
      completenessIssues: null,
      activeIssueScope: "basis_excel",
      sessions: [],
      activeSessionId: null,
      sessionToDelete: null,
      deletingSession: false,
    };
  },
  computed: {
    currentIssues() {
      if (this.activeIssueScope === "basis_excel") return this.basisIssues;
      if (this.activeIssueScope === "body_basis") return this.bodyIssues;
      return this.completenessIssues;
    },
    totals() {
      const issues = [
        ...((this.basisIssues && this.basisIssues.issues) || []),
        ...((this.bodyIssues && this.bodyIssues.issues) || []),
        ...((this.completenessIssues && this.completenessIssues.issues) || []),
      ];
      return {
        high: issues.filter((item) => item.severity === "high").length,
        warning: issues.filter((item) => item.severity === "warning").length,
        info: issues.filter((item) => item.severity === "info").length,
        total: (this.basisIssues ? this.basisIssues.issue_count : 0)
          + (this.bodyIssues ? this.bodyIssues.issue_count : 0)
          + (this.completenessIssues ? this.completenessIssues.issue_count : 0),
      };
    },
    sending() {
      return this.loading.check || this.loading.uploadWord;
    },
  },
  created() {
    this.fetchSessions();
  },
  beforeDestroy() {
    this.stopResponse();
    if (this.toastTimer) window.clearTimeout(this.toastTimer);
  },
  methods: {
    showMessage(type, text) {
      this.toast = { type, text };
      if (this.toastTimer) window.clearTimeout(this.toastTimer);
      this.toastTimer = window.setTimeout(() => { this.toast = null; }, 3200);
    },
    startNewChat() {
      this.stopResponse();
      this.taskTitle = "新对话";
      this.messages = [];
      this.draft = "";
      this.wordFile = null;
      this.wordUpload = null;
      this.documentId = "";
      this.agentResult = null;
      this.agentTask = null;
      this.editResult = null;
      this.basisIssues = null;
      this.bodyIssues = null;
      this.completenessIssues = null;
      this.activeSessionId = null;
    },
    changeFile(file) {
      this.wordFile = file;
      if (!file || !this.wordUpload || file.name !== this.wordUpload.file_name) {
        this.wordUpload = null;
        this.documentId = "";
        this.editResult = null;
      }
    },
    async sendMessage() {
      if (this.activeController) return;
      const message = this.draft.trim() || defaultAttachmentPrompt(Boolean(this.wordFile || this.documentId));
      if (!message) return;
      if (!this.wordFile && !this.documentId) return this.showMessage("error", "请先附加需要检查或修改的 Word 文档");

      this.draft = "";
      const attachedName = this.wordFile && this.wordFile.name;
      if (this.taskTitle === "新对话") this.taskTitle = shortTitle(attachedName || message);
      this.messages.push({ id: messageId(), role: "user", content: message });

      const controller = new AbortController();
      this.activeController = controller;
      try {
        await this.runDocumentCheck(message, controller.signal);
      } finally {
        if (this.activeController === controller) this.activeController = null;
      }
    },
    stopResponse() {
      if (this.activeController) this.activeController.abort();
    },
    updateChatMessage(id, changes) {
      const index = this.messages.findIndex((item) => item.id === id);
      if (index >= 0) this.$set(this.messages, index, { ...this.messages[index], ...changes });
    },
    async runDocumentCheck(message, signal) {
      const assistantId = messageId();
      this.messages.push({ id: assistantId, role: "assistant", content: "正在准备文档…", pending: true });
      this.loading.check = true;
      this.editResult = null;
      let answer = "";
      let receivedDelta = false;
      let streamResult = {};
      let returnedEditResult = null;
      try {
        let targetDocumentId = Number(this.documentId) || 0;
        if (this.wordFile && (!this.wordUpload || this.wordUpload.file_name !== this.wordFile.name)) {
          const upload = await this.uploadWordFile(this.wordFile, signal);
          targetDocumentId = upload.document_id;
        }
        const form = new FormData();
        form.append("message", message);
        form.append("document_id", String(targetDocumentId));
        if (this.activeSessionId) form.append("session_id", String(this.activeSessionId));
        await streamAgentCheck(form, (event) => {
          if (event.type === "error") throw new Error(String(event.data.content || "校核失败"));
          if (event.type === "status") this.updateChatMessage(assistantId, { content: String(event.data.content || "正在校核…"), pending: true });
          if (event.type === "result") {
            const sessionId = Number(event.data.session_id) || undefined;
            streamResult = agentStreamResult(event.data, sessionId);
            if (sessionId) this.activeSessionId = sessionId;
            returnedEditResult = editResultFromToolResults(event.data.tool_results);
            if (returnedEditResult) {
              this.editResult = returnedEditResult;
              if (returnedEditResult.output_document_id) {
                targetDocumentId = returnedEditResult.output_document_id;
                this.documentId = targetDocumentId;
                this.wordFile = null;
                this.wordUpload = {
                  document_id: targetDocumentId,
                  file_name: returnedEditResult.output_file_name,
                  parse_status: "parsed",
                  reference_count: 0,
                  section_count: 0,
                  chunk_count: 0,
                };
              }
            }
          }
          if (event.type === "delta") {
            const delta = String(event.data.content || "");
            answer = receivedDelta ? answer + delta : delta;
            receivedDelta = true;
            this.updateChatMessage(assistantId, { content: answer, pending: true });
          }
          if (event.type === "done") this.updateChatMessage(assistantId, { content: answer, pending: false });
        }, signal);
        assertNotAborted(signal);
        this.agentResult = { ...streamResult, answer };
        this.agentTask = streamResult.task_id ? await request(`/agent/tasks/${streamResult.task_id}`) : null;
        const scopes = returnedEditResult ? ["basis_excel", "body_basis"] : scopesForMessage(message);
        this.clearInactiveIssues(scopes);
        await Promise.all([...scopes.map((scope) => this.fetchIssues(scope, targetDocumentId)), this.fetchSessions()]);
        this.resultPanelOpen = true;
        this.showMessage("success", "文档校核完成");
      } catch (error) {
        if (isAbortError(error)) return this.updateChatMessage(assistantId, { content: stoppedAnswer(answer), pending: false });
        const text = errorMessage(error);
        this.updateChatMessage(assistantId, { content: `请求未完成：${text}`, pending: false });
        this.showMessage("error", text);
      } finally {
        this.loading.check = false;
      }
    },
    async uploadWordFile(file, signal) {
      this.loading.uploadWord = true;
      try {
        const form = new FormData();
        form.append("file", file);
        const data = await request("/word/upload", { method: "POST", body: form, signal });
        this.wordUpload = data;
        this.documentId = data.document_id;
        return data;
      } finally {
        this.loading.uploadWord = false;
      }
    },
    async fetchIssues(scope, documentId = Number(this.documentId)) {
      if (!documentId) return;
      this.loading.issues = true;
      try {
        const data = await request(`/word/issues?document_id=${documentId}&check_scope=${scope}&issue_limit=0`);
        if (scope === "basis_excel") this.basisIssues = data;
        if (scope === "body_basis") this.bodyIssues = data;
        if (scope === "completeness") this.completenessIssues = data;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.issues = false;
      }
    },
    clearInactiveIssues(scopes) {
      if (!scopes.includes("basis_excel")) this.basisIssues = null;
      if (!scopes.includes("body_basis")) this.bodyIssues = null;
      if (!scopes.includes("completeness")) this.completenessIssues = null;
      this.activeIssueScope = scopes[0];
    },
    async fetchSessions() {
      this.loading.sessions = true;
      try {
        const data = await request("/agent/sessions?limit=30");
        this.sessions = data.items;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.sessions = false;
      }
    },
    async openSession(sessionId) {
      this.loading.sessionDetail = true;
      try {
        const data = await request(`/agent/sessions/${sessionId}`);
        const task = data.last_task_id ? await request(`/agent/tasks/${data.last_task_id}`) : null;
        const taskResults = toolResultsFromTask(task);
        this.activeSessionId = data.session_id;
        this.taskTitle = data.title;
        this.documentId = data.active_document_id || "";
        this.wordFile = null;
        this.wordUpload = data.active_document_id && data.document_file_name ? {
          document_id: data.active_document_id,
          file_name: data.document_file_name,
          parse_status: "parsed",
          reference_count: 0,
          section_count: 0,
          chunk_count: 0,
        } : null;
        this.messages = data.messages.map((item, index) => ({ id: `${data.session_id}-${index}-${item.created_at}`, role: item.role, content: item.content }));
        this.agentTask = task;
        this.agentResult = task ? { session_id: data.session_id, task_id: task.task_id, status: task.status, tool_results: taskResults, answer: task.final_output.answer } : null;
        this.editResult = editResultFromToolResults(taskResults);
        if (data.active_document_id) {
          await Promise.all([
            this.fetchIssues("basis_excel", data.active_document_id),
            this.fetchIssues("body_basis", data.active_document_id),
            this.fetchIssues("completeness", data.active_document_id),
          ]);
        } else {
          this.basisIssues = null;
          this.bodyIssues = null;
          this.completenessIssues = null;
        }
        this.resultPanelOpen = true;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.sessionDetail = false;
      }
    },
    async deleteSession() {
      if (!this.sessionToDelete) return;
      const target = this.sessionToDelete;
      this.deletingSession = true;
      try {
        await request(`/agent/sessions/${target.session_id}`, { method: "DELETE" });
        this.sessions = this.sessions.filter((item) => item.session_id !== target.session_id);
        if (this.activeSessionId === target.session_id) this.startNewChat();
        this.sessionToDelete = null;
        this.showMessage("success", "对话已删除");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.deletingSession = false;
      }
    },
    async downloadEdit(result) {
      if (!result.output_document_id) return;
      try {
        await downloadWordDocument(result.output_document_id, result.output_file_name);
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      }
    },
  },
};

function scopesForMessage(message) {
  if (message === "只检查依据章节有没有问题") return ["basis_excel"];
  if (message === "检查正文和依据章节有没有冲突") return ["body_basis"];
  if (message === "只检查正文完整性有没有问题") return ["completeness"];
  return ["basis_excel", "body_basis", "completeness"];
}

function resultFromToolResults(value, names) {
  if (!Array.isArray(value)) return null;
  const item = value.find((entry) => names.includes(entry.tool));
  return item ? item.result : null;
}

const editResultFromToolResults = (value) => resultFromToolResults(value, ["word_edit_result", "fix_consistency_issues_tool"]);

function agentStreamResult(data, sessionId) {
  return {
    session_id: sessionId,
    task_id: Number(data.task_id) || undefined,
    episode_id: Number(data.episode_id) || undefined,
    attempt_no: Number(data.attempt_no) || 1,
    status: data.status,
    evaluation: data.evaluation,
    run_id: Number(data.run_id) || undefined,
    tool_plan: data.tool_plan,
    tool_results: data.tool_results,
  };
}

function toolResultsFromTask(task) {
  if (!task || !task.final_output) return [];
  if (task.task_type === "document_check") return task.final_output.tool_results || [];
  if (task.task_type === "word_edit") return [{ tool: "word_edit_result", result: task.final_output }];
  return [];
}

function defaultAttachmentPrompt(hasWord) {
  return hasWord ? "请全面检查这个文档有没有问题" : "";
}

function assertNotAborted(signal) {
  if (signal.aborted) throw new DOMException("已停止回答", "AbortError");
}

function isAbortError(error) {
  return error instanceof Error && error.name === "AbortError";
}

function stoppedAnswer(answer) {
  return answer ? `${answer}\n\n已停止回答。` : "已停止回答。";
}

function shortTitle(value) {
  const clean = value.replace(/\.docx$/i, "").trim();
  return clean.length > 30 ? `${clean.slice(0, 30)}…` : clean;
}

function messageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

</script>
