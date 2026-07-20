import {
  ChevronDown,
  ChevronRight,
  Database,
  FileSpreadsheet,
  FileText,
  LogOut,
  RefreshCw,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { FormEvent, ReactNode } from "react";

import { knowledgeStatusLabel } from "../lib/labels";
import {
  AuthUser,
  ExcelIngestResult,
  KnowledgeDocumentSummary,
  LoadingState,
  TemplateSummary,
  TemplateUploadItem,
} from "../types";
import { Button, LoadingIcon } from "./ui";


export type SettingsTab = "knowledge" | "templates" | "excel" | "account";

type Props = {
  open: boolean;
  activeTab: SettingsTab;
  currentUser: AuthUser;
  loading: LoadingState;
  knowledgeFiles: File[];
  knowledgeDocuments: KnowledgeDocumentSummary[];
  templateFiles: File[];
  templateLibrary: TemplateSummary[];
  expandedTemplateId: number | null;
  expandedTemplate: TemplateUploadItem | null;
  excelFile: File | null;
  excelReplace: boolean;
  excelResult: ExcelIngestResult | null;
  excelImportedAt: string;
  onClose: () => void;
  onTabChange: (tab: SettingsTab) => void;
  onKnowledgeFilesChange: (files: File[]) => void;
  onKnowledgeUpload: (event: FormEvent<HTMLFormElement>) => void;
  onKnowledgeRefresh: () => void;
  onKnowledgeDelete: (document: KnowledgeDocumentSummary) => void;
  onTemplateFilesChange: (files: File[]) => void;
  onTemplateUpload: (event: FormEvent<HTMLFormElement>) => void;
  onTemplateRefresh: () => void;
  onTemplateToggle: (templateId: number) => void;
  onTemplateDelete: (template: TemplateSummary) => void;
  onExcelFileChange: (file: File | null) => void;
  onExcelReplaceChange: (value: boolean) => void;
  onExcelUpload: (event: FormEvent<HTMLFormElement>) => void;
  onLogout: () => void;
};


export function SettingsPanel(props: Props) {
  if (!props.open) return null;
  return (
    <div className="settings-layer">
      <button className="settings-backdrop" type="button" aria-label="关闭设置" onClick={props.onClose} />
      <aside className="settings-drawer">
        <header className="settings-header">
          <div>
            <span>工作区设置</span>
            <strong>资料库与账号</strong>
          </div>
          <button className="icon-action" type="button" title="关闭" onClick={props.onClose}><X size={19} /></button>
        </header>

        <nav className="settings-tabs" aria-label="设置分类">
          <SettingsTabButton active={props.activeTab === "knowledge"} icon={<Database size={17} />} label="知识库" onClick={() => props.onTabChange("knowledge")} />
          <SettingsTabButton active={props.activeTab === "templates"} icon={<FileText size={17} />} label="Word 模板" onClick={() => props.onTabChange("templates")} />
          <SettingsTabButton active={props.activeTab === "excel"} icon={<FileSpreadsheet size={17} />} label="Excel 标准库" onClick={() => props.onTabChange("excel")} />
          <SettingsTabButton active={props.activeTab === "account"} icon={<UserRound size={17} />} label="账号" onClick={() => props.onTabChange("account")} />
        </nav>

        <div className="settings-content">
          {props.activeTab === "knowledge" && (
            <KnowledgeSettings {...props} />
          )}
          {props.activeTab === "templates" && (
            <TemplateSettings {...props} />
          )}
          {props.activeTab === "excel" && (
            <ExcelSettings {...props} />
          )}
          {props.activeTab === "account" && (
            <AccountSettings user={props.currentUser} onLogout={props.onLogout} />
          )}
        </div>
      </aside>
    </div>
  );
}


function SettingsTabButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return <button className={active ? "active" : ""} type="button" onClick={onClick}>{icon}<span>{label}</span></button>;
}


function KnowledgeSettings(props: Props) {
  return (
    <section className="settings-section">
      <div className="settings-section-heading">
        <div><h2>知识库</h2><p>上传用于检索问答的业务资料。</p></div>
        <Button variant="icon" title="刷新知识库" icon={props.loading.knowledgeDocuments ? <LoadingIcon /> : <RefreshCw size={17} />} onClick={props.onKnowledgeRefresh} />
      </div>
      <form className="settings-upload" onSubmit={props.onKnowledgeUpload}>
        <label className="settings-file-picker">
          <Upload size={18} />
          <input type="file" multiple onChange={(event) => props.onKnowledgeFilesChange(Array.from(event.target.files ?? []))} />
          <span>{fileLabel(props.knowledgeFiles, "选择知识库文件")}</span>
        </label>
        <Button variant="primary" disabled={props.loading.knowledgeUpload} icon={props.loading.knowledgeUpload ? <LoadingIcon /> : <Upload size={17} />}>解析入库</Button>
      </form>
      <div className="resource-list">
        {props.knowledgeDocuments.length ? props.knowledgeDocuments.map((document) => (
          <div className="resource-row" key={document.document_id}>
            <FileText size={17} />
            <span><strong>{document.file_name}</strong><small>{knowledgeStatusLabel(document.parse_status)} · {document.page_count} 页 · {document.chunk_count} 个切块</small></span>
            <Button variant="icon" title="删除文件" icon={<Trash2 size={16} />} onClick={() => props.onKnowledgeDelete(document)} />
          </div>
        )) : <ResourceEmpty text="暂无知识库文件" />}
      </div>
    </section>
  );
}


