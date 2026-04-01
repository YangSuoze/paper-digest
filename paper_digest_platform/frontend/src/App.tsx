import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "./api";
import type {
  AutoKeywordsResponse,
  DigestSettingsResponse,
  DispatchLogItem,
  FeedbackItem,
  RunNowSubmitResponse,
  RunNowTaskStatus,
  FeedbackSubmitResponse,
  LoginResponse,
  MessageResponse,
  PaperRecordItem,
  TriggerResponse,
  UserProfile,
} from "./types";

const TOKEN_KEY = "paper_digest_platform_token";

type AuthTab = "login" | "register" | "reset";
type DashboardTab = "keywords" | "records" | "feedback";
type KeywordGroup = string[];

const KEYWORD_GROUP_AND_SPLITTER = /\s*(?:&&|&|＆＆|＆|,|，|;|；)\s*/;

interface LoginFormState {
  username: string;
  password: string;
}

interface RegisterFormState {
  email: string;
  username: string;
  password: string;
  code: string;
}

interface ResetFormState {
  email: string;
  new_password: string;
  code: string;
}

interface SettingsFormState {
  target_email: string;
  daily_send_time: string;
  timezone: string;
  keyword_rows: string[];
  active: boolean;
}

interface ToastState {
  message: string;
  error: boolean;
  visible: boolean;
}

const EMPTY_TOAST: ToastState = {
  message: "",
  error: false,
  visible: false,
};

const EMPTY_SETTINGS: SettingsFormState = {
  target_email: "",
  daily_send_time: "09:30",
  timezone: "Asia/Shanghai",
  keyword_rows: [""],
  active: false,
};

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "请求失败";
}

function normalizeKeywordGroup(values: string[]): KeywordGroup {
  const seen = new Set<string>();
  const group: string[] = [];

  for (const value of values) {
    const term = value.trim();
    if (!term) {
      continue;
    }
    const key = term.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    group.push(term);
  }

  return group;
}

function parseKeywordLine(line: string): KeywordGroup {
  const cleaned = line.trim();
  if (!cleaned) {
    return [];
  }
  return normalizeKeywordGroup(cleaned.split(KEYWORD_GROUP_AND_SPLITTER));
}

function parseKeywordRows(rows: string[]): KeywordGroup[] {
  const groups: KeywordGroup[] = [];
  const seen = new Set<string>();

  for (const row of rows) {
    const group = parseKeywordLine(row);
    if (!group.length) {
      continue;
    }
    const key = group.map((item) => item.toLowerCase()).join("&&");
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    groups.push(group);
  }

  return groups;
}

function formatKeywordGroup(group: KeywordGroup): string {
  return group.join(" && ");
}

function toKeywordRows(keywordsList: KeywordGroup[]): string[] {
  const rows = keywordsList.map((group) => formatKeywordGroup(group)).filter(Boolean);
  return rows.length ? rows : [""];
}

function resolveKeywordsList(data: DigestSettingsResponse): KeywordGroup[] {
  const groupsFromList = (data.keywords_list || [])
    .map((group) => normalizeKeywordGroup(group || []))
    .filter((group) => group.length > 0);
  if (groupsFromList.length > 0) {
    return groupsFromList;
  }

  return (data.keywords || [])
    .map((item) => parseKeywordLine(item || ""))
    .filter((group) => group.length > 0);
}

