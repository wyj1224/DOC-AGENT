<template>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <div class="admin-brand">
        <span class="product-mark"><FileCheck2 :size="20" /></span>
        <span>
          <strong>灵枢·规鉴</strong>
          <small>基于大模型的通信工程<br />强制性条文智能检测系统</small>
        </span>
      </div>

      <nav class="admin-nav" aria-label="资料类型">
        <button :class="{ active: activeTab === 'knowledge' }" type="button" @click="activeTab = 'knowledge'">
          <Database :size="19" /><span>知识库</span>
        </button>
        <button :class="{ active: activeTab === 'templates' }" type="button" @click="activeTab = 'templates'">
          <FileText :size="19" /><span>Word 模板</span>
        </button>
        <button :class="{ active: activeTab === 'excel' }" type="button" @click="activeTab = 'excel'">
          <FileSpreadsheet :size="19" /><span>Excel 标准库</span>
        </button>
      </nav>

      <a class="admin-public-link" href="http://127.0.0.1:5174">
        <ArrowLeft :size="17" />返回文档工作台
      </a>
    </aside>

    <main class="admin-main">
      <header class="admin-header">
        <div><span>资料中心</span><h1>{{ currentTitle }}</h1><p>{{ currentDescription }}</p></div>
        <button v-if="activeTab !== 'excel'" class="button button-secondary" type="button" :disabled="refreshing" @click="refreshCurrent">
          <Loader2 v-if="refreshing" class="spin" :size="17" /><RefreshCw v-else :size="17" />刷新
        </button>
      </header>

      <section v-if="activeTab === 'knowledge'" class="admin-section settings-section">
        <form class="settings-upload" @submit.prevent="uploadKnowledgeDocuments">
          <label class="settings-file-picker">
            <Upload :size="18" /><input type="file" multiple @change="knowledgeFilesChanged" />
            <span>{{ fileLabel(knowledgeFiles, "选择知识库文件") }}</span>
          </label>
          <button class="button button-primary" :disabled="loading.knowledgeUpload">
            <Loader2 v-if="loading.knowledgeUpload" class="spin" :size="17" /><Upload v-else :size="17" />解析入库
          </button>
        </form>
        <div class="resource-list admin-resource-list">
          <div v-for="document in knowledgeDocuments" :key="document.document_id" class="resource-row">
            <FileText :size="18" />
            <span><strong>{{ document.file_name }}</strong><small>{{ knowledgeStatusLabel(document.parse_status) }} · {{ document.page_count }} 页 · {{ document.chunk_count }} 个切块</small></span>
            <button class="button button-icon" type="button" title="删除文件" @click="deleteKnowledgeDocument(document)"><Trash2 :size="16" /></button>
          </div>
          <div v-if="!knowledgeDocuments.length" class="resource-empty">暂无知识库文件</div>
        </div>
      </section>

      <section v-if="activeTab === 'templates'" class="admin-section settings-section">
        <form class="settings-upload" @submit.prevent="uploadTemplate">
          <label class="settings-file-picker">
            <Upload :size="18" /><input type="file" accept=".docx" multiple @change="templateFilesChanged" />
            <span>{{ fileLabel(templateFiles, "选择模板 Word") }}</span>
          </label>
          <button class="button button-primary" :disabled="loading.template">
            <Loader2 v-if="loading.template" class="spin" :size="17" /><Upload v-else :size="17" />上传模板
          </button>
        </form>
        <div class="resource-list admin-resource-list template-resource-list">
          <div v-for="template in templateLibrary" :key="template.template_id" class="template-resource">
            <div class="resource-row">
              <FileText :size="18" />
              <span><strong>{{ template.file_name }}</strong><small>{{ template.template_year }} {{ template.template_type_label }} · {{ template.heading_count }} 个标题</small></span>
              <div class="resource-actions">
                <button class="button button-icon" type="button" :title="expandedTemplateId === template.template_id ? '收起标题' : '展开标题'" @click="toggleTemplate(template.template_id)">
                  <ChevronDown v-if="expandedTemplateId === template.template_id" :size="16" /><ChevronRight v-else :size="16" />
                </button>
                <button class="button button-icon" type="button" title="删除模板" @click="deleteTemplate(template)"><Trash2 :size="16" /></button>
              </div>
            </div>
            <div v-if="expandedTemplateId === template.template_id && expandedTemplate" class="template-heading-list">
              <div v-for="heading in expandedTemplate.headings" :key="heading.heading_index" :style="{ paddingLeft: `${(heading.level - 1) * 16 + 10}px` }">
                <span>H{{ heading.level }}</span><strong>{{ heading.title }}</strong>
              </div>
            </div>
          </div>
          <div v-if="!templateLibrary.length" class="resource-empty">暂无 Word 模板</div>
        </div>
      </section>

      <section v-if="activeTab === 'excel'" class="admin-section settings-section">
        <form class="settings-upload excel-upload" @submit.prevent="ingestExcel">
          <label class="settings-file-picker">
            <FileSpreadsheet :size="18" /><input type="file" accept=".xlsx,.xls" @change="excelFileChanged" />
            <span>{{ excelFile ? excelFile.name : "选择 Excel 文件" }}</span>
          </label>
          <label class="replace-option"><input v-model="excelReplace" type="checkbox" /><span>替换现有库</span></label>
          <button class="button button-primary" :disabled="loading.excel">
            <Loader2 v-if="loading.excel" class="spin" :size="17" /><Upload v-else :size="17" />更新标准库
          </button>
        </form>
        <div class="settings-metrics">
          <div class="settings-metric"><span>最近文件</span><strong>{{ excelResult ? excelResult.file_name : "-" }}</strong></div>
          <div class="settings-metric"><span>导入时间</span><strong>{{ excelImportedAt || "-" }}</strong></div>
          <div class="settings-metric"><span>强条记录</span><strong>{{ excelResult && excelResult.clause_chunk_count != null ? excelResult.clause_chunk_count : "-" }}</strong></div>
          <div class="settings-metric"><span>有效性记录</span><strong>{{ excelResult && excelResult.standard_validity_count != null ? excelResult.standard_validity_count : "-" }}</strong></div>
        </div>
        <div class="admin-note"><CircleHelp :size="18" /><span>更新后，公共工作台会直接使用最新的 Excel 标准库。</span></div>
      </section>
    </main>

    <div v-if="toast" class="toast" :class="`toast-${toast.type}`" role="status">
      <CheckCircle2 v-if="toast.type === 'success'" :size="18" /><AlertCircle v-else :size="18" /><span>{{ toast.text }}</span>
    </div>
  </div>
