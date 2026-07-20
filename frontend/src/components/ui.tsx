import { AlertCircle, CheckCircle2, Loader2, Trash2 } from "lucide-react";
import { ButtonHTMLAttributes, ReactNode } from "react";

import { translateDisplayText } from "../lib/labels";
import { Toast } from "../types";


export function Button({
  variant = "secondary",
  icon,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "icon";
  icon?: ReactNode;
}) {
  return (
    <button className={`button button-${variant} ${className}`.trim()} {...props}>
      {icon}
      {children}
    </button>
  );
}


export function LoadingIcon({ size = 17 }: { size?: number }) {
  return <Loader2 className="spin" size={size} />;
}


export function ToastBanner({ toast }: { toast: Toast }) {
  return (
    <div className={`toast toast-${toast.type}`} role="status">
      {toast.type === "success" ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
      <span>{toast.text}</span>
    </div>
  );
}


export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="confirm-layer">
      <button className="confirm-backdrop" type="button" aria-label="关闭确认框" onClick={onCancel} />
      <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
        <div className="confirm-dialog-heading">
          <span className="confirm-dialog-icon"><Trash2 size={18} /></span>
          <div>
            <h2 id="confirm-dialog-title">{title}</h2>
            <p>{description}</p>
          </div>
        </div>
        <div className="confirm-dialog-actions">
          <Button type="button" onClick={onCancel} disabled={busy}>取消</Button>
          <Button type="button" variant="danger" onClick={onConfirm} disabled={busy}>
            {busy && <LoadingIcon />}
            {confirmLabel}
          </Button>
        </div>
      </section>
    </div>
  );
}


export function ReportMarkdown({ text }: { text: string }) {
  const lines = translateDisplayText(text).split(/\r?\n/);
  return (
    <div className="report-markdown">
      {lines.map((rawLine, index) => {
        const line = rawLine.trim();
        if (!line) return <div className="report-space" key={index} />;
        if (line === "---") return <hr key={index} />;
        if (line.startsWith("### ")) return <h3 key={index}>{renderInline(line.slice(4))}</h3>;
        if (line.startsWith("## ")) return <h2 key={index}>{renderInline(line.slice(3))}</h2>;
        if (line.startsWith("# ")) return <h1 key={index}>{renderInline(line.slice(2))}</h1>;
        if (/^\d+\.\s+/.test(line)) return <p className="report-numbered" key={index}>{renderInline(line)}</p>;
        if (line.startsWith("- ")) return <p className="report-bullet" key={index}>{renderInline(line.slice(2))}</p>;
        return <p key={index}>{renderInline(line)}</p>;
      })}
    </div>
  );
}


function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return <span key={index}>{part}</span>;
  });
}