export default function App() {
  const [authToken, setAuthToken] = useState<string>(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [isBooting, setIsBooting] = useState<boolean>(true);
  const [authTab, setAuthTab] = useState<AuthTab>("login");
  const [dashboardTab, setDashboardTab] = useState<DashboardTab>("keywords");
  const [user, setUser] = useState<UserProfile | null>(null);
  const [logs, setLogs] = useState<DispatchLogItem[]>([]);
  const [papers, setPapers] = useState<PaperRecordItem[]>([]);
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([]);
  const [feedbackContent, setFeedbackContent] = useState<string>("");
  const [runNowTask, setRunNowTask] = useState<RunNowTaskStatus | null>(null);
  const [smtpReady, setSmtpReady] = useState<boolean>(false);
  const [senderEmail, setSenderEmail] = useState<string>("");
  const [keywordIntent, setKeywordIntent] = useState<string>("");
  const [toast, setToast] = useState<ToastState>(EMPTY_TOAST);
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({});

  const [loginForm, setLoginForm] = useState<LoginFormState>({ username: "", password: "" });
  const [registerForm, setRegisterForm] = useState<RegisterFormState>({
    email: "",
    username: "",
    password: "",
    code: "",
  });
  const [resetForm, setResetForm] = useState<ResetFormState>({
    email: "",
    new_password: "",
    code: "",
  });
  const [settingsForm, setSettingsForm] = useState<SettingsFormState>(EMPTY_SETTINGS);

  const isAuthed = useMemo(() => Boolean(authToken && user), [authToken, user]);

  const digestLogs = useMemo(
    () => logs.filter((item) => item.run_type !== "manual_test"),
    [logs],
  );
  const totalRuns = digestLogs.length;
  const successRuns = digestLogs.filter((item) => item.status === "success").length;
  const failedRuns = digestLogs.filter((item) => item.status === "failed").length;
  const successRate = totalRuns > 0 ? Math.round((successRuns / totalRuns) * 100) : 0;
  const runNowInFlight =
    runNowTask !== null && (runNowTask.status === "queued" || runNowTask.status === "running");

  const showToast = (message: string, error = false) => {
    setToast({ message, error, visible: true });
  };

  const setBusy = (key: string, value: boolean) => {
    setBusyMap((previous) => ({ ...previous, [key]: value }));
  };

  const isBusy = (key: string) => Boolean(busyMap[key]);

  const applySettings = (data: DigestSettingsResponse) => {
    const keywordsList = resolveKeywordsList(data);
    setSettingsForm({
      target_email: data.target_email,
      daily_send_time: data.daily_send_time || "09:30",
      timezone: data.timezone || "Asia/Shanghai",
      keyword_rows: toKeywordRows(keywordsList),
      active: Boolean(data.active),
    });
    setKeywordIntent(String(data.user_search_intent || ""));
    setSmtpReady(Boolean(data.smtp_ready));
    setSenderEmail(String(data.sender_email || ""));
  };

  const loadDashboardData = async (token: string) => {
    const [settingsData, logData, paperData, feedbackData] = await Promise.all([
      apiRequest<DigestSettingsResponse>("/settings/me", { token }),
      apiRequest<DispatchLogItem[]>("/push/logs?limit=20", { token }),
      apiRequest<PaperRecordItem[]>("/push/papers?limit=20", { token }),
      apiRequest<FeedbackItem[]>("/settings/feedback?limit=20", { token }),
    ]);
    applySettings(settingsData);
    setLogs(logData);
    setPapers(paperData);
    setFeedbackItems(feedbackData);
  };

  useEffect(() => {
    if (!toast.visible) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setToast(EMPTY_TOAST);
    }, 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      if (!authToken) {
        if (!cancelled) {
          setIsBooting(false);
          setUser(null);
        }
        return;
      }

      try {
        const profile = await apiRequest<UserProfile>("/auth/me", { token: authToken });
        if (cancelled) {
          return;
        }
        setUser(profile);
        await loadDashboardData(authToken);
      } catch {
        if (cancelled) {
          return;
        }
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken("");
        setUser(null);
      } finally {
        if (!cancelled) {
          setIsBooting(false);
        }
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [authToken]);

  useEffect(() => {
    if (!authToken || !runNowTask?.task_id) {
      return undefined;
    }
    if (runNowTask.status === "success" || runNowTask.status === "failed") {
      return undefined;
    }

    let cancelled = false;
    let timer: number | null = null;

    const pollTask = async () => {
      try {
        const latest = await apiRequest<RunNowTaskStatus>(`/push/tasks/${runNowTask.task_id}`, {
          token: authToken,
        });
        if (cancelled) {
          return;
        }
        setRunNowTask(latest);

        if (latest.status === "success") {
          showToast(latest.result_message || "推送任务执行完成");
          await loadDashboardData(authToken);
          return;
        }
        if (latest.status === "failed") {
          showToast(latest.error_message || "推送任务执行失败", true);
          await loadDashboardData(authToken);
          return;
        }
      } catch (error) {
        if (!cancelled) {
          const message = errorMessage(error);
          showToast(message, true);
          setRunNowTask((previous) => {
            if (!previous) {
              return previous;
            }
            return {
              ...previous,
              status: "failed",
              progress_stage: "failed",
              progress_message: "任务状态查询失败",
              error_message: message,
            };
          });
        }
        return;
      }

      if (!cancelled) {
        timer = window.setTimeout(() => {
          void pollTask();
        }, 2000);
      }
    };

    timer = window.setTimeout(() => {
      void pollTask();
    }, 1200);

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [authToken, runNowTask?.task_id, runNowTask?.status]);

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy("login", true);
    try {
      const payload = {
        username: loginForm.username.trim(),
        password: loginForm.password,
      };
      const data = await apiRequest<LoginResponse>("/auth/login", {
        method: "POST",
        body: payload,
      });
      localStorage.setItem(TOKEN_KEY, data.token);
      setAuthToken(data.token);
      setUser(data.user);
      showToast("登录成功");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("login", false);
    }
  };

  const handleSendRegisterCode = async () => {
    const email = registerForm.email.trim();
    if (!email) {
      showToast("请先输入邮箱", true);
      return;
    }
    setBusy("register-code", true);
    try {
      await apiRequest<MessageResponse>("/auth/register/request-code", {
        method: "POST",
        body: { email },
      });
      showToast("验证码已发送");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("register-code", false);
    }
  };

  const handleRegister = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy("register", true);
    try {
      const payload = {
        email: registerForm.email.trim(),
        username: registerForm.username.trim(),
        password: registerForm.password,
        code: registerForm.code.trim(),
      };
      await apiRequest<MessageResponse>("/auth/register/confirm", {
        method: "POST",
        body: payload,
      });
      showToast("注册成功，请登录");
      setAuthTab("login");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("register", false);
    }
  };

  const handleSendResetCode = async () => {
    const email = resetForm.email.trim();
    if (!email) {
      showToast("请先输入邮箱", true);
      return;
    }
    setBusy("reset-code", true);
    try {
      await apiRequest<MessageResponse>("/auth/password/request-code", {
        method: "POST",
        body: { email },
      });
      showToast("如邮箱有效，验证码已发送");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("reset-code", false);
    }
  };

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy("reset", true);
    try {
      const payload = {
        email: resetForm.email.trim(),
        new_password: resetForm.new_password,
        code: resetForm.code.trim(),
      };
      await apiRequest<MessageResponse>("/auth/password/reset", {
        method: "POST",
        body: payload,
      });
      showToast("密码已重置，请重新登录");
      setAuthTab("login");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("reset", false);
    }
  };

  const handleKeywordRowChange = (index: number, value: string) => {
    setSettingsForm((previous) => {
      const next = [...previous.keyword_rows];
      next[index] = value;
      return { ...previous, keyword_rows: next };
    });
  };

  const handleAddKeywordRow = () => {
    setSettingsForm((previous) => ({
      ...previous,
      keyword_rows: [...previous.keyword_rows, ""],
    }));
  };

  const handleRemoveKeywordRow = (index: number) => {
    setSettingsForm((previous) => {
      const next = previous.keyword_rows.filter((_, rowIndex) => rowIndex !== index);
      return { ...previous, keyword_rows: next.length ? next : [""] };
    });
  };

  const handleGenerateKeywords = async () => {
    const query = keywordIntent.trim();
    if (!query) {
      showToast("请先输入中文需求", true);
      return;
    }

    setBusy("auto-keywords", true);
    try {
      const data = await apiRequest<AutoKeywordsResponse>("/settings/auto_generate_keywords_list", {
        method: "POST",
        token: authToken,
        body: { user_query: query },
      });

      const generatedGroups = (data.keywords_list || [])
        .map((group) => normalizeKeywordGroup(group || []))
        .filter((group) => group.length > 0);

      if (!generatedGroups.length) {
        showToast("未生成有效关键词组，请尝试换一种描述", true);
        return;
      }

      setSettingsForm((previous) => ({
        ...previous,
        keyword_rows: toKeywordRows(generatedGroups),
      }));
      setDashboardTab("keywords");
      showToast(`已生成 ${generatedGroups.length} 组关键词，可继续编辑`);
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("auto-keywords", false);
    }
  };

  const handleSaveSettings = async () => {
    if (!authToken) {
      showToast("请先登录", true);
      return;
    }

    const keywordsList = parseKeywordRows(settingsForm.keyword_rows);
    if (!keywordsList.length) {
      showToast("关键词组不能为空", true);
      return;
    }

    setBusy("save-settings", true);
    try {
      const payload = {
        target_email: settingsForm.target_email.trim(),
        daily_send_time: settingsForm.daily_send_time || "09:30",
        timezone: settingsForm.timezone.trim() || "Asia/Shanghai",
        keywords_list: keywordsList,
        active: settingsForm.active,
        user_search_intent: keywordIntent.trim() || "",
      };
      await apiRequest<DigestSettingsResponse>("/settings/me", {
        method: "PUT",
        body: payload,
        token: authToken,
      });
      await loadDashboardData(authToken);
      showToast("配置已保存，调度已更新");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("save-settings", false);
    }
  };

  const handleTestEmail = async () => {
    if (!authToken) {
      showToast("请先登录", true);
      return;
    }
    setBusy("test-email", true);
    try {
      const data = await apiRequest<TriggerResponse>("/push/test-email", {
        method: "POST",
        body: {},
        token: authToken,
      });
      showToast(data.message || "测试邮件已发送");
      await loadDashboardData(authToken);
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("test-email", false);
    }
  };

  const handleRunNow = async () => {
    if (!authToken) {
      showToast("请先登录", true);
      return;
    }
    if (runNowInFlight) {
      showToast("已有任务正在执行，请稍候", true);
      return;
    }
    const keywordsList = parseKeywordRows(settingsForm.keyword_rows);
    if (!keywordsList.length) {
      showToast("关键词组不能为空", true);
      return;
    }
    setBusy("run-now", true);
    try {
      const data = await apiRequest<RunNowSubmitResponse>("/push/run-now", {
        method: "POST",
        body: { keywords_list: keywordsList },
        token: authToken,
      });
      setRunNowTask(data.task);
      showToast(data.message || "推送任务已提交");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("run-now", false);
    }
  };

  const handleRefreshLogs = async () => {
    if (!authToken) {
      showToast("请先登录", true);
      return;
    }
    setBusy("refresh-logs", true);
    try {
      const [logItems, paperItems, feedbackData] = await Promise.all([
        apiRequest<DispatchLogItem[]>("/push/logs?limit=20", { token: authToken }),
        apiRequest<PaperRecordItem[]>("/push/papers?limit=20", { token: authToken }),
        apiRequest<FeedbackItem[]>("/settings/feedback?limit=20", { token: authToken }),
      ]);
      setLogs(logItems);
      setPapers(paperItems);
      setFeedbackItems(feedbackData);
      showToast("日志、论文与反馈记录已刷新");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("refresh-logs", false);
    }
  };

  const handleSubmitFeedback = async () => {
    if (!authToken) {
      showToast("请先登录", true);
      return;
    }

    const content = feedbackContent.trim();
    if (!content) {
      showToast("请先输入你的使用建议", true);
      return;
    }

    setBusy("submit-feedback", true);
    try {
      const data = await apiRequest<FeedbackSubmitResponse>("/settings/feedback", {
        method: "POST",
        token: authToken,
        body: { content },
      });
      setFeedbackContent("");
      setFeedbackItems((prev) => [data.item, ...prev].slice(0, 20));
      showToast(data.message || "反馈已提交");
    } catch (error) {
      showToast(errorMessage(error), true);
    } finally {
      setBusy("submit-feedback", false);
    }
  };

  const handleLogout = async () => {
    const token = authToken;
    setBusy("logout", true);
    try {
      if (token) {
        await apiRequest<MessageResponse>("/auth/logout", {
          method: "POST",
          token,
        });
      }
    } catch {
    } finally {
      localStorage.removeItem(TOKEN_KEY);
      setAuthToken("");
      setUser(null);
      setSettingsForm(EMPTY_SETTINGS);
      setLogs([]);
      setPapers([]);
      setFeedbackItems([]);
      setFeedbackContent("");
      setRunNowTask(null);
      setBusy("logout", false);
      showToast("已退出登录");
    }
  };

  return (
    <main className="shell">
      {isBooting ? (
        <section className="panel loading-panel">
          <p className="eyebrow">Paper Digest Platform</p>
          <h1>正在加载工作台...</h1>
        </section>
      ) : null}

      {!isBooting && !isAuthed ? (
        <section className="panel auth-panel">
          <header className="panel-header auth-header">
            <p className="eyebrow">Paper Digest Platform</p>
            <h1>论文智能推送助手</h1>
          </header>

          <div className="tabs">
            <button
              className={`tab-btn ${authTab === "login" ? "active" : ""}`}
              onClick={() => setAuthTab("login")}
              type="button"
            >
              登录
            </button>
            <button
              className={`tab-btn ${authTab === "register" ? "active" : ""}`}
              onClick={() => setAuthTab("register")}
              type="button"
            >
              注册
            </button>
            <button
              className={`tab-btn ${authTab === "reset" ? "active" : ""}`}
              onClick={() => setAuthTab("reset")}
              type="button"
            >
              忘记密码
            </button>
          </div>

          <form className={`tab-form ${authTab === "login" ? "active" : ""}`} onSubmit={handleLogin}>
            <label>
              用户名
              <input
                required
                minLength={3}
                maxLength={64}
                value={loginForm.username}
                onChange={(event) => setLoginForm((prev) => ({ ...prev, username: event.target.value }))}
              />
            </label>
            <label>
              密码
              <input
                type="password"
                required
                minLength={8}
                value={loginForm.password}
                onChange={(event) => setLoginForm((prev) => ({ ...prev, password: event.target.value }))}
              />
            </label>
            <button type="submit" className="primary" disabled={isBusy("login")}>
              {isBusy("login") ? "处理中..." : "登录"}
            </button>
          </form>

          <form className={`tab-form ${authTab === "register" ? "active" : ""}`} onSubmit={handleRegister}>
            <div className="inline-wrap">
              <label>
                邮箱
                <input
                  type="email"
                  required
                  value={registerForm.email}
                  onChange={(event) => setRegisterForm((prev) => ({ ...prev, email: event.target.value }))}
                />
              </label>
              <button
                type="button"
                className="ghost"
                onClick={handleSendRegisterCode}
                disabled={isBusy("register-code")}
              >
                {isBusy("register-code") ? "发送中..." : "发送验证码"}
              </button>
            </div>
            <label>
              用户名
              <input
                required
                minLength={3}
                maxLength={32}
                value={registerForm.username}
                onChange={(event) => setRegisterForm((prev) => ({ ...prev, username: event.target.value }))}
              />
            </label>
            <label>
              密码
              <input
                type="password"
                required
                minLength={8}
                value={registerForm.password}
                onChange={(event) => setRegisterForm((prev) => ({ ...prev, password: event.target.value }))}
              />
            </label>
            <label>
              验证码
              <input
                required
                minLength={6}
                maxLength={6}
                value={registerForm.code}
                onChange={(event) => setRegisterForm((prev) => ({ ...prev, code: event.target.value }))}
              />
            </label>
            <button type="submit" className="primary" disabled={isBusy("register")}>
              {isBusy("register") ? "处理中..." : "完成注册"}
            </button>
          </form>

          <form className={`tab-form ${authTab === "reset" ? "active" : ""}`} onSubmit={handleResetPassword}>
            <div className="inline-wrap">
              <label>
                邮箱
                <input
                  type="email"
                  required
                  value={resetForm.email}
                  onChange={(event) => setResetForm((prev) => ({ ...prev, email: event.target.value }))}
                />
              </label>
              <button type="button" className="ghost" onClick={handleSendResetCode} disabled={isBusy("reset-code")}>
                {isBusy("reset-code") ? "发送中..." : "发送验证码"}
              </button>
            </div>
            <label>
              新密码
              <input
                type="password"
                required
                minLength={8}
                value={resetForm.new_password}
                onChange={(event) => setResetForm((prev) => ({ ...prev, new_password: event.target.value }))}
              />
            </label>
            <label>
              验证码
              <input
                required
                minLength={6}
                maxLength={6}
                value={resetForm.code}
                onChange={(event) => setResetForm((prev) => ({ ...prev, code: event.target.value }))}
              />
            </label>
            <button type="submit" className="primary" disabled={isBusy("reset")}>
              {isBusy("reset") ? "处理中..." : "重置密码"}
            </button>
          </form>
        </section>
      ) : null}

      {!isBooting && isAuthed ? (
        <section className="panel dashboard-panel">
          <header className="panel-header compact">
            <div>
              <p className="eyebrow"> 你的智能论文追踪助手</p>
              <h2>欢迎回来，{user?.username}</h2>
              <p className="subline">反馈接收邮箱：{senderEmail || "未配置"}</p>
            </div>
            <button className="ghost" onClick={handleLogout} disabled={isBusy("logout")}>
              {isBusy("logout") ? "退出中..." : "退出登录"}
            </button>
          </header>

          <div className="segment-control" role="tablist" aria-label="工作台维度切换">
            <button
              type="button"
              className={dashboardTab === "keywords" ? "active" : ""}
              onClick={() => setDashboardTab("keywords")}
            >
              关键词配置
            </button>
            <button
              type="button"
              className={dashboardTab === "records" ? "active" : ""}
              onClick={() => setDashboardTab("records")}
            >
              日志与论文
            </button>
            <button
              type="button"
              className={dashboardTab === "feedback" ? "active" : ""}
              onClick={() => setDashboardTab("feedback")}
            >
              反馈看板
            </button>
          </div>

          {dashboardTab === "keywords" ? (
            <div className="action-board">
              <article className="action-group action-group-primary">
                <div className="action-group-head">
                  <h3>配置与执行</h3>
                  <p>保存关键词配置策略后可立即触发一次真实推送</p>
                </div>
                <div className="action-group-buttons">
                  <button className="primary" onClick={handleSaveSettings} disabled={isBusy("save-settings")}>
                    {isBusy("save-settings") ? "保存中..." : "保存配置"}
                  </button>
                  <button
                    className="warn"
                    onClick={handleRunNow}
                    disabled={isBusy("run-now") || runNowInFlight}
                  >
                    {isBusy("run-now")
                      ? "提交中..."
                      : runNowInFlight
                        ? "后台执行中..."
                        : "立即执行一次推送"}
                  </button>
                </div>
                {runNowTask ? (
                  <div className={`task-progress task-${runNowTask.status}`}>
                    <strong>
                      任务状态：
                      {runNowTask.status === "queued"
                        ? "排队中"
                        : runNowTask.status === "running"
                          ? "执行中"
                          : runNowTask.status === "success"
                            ? "已完成"
                            : runNowTask.status === "failed"
                              ? "失败"
                              : runNowTask.status}
                    </strong>
                    <span>
                      {runNowTask.status === "success"
                        ? runNowTask.result_message || "推送完成"
                        : runNowTask.status === "failed"
                          ? runNowTask.error_message || "执行失败"
                          : runNowTask.progress_message || "任务执行中"}
                    </span>
                  </div>
                ) : null}
              </article>

              <article className="action-group">
                <div className="action-group-head">
                  <h3>调试与回看</h3>
                  <p>验证邮箱链路并快速刷新执行日志</p>
                </div>
                <div className="action-group-buttons">
                  <button className="ghost" onClick={handleTestEmail} disabled={isBusy("test-email")}>
                    {isBusy("test-email") ? "测试中..." : "测试邮件"}
                  </button>
                  <button className="ghost" onClick={handleRefreshLogs} disabled={isBusy("refresh-logs")}>
                    {isBusy("refresh-logs") ? "刷新中..." : "刷新日志"}
                  </button>
                </div>
              </article>
            </div>
          ) : null}

          {dashboardTab === "records" ? (
            <>
              <div className="stats-grid">
                <article className="card metric-card">
                  <h3>推送任务</h3>
                  <div className="metric-value">{totalRuns}</div>
                  <p className="hint">近 20 条日志（不含测试邮件）</p>
                </article>
                <article className="card metric-card">
                  <h3>成功率</h3>
                  <div className="metric-value">{successRate}%</div>
                  <p className="hint">
                    成功 {successRuns} · 失败 {failedRuns}
                  </p>
                </article>
                <article className="card metric-card">
                  <h3>论文入库</h3>
                  <div className="metric-value">{papers.length}</div>
                  <p className="hint">近 20 条论文记录</p>
                </article>
              </div>

            </>
          ) : null}

          {dashboardTab === "keywords" ? (
            <div className="settings-grid">
              <article className="card">
                <h3>投递设置</h3>
                <div className="two-col">
                  <label>
                    目标邮箱
                    <input
                      type="email"
                      required
                      value={settingsForm.target_email}
                      onChange={(event) =>
                        setSettingsForm((prev) => ({ ...prev, target_email: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    发送时间
                    <input
                      type="time"
                      required
                      value={settingsForm.daily_send_time}
                      onChange={(event) =>
                        setSettingsForm((prev) => ({ ...prev, daily_send_time: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    时区
                    <input
                      value={settingsForm.timezone}
                      onChange={(event) =>
                        setSettingsForm((prev) => ({ ...prev, timezone: event.target.value }))
                      }
                    />
                  </label>
                  <label className="switch-item">
                    <span>自动推送</span>
                    <input
                      type="checkbox"
                      checked={settingsForm.active}
                      onChange={(event) =>
                        setSettingsForm((prev) => ({ ...prev, active: event.target.checked }))
                      }
                    />
                  </label>
                </div>
                <p className="hint">系统 SMTP：{smtpReady ? "已就绪" : "未就绪"}</p>
              </article>

              <article className="card">
                <h3>AI 生成关键词组</h3>
                <label>
                  中文需求描述
                  <textarea
                    rows={4}
                    placeholder="例如：我想追踪医疗报告生成和大模型相关英文论文"
                    value={keywordIntent}
                    onChange={(event) => setKeywordIntent(event.target.value)}
                  ></textarea>
                </label>
                <div className="inline-actions">
                  <button className="primary" onClick={handleGenerateKeywords} disabled={isBusy("auto-keywords")}>
                    {isBusy("auto-keywords") ? "生成中..." : "自动生成 keywords_list"}
                  </button>
                </div>
                <p className="hint">生成后可在下方逐行编辑，每行是一个 OR 分组，行内词用 `&&` 表示 AND。</p>
              </article>

              <article className="card span-all">
                <div className="card-title-row">
                  <h3>关键词组编辑</h3>
                  <button className="ghost" onClick={handleAddKeywordRow} type="button">
                    新增一组
                  </button>
                </div>
                <div className="keyword-table">
                  {settingsForm.keyword_rows.map((row, index) => (
                    <div key={`keyword-row-${index}`} className="keyword-row">
                      <span className="row-index">#{index + 1}</span>
                      <input
                        value={row}
                        placeholder="例如：report generation && llm"
                        onChange={(event) => handleKeywordRowChange(index, event.target.value)}
                      />
                      <button
                        className="ghost"
                        type="button"
                        onClick={() => handleRemoveKeywordRow(index)}
                        disabled={settingsForm.keyword_rows.length <= 1}
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
                <p className="hint">
                  逻辑预览：{parseKeywordRows(settingsForm.keyword_rows).map((group) => `(${formatKeywordGroup(group)})`).join(" OR ") || "未配置"}
                </p>
              </article>
            </div>
          ) : null}

          {dashboardTab === "records" ? (
            <div className="records-grid">
              <article className="card log-card">
                <div className="card-title-row">
                  <h3>最近执行日志</h3>
                  <span className="badge">{logs.length} 条</span>
                </div>
                <ul className="log-list">
                  {logs.length === 0 ? <li className="log-item">暂无执行记录</li> : null}
                  {logs.map((item) => (
                    <li key={item.id} className="log-item">
                      <div className="meta">
                        <span>{item.created_at}</span>
                        <span>{item.run_type}</span>
                        <span>{item.status}</span>
                      </div>
                      <div>{item.message}</div>
                    </li>
                  ))}
                </ul>
              </article>

              <article className="card log-card">
                <div className="card-title-row">
                  <h3>最近入库论文</h3>
                  <span className="badge">{papers.length} 条</span>
                </div>
                <ul className="log-list">
                  {papers.length === 0 ? <li className="log-item">暂无论文记录</li> : null}
                  {papers.map((paper) => (
                    <li key={paper.id} className="log-item">
                      <div className="meta">
                        <span>{paper.push_date}</span>
                        <span>{paper.source || "unknown"}</span>
                        <span>{paper.run_type}</span>
                      </div>
                      <div>{paper.title || paper.uid}</div>
                      {paper.url ? (
                        <a className="paper-link" href={paper.url} target="_blank" rel="noreferrer">
                          {paper.url}
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </article>


            </div>
          ) : null}
          {dashboardTab === "feedback" ? (
            <article className="card span-all feedback-card">
              <div className="card-title-row">
                <h3>感谢您提供宝贵意见～</h3>
                <span className="badge">{feedbackItems.length} 条</span>
              </div>

              <label>
                <textarea
                  className="feedback-textarea"
                  rows={4}
                  maxLength={4000}
                  placeholder="例如：希望支持按期刊分组展示、关键词命中高亮、推送摘要更精简..."
                  value={feedbackContent}
                  onChange={(event) => setFeedbackContent(event.target.value)}
                ></textarea>
              </label>
              <div className="inline-actions">
                <button className="primary" onClick={handleSubmitFeedback} disabled={isBusy("submit-feedback")}>
                  {isBusy("submit-feedback") ? "提交中..." : "提交反馈"}
                </button>
              </div>

              <ul className="feedback-list">
                {feedbackItems.length === 0 ? (
                  <li className="log-item">暂时还没有反馈记录，欢迎留下第一条建议。</li>
                ) : null}
                {feedbackItems.map((item) => (
                  <li key={item.id} className="log-item">
                    <div className="meta">
                      <span>{item.created_at}</span>
                      <span>{item.email_sent ? "已发送到管理员邮箱" : "邮件发送失败"}</span>
                    </div>
                    <div>{item.content}</div>
                    {!item.email_sent && item.email_error ? (
                      <p className="hint">失败原因：{item.email_error}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </article>
          ) : null}

        </section>
      ) : null}

      <div className={`toast ${toast.visible ? "" : "hidden"} ${toast.error ? "error" : ""}`}>{toast.message}</div>
    </main>
  );
}
