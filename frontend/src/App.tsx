import { Loader2 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AppSidebar } from "./components/AppSidebar";
import { AuthScreen } from "./components/AuthScreen";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { ResultPanel } from "./components/ResultPanel";
import { SettingsPanel, SettingsTab } from "./components/SettingsPanel";
import { ConfirmDialog, ToastBanner } from "./components/ui";
import {
  clearAccessToken,
  downloadWordDocument,
  errorMessage,
  hasAccessToken,
  request,
  streamAgentCheck,
} from "./lib/api";
import {
  AgentSessionDetail,
  AgentSessionSummary,
  AgentResult,
  AuthUser,
  ChatMessage,
  ChatMode,
  ClauseExtractionResult,
  ExcelIngestResult,
  IssuesResult,
  IssueScope,
  KnowledgeDocumentSummary,
  KnowledgeQueryResult,
  LoadingState,
  RunDetail,
  TemplateSummary,
  TemplateUploadItem,
  TemplateUploadResult,
  Toast,
  WordUploadResult,
  WordEditResult,
} from "./types";


const INITIAL_LOADING: LoadingState = {
  uploadWord: false,
  check: false,
  excel: false,
  template: false,
  issues: false,
  sessions: false,
  sessionDetail: false,
  knowledgeUpload: false,
  knowledgeQuery: false,
  knowledgeDocuments: false,
  clauseExtraction: false,
};


function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    if (!hasAccessToken()) {
      setCheckingAuth(false);
      return;
    }
    void request<AuthUser>("/auth/me")
      .then(setCurrentUser)
      .catch(clearAccessToken)
      .finally(() => setCheckingAuth(false));
  }, []);

  if (checkingAuth) {
    return <div className="app-loading"><Loader2 className="spin" size={28} /></div>;
  }
  if (!currentUser) return <AuthScreen onAuthenticated={setCurrentUser} />;

  return (
    <Workspace
      currentUser={currentUser}
      onLogout={() => {
        clearAccessToken();
        setCurrentUser(null);
      }}
    />
  );
}


