import {
  ChevronDown,
  Download,
  PanelRightClose,
  ScanText,
  SearchX,
} from "lucide-react";

import { checkScopeLabel, issueTypeLabel, severityLabel } from "../lib/labels";
import { AgentResult, ChatMode, ClauseExtractionResult, IssueScope, IssuesResult, KnowledgeSource, WordEditResult } from "../types";


type Props = {
  open: boolean;
  mode: ChatMode;
  totals: { high: number; warning: number; info: number; total: number };
  activeScope: IssueScope;
  basisIssues: IssuesResult | null;
  bodyIssues: IssuesResult | null;
  completenessIssues: IssuesResult | null;
  currentIssues: IssuesResult | null;
  sources: KnowledgeSource[];
  agentResult: AgentResult | null;
  editResult: WordEditResult | null;
  clauseExtractionResult: ClauseExtractionResult | null;
  onToggle: () => void;
  onScopeChange: (scope: IssueScope) => void;
  onDownloadEdit: (result: WordEditResult) => void;
};


export function ResultPanel(props: Props) {
  if (!props.open) return null;

  return (
    <aside className="result-panel">
      <div className="result-panel-overview">
        <header className="result-header">
          <div>
            <span>{panelTitle(props.mode)}</span>
            <strong>{panelCount(props)}</strong>
          </div>
          <button className="icon-action" type="button" title="收起结果面板" onClick={props.onToggle}>
            <PanelRightClose size={19} />
          </button>
        </header>

        {props.mode === "check" && (
          <>
            <div className="result-summary">
              <SummaryItem label="高风险" value={props.totals.high} tone="high" />
              <SummaryItem label="警告" value={props.totals.warning} tone="warning" />
              <SummaryItem label="提示" value={props.totals.info} tone="info" />
            </div>
            <div className="result-toolbar">
              <div className="result-tabs">
                <ScopeButton scope="basis_excel" active={props.activeScope} count={props.basisIssues?.issue_count ?? 0} onClick={props.onScopeChange} />
                <ScopeButton scope="body_basis" active={props.activeScope} count={props.bodyIssues?.issue_count ?? 0} onClick={props.onScopeChange} />
                <ScopeButton scope="completeness" active={props.activeScope} count={props.completenessIssues?.issue_count ?? 0} onClick={props.onScopeChange} />
              </div>
            </div>
          </>
        )}
      </div>

      <div className="result-panel-scroll">
        {props.mode === "knowledge" ? (
          <KnowledgeSources sources={props.sources} />
        ) : props.mode === "clause_extract" ? (
          <ClauseExtractionPanel result={props.clauseExtractionResult} />
        ) : (
          <>
            {props.editResult && (
              <div className="edit-result-block">
                <div className="edit-result-card">
                  <div>
                    <span>{props.editResult.output_document_id ? "Word 修订副本" : "Word 修改结果"}</span>
                    {props.editResult.output_file_name && <strong>{props.editResult.output_file_name}</strong>}
                    <small>{props.editResult.message}</small>
                    <small>
                      已修改 {props.editResult.applied_count} 处
                      {props.editResult.status === "completed"
                        ? "，复检通过"
                        : props.editResult.remaining_issue_count > 0
                          ? `，仍有 ${props.editResult.remaining_issue_count} 个问题`
                          : "，需人工确认"}
                    </small>
                    <small>
                      LLM 决策 {props.editResult.llm_decision_count} 次 · 工具调用 {props.editResult.tool_call_count} 次 · 修订 {props.editResult.attempt_count} 轮
                    </small>
                  </div>
                  {props.editResult.output_document_id && (
                    <button type="button" onClick={() => props.onDownloadEdit(props.editResult!)}>
                      <Download size={16} />下载副本
                    </button>
                  )}
                </div>
                {props.editResult.agent_trace?.length > 0 && (
                  <details className="edit-agent-trace">
                    <summary>查看 Agent 执行循环</summary>
                    <ol>
                      {props.editResult.agent_trace.map((step) => (
                        <li key={step.step}>
                          <span className={`trace-actor ${step.actor}`}>{step.actor === "llm" ? "LLM" : "工具"}</span>
                          <div>
                            <strong>{step.phase}</strong>
                            <p>{step.summary}</p>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
              </div>
            )}

            <IssueList result={props.currentIssues} />

            {props.agentResult && (
              <details className="trace-details">
                <summary>查看工具执行详情</summary>
                <pre>{JSON.stringify({ tool_plan: props.agentResult.tool_plan, tool_results: props.agentResult.tool_results }, null, 2)}</pre>
              </details>
            )}
          </>
        )}
      </div>
    </aside>
  );
}


function ClauseExtractionPanel({ result }: { result: ClauseExtractionResult | null }) {
  if (!result) return <PanelEmpty title="等待抽取" text="上传 PDF 后，Agent 会自动识别公告、粗体和正文条文。" />;
  return (
    <div className="clause-extraction-result">
      <div className="clause-extraction-summary">
        <ScanText size={20} />
        <div>
          <span>{mandatoryStatusLabel(result.mandatory_status)}</span>
          <strong>{result.file_name}</strong>
          <small>{result.message}</small>
          <small>
            {result.page_count} 页 · LLM 决策 {result.llm_decision_count} 次 · 工具调用 {result.tool_call_count} 次
          </small>
        </div>
      </div>

      <div className="clause-methods">
        {result.detection_methods.map((method) => <span key={method}>{detectionMethodLabel(method)}</span>)}
      </div>

      {result.warnings.length > 0 && (
        <div className="clause-warnings">
          {result.warnings.map((warning) => <p key={warning}>{warning}</p>)}
        </div>
      )}

      {result.agent_trace.length > 0 && (
        <details className="edit-agent-trace">
          <summary>查看强条抽取 Agent Loop</summary>
          <ol>
            {result.agent_trace.map((step) => (
              <li key={step.step}>
                <span className={`trace-actor ${step.actor}`}>{step.actor === "llm" ? "LLM" : "工具"}</span>
                <div><strong>{step.phase}</strong><p>{step.summary}</p></div>
              </li>
            ))}
          </ol>
        </details>
      )}

      <div className="clause-list">
        {result.clauses.length ? result.clauses.map((clause) => (
          <article className="clause-item" key={`${clause.clause_no}-${clause.page_no}`}>
            <div>
              <strong>{clause.clause_no}</strong>
              <span>PDF 第 {clause.page_no} 页 · {detectionMethodLabel(clause.evidence_type)}</span>
            </div>
            <p>{clause.clause_text}</p>
          </article>
        )) : <PanelEmpty title="未识别到强条" text="请结合识别状态和原始 PDF 复核，系统不会把未识别到等同于确定没有。" />}
      </div>
    </div>
  );
}


function panelTitle(mode: ChatMode) {
  if (mode === "check") return "校核结果";
  if (mode === "clause_extract") return "强条抽取";
  return "引用来源";
}


function panelCount(props: Props) {
  if (props.mode === "check") return `${props.totals.total} 个问题`;
  if (props.mode === "clause_extract") return `${props.clauseExtractionResult?.clause_count ?? 0} 条强条`;
  return `${props.sources.length} 条材料`;
}


function mandatoryStatusLabel(status: ClauseExtractionResult["mandatory_status"]) {
  return {
    present: "识别到强制性条文",
    confirmed_none: "PDF 明确说明无强条",
    none_detected: "未识别到强条",
    needs_review: "需要人工复核",
  }[status];
}


function detectionMethodLabel(method: string) {
  return {
    announcement_list: "公告列出",
    bold_rule: "PDF 声明黑体标识",
    vision_announcement: "视觉识别公告条号",
    vision_bold_rule: "视觉识别黑体规则",
    vision_bold_body: "视觉确认黑体正文",
    vision_explicit_none: "视觉确认无强条声明",
    vision_no_evidence: "全页视觉扫描未发现证据",
    body_high_accuracy: "正文页高精度复识别",
    body_cache: "复用同文件有效正文缓存",
    explicit_none: "明确无强条",
    no_evidence: "未发现明确证据",
    announcement_and_body: "公告 + 正文",
    announcement_and_body_ocr_recovered: "公告 + 正文（条号纠偏）",
    announcement_and_bold_body: "公告 + 黑体正文",
    vision_bold_body_and_ocr: "视觉黑体 + 正文 OCR",
  }[method] ?? method;
}


function SummaryItem({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`result-stat ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}


function ScopeButton({
  scope,
  active,
  count,
  onClick,
}: {
  scope: IssueScope;
  active: IssueScope;
  count: number;
  onClick: (scope: IssueScope) => void;
}) {
  return (
    <button className={scope === active ? "active" : ""} type="button" onClick={() => onClick(scope)}>
      <span>{checkScopeLabel(scope)}</span>
      <em>{count}</em>
    </button>
  );
}


function IssueList({ result }: { result: IssuesResult | null }) {
  if (!result) return <PanelEmpty title="等待校核" text="完成文档校核后，问题会显示在这里。" />;
  if (!result.issues.length) return <PanelEmpty title="未发现问题" text="当前分类没有返回问题。" />;
  return (
    <div className="result-issue-list">
      {result.issues.map((issue, index) => (
        <article className={`result-issue severity-${issue.severity}`} key={`${issue.issue_id ?? index}-${issue.issue_type}`}>
          <div className="result-issue-title">
            <strong>{issueTypeLabel(issue.issue_type)}</strong>
            <span>{severityLabel(issue.severity)}</span>
          </div>
          <div className="result-issue-meta">
            <span>{issue.section_title || "未识别章节"}</span>
            <span>段落 {issue.paragraph_index}</span>
          </div>
          <p>{issue.reason}</p>
          {issue.suggestion && <p className="result-suggestion">{issue.suggestion}</p>}
          {issue.original_text && (
            <details>
              <summary><ChevronDown size={14} />查看原文</summary>
              <div>{issue.original_text}</div>
            </details>
          )}
        </article>
      ))}
    </div>
  );
}


function KnowledgeSources({ sources }: { sources: KnowledgeSource[] }) {
  if (!sources.length) return <PanelEmpty title="暂无引用" text="知识库回答生成后会展示命中的材料。" />;
  return (
    <div className="source-list">
      {sources.map((source) => (
        <article className="source-item" key={`${source.document_id}-${source.chunk_index}`}>
          <div>
            <strong>[{source.rank}] {source.source_file}</strong>
            <span>第 {source.page_no} 页 · 相关度 {source.score.toFixed(3)}</span>
          </div>
          <p>{source.text}</p>
        </article>
      ))}
    </div>
  );
}


function PanelEmpty({ title, text }: { title: string; text: string }) {
  return (
    <div className="result-empty">
      <SearchX size={23} />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}
