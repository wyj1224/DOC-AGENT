import { AlertCircle, FileCheck2, LogIn, UserPlus } from "lucide-react";
import { FormEvent, useState } from "react";

import { errorMessage, request, saveAccessToken } from "../lib/api";
import { AuthResult, AuthUser } from "../types";
import { Button, LoadingIcon } from "./ui";


export function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const body = mode === "register"
        ? { username, password, display_name: displayName }
        : { username, password };
      const result = await request<AuthResult>(`/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      saveAccessToken(result.access_token);
      onAuthenticated(result.user);
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setLoading(false);
    }
  }

  function switchMode(nextMode: "login" | "register") {
    setMode(nextMode);
    setError("");
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-logo" aria-hidden="true"><FileCheck2 size={24} /></div>
        <div className="auth-heading">
          <h1>DOC AGENT</h1>
          <p>文档问答与校验智能体</p>
        </div>

        <form className="auth-form" onSubmit={submit}>
          {mode === "register" && (
            <label>
              <span>显示名称</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" />
            </label>
          )}
          <label>
            <span>用户名</span>
            <input required minLength={3} maxLength={128} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            <span>密码</span>
            <input required minLength={mode === "register" ? 8 : undefined} maxLength={128} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </label>

          {error && <div className="auth-error"><AlertCircle size={17} /><span>{error}</span></div>}

          <Button
            className="auth-submit"
            variant="primary"
            disabled={loading}
            icon={loading ? <LoadingIcon /> : mode === "login" ? <LogIn size={17} /> : <UserPlus size={17} />}
          >
            {mode === "login" ? "登录" : "创建账号"}
          </Button>
        </form>

        <div className="auth-switch">
          {mode === "login" ? "还没有账号？" : "已经有账号？"}
          <button type="button" onClick={() => switchMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "注册账号" : "返回登录"}
          </button>
        </div>
      </section>
    </main>
  );
}