</template>

<script>
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Database,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-vue";

import { errorMessage, request } from "./lib/api";

const titles = {
  knowledge: ["知识库", "维护用于检索问答的业务资料。"],
  templates: ["Word 模板", "维护完整性检查使用的年度与场景模板。"],
  excel: ["Excel 标准库", "更新强制性条文和标准有效性数据。"],
};

export default {
  name: "AdminApp",
  components: {
    AlertCircle, ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, CircleHelp,
    Database, FileCheck2, FileSpreadsheet, FileText, Loader2, RefreshCw, Trash2, Upload,
  },
  data() {
    return {
      activeTab: "knowledge",
      loading: { knowledgeUpload: false, knowledgeDocuments: false, template: false, excel: false },
      knowledgeFiles: [],
      knowledgeDocuments: [],
      templateFiles: [],
      templateLibrary: [],
      expandedTemplateId: null,
      expandedTemplate: null,
      excelFile: null,
      excelReplace: true,
      excelResult: null,
      excelImportedAt: "",
      toast: null,
      toastTimer: null,
    };
  },
  computed: {
    currentTitle() { return titles[this.activeTab][0]; },
    currentDescription() { return titles[this.activeTab][1]; },
    refreshing() { return this.loading.knowledgeDocuments || this.loading.template; },
  },
  created() {
    this.fetchKnowledgeDocuments();
    this.fetchTemplates();
  },
  beforeDestroy() {
    if (this.toastTimer) window.clearTimeout(this.toastTimer);
  },
  methods: {
    showMessage(type, text) {
      this.toast = { type, text };
      if (this.toastTimer) window.clearTimeout(this.toastTimer);
      this.toastTimer = window.setTimeout(() => { this.toast = null; }, 3200);
    },
    refreshCurrent() {
      if (this.activeTab === "knowledge") return this.fetchKnowledgeDocuments();
      if (this.activeTab === "templates") return this.fetchTemplates();
    },
    fileLabel(files, empty) {
      if (!files.length) return empty;
      return files.length === 1 ? files[0].name : `${files.length} 个文件`;
    },
    knowledgeStatusLabel(status) {
      return ({ parsing: "解析中", parsed: "已解析", failed: "解析失败" })[status] || status;
    },
    knowledgeFilesChanged(event) {
      this.knowledgeFiles = Array.from(event.target.files || []);
      event.target.value = "";
    },
    templateFilesChanged(event) {
      this.templateFiles = Array.from(event.target.files || []);
      event.target.value = "";
    },
    excelFileChanged(event) {
      this.excelFile = event.target.files && event.target.files[0] ? event.target.files[0] : null;
      event.target.value = "";
    },
    async uploadKnowledgeDocuments() {
      if (!this.knowledgeFiles.length) return this.showMessage("error", "请先选择知识库文件");
      this.loading.knowledgeUpload = true;
      try {
        const form = new FormData();
        this.knowledgeFiles.forEach((file) => form.append("files", file));
        const data = await request("/knowledge/documents", { method: "POST", body: form });
        this.knowledgeFiles = [];
        await this.fetchKnowledgeDocuments();
        this.showMessage("success", `已将 ${data.count} 个文件写入知识库`);
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.knowledgeUpload = false;
      }
    },
    async fetchKnowledgeDocuments() {
      this.loading.knowledgeDocuments = true;
      try {
        const data = await request("/knowledge/documents?limit=100");
        this.knowledgeDocuments = data.items;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.knowledgeDocuments = false;
      }
    },
    async deleteKnowledgeDocument(document) {
      if (!window.confirm(`确定删除知识库文件“${document.file_name}”吗？`)) return;
      try {
        await request(`/knowledge/documents/${document.document_id}`, { method: "DELETE" });
        await this.fetchKnowledgeDocuments();
        this.showMessage("success", "知识库文件已删除");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      }
    },
    async uploadTemplate() {
      if (!this.templateFiles.length) return this.showMessage("error", "请先选择模板 Word");
      this.loading.template = true;
      try {
        const form = new FormData();
        this.templateFiles.forEach((file) => form.append("files", file));
        const data = await request("/templates/upload", { method: "POST", body: form });
        this.templateFiles = [];
        await this.fetchTemplates();
        this.showMessage("success", `已上传 ${data.count || 1} 个 Word 模板`);
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.template = false;
      }
    },
    async fetchTemplates() {
      this.loading.template = true;
      try {
        const data = await request("/templates?limit=100");
        this.templateLibrary = data.items;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.template = false;
      }
    },
    async toggleTemplate(templateId) {
      if (this.expandedTemplateId === templateId) {
        this.expandedTemplateId = null;
        return;
      }
      this.loading.template = true;
      try {
        this.expandedTemplate = await request(`/templates/${templateId}`);
        this.expandedTemplateId = templateId;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.template = false;
      }
    },
    async deleteTemplate(template) {
      if (!window.confirm(`确定删除模板“${template.file_name}”吗？`)) return;
      try {
        await request(`/templates/${template.template_id}`, { method: "DELETE" });
        if (this.expandedTemplateId === template.template_id) this.expandedTemplateId = null;
        await this.fetchTemplates();
        this.showMessage("success", "模板已删除");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      }
    },
    async ingestExcel() {
      if (!this.excelFile) return this.showMessage("error", "请先选择 Excel 文件");
      this.loading.excel = true;
      try {
        const form = new FormData();
        form.append("file", this.excelFile);
        form.append("sheet", "强条");
        form.append("replace", String(this.excelReplace));
        this.excelResult = await request("/excel/ingest", { method: "POST", body: form });
        this.excelImportedAt = formatDateTime(new Date());
        this.showMessage("success", "Excel 标准库已更新");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.excel = false;
      }
    },
  },
};

function formatDateTime(value) {
  const pad = (number) => String(number).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`;
}
</script>
