import {
  FileCheck2,
  Loader2,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
  Trash2,
} from "lucide-react";

import { AgentSessionSummary, AuthUser } from "../types";
import { Button } from "./ui";


type Props = {
  collapsed: boolean;
  currentUser: AuthUser;
  sessions: AgentSessionSummary[];
  selectedSessionId?: number;
  loading: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  onOpenSession: (sessionId: number) => void;
  onDeleteSession: (session: AgentSessionSummary) => void;
  onOpenSettings: () => void;
};


export function AppSidebar(props: Props) {
  return (
    <aside className={`app-sidebar ${props.collapsed ? "is-collapsed" : ""}`}>
      <div className="sidebar-brand-row">
        <div className="product-mark"><FileCheck2 size={20} /></div>
        {!props.collapsed && <strong>DOC AGENT</strong>}
        <button className="sidebar-collapse" type="button" title={props.collapsed ? "展开侧栏" : "收起侧栏"} onClick={props.onToggle}>
          {props.collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <Button
        className="new-chat-button"
        variant="secondary"
        icon={<Plus size={18} />}
        title="新建对话"
        onClick={props.onNewChat}
      >
        {!props.collapsed && "新建对话"}
      </Button>

      <div className="sidebar-history">
        {!props.collapsed && <span className="sidebar-section-label">最近任务</span>}
        <div className="history-list">
          {props.loading && !props.sessions.length ? (
            <div className="sidebar-loading"><Loader2 className="spin" size={17} /></div>
          ) : props.sessions.length ? (
            props.sessions.map((session) => (
              <div className="history-row" data-session-id={session.session_id} key={session.session_id}>
                <button
                  className={`history-item ${props.selectedSessionId === session.session_id ? "active" : ""}`}
                  type="button"
                  title={session.title}
                  onClick={() => props.onOpenSession(session.session_id)}
                >
                  <MessageSquareText size={16} />
                  {!props.collapsed && (
                    <span>
                      <strong>{session.title}</strong>
                      <small>{formatRunDate(session.updated_at)}</small>
                    </span>
                  )}
                </button>
                {!props.collapsed && (
                  <button
                    className="history-delete"
                    type="button"
                    title="删除对话"
                    aria-label={`删除对话 ${session.title}`}
                    onClick={() => props.onDeleteSession(session)}
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            ))
          ) : !props.collapsed ? (
            <p className="sidebar-empty">暂无历史任务</p>
          ) : null}
        </div>
      </div>

      <div className="sidebar-account">
        <button className="settings-button" type="button" title="设置与资料库" onClick={props.onOpenSettings}>
          <Settings size={18} />
          {!props.collapsed && <span>设置与资料库</span>}
        </button>
        <div className="user-summary" title={props.currentUser.display_name || props.currentUser.username}>
          <span className="user-avatar">{userInitial(props.currentUser)}</span>
          {!props.collapsed && (
            <span>
              <strong>{props.currentUser.display_name || props.currentUser.username}</strong>
              <small>@{props.currentUser.username}</small>
            </span>
          )}
        </div>
      </div>
    </aside>
  );
}


function userInitial(user: AuthUser) {
  return (user.display_name || user.username).trim().slice(0, 1).toUpperCase();
}


function formatRunDate(value: string) {
  if (!value) return "";
  const date = new Date(value);
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