function Workspace({ currentUser, onLogout }: { currentUser: AuthUser; onLogout: () => void }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [resultPanelOpen, setResultPanelOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("knowledge");
  const [mode, setMode] = useState<ChatMode>("check");
  const [taskTitle, setTaskTitle] = useState("新对话");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [toast, setToast] = useState<Toast | null>(null);
  const [loading, setLoading] = useState<LoadingState>(INITIAL_LOADING);
  const activeRequestRef = useRef<AbortController | null>(null);

  const [wordFile, setWordFile] = useState<File | null>(null);
  const [wordUpload, setWordUpload] = useState<WordUploadResult | null>(null);
  const [documentId, setDocumentId] = useState<number | "">("");
  const [agentResult, setAgentResult] = useState<AgentResult | null>(null);
  const [editResult, setEditResult] = useState<WordEditResult | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [clauseExtractionResult, setClauseExtractionResult] = useState<ClauseExtractionResult | null>(null);
  const [basisIssues, setBasisIssues] = useState<IssuesResult | null>(null);
  const [bodyIssues, setBodyIssues] = useState<IssuesResult | null>(null);
  const [completenessIssues, setCompletenessIssues] = useState<IssuesResult | null>(null);
  const [activeIssueScope, setActiveIssueScope] = useState<IssueScope>("basis_excel");

  const [sessions, setSessions] = useState<AgentSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [sessionToDelete, setSessionToDelete] = useState<AgentSessionSummary | null>(null);
  const [deletingSession, setDeletingSession] = useState(false);

  const [knowledgeFiles, setKnowledgeFiles] = useState<File[]>([]);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [knowledgeResult, setKnowledgeResult] = useState<KnowledgeQueryResult | null>(null);

  const [templateFiles, setTemplateFiles] = useState<File[]>([]);
  const [templateLibrary, setTemplateLibrary] = useState<TemplateSummary[]>([]);
  const [expandedTemplateId, setExpandedTemplateId] = useState<number | null>(null);
  const [expandedTemplate, setExpandedTemplate] = useState<TemplateUploadItem | null>(null);

  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [excelReplace, setExcelReplace] = useState(true);
  const [excelResult, setExcelResult] = useState<ExcelIngestResult | null>(null);
  const [excelImportedAt, setExcelImportedAt] = useState("");

  const currentIssues = activeIssueScope === "basis_excel"
    ? basisIssues
    : activeIssueScope === "body_basis"
      ? bodyIssues
      : completenessIssues;

  const totals = useMemo(() => {
    const issues = [
      ...(basisIssues?.issues ?? []),
      ...(bodyIssues?.issues ?? []),
      ...(completenessIssues?.issues ?? []),
    ];
    return {
      high: issues.filter((item) => item.severity === "high").length,
      warning: issues.filter((item) => item.severity === "warning").length,
      info: issues.filter((item) => item.severity === "info").length,
      total: (basisIssues?.issue_count ?? 0) + (bodyIssues?.issue_count ?? 0) + (completenessIssues?.issue_count ?? 0),
    };
  }, [basisIssues, bodyIssues, completenessIssues]);

  useEffect(() => {
    void fetchTemplates();
    void fetchKnowledgeDocuments();
    void fetchSessions();
    return () => activeRequestRef.current?.abort();
  }, []);

  function showMessage(type: Toast["type"], text: string) {
    setToast({ type, text });
    window.setTimeout(() => setToast(null), 3200);
  }

  function startNewChat(nextMode: ChatMode = "check") {
    stopResponse();
    setMode(nextMode);
    setTaskTitle("新对话");
    setMessages([]);
    setDraft("");
    setWordFile(null);
    setWordUpload(null);
    setPdfFile(null);
    setDocumentId("");
    setAgentResult(null);
    setEditResult(null);
    setClauseExtractionResult(null);
    setKnowledgeResult(null);
    setBasisIssues(null);
    setBodyIssues(null);
    setCompletenessIssues(null);
    setActiveSessionId(null);
  }

  function changeWordFile(file: File | null) {
    setWordFile(file);
    if (!file || file.name !== wordUpload?.file_name) {
      setWordUpload(null);
      setDocumentId("");
      setEditResult(null);
    }
  }

  function changePdfFile(file: File | null) {
    setPdfFile(file);
    setClauseExtractionResult(null);
  }

  async function sendMessage() {
    if (activeRequestRef.current) return;
    const message = draft.trim() || defaultAttachmentPrompt(
      mode,
      Boolean(wordFile || documentId),
      Boolean(pdfFile || clauseExtractionResult || activeSessionId),
    );
    if (!message) return;
    if (mode === "check" && !wordFile && !documentId) {
      showMessage("error", "请先附加需要校核的 Word 文档");
      return;
    }
    if (mode === "clause_extract" && !pdfFile && !clauseExtractionResult && !activeSessionId) {
      showMessage("error", "请先附加需要自动提取强条的 PDF");
      return;
    }

    setDraft("");
    const attachedName = mode === "clause_extract" ? pdfFile?.name : wordFile?.name;
    setTaskTitle((current) => current === "新对话" ? shortTitle(attachedName || message) : current);
    setMessages((items) => [...items, { id: messageId(), role: "user", content: message }]);

    const controller = new AbortController();
    activeRequestRef.current = controller;
    try {
      if (mode === "check") await runDocumentCheck(message, controller.signal);
      else if (mode === "clause_extract") await runClauseExtraction(message, controller.signal);
      else await runKnowledgeQuery(message, controller.signal);
    } finally {
      if (activeRequestRef.current === controller) activeRequestRef.current = null;
    }
  }

  function stopResponse() {
    activeRequestRef.current?.abort();
  }

  async function runDocumentCheck(message: string, signal: AbortSignal) {
    const assistantId = messageId();
    setMessages((items) => [...items, { id: assistantId, role: "assistant", content: "正在准备文档…", pending: true }]);
    setLoading((value) => ({ ...value, check: true }));
    let answer = "";
    let receivedDelta = false;
    let streamResult: Omit<AgentResult, "answer"> = {};
    let returnedEditResult: WordEditResult | null = null;
    setEditResult(null);

    try {
      let targetDocumentId = documentId || 0;
      if (wordFile && (!wordUpload || wordUpload.file_name !== wordFile.name)) {
        const upload = await uploadWordFile(wordFile, signal);
        targetDocumentId = upload.document_id;
      }

      const form = new FormData();
      form.append("message", message);
      form.append("mode", "check");
      form.append("document_id", String(targetDocumentId));
      if (activeSessionId) form.append("session_id", String(activeSessionId));
      await streamAgentCheck(form, (event) => {
        if (event.type === "error") throw new Error(String(event.data.content || "校核失败"));
        if (event.type === "status") {
          updateChatMessage(assistantId, { content: String(event.data.content || "正在校核…"), pending: true });
        }
        if (event.type === "result") {
          const returnedSessionId = Number(event.data.session_id) || undefined;
          streamResult = {
            session_id: returnedSessionId,
            run_id: Number(event.data.run_id) || undefined,
            tool_plan: event.data.tool_plan,
            tool_results: event.data.tool_results,
          };
          if (returnedSessionId) setActiveSessionId(returnedSessionId);
          returnedEditResult = editResultFromToolResults(event.data.tool_results);
          if (returnedEditResult) {
            setEditResult(returnedEditResult);
            if (returnedEditResult.output_document_id) {
              targetDocumentId = returnedEditResult.output_document_id;
              setDocumentId(targetDocumentId);
              setWordFile(null);
              setWordUpload({
                document_id: targetDocumentId,
                file_name: returnedEditResult.output_file_name,
                parse_status: "parsed",
                reference_count: 0,
                section_count: 0,
                chunk_count: 0,
              });
            }
          }
        }
        if (event.type === "delta") {
          const delta = String(event.data.content || "");
          answer = receivedDelta ? answer + delta : delta;
          receivedDelta = true;
          updateChatMessage(assistantId, { content: answer, pending: true });
        }
        if (event.type === "done") updateChatMessage(assistantId, { content: answer, pending: false });
      }, signal);
      assertNotAborted(signal);

      setAgentResult({ ...streamResult, answer });
      const scopes = returnedEditResult
        ? ["basis_excel", "body_basis"] as IssueScope[]
        : scopesForMessage(message);
      clearInactiveIssues(scopes);
      await Promise.all([
        ...scopes.map((scope) => fetchIssues(scope, targetDocumentId)),
        fetchSessions(),
      ]);
      setResultPanelOpen(true);
      showMessage("success", "文档校核完成");
    } catch (error) {
      if (isAbortError(error)) {
        updateChatMessage(assistantId, { content: stoppedAnswer(answer), pending: false });
        return;
      }
      const text = errorMessage(error);
      updateChatMessage(assistantId, { content: `请求未完成：${text}`, pending: false });
      showMessage("error", text);
    } finally {
      setLoading((value) => ({ ...value, check: false }));
    }
  }

  async function uploadWordFile(file: File, signal?: AbortSignal) {
    setLoading((value) => ({ ...value, uploadWord: true }));
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await request<WordUploadResult>("/word/upload", { method: "POST", body: form, signal });
      setWordUpload(data);
      setDocumentId(data.document_id);
      return data;
    } finally {
      setLoading((value) => ({ ...value, uploadWord: false }));
    }
  }

  async function runClauseExtraction(message: string, signal: AbortSignal) {
    const assistantId = messageId();
    setMessages((items) => [...items, { id: assistantId, role: "assistant", content: "正在自动识别 PDF 中的强制性条文…", pending: true }]);
    setLoading((value) => ({ ...value, clauseExtraction: true }));
    let answer = "";
    let receivedDelta = false;
    let streamResult: Omit<AgentResult, "answer"> = {};
    try {
      const form = new FormData();
      form.append("message", message);
      form.append("mode", "clause_extract");
      if (activeSessionId) form.append("session_id", String(activeSessionId));
      if (pdfFile) form.append("file", pdfFile);
      await streamAgentCheck(form, (event) => {
        if (event.type === "error") throw new Error(String(event.data.content || "强条抽取失败"));
        if (event.type === "status") {
          updateChatMessage(assistantId, { content: String(event.data.content || "正在分析 PDF…"), pending: true });
        }
        if (event.type === "result") {
          const returnedSessionId = Number(event.data.session_id) || undefined;
          streamResult = {
            session_id: returnedSessionId,
            run_id: Number(event.data.run_id) || undefined,
            tool_plan: event.data.tool_plan,
            tool_results: event.data.tool_results,
          };
          if (returnedSessionId) setActiveSessionId(returnedSessionId);
          const extraction = clauseExtractionResultFromToolResults(event.data.tool_results);
          if (extraction) {
            setClauseExtractionResult(extraction);
            setPdfFile(null);
          }
        }
        if (event.type === "delta") {
          const delta = String(event.data.content || "");
          answer = receivedDelta ? answer + delta : delta;
          receivedDelta = true;
          updateChatMessage(assistantId, { content: answer, pending: true });
        }
        if (event.type === "done") updateChatMessage(assistantId, { content: answer, pending: false });
      }, signal);
      assertNotAborted(signal);
      setAgentResult({ ...streamResult, answer });
      await fetchSessions();
      setResultPanelOpen(true);
      showMessage("success", "强条抽取完成");
    } catch (error) {
      if (isAbortError(error)) {
        updateChatMessage(assistantId, { content: stoppedAnswer(answer), pending: false });
        return;
      }
      const text = errorMessage(error);
      updateChatMessage(assistantId, { content: `请求未完成：${text}`, pending: false });
      showMessage("error", text);
    } finally {
      setLoading((value) => ({ ...value, clauseExtraction: false }));
    }
  }

  async function runKnowledgeQuery(question: string, signal: AbortSignal) {
    const assistantId = messageId();
    setMessages((items) => [...items, { id: assistantId, role: "assistant", content: "正在检索知识库…", pending: true }]);
    setLoading((value) => ({ ...value, knowledgeQuery: true }));
    let answer = "";
    let receivedDelta = false;
    try {
      const form = new FormData();
      form.append("message", question);
      form.append("mode", "knowledge");
      if (activeSessionId) form.append("session_id", String(activeSessionId));
      await streamAgentCheck(form, (event) => {
        if (event.type === "error") throw new Error(String(event.data.content || "知识库查询失败"));
        if (event.type === "status") {
          updateChatMessage(assistantId, { content: String(event.data.content || "正在检索知识库…"), pending: true });
        }
        if (event.type === "result") {
          const returnedSessionId = Number(event.data.session_id) || undefined;
          if (returnedSessionId) setActiveSessionId(returnedSessionId);
          const knowledge = knowledgeResultFromToolResults(event.data.tool_results);
          if (knowledge) setKnowledgeResult(knowledge);
        }
        if (event.type === "delta") {
          const delta = String(event.data.content || "");
          answer = receivedDelta ? answer + delta : delta;
          receivedDelta = true;
          updateChatMessage(assistantId, { content: answer, pending: true });
        }
        if (event.type === "done") updateChatMessage(assistantId, { content: answer, pending: false });
      }, signal);
      assertNotAborted(signal);
      await fetchSessions();
      setResultPanelOpen(true);
    } catch (error) {
      if (isAbortError(error)) {
        updateChatMessage(assistantId, { content: stoppedAnswer(answer), pending: false });
        return;
      }
      const text = errorMessage(error);
      updateChatMessage(assistantId, { content: `请求未完成：${text}`, pending: false });
      showMessage("error", text);
    } finally {
      setLoading((value) => ({ ...value, knowledgeQuery: false }));
    }
  }

  function updateChatMessage(id: string, changes: Partial<ChatMessage>) {
    setMessages((items) => items.map((item) => item.id === id ? { ...item, ...changes } : item));
  }

  async function fetchIssues(scope: IssueScope, targetDocumentId = Number(documentId)) {
    if (!targetDocumentId) return;
    setLoading((value) => ({ ...value, issues: true }));
    try {
      const data = await request<IssuesResult>(`/word/issues?document_id=${targetDocumentId}&check_scope=${scope}&issue_limit=0`);
      if (scope === "basis_excel") setBasisIssues(data);
      if (scope === "body_basis") setBodyIssues(data);
      if (scope === "completeness") setCompletenessIssues(data);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, issues: false }));
    }
  }

  function clearInactiveIssues(scopes: IssueScope[]) {
    if (!scopes.includes("basis_excel")) setBasisIssues(null);
    if (!scopes.includes("body_basis")) setBodyIssues(null);
    if (!scopes.includes("completeness")) setCompletenessIssues(null);
    setActiveIssueScope(scopes[0]);
  }

  async function fetchSessions() {
    setLoading((value) => ({ ...value, sessions: true }));
    try {
      const data = await request<{ count: number; items: AgentSessionSummary[] }>("/agent/sessions?limit=30");
      setSessions(data.items);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, sessions: false }));
    }
  }

  async function openSession(sessionId: number) {
    setLoading((value) => ({ ...value, sessionDetail: true }));
    try {
      const data = await request<AgentSessionDetail>(`/agent/sessions/${sessionId}`);
      const run = data.last_run_id
        ? await request<RunDetail>(`/agent/runs/${data.last_run_id}`)
        : null;
      const checkMode = Boolean(data.active_document_id);
      const clauseMode = Boolean(data.active_clause_extraction_run_id);

      setActiveSessionId(data.session_id);
      setMode(clauseMode ? "clause_extract" : checkMode ? "check" : "knowledge");
      setTaskTitle(data.title);
      setDocumentId(data.active_document_id || "");
      setWordFile(null);
      setPdfFile(null);
      setWordUpload(data.active_document_id && data.document_file_name ? {
        document_id: data.active_document_id,
        file_name: data.document_file_name,
        parse_status: "parsed",
        reference_count: 0,
        section_count: 0,
        chunk_count: 0,
      } : null);
      setMessages(data.messages.map((item, index) => ({
        id: `${data.session_id}-${index}-${item.created_at}`,
        role: item.role,
        content: item.content,
      })));
      setAgentResult(run ? {
        session_id: data.session_id,
        run_id: run.run_id,
        tool_plan: run.tool_plan,
        tool_results: run.tool_results,
        answer: run.answer,
      } : null);
      setKnowledgeResult(run ? knowledgeResultFromToolResults(run.tool_results) : null);
      setEditResult(run ? editResultFromToolResults(run.tool_results) : null);
      setClauseExtractionResult(run ? clauseExtractionResultFromToolResults(run.tool_results) : null);
      if (data.active_document_id && !clauseMode) {
        await Promise.all([
          fetchIssues("basis_excel", data.active_document_id),
          fetchIssues("body_basis", data.active_document_id),
          fetchIssues("completeness", data.active_document_id),
        ]);
      } else {
        setBasisIssues(null);
        setBodyIssues(null);
        setCompletenessIssues(null);
      }
      setResultPanelOpen(true);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, sessionDetail: false }));
    }
  }

  async function deleteSession() {
    if (!sessionToDelete) return;
    const target = sessionToDelete;
    setDeletingSession(true);
    try {
      await request(`/agent/sessions/${target.session_id}`, { method: "DELETE" });
      setSessions((items) => items.filter((item) => item.session_id !== target.session_id));
      if (activeSessionId === target.session_id) startNewChat("check");
      setSessionToDelete(null);
      showMessage("success", "对话已删除");
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setDeletingSession(false);
    }
  }

  async function uploadKnowledgeDocuments(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!knowledgeFiles.length) return showMessage("error", "请先选择知识库文件");
    setLoading((value) => ({ ...value, knowledgeUpload: true }));
    try {
      const form = new FormData();
      knowledgeFiles.forEach((file) => form.append("files", file));
      const data = await request<{ count: number }>("/knowledge/documents", { method: "POST", body: form });
      setKnowledgeFiles([]);
      await fetchKnowledgeDocuments();
      showMessage("success", `已将 ${data.count} 个文件写入知识库`);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, knowledgeUpload: false }));
    }
  }

  async function fetchKnowledgeDocuments() {
    setLoading((value) => ({ ...value, knowledgeDocuments: true }));
    try {
      const data = await request<{ count: number; items: KnowledgeDocumentSummary[] }>("/knowledge/documents?limit=100");
      setKnowledgeDocuments(data.items);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, knowledgeDocuments: false }));
    }
  }

  async function deleteKnowledgeDocument(document: KnowledgeDocumentSummary) {
    if (!window.confirm(`确定删除知识库文件“${document.file_name}”吗？`)) return;
    try {
      await request(`/knowledge/documents/${document.document_id}`, { method: "DELETE" });
      await fetchKnowledgeDocuments();
      showMessage("success", "知识库文件已删除");
    } catch (error) {
      showMessage("error", errorMessage(error));
    }
  }

  async function uploadTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!templateFiles.length) return showMessage("error", "请先选择模板 Word");
    setLoading((value) => ({ ...value, template: true }));
    try {
      const form = new FormData();
      templateFiles.forEach((file) => form.append("files", file));
      const data = await request<TemplateUploadResult>("/templates/upload", { method: "POST", body: form });
      setTemplateFiles([]);
      await fetchTemplates();
      showMessage("success", `已上传 ${data.count ?? 1} 个 Word 模板`);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, template: false }));
    }
  }

  async function fetchTemplates() {
    try {
      const data = await request<{ count: number; items: TemplateSummary[] }>("/templates?limit=100");
      setTemplateLibrary(data.items);
    } catch (error) {
      showMessage("error", errorMessage(error));
    }
  }

  async function toggleTemplate(templateId: number) {
    if (expandedTemplateId === templateId) return setExpandedTemplateId(null);
    setLoading((value) => ({ ...value, template: true }));
    try {
      const data = await request<TemplateUploadItem>(`/templates/${templateId}`);
      setExpandedTemplate(data);
      setExpandedTemplateId(templateId);
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, template: false }));
    }
  }

  async function deleteTemplate(template: TemplateSummary) {
    if (!window.confirm(`确定删除模板“${template.file_name}”吗？`)) return;
    try {
      await request(`/templates/${template.template_id}`, { method: "DELETE" });
      if (expandedTemplateId === template.template_id) setExpandedTemplateId(null);
      await fetchTemplates();
      showMessage("success", "模板已删除");
    } catch (error) {
      showMessage("error", errorMessage(error));
    }
  }

  async function ingestExcel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!excelFile) return showMessage("error", "请先选择 Excel 文件");
    setLoading((value) => ({ ...value, excel: true }));
    try {
      const form = new FormData();
      form.append("file", excelFile);
      form.append("sheet", "强条");
      form.append("replace", String(excelReplace));
      const data = await request<ExcelIngestResult>("/excel/ingest", { method: "POST", body: form });
      setExcelResult(data);
      setExcelImportedAt(formatDateTime(new Date()));
      showMessage("success", "Excel 标准库已更新");
    } catch (error) {
      showMessage("error", errorMessage(error));
    } finally {
      setLoading((value) => ({ ...value, excel: false }));
    }
  }

  return (
    <div className={`doc-agent-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${resultPanelOpen ? "results-open" : ""}`}>
      <AppSidebar
        collapsed={sidebarCollapsed}
        currentUser={currentUser}
        sessions={sessions}
        selectedSessionId={activeSessionId ?? undefined}
        loading={loading.sessions || loading.sessionDetail}
        onToggle={() => setSidebarCollapsed((value) => !value)}
        onNewChat={() => startNewChat("check")}
        onOpenSession={(sessionId) => void openSession(sessionId)}
        onDeleteSession={setSessionToDelete}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <ChatWorkspace
        title={taskTitle}
        mode={mode}
        messages={messages}
        draft={draft}
        attachedFile={mode === "clause_extract" ? pdfFile : wordFile}
        wordUpload={wordUpload}
        clauseFileName={clauseExtractionResult?.file_name ?? ""}
        sending={loading.check || loading.uploadWord || loading.knowledgeQuery || loading.clauseExtraction}
        resultPanelOpen={resultPanelOpen}
        onModeChange={startNewChat}
        onDraftChange={setDraft}
        onFileChange={(file) => mode === "clause_extract" ? changePdfFile(file) : changeWordFile(file)}
        onSend={() => void sendMessage()}
        onStop={stopResponse}
        onQuickPrompt={setDraft}
        onOpenResults={() => setResultPanelOpen(true)}
      />

      <ResultPanel
        open={resultPanelOpen}
        mode={mode}
        totals={totals}
        activeScope={activeIssueScope}
        basisIssues={basisIssues}
        bodyIssues={bodyIssues}
        completenessIssues={completenessIssues}
        currentIssues={currentIssues}
        sources={knowledgeResult?.sources ?? []}
        agentResult={agentResult}
        editResult={editResult}
        clauseExtractionResult={clauseExtractionResult}
        onToggle={() => setResultPanelOpen((value) => !value)}
        onScopeChange={setActiveIssueScope}
        onDownloadEdit={(result) => {
          if (!result.output_document_id) return;
          void downloadWordDocument(result.output_document_id, result.output_file_name)
            .catch((error) => showMessage("error", errorMessage(error)));
        }}
      />

      {toast && <ToastBanner toast={toast} />}

      {sessionToDelete && (
        <ConfirmDialog
          title="确认删除对话？"
          description={`删除“${sessionToDelete.title}”后，这条历史对话将无法恢复。已上传文档和校核问题不会被删除。`}
          confirmLabel="删除对话"
          busy={deletingSession}
          onCancel={() => !deletingSession && setSessionToDelete(null)}
          onConfirm={() => void deleteSession()}
        />
      )}

      <SettingsPanel
        open={settingsOpen}
        activeTab={settingsTab}
        currentUser={currentUser}
        loading={loading}
        knowledgeFiles={knowledgeFiles}
        knowledgeDocuments={knowledgeDocuments}
        templateFiles={templateFiles}
        templateLibrary={templateLibrary}
        expandedTemplateId={expandedTemplateId}
        expandedTemplate={expandedTemplate}
        excelFile={excelFile}
        excelReplace={excelReplace}
        excelResult={excelResult}
        excelImportedAt={excelImportedAt}
        onClose={() => setSettingsOpen(false)}
        onTabChange={setSettingsTab}
        onKnowledgeFilesChange={setKnowledgeFiles}
        onKnowledgeUpload={(event) => void uploadKnowledgeDocuments(event)}
        onKnowledgeRefresh={() => void fetchKnowledgeDocuments()}
        onKnowledgeDelete={(document) => void deleteKnowledgeDocument(document)}
        onTemplateFilesChange={setTemplateFiles}
        onTemplateUpload={(event) => void uploadTemplate(event)}
        onTemplateRefresh={() => void fetchTemplates()}
        onTemplateToggle={(templateId) => void toggleTemplate(templateId)}
        onTemplateDelete={(template) => void deleteTemplate(template)}
        onExcelFileChange={setExcelFile}
        onExcelReplaceChange={setExcelReplace}
        onExcelUpload={(event) => void ingestExcel(event)}
        onLogout={onLogout}
      />
    </div>
  );
}


