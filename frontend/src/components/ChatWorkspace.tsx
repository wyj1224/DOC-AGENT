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
} from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useRef } from "react";

import { ChatMessage, ChatMode, WordUploadResult } from "../types";
import { ReportMarkdown } from "./ui";


type Props = {
  title: string;
  mode: ChatMode;
  messages: ChatMessage[];
  draft: string;
  attachedFile: File | null;
  wordUpload: WordUploadResult | null;
  clauseFileName: string;
  sending: boolean;
  resultPanelOpen: boolean;
  onModeChange: (mode: ChatMode) => void;
  onDraftChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onSend: () => void;
  onStop: () => void;
  onQuickPrompt: (prompt: string) => void;
  onOpenResults: () => void;
};


export function ChatWorkspace(props: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const composingRef = useRef(false);
  const attachmentName = props.attachedFile?.name || props.wordUpload?.file_name || props.clauseFileName;
  const attachmentParsed = Boolean(
    (props.wordUpload && !props.attachedFile)
    || (props.clauseFileName && !props.attachedFile),
  );
  const canSend = Boolean(
    props.draft.trim()
    || (props.mode !== "knowledge" && attachmentName),
  );

  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [props.messages]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (props.sending) props.onStop();
    else props.onSend();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (composingRef.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!props.sending) props.onSend();
    }
  }

  return (
    <main className="chat-workspace">
      <header className="chat-header">
        <div>
          <span className="task-label">当前任务</span>
          <h1>{props.title}</h1>
        </div>
        <div className="chat-header-actions">
          <div className="mode-switch" aria-label="工作模式">
            <button className={props.mode === "check" ? "active" : ""} type="button" onClick={() => props.onModeChange("check")}>
              <FileText size={15} />文档校核
            </button>
            <button className={props.mode === "clause_extract" ? "active" : ""} type="button" onClick={() => props.onModeChange("clause_extract")}>
              <ScanText size={15} />强条抽取
            </button>
            <button className={props.mode === "knowledge" ? "active" : ""} type="button" onClick={() => props.onModeChange("knowledge")}>
              <Search size={15} />知识问答
            </button>
          </div>
          {!props.resultPanelOpen && (
            <button className="icon-action" type="button" title="展开结果面板" onClick={props.onOpenResults}>
              <PanelRightOpen size={19} />
            </button>
          )}
        </div>
      </header>

      <div className="conversation" ref={scrollRef}>
        {!props.messages.length ? (
          <div className="conversation-empty">
            <div className="empty-mark"><MessageSquareText size={24} /></div>
            <div className="empty-heading">
              <h2>{emptyHeading(props.mode)}</h2>
              <span>（重要结论请结合原始文档复核）</span>
            </div>
            {props.mode === "check" && (
              <div className="prompt-actions">
                <button type="button" onClick={() => props.onQuickPrompt("请全面检查这个文档有没有问题")}>全面校核文档</button>
                <button type="button" onClick={() => props.onQuickPrompt("只检查正文完整性有没有问题")}>检查正文完整性</button>
                <button type="button" onClick={() => props.onQuickPrompt("检查正文和依据章节有没有冲突")}>核对正文与依据</button>
              </div>
            )}
            {props.mode === "clause_extract" && (
              <div className="prompt-actions">
                <button type="button" onClick={() => props.onQuickPrompt("请自动识别并提取这份 PDF 中的全部强制性条文")}>自动提取全部强条</button>
                <button type="button" onClick={() => props.onQuickPrompt("请识别强条并按章节进行汇总")}>按章节汇总</button>
              </div>
            )}
          </div>
        ) : (
          <div className="message-stream">
            {props.messages.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                <div className="message-avatar">{message.role === "assistant" ? "D" : "你"}</div>
                <div className="message-content">
                  <span className="message-author">{message.role === "assistant" ? "DOC AGENT" : "你"}</span>
                  {message.role === "assistant" ? <ReportMarkdown text={message.content} /> : <p>{message.content}</p>}
                  {message.pending && <span className="streaming-cursor" aria-label="正在生成" />}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="composer-wrap">
        <form className={`chat-composer ${attachmentName ? "has-attachment" : ""}`} onSubmit={submit}>
          {attachmentName && props.mode !== "knowledge" && (
            <div className="attachment-card">
              <span className={`attachment-file-icon ${props.mode === "clause_extract" ? "pdf" : "word"}`}>
                {props.mode === "clause_extract" ? <ScanText size={18} /> : <FileText size={18} />}
              </span>
              <span className="attachment-copy">
                <strong>{attachmentName}</strong>
                <small>{props.mode === "clause_extract" ? "PDF" : "Word"}{attachmentParsed ? " · 已解析" : ""}</small>
              </span>
              <button className="attachment-remove" type="button" title="移除文档" onClick={() => props.onFileChange(null)}>
                <X size={15} />
              </button>
            </div>
          )}
          <textarea
            rows={1}
            value={props.draft}
            placeholder={composerPlaceholder(props.mode)}
            onChange={(event) => props.onDraftChange(event.target.value)}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
          />
          <div className="composer-actions">
            {props.mode !== "knowledge" ? (
              <label className="composer-icon" title={props.mode === "clause_extract" ? "附加 PDF" : "附加 Word 文档"}>
                <Plus size={22} />
                <input
                  type="file"
                  accept={props.mode === "clause_extract" ? ".pdf,application/pdf" : ".docx"}
                  onChange={(event) => {
                    props.onFileChange(event.target.files?.[0] ?? null);
                    event.currentTarget.value = "";
                  }}
                />
              </label>
            ) : <span />}
            <button
              className={`send-button ${props.sending ? "is-stopping" : ""}`}
              type="submit"
              title={props.sending ? "停止回答" : "发送"}
              aria-label={props.sending ? "停止回答" : "发送"}
              disabled={!props.sending && !canSend}
            >
              {props.sending ? <Square size={12} fill="currentColor" /> : <ArrowUp size={21} />}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}


function emptyHeading(mode: ChatMode) {
  if (mode === "check") return "需要校核哪份文档？";
  if (mode === "clause_extract") return "需要从哪份 PDF 提取强条？";
  return "想从知识库了解什么？";
}


function composerPlaceholder(mode: ChatMode) {
  if (mode === "check") return "输入校核要求…";
  if (mode === "clause_extract") return "输入强条提取或追问要求…";
  return "向知识库提问…";
}