function TemplateSettings(props: Props) {
  return (
    <section className="settings-section">
      <div className="settings-section-heading">
        <div><h2>Word 模板库</h2><p>模板用于提取标题并执行完整性检查。</p></div>
        <Button variant="icon" title="刷新模板" icon={<RefreshCw size={17} />} onClick={props.onTemplateRefresh} />
      </div>
      <form className="settings-upload" onSubmit={props.onTemplateUpload}>
        <label className="settings-file-picker">
          <Upload size={18} />
          <input type="file" accept=".docx" multiple onChange={(event) => props.onTemplateFilesChange(Array.from(event.target.files ?? []))} />
          <span>{fileLabel(props.templateFiles, "选择模板 Word")}</span>
        </label>
        <Button variant="primary" disabled={props.loading.template} icon={props.loading.template ? <LoadingIcon /> : <Upload size={17} />}>上传模板</Button>
      </form>
      <div className="resource-list template-resource-list">
        {props.templateLibrary.length ? props.templateLibrary.map((template) => {
          const expanded = props.expandedTemplateId === template.template_id;
          return (
            <div className="template-resource" key={template.template_id}>
              <div className="resource-row">
                <FileText size={17} />
                <span><strong>{template.file_name}</strong><small>{template.template_year} {template.template_type_label} · {template.heading_count} 个标题</small></span>
                <div className="resource-actions">
                  <Button variant="icon" title={expanded ? "收起标题" : "展开标题"} icon={expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />} onClick={() => props.onTemplateToggle(template.template_id)} />
                  <Button variant="icon" title="删除模板" icon={<Trash2 size={16} />} onClick={() => props.onTemplateDelete(template)} />
                </div>
              </div>
              {expanded && props.expandedTemplate?.template_id === template.template_id && (
                <div className="template-heading-list">
                  {props.expandedTemplate.headings.map((heading) => (
                    <div style={{ paddingLeft: `${(heading.level - 1) * 16 + 10}px` }} key={heading.heading_index}>
                      <span>H{heading.level}</span><strong>{heading.title}</strong>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        }) : <ResourceEmpty text="暂无 Word 模板" />}
      </div>
    </section>
  );
}


function ExcelSettings(props: Props) {
  return (
    <section className="settings-section">
      <div className="settings-section-heading"><div><h2>Excel 标准库</h2><p>导入强制性条文和标准有效性数据。</p></div></div>
      <form className="settings-upload excel-upload" onSubmit={props.onExcelUpload}>
        <label className="settings-file-picker">
          <FileSpreadsheet size={18} />
          <input type="file" accept=".xlsx,.xls" onChange={(event) => props.onExcelFileChange(event.target.files?.[0] ?? null)} />
          <span>{props.excelFile?.name ?? "选择 Excel 文件"}</span>
        </label>
        <label className="replace-option"><input type="checkbox" checked={props.excelReplace} onChange={(event) => props.onExcelReplaceChange(event.target.checked)} /><span>替换现有库</span></label>
        <Button variant="primary" disabled={props.loading.excel} icon={props.loading.excel ? <LoadingIcon /> : <Upload size={17} />}>更新标准库</Button>
      </form>
      <div className="settings-metrics">
        <Metric label="最近文件" value={props.excelResult?.file_name ?? "-"} />
        <Metric label="导入时间" value={props.excelImportedAt || "-"} />
        <Metric label="强条记录" value={props.excelResult?.clause_chunk_count ?? "-"} />
        <Metric label="有效性记录" value={props.excelResult?.standard_validity_count ?? "-"} />
      </div>
    </section>
  );
}


function AccountSettings({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  return (
    <section className="settings-section account-settings">
      <div className="account-avatar">{(user.display_name || user.username).slice(0, 1).toUpperCase()}</div>
      <div><h2>{user.display_name || user.username}</h2><p>@{user.username}</p></div>
      <Button variant="danger" icon={<LogOut size={17} />} onClick={onLogout}>退出登录</Button>
    </section>
  );
}


function ResourceEmpty({ text }: { text: string }) {
  return <div className="resource-empty">{text}</div>;
}


function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="settings-metric"><span>{label}</span><strong>{value}</strong></div>;
}


function fileLabel(files: File[], empty: string) {
  if (!files.length) return empty;
  return files.length === 1 ? files[0].name : `${files.length} 个文件`;
}
