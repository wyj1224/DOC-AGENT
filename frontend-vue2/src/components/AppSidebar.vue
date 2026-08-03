<template>
  <aside class="app-sidebar" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-brand-row">
      <div class="product-mark"><FileCheck2 :size="20" /></div>
      <strong v-if="!collapsed">DOC AGENT</strong>
      <button class="sidebar-collapse" type="button" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="$emit('toggle')">
        <PanelLeftOpen v-if="collapsed" :size="18" />
        <PanelLeftClose v-else :size="18" />
      </button>
    </div>

    <button class="button button-secondary new-chat-button" type="button" title="新建对话" @click="$emit('new-chat')">
      <Plus :size="18" /><span v-if="!collapsed">新建对话</span>
    </button>

    <div class="sidebar-history">
      <span v-if="!collapsed" class="sidebar-section-label">最近任务</span>
      <div class="history-list">
        <div v-if="loading && !sessions.length" class="sidebar-loading"><Loader2 class="spin" :size="17" /></div>
        <template v-else-if="sessions.length">
          <div v-for="session in sessions" :key="session.session_id" class="history-row" :data-session-id="session.session_id">
            <button
              class="history-item"
              :class="{ active: selectedSessionId === session.session_id }"
              type="button"
              :title="session.title"
              @click="$emit('open-session', session.session_id)"
            >
              <MessageSquareText :size="16" />
              <span v-if="!collapsed"><strong>{{ session.title }}</strong><small>{{ formatRunDate(session.updated_at) }}</small></span>
            </button>
            <button
              v-if="!collapsed"
              class="history-delete"
              type="button"
              title="删除对话"
              :aria-label="`删除对话 ${session.title}`"
              @click="$emit('delete-session', session)"
            ><Trash2 :size="15" /></button>
          </div>
        </template>
        <p v-else-if="!collapsed" class="sidebar-empty">暂无历史任务</p>
      </div>
    </div>

  </aside>
</template>

<script>
import {
  FileCheck2,
  Loader2,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
} from "lucide-vue";

export default {
  name: "AppSidebar",
  components: { FileCheck2, Loader2, MessageSquareText, PanelLeftClose, PanelLeftOpen, Plus, Trash2 },
  props: {
    collapsed: Boolean,
    sessions: { type: Array, default: () => [] },
    selectedSessionId: { type: Number, default: null },
    loading: Boolean,
  },
  methods: {
    formatRunDate(value) {
      if (!value) return "";
      const date = new Date(value);
      const pad = (number) => String(number).padStart(2, "0");
      return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    },
  },
};
</script>