function scopesForMessage(message: string): IssueScope[] {
  if (message === "只检查依据章节有没有问题") return ["basis_excel"];
  if (message === "检查正文和依据章节有没有冲突") return ["body_basis"];
  if (message === "只检查正文完整性有没有问题") return ["completeness"];
  return ["basis_excel", "body_basis", "completeness"];
}


function knowledgeResultFromToolResults(value: unknown): KnowledgeQueryResult | null {
  if (!Array.isArray(value)) return null;
  const item = (value as Array<{ tool?: string; result?: KnowledgeQueryResult }>).find(
    (entry) => entry.tool === "knowledge_query_tool",
  );
  return item?.result ?? null;
}


function editResultFromToolResults(value: unknown): WordEditResult | null {
  if (!Array.isArray(value)) return null;
  const item = (value as Array<{ tool?: string; result?: WordEditResult }>).find(
    (entry) => entry.tool === "word_edit_result" || entry.tool === "fix_consistency_issues_tool",
  );
  return item?.result ?? null;
}


function clauseExtractionResultFromToolResults(value: unknown): ClauseExtractionResult | null {
  if (!Array.isArray(value)) return null;
  const item = (value as Array<{ tool?: string; result?: ClauseExtractionResult }>).find(
    (entry) => entry.tool === "clause_extraction_result",
  );
  return item?.result ?? null;
}


function defaultAttachmentPrompt(mode: ChatMode, hasWord: boolean, hasClauseDocument: boolean) {
  if (mode === "check" && hasWord) return "请全面检查这个文档有没有问题";
  if (mode === "clause_extract" && hasClauseDocument) return "请自动识别并提取这份 PDF 中的全部强制性条文";
  return "";
}


function assertNotAborted(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException("已停止回答", "AbortError");
}


function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError";
}


function stoppedAnswer(answer: string) {
  return answer ? `${answer}\n\n已停止回答。` : "已停止回答。";
}


function shortTitle(value: string) {
  const clean = value.replace(/\.(docx|pdf)$/i, "").trim();
  return clean.length > 30 ? `${clean.slice(0, 30)}…` : clean;
}


function messageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


function formatDateTime(value: Date) {
  const pad = (number: number) => String(number).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`;
}


export default App;
