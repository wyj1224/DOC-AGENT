<template>
  <aside class="app-sidebar" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-brand-row">
      <div class="product-mark"><FileCheck2 :size="20" /></div>
      <span v-if="!collapsed" class="sidebar-brand-copy">
        <strong>灵枢·规鉴</strong>
        <small>基于大模型的通信工程<br />强制性条文智能检测系统</small>
      </span>
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

    <button class="sidebar-admin-button" type="button" title="资料管理" @click="$emit('open-admin')">
      <Settings :size="17" /><span v-if="!collapsed">资料管理</span>
    </button>
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
  Settings,
  Trash2,
} from "lucide-vue";

export default {
  name: "AppSidebar",
  components: { FileCheck2, Loader2, MessageSquareText, PanelLeftClose, PanelLeftOpen, Plus, Settings, Trash2 },
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
