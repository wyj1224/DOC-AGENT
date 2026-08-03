<template>
  <main class="chat-workspace">
    <header class="chat-header">
      <div><span class="task-label">当前任务</span><h1>{{ title }}</h1></div>
      <div class="chat-header-actions">
        <div class="mode-switch" aria-label="工作模式">
          <button :class="{ active: mode === 'check' }" type="button" @click="$emit('mode-change', 'check')">
            <FileText :size="15" />文档校核
          </button>
          <button :class="{ active: mode === 'clause_extract' }" type="button" @click="$emit('mode-change', 'clause_extract')">
            <ScanText :size="15" />强条抽取
          </button>
          <button :class="{ active: mode === 'knowledge' }" type="button" @click="$emit('mode-change', 'knowledge')">
            <Search :size="15" />知识问答
          </button>
        </div>
        <button v-if="!resultPanelOpen" class="icon-action" type="button" title="展开结果面板" @click="$emit('open-results')">
          <PanelRightOpen :size="19" />
        </button>
      </div>
    </header>

    <div ref="conversation" class="conversation">
      <div v-if="!messages.length" class="conversation-empty">
        <div class="empty-mark"><MessageSquareText :size="24" /></div>
        <div class="empty-heading"><h2>{{ emptyHeading }}</h2><span>（重要结论请结合原始文档复核）</span></div>
        <div v-if="mode === 'check'" class="prompt-actions">
          <button type="button" @click="$emit('quick-prompt', '请全面检查这个文档有没有问题')">全面校核文档</button>
          <button type="button" @click="$emit('quick-prompt', '只检查正文完整性有没有问题')">检查正文完整性</button>
          <button type="button" @click="$emit('quick-prompt', '检查正文和依据章节有没有冲突')">核对正文与依据</button>
        </div>
        <div v-if="mode === 'clause_extract'" class="prompt-actions">
          <button type="button" @click="$emit('quick-prompt', '请自动识别并提取这份 PDF 中的全部强制性条文')">自动提取全部强条</button>
          <button type="button" @click="$emit('quick-prompt', '请识别强条并按章节进行汇总')">按章节汇总</button>
        </div>
      </div>
      <div v-else class="message-stream">
        <article v-for="message in messages" :key="message.id" class="chat-message" :class="message.role">
          <div class="message-avatar">{{ message.role === "assistant" ? "D" : "你" }}</div>
          <div class="message-content">
            <span class="message-author">{{ message.role === "assistant" ? "DOC AGENT" : "你" }}</span>
            <ReportMarkdown v-if="message.role === 'assistant'" :text="message.content" />
            <p v-else>{{ message.content }}</p>
            <span v-if="message.pending" class="streaming-cursor" aria-label="正在生成" />
          </div>
        </article>
      </div>
    </div>

    <div class="composer-wrap">
      <form class="chat-composer" :class="{ 'has-attachment': attachmentName }" @submit.prevent="submit">
        <div v-if="attachmentName && mode !== 'knowledge'" class="attachment-card">
          <span class="attachment-file-icon" :class="mode === 'clause_extract' ? 'pdf' : 'word'">
            <ScanText v-if="mode === 'clause_extract'" :size="18" />
            <FileText v-else :size="18" />
          </span>
          <span class="attachment-copy">
            <strong>{{ attachmentName }}</strong>
            <small>{{ mode === "clause_extract" ? "PDF" : "Word" }}{{ attachmentParsed ? " · 已解析" : "" }}</small>
          </span>
          <button class="attachment-remove" type="button" title="移除文档" @click="$emit('file-change', null)"><X :size="15" /></button>
        </div>

        <textarea
          rows="1"
          :value="draft"
          :placeholder="composerPlaceholder"
          @input="$emit('draft-change', $event.target.value)"
          @keydown="handleKeyDown"
          @compositionstart="composing = true"
          @compositionend="composing = false"
        />
        <div class="composer-actions">
          <label v-if="mode !== 'knowledge'" class="composer-icon" :title="mode === 'clause_extract' ? '附加 PDF' : '附加 Word 文档'">
            <Plus :size="22" />
            <input
              ref="fileInput"
              type="file"
              :accept="mode === 'clause_extract' ? '.pdf,application/pdf' : '.docx'"
              @change="selectFile"
            />
          </label>
          <span v-else />
          <button
            class="send-button"
            :class="{ 'is-stopping': sending }"
            type="submit"
            :title="sending ? '停止回答' : '发送'"
            :aria-label="sending ? '停止回答' : '发送'"
            :disabled="!sending && !canSend"
          >
            <Square v-if="sending" :size="12" fill="currentColor" />
            <ArrowUp v-else :size="21" />
          </button>
        </div>
      </form>
    </div>
  </main>
</template>

<script>
import {
  ArrowUp,
  FileText,
  MessageSquareText,
  PanelRightOpen,
  Plus,
  ScanText,
  Search,
  Square,
  X,
} from "lucide-vue";

import ReportMarkdown from "./ReportMarkdown.vue";

export default {
  name: "ChatWorkspace",
  components: { ArrowUp, FileText, MessageSquareText, PanelRightOpen, Plus, ReportMarkdown, ScanText, Search, Square, X },
  props: {
    title: { type: String, required: true },
    mode: { type: String, required: true },
    messages: { type: Array, default: () => [] },
    draft: { type: String, default: "" },
    attachedFile: { type: Object, default: null },
    wordUpload: { type: Object, default: null },
    clauseFileName: { type: String, default: "" },
    sending: Boolean,
    resultPanelOpen: Boolean,
  },
  data() {
    return { composing: false };
  },
  computed: {
    attachmentName() {
      return (this.attachedFile && this.attachedFile.name)
        || (this.wordUpload && this.wordUpload.file_name)
        || this.clauseFileName;
    },
    attachmentParsed() {
      return Boolean((this.wordUpload && !this.attachedFile) || (this.clauseFileName && !this.attachedFile));
    },
    canSend() {
      return Boolean(this.draft.trim() || (this.mode !== "knowledge" && this.attachmentName));
    },
    emptyHeading() {
      if (this.mode === "check") return "需要校核哪份文档？";
      if (this.mode === "clause_extract") return "需要从哪份 PDF 提取强条？";
      return "想从知识库了解什么？";
    },
    composerPlaceholder() {
      if (this.mode === "check") return "输入校核要求…";
      if (this.mode === "clause_extract") return "输入强条提取或追问要求…";
      return "向知识库提问…";
    },
  },
  watch: {
    messages: {
      deep: true,
      handler() {
        this.$nextTick(() => {
          const element = this.$refs.conversation;
          if (element) element.scrollTop = element.scrollHeight;
        });
      },
    },
  },
  methods: {
    submit() {
      this.$emit(this.sending ? "stop" : "send");
    },
    handleKeyDown(event) {
      if (this.composing || event.isComposing || event.keyCode === 229) return;
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (!this.sending) this.$emit("send");
      }
    },
    selectFile(event) {
      this.$emit("file-change", event.target.files && event.target.files[0] ? event.target.files[0] : null);
      event.target.value = "";
    },
  },
};
</script>
