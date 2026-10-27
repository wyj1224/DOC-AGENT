<template>
  <div class="admin-shell">
    <aside class="admin-sidebar">
      <div class="admin-brand">
        <span class="product-mark"><FileCheck2 :size="20" /></span>
        <span><strong>灵枢·规鉴</strong><small>资料管理中心</small></span>
      </div>

      <nav class="admin-nav" aria-label="资料类型">
        <button :class="{ active: activeTab === 'excel' }" type="button" @click="activeTab = 'excel'">
          <FileSpreadsheet :size="19" /><span>强条标准库</span>
        </button>
        <button :class="{ active: activeTab === 'templates' }" type="button" @click="activeTab = 'templates'">
          <FileText :size="19" /><span>Word 模板库</span>
        </button>
      </nav>

      <button class="admin-public-link" type="button" @click="$emit('close')">
        <ArrowLeft :size="17" />返回 Agent 工作台
      </button>
    </aside>

    <main class="admin-main">
      <header class="admin-header">
        <div><span>资料管理</span><h1>{{ currentTitle }}</h1><p>{{ currentDescription }}</p></div>
        <button class="button button-secondary" type="button" :disabled="refreshing" @click="refreshCurrent">
          <Loader2 v-if="refreshing" class="spin" :size="17" /><RefreshCw v-else :size="17" />刷新
        </button>
      </header>

      <section v-if="activeTab === 'excel'" class="admin-section settings-section">
        <form class="settings-upload excel-upload" @submit.prevent="ingestExcel">
          <label class="settings-file-picker">
            <FileSpreadsheet :size="18" /><input type="file" accept=".xlsx,.xls" @change="excelFileChanged" />
            <span>{{ excelFile ? excelFile.name : "选择强条 Excel" }}</span>
          </label>
          <label class="replace-option"><input v-model="excelReplace" type="checkbox" /><span>替换现有库</span></label>
          <button class="button button-primary" :disabled="loading.excel">
            <Loader2 v-if="loading.excel" class="spin" :size="17" /><Upload v-else :size="17" />更新标准库
          </button>
        </form>

        <div class="settings-metrics">
          <div class="settings-metric"><span>强条记录</span><strong>{{ clauses.length }}</strong></div>
          <div class="settings-metric"><span>标准有效性</span><strong>{{ validityRecords.length }}</strong></div>
          <div class="settings-metric"><span>最近导入</span><strong>{{ excelResult ? excelResult.file_name : "-" }}</strong></div>
          <div class="settings-metric"><span>导入时间</span><strong>{{ excelImportedAt || "-" }}</strong></div>
        </div>

        <div class="library-toolbar">
          <div class="library-tabs">
            <button :class="{ active: libraryView === 'clauses' }" type="button" @click="libraryView = 'clauses'">强制性条文</button>
            <button :class="{ active: libraryView === 'validity' }" type="button" @click="libraryView = 'validity'">标准替代关系</button>
          </div>
          <label class="library-search"><Search :size="16" /><input v-model.trim="searchText" type="search" placeholder="搜索标准号、名称或条文" /></label>
        </div>

        <div v-if="loading.library" class="admin-loading"><Loader2 class="spin" :size="22" />正在读取标准库…</div>
        <div v-else-if="libraryView === 'clauses'" class="library-list">
          <article v-for="item in visibleClauses" :key="item.id" class="library-card">
            <div class="library-card-title"><strong>{{ item.standard_no || "未填标准号" }}<span v-if="item.clause_no"> · {{ item.clause_no }}</span></strong><em>{{ item.mandatory_type || "条文" }}</em></div>
            <h3>{{ item.standard_name || "未填标准名称" }}</h3>
            <p>{{ item.clause_text || item.chunk_text }}</p>
            <small>{{ item.category || "未分类" }}<template v-if="item.applicable_scope"> · {{ item.applicable_scope }}</template></small>
          </article>
          <div v-if="!visibleClauses.length" class="resource-empty">没有匹配的强条记录</div>
          <p v-if="filteredClauses.length > displayLimit" class="library-limit">当前展示前 {{ displayLimit }} 条，请搜索缩小范围。</p>
        </div>
        <div v-else class="library-list">
          <article v-for="item in visibleValidityRecords" :key="item.id" class="library-card validity-card">
            <div class="library-card-title"><strong>{{ item.old_standard_text || "未填原标准" }}</strong><em>替代关系</em></div>
            <p class="replacement-arrow">→ {{ item.new_standard_text || "尚未填写新标准" }}</p>
            <small>发布：{{ item.new_publish_date || "-" }} · 实施：{{ item.new_effective_date || "-" }}</small>
            <p v-if="item.note" class="validity-note">{{ item.note }}</p>
          </article>
          <div v-if="!visibleValidityRecords.length" class="resource-empty">没有匹配的标准替代记录</div>
          <p v-if="filteredValidityRecords.length > displayLimit" class="library-limit">当前展示前 {{ displayLimit }} 条，请搜索缩小范围。</p>
        </div>

        <div class="admin-note"><CircleHelp :size="18" /><span>当前通过 Excel 批量更新。勾选“替换现有库”后，原强条、标准有效性记录及历史检查问题会被替换。</span></div>
      </section>

      <section v-else class="admin-section settings-section">
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
          <div v-if="!templateLibrary.length && !loading.template" class="resource-empty">暂无 Word 模板</div>
        </div>
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
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-vue";

