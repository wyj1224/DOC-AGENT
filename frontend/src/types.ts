export type AuthUser = {
  id: number;
  username: string;
  display_name: string;
};

export type AuthResult = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export type ChatMode = "check" | "clause_extract" | "knowledge";
export type IssueScope = "basis_excel" | "body_basis" | "completeness";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
};

export type WordUploadResult = {
  document_id: number;
  file_name: string;
  parse_status: string;
  reference_count: number;
  section_count: number;
  chunk_count: number;
};

export type ExcelIngestResult = {
  file_name: string;
  sheet: string;
  replace: boolean;
  excel_item_count?: number;
  clause_chunk_count?: number;
  standard_only_count?: number;
  standard_validity_count?: number;
};

export type TemplateHeading = {
  heading_index: number;
  paragraph_index: number;
  level: number;
  heading_no: string;
  title: string;
  full_title: string;
};

export type TemplateSummary = {
  template_id: number;
  file_name: string;
  template_year: number;
  template_type: string;
  template_type_label: string;
  heading_count: number;
  created_at?: string;
};

export type TemplateUploadItem = TemplateSummary & {
  headings: TemplateHeading[];
};

export type TemplateUploadResult = TemplateSummary & {
  count?: number;
  items?: TemplateSummary[];
};

export type KnowledgeDocumentSummary = {
  document_id: number;
  file_name: string;
  file_type: string;
  parse_status: string;
  page_count: number;
  chunk_count: number;
  error_message: string;
  created_at?: string;
};

export type KnowledgeSource = {
  rank: number;
  score: number;
  document_id: number;
  source_file: string;
  page_no: number;
  chunk_index: number;
  text: string;
};

export type KnowledgeQueryResult = {
  question: string;
  answer: string;
  sources: KnowledgeSource[];
  weights: { keyword: number; dense: number };
};

export type AgentResult = {
  session_id?: number;
  run_id?: number;
  tool_plan?: unknown;
  tool_results?: unknown;
  answer: string;
};

export type WordEditResult = {
  status: "completed" | "partial";
  source_document_id: number;
  document_id: number;
  output_document_id: number | null;
  output_file_name: string;
  download_url: string;
  edit_run_id: number | null;
  attempt_count: number;
  applied_count: number;
  failed_count: number;
  remaining_issue_count: number;
  llm_decision_count: number;
  tool_call_count: number;
  agent_trace: AgentTraceStep[];
  message: string;
};

export type AgentTraceStep = {
  step: number;
  phase: string;
  actor: "llm" | "tool";
  name: string;
  summary: string;
  output: Record<string, unknown>;
};

export type ExtractedClause = {
  clause_no: string;
  clause_text: string;
  page_no: number;
  evidence_type: string;
  confidence: number;
};

export type ClauseExtractionResult = {
  status: "completed" | "partial";
  extraction_run_id: number;
  file_name: string;
  mandatory_status: "present" | "confirmed_none" | "none_detected" | "needs_review";
  detection_methods: string[];
  page_count: number;
  clause_count: number;
  clauses: ExtractedClause[];
  missing_clause_nos: string[];
  warnings: string[];
  llm_decision_count: number;
  tool_call_count: number;
  agent_trace: AgentTraceStep[];
  message: string;
};

export type Issue = {
  issue_id?: number;
  issue_type: string;
  severity: string;
  check_scope: string;
  section_title: string;
  paragraph_index: number;
  standard_no: string;
  standard_name: string;
  clause_no: string;
  original_text: string;
  reason: string;
  suggestion: string;
};

export type IssuesResult = {
  document_id: number;
  check_scope: string;
  issue_count: number;
  returned_issue_count: number;
  issues: Issue[];
};

export type RunSummary = {
  run_id: number;
  document_id: number | null;
  document_file_name: string;
  status: string;
  issue_count: number;
  duration_ms: number;
  started_at: string;
  finished_at: string | null;
  user_message: string;
};

export type RunDetail = RunSummary & {
  tool_plan?: unknown;
  tool_results?: unknown;
  answer: string;
  error_message: string;
};

export type AgentSessionMessage = {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  run_id?: number;
};

export type AgentSessionSummary = {
  session_id: number;
  title: string;
  active_document_id: number | null;
  document_file_name: string;
  active_clause_extraction_run_id: number | null;
  clause_extraction_file_name: string;
  last_run_id: number | null;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type AgentSessionDetail = AgentSessionSummary & {
  messages: AgentSessionMessage[];
  summary: string;
  summarized_message_count: number;
  last_check_run_id: number | null;
};

export type Toast = {
  type: "success" | "error" | "info";
  text: string;
};

export type LoadingState = {
  uploadWord: boolean;
  check: boolean;
  excel: boolean;
  template: boolean;
  issues: boolean;
  sessions: boolean;
  sessionDetail: boolean;
  knowledgeUpload: boolean;
  knowledgeQuery: boolean;
  knowledgeDocuments: boolean;
  clauseExtraction: boolean;
};