import { adminRequest, errorMessage, request } from "../lib/api";

const titles = {
  excel: ["强条标准库", "查看强制性条文与标准替代关系，通过 Excel 批量更新。"],
  templates: ["Word 模板库", "管理文档完整性检查使用的年度与场景模板。"],
};

export default {
  name: "AdminWorkspace",
  components: {
    AlertCircle, ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, CircleHelp,
    FileCheck2, FileSpreadsheet, FileText, Loader2, RefreshCw, Search, Trash2, Upload,
  },
  data() {
    return {
      activeTab: "excel",
      libraryView: "clauses",
      searchText: "",
      displayLimit: 120,
      loading: { template: false, excel: false, library: false },
      clauses: [],
      validityRecords: [],
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
    refreshing() { return this.loading.library || this.loading.template; },
    filteredClauses() {
      return filterItems(this.clauses, this.searchText, ["standard_no", "standard_name", "clause_no", "clause_text", "category"]);
    },
    visibleClauses() { return this.filteredClauses.slice(0, this.displayLimit); },
    filteredValidityRecords() {
      return filterItems(this.validityRecords, this.searchText, ["old_standard_text", "new_standard_text", "involved_content", "note"]);
    },
    visibleValidityRecords() { return this.filteredValidityRecords.slice(0, this.displayLimit); },
  },
  created() {
    this.fetchLibraries();
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
      return this.activeTab === "excel" ? this.fetchLibraries() : this.fetchTemplates();
    },
    fileLabel(files, empty) {
      if (!files.length) return empty;
      return files.length === 1 ? files[0].name : `${files.length} 个文件`;
    },
    templateFilesChanged(event) {
      this.templateFiles = Array.from(event.target.files || []);
      event.target.value = "";
    },
    excelFileChanged(event) {
      this.excelFile = event.target.files && event.target.files[0] ? event.target.files[0] : null;
      event.target.value = "";
    },
    async fetchLibraries() {
      this.loading.library = true;
      try {
        const [clauses, validity] = await Promise.all([
          request("/excel/clauses"),
          request("/excel/standard-validity"),
        ]);
        this.clauses = clauses.items || [];
        this.validityRecords = validity.items || [];
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.library = false;
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
        this.excelResult = await adminRequest("/excel/ingest", { method: "POST", body: form });
        this.excelImportedAt = formatDateTime(new Date());
        this.excelFile = null;
        await this.fetchLibraries();
        this.showMessage("success", "强条标准库已更新");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      } finally {
        this.loading.excel = false;
      }
    },
    async uploadTemplate() {
      if (!this.templateFiles.length) return this.showMessage("error", "请先选择模板 Word");
      this.loading.template = true;
      try {
        const form = new FormData();
        this.templateFiles.forEach((file) => form.append("files", file));
        const data = await adminRequest("/templates/upload", { method: "POST", body: form });
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
        this.templateLibrary = data.items || [];
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
      try {
        this.expandedTemplate = await request(`/templates/${templateId}`);
        this.expandedTemplateId = templateId;
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      }
    },
    async deleteTemplate(template) {
      if (!window.confirm(`确定删除模板“${template.file_name}”吗？`)) return;
      try {
        await adminRequest(`/templates/${template.template_id}`, { method: "DELETE" });
        if (this.expandedTemplateId === template.template_id) this.expandedTemplateId = null;
        await this.fetchTemplates();
        this.showMessage("success", "模板已删除");
      } catch (error) {
        this.showMessage("error", errorMessage(error));
      }
    },
  },
};

function filterItems(items, searchText, fields) {
  const keyword = searchText.toLowerCase();
  if (!keyword) return items;
  return items.filter((item) => fields.some((field) => String(item[field] || "").toLowerCase().includes(keyword)));
}

function formatDateTime(value) {
  const pad = (number) => String(number).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`;
}
</script>

<style scoped>
.admin-shell { width: 100%; height: 100vh; display: grid; grid-template-columns: 250px minmax(0, 1fr); overflow: auto; background: #f7f8fa; }
.admin-sidebar { position: sticky; top: 0; height: 100vh; padding: 24px 18px; display: flex; flex-direction: column; border-right: 1px solid var(--line); background: #f1f3f5; }
.admin-brand { display: flex; align-items: center; gap: 12px; padding: 2px 8px 24px; }
.admin-brand > span:last-child { display: grid; gap: 3px; }
.admin-brand strong { font-size: 17px; }
.admin-brand small { color: var(--muted); font-size: 11px; }
.admin-nav { display: grid; gap: 8px; }
.admin-nav button, .admin-public-link { width: 100%; min-height: 48px; padding: 0 14px; display: flex; align-items: center; gap: 12px; border: 1px solid transparent; border-radius: 10px; background: transparent; color: var(--muted); font: inherit; font-weight: 650; text-align: left; }
.admin-nav button:hover, .admin-nav button.active { border-color: var(--line); background: #fff; color: var(--text); }
.admin-public-link { margin-top: auto; cursor: pointer; }
.admin-main { min-width: 0; padding: 34px clamp(28px, 5vw, 72px) 56px; }
.admin-header { max-width: 1120px; margin: 0 auto 24px; display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.admin-header span, .admin-header p { color: var(--muted); }
.admin-header span { font-size: 13px; font-weight: 700; }
.admin-header h1 { margin: 7px 0 5px; font-size: 28px; }
.admin-header p { margin: 0; font-size: 14px; }
.admin-section { max-width: 1120px; margin: 0 auto; padding: 24px; border: 1px solid var(--line); border-radius: 16px; background: #fff; box-shadow: 0 8px 30px rgba(20, 24, 32, 0.04); }
.admin-resource-list { margin-top: 20px; max-height: calc(100vh - 250px); overflow-y: auto; }
.library-toolbar { margin-top: 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.library-tabs { display: flex; gap: 4px; padding: 4px; border-radius: 10px; background: var(--surface-muted); }
.library-tabs button { min-height: 34px; padding: 0 12px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-weight: 650; }
.library-tabs button.active { background: #fff; color: var(--text); box-shadow: 0 1px 3px rgba(20, 24, 32, 0.1); }
.library-search { width: min(390px, 45%); min-height: 40px; padding: 0 12px; display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 9px; color: var(--muted); }
.library-search input { width: 100%; border: 0; outline: 0; background: transparent; }
.library-list { margin-top: 16px; display: grid; gap: 10px; }
.library-card { padding: 16px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.library-card-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.library-card-title strong { font-size: 14px; }
.library-card-title em { padding: 3px 7px; border-radius: 999px; color: var(--accent); background: var(--accent-soft); font-size: 11px; font-style: normal; white-space: nowrap; }
.library-card h3 { margin: 8px 0 6px; font-size: 14px; }
.library-card p { margin: 8px 0; color: #4b5563; font-size: 13px; line-height: 1.65; white-space: pre-wrap; }
.library-card small { color: var(--muted); }
.replacement-arrow { color: var(--success) !important; font-weight: 650; }
.validity-note { padding: 8px 10px; border-radius: 7px; background: var(--surface-muted); }
.library-limit, .resource-empty, .admin-loading { color: var(--muted); font-size: 13px; text-align: center; }
.admin-loading { min-height: 180px; display: flex; align-items: center; justify-content: center; gap: 8px; }
.admin-note { margin-top: 20px; padding: 14px 16px; display: flex; align-items: flex-start; gap: 10px; border-radius: 10px; background: #f5f7f9; color: var(--muted); font-size: 13px; line-height: 1.6; }
@media (max-width: 800px) {
  .admin-shell { grid-template-columns: 1fr; }
  .admin-sidebar { position: static; height: auto; padding: 14px; }
  .admin-brand { padding-bottom: 14px; }
  .admin-nav { grid-template-columns: repeat(2, 1fr); }
  .admin-public-link { margin-top: 12px; }
  .admin-main { padding: 24px 14px 36px; }
  .library-toolbar { align-items: stretch; flex-direction: column; }
  .library-search { width: 100%; }
}
</style>
