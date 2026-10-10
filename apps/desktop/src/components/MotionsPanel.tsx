/** Character motions are downloaded VRMA files, grouped as role defaults or user extensions. */
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ACTION_LABELS, SEMANTIC_ACTIONS } from "@mochi/protocol";
import { configApi } from "../api/configClient";
import { skinsApi, type SkinSummary } from "../api/skinsClient";
import {
  MOTIONS_CHANGED,
  motionsApi,
  type MotionEntry,
  type MotionPatch,
} from "../api/motionsClient";
import { loadVrmStage, type VrmStage } from "../character/vrm/driver";
import { loadMotionTracks, loadVrmaFile } from "../character/vrm/motionLoader";

interface MotionsPanelProps {
  onClose: () => void;
}
const initialForm = {
  category: "custom" as "builtin" | "custom",
  actionId: "",
  label: "",
  credit: "",
  idle: false,
  agentSelectable: false,
};

export function MotionsPanel({ onClose }: MotionsPanelProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<VrmStage | null>(null);
  const requestRef = useRef(0);
  const timerRef = useRef<number | undefined>(undefined);
  const [skin, setSkin] = useState<SkinSummary | null>(null);
  const [ready, setReady] = useState(false);
  const [motions, setMotions] = useState<MotionEntry[]>([]);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState("");
  const [selected, setSelected] = useState<MotionEntry | null>(null);
  const [tab, setTab] = useState<"builtin" | "custom">("builtin");
  const [showImport, setShowImport] = useState(false);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [form, setForm] = useState(initialForm);
  const refresh = async () => setMotions(await motionsApi.listMotions(skin?.id));

  useEffect(() => {
    let cancelled = false;
    void Promise.all([skinsApi.listSkins(), configApi.getCharacter(), motionsApi.listMotions()])
      .then(([skins, character, list]) => {
        if (cancelled) return;
        setSkin(skins.find((entry) => entry.id === character.activeSkin) ?? null);
        setMotions(list.filter((entry) => !entry.skinId || entry.skinId === character.activeSkin));
      })
      .catch((err) => {
        if (!cancelled) setError(`动作管理加载失败：${err.message}`);
      });
    return () => {
      cancelled = true;
      requestRef.current += 1;
      window.clearTimeout(timerRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const update = () => {
      void motionsApi
        .listMotions(skin?.id)
        .then((list) => {
          if (!cancelled) setMotions(list);
        })
        .catch((err) => {
          if (!cancelled) setError(`动作列表刷新失败：${err.message}`);
        });
    };
    window.addEventListener("focus", update);
    window.addEventListener(MOTIONS_CHANGED, update);
    const channel =
      typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(MOTIONS_CHANGED) : null;
    if (channel) channel.onmessage = update;
    return () => {
      cancelled = true;
      window.removeEventListener("focus", update);
      window.removeEventListener(MOTIONS_CHANGED, update);
      channel?.close();
    };
  }, [skin?.id]);

  const idleMotion = motions.find((entry) => entry.id === "idle_neutral");
  useEffect(() => {
    if (!skin || skin.resourceType !== "vrm" || !hostRef.current) return;
    let cancelled = false;
    let stage: VrmStage | null = null;
    setReady(false);
    void loadVrmStage(hostRef.current, `${skin.resourceBaseUrl}/${skin.modelFile ?? ""}`, {
      view: "preview",
    })
      .then((loaded) => {
        if (cancelled) {
          loaded.dispose();
          return;
        }
        stage = loaded;
        stageRef.current = loaded;
        setReady(true);
      })
      .catch((err) => {
        if (!cancelled) setError(`预览加载失败：${err.message}`);
      });
    return () => {
      cancelled = true;
      stage?.dispose();
      stageRef.current = null;
    };
  }, [skin?.id, skin?.resourceType, skin?.resourceBaseUrl, skin?.modelFile]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!ready || !stage) return;
    let cancelled = false;
    const idle = idleMotion;
    if (!idle) stage.driver.setIdleMotion(null);
    else
      void loadMotionTracks(motionsApi.motionFileUrl(idle))
        .then((tracks) => {
          if (!cancelled) stage.driver.setIdleMotion(tracks);
        })
        .catch((err) => {
          if (!cancelled) setError(`待机文件无法播放：${err.message}`);
        });
    return () => {
      cancelled = true;
    };
  }, [ready, idleMotion?.file, idleMotion?.createdAt]);

  function stop() {
    requestRef.current += 1;
    window.clearTimeout(timerRef.current);
    stageRef.current?.driver.stopAction();
    setPlaying("");
  }

  async function play(entry: MotionEntry) {
    setSelected(entry);
    if (playing === entry.id) {
      stop();
      return;
    }
    const request = ++requestRef.current;
    window.clearTimeout(timerRef.current);
    setError("");
    setPlaying(entry.id);
    try {
      const tracks = await loadMotionTracks(motionsApi.motionFileUrl(entry));
      if (request !== requestRef.current) return;
      // Trial playback runs once even when the imported file is the looping idle base.
      stageRef.current?.driver.playAction({ ...entry, kind: "oneshot" }, tracks);
      timerRef.current = window.setTimeout(
        () => setPlaying(""),
        Math.round(tracks.duration * 1000),
      );
    } catch (err) {
      if (request !== requestRef.current) return;
      setError(`动作无法播放：${err instanceof Error ? err.message : String(err)}`);
      setPlaying("");
    }
  }

  async function importMotion() {
    if (!file) return;
    setImporting(true);
    setError("");
    try {
      const tracks = await loadVrmaFile(file);
      const base = file.name.replace(/\.vrma$/i, "");
      const safeName =
        base
          .toLowerCase()
          .replace(/[^a-z0-9_]/g, "_")
          .replace(/^[^a-z]+/, "")
          .slice(0, 30) || "motion";
      const id =
        form.actionId ||
        `ext.user.${safeName}_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
      const idle = id === "idle_neutral";
      await motionsApi.importMotion(file, {
        id,
        label: form.label.trim() || base,
        category: form.category,
        credit: form.credit.trim(),
        kind: idle ? "loop" : "oneshot",
        durationMs: Math.round(tracks.duration * 1000),
        priority: idle ? 10 : 50,
        cooldownMs: 5000,
        agentSelectable: !!form.actionId && !idle && form.agentSelectable,
        tags: idle || form.idle ? ["idle"] : id === "wave" ? ["greeting"] : [],
      });
      setFile(null);
      setForm(initialForm);
      setShowImport(false);
      setTab("custom");
      setSearch("");
      setNotice("动作已加入我的动作，可以点击预览。");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refresh();
    } catch (err) {
      setError(`导入失败：${err instanceof Error ? err.message : String(err)}`);
      void refresh().catch(() => undefined);
    } finally {
      setImporting(false);
    }
  }

  async function patch(id: string, values: MotionPatch) {
    setError("");
    try {
      await motionsApi.updateMotion(id, values);
      setEditing(null);
      setSelected((old) => (old?.id === id ? { ...old, ...values } : old));
      setNotice("播放设置已保存。");
      await refresh();
    } catch (err) {
      setError(`修改失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }
  async function remove(id: string) {
    setError("");
    try {
      await motionsApi.deleteMotion(id);
      if (playing === id) {
        requestRef.current += 1;
        window.clearTimeout(timerRef.current);
        stageRef.current?.driver.stopAction();
        setPlaying("");
      }
      setDeleting(null);
      setSelected((old) => (old?.id === id ? null : old));
      setNotice("动作已删除。");
      await refresh();
    } catch (err) {
      setError(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }
  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    if (selected) setForm((old) => ({ ...old, label: selected.name.replace(/\.vrma$/i, "") }));
  }

  const builtins = motions.filter((entry) => entry.source === "builtin");
  const custom = motions.filter((entry) => entry.source !== "builtin");
  const visible = (tab === "builtin" ? builtins : custom).filter((entry) =>
    entry.label.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <div className="settings-overlay">
      <div className="settings motions">
        <header className="settings__header motions__header" data-tauri-drag-region>
          <div>
            <h2>动作管理</h2>
            <p className="motions__hint">为 {skin?.name ?? "角色"} 选择喜欢的动作</p>
          </div>
          <div className="motions__header-actions">
            <button
              className="motions__add"
              onClick={() => {
                setShowImport(!showImport);
                setError("");
                setNotice("");
              }}
            >
              {showImport ? "返回动作列表" : "＋ 导入动作"}
            </button>
            <button className="settings__close" onClick={onClose} aria-label="关闭">
              ✕
            </button>
          </div>
        </header>
        {error ? (
          <p role="alert" className="settings__feedback settings__feedback--error">
            {error}
          </p>
        ) : null}
        {notice && !error ? (
          <p role="status" className="motions__notice">
            {notice}
          </p>
        ) : null}
        <div className="settings__body motions__body">
          <aside className="motions__preview">
            <div className="motions__preview-heading">
              <span>角色预览</span>
              <span className="motions__badge">{playing ? "播放中" : "待机"}</span>
            </div>
            <div className="motions__stage" ref={hostRef} aria-label="动作预览舞台">
              {!ready ? (
                <span className="motions__loading">
                  {skin?.resourceType === "vrm" ? "正在加载角色…" : "请选择 VRM 角色"}
                </span>
              ) : null}
            </div>
            <div className="motions__view-controls">
              <span className="motions__hint">拖动旋转 · 滚轮缩放</span>
              <button className="motions__link" onClick={() => stageRef.current?.resetView()}>
                重置视角
              </button>
            </div>
            <div className="motions__now-playing">
              <strong>{selected?.label ?? skin?.name ?? "Mochi"}</strong>
              <span className="motions__hint">
                {selected
                  ? `${(selected.durationMs / 1000).toFixed(1)} 秒 · ${selected.source === "builtin" ? "角色内置" : "我的动作"}`
                  : "选择右侧动作，看看角色的表现"}
              </span>
              {selected?.credit ? (
                <p className="motions__credit">作者署名：{selected.credit}</p>
              ) : null}
            </div>
          </aside>
          <section className="motions__workspace" aria-label="动作库">
            <div className="motions__library" hidden={showImport}>
              <div className="motions__tabs" role="tablist" aria-label="动作分类">
                <button
                  role="tab"
                  aria-selected={tab === "builtin"}
                  aria-controls="motion-list"
                  onClick={() => {
                    setTab("builtin");
                    setEditing(null);
                    setDeleting(null);
                  }}
                >
                  角色内置 <span>{builtins.length}</span>
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "custom"}
                  aria-controls="motion-list"
                  onClick={() => {
                    setTab("custom");
                    setEditing(null);
                    setDeleting(null);
                  }}
                >
                  我的动作 <span>{custom.length}</span>
                </button>
              </div>
              <input
                className="motions__input motions__search"
                aria-label="搜索动作"
                placeholder="搜索动作名称…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div
                className="motions__scroll"
                id="motion-list"
                role="tabpanel"
                aria-label={tab === "builtin" ? "角色内置" : "我的动作"}
              >
                {!visible.length ? (
                  <div className="motions__empty">
                    <strong>
                      {search
                        ? "没有找到这个动作"
                        : tab === "custom"
                          ? "添加一个喜欢的动作"
                          : "这个角色还没有内置动作"}
                    </strong>
                    <p className="motions__hint">
                      {search
                        ? "试试其他名称。"
                        : "从 VRoid 等网站下载 VRMA 文件，点击右上角导入。"}
                    </p>
                  </div>
                ) : null}
                <ul className="motions__list">
                  {visible.map((entry, index) => (
                    <li
                      key={entry.id}
                      className={`motions__row${selected?.id === entry.id ? " motions__row--selected" : ""}`}
                    >
                      <span className="motions__number">{String(index + 1).padStart(2, "0")}</span>
                      <span className="motions__label">
                        <strong>{entry.label}</strong>
                        <small className="motions__meta">
                          {(entry.durationMs / 1000).toFixed(1)} 秒 ·{" "}
                          {entry.id === "idle_neutral"
                            ? "待机循环"
                            : entry.id in ACTION_LABELS
                              ? ACTION_LABELS[entry.id as keyof typeof ACTION_LABELS]
                              : "自定义"}
                        </small>
                        <span className="motions__tags">
                          {entry.tags.includes("idle") && entry.id !== "idle_neutral" ? (
                            <span>待机随机</span>
                          ) : null}
                          {entry.agentSelectable ? <span>AI 可用</span> : null}
                        </span>
                      </span>
                      <button
                        className="motions__play"
                        disabled={!ready}
                        onClick={() => void play(entry)}
                        aria-label={`${playing === entry.id ? "停止" : "预览"}${entry.label}`}
                      >
                        {playing === entry.id ? "停止" : "预览"}
                      </button>
                      <button
                        className="motions__link"
                        aria-label={`设置${entry.label}`}
                        onClick={() => {
                          setSelected(entry);
                          setEditing(editing === entry.id ? null : entry.id);
                          setDeleting(null);
                        }}
                      >
                        设置
                      </button>
                      {editing === entry.id ? (
                        <EditForm
                          entry={entry}
                          onSave={(values) => void patch(entry.id, values)}
                          onCancel={() => setEditing(null)}
                        />
                      ) : null}
                      {entry.source !== "builtin" && editing === entry.id ? (
                        <div className="motions__delete">
                          {deleting === entry.id ? (
                            <>
                              <span>删除这个动作？</span>
                              <button
                                className="motions__link motions__link--danger"
                                onClick={() => void remove(entry.id)}
                              >
                                确认删除
                              </button>
                              <button className="motions__link" onClick={() => setDeleting(null)}>
                                取消
                              </button>
                            </>
                          ) : (
                            <button
                              className="motions__link motions__link--danger"
                              onClick={() => setDeleting(entry.id)}
                            >
                              删除动作
                            </button>
                          )}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="motions__footer">
                {tab === "builtin"
                  ? "角色自带的原始 VRMA · 点击设置调整自动播放"
                  : "你的 VRMA 收藏 · 可预览、设置或删除"}
              </p>
            </div>
            <div className="motions__import-pane" hidden={!showImport}>
              <h3>导入到我的动作</h3>
              <p className="motions__hint">选择下载并解压的 .vrma 文件，保留原有动作和时长。</p>
              <div className="motions__import">
                <label className="motions__file">
                  VRMA 文件
                  <input
                    ref={fileInputRef}
                    aria-label="VRMA 动作文件"
                    type="file"
                    accept=".vrma"
                    onChange={chooseFile}
                    disabled={importing}
                  />
                </label>
                <label>
                  动作名称
                  <input
                    className="motions__input"
                    aria-label="动作名称"
                    placeholder="给动作起一个名字"
                    maxLength={48}
                    value={form.label}
                    onChange={(e) => setForm((old) => ({ ...old, label: e.target.value }))}
                  />
                </label>
                <label>
                  用途
                  <select
                    className="motions__input"
                    aria-label="动作用途"
                    value={form.actionId}
                    onChange={(e) =>
                      setForm((old) => ({
                        ...old,
                        actionId: e.target.value,
                        agentSelectable: false,
                      }))
                    }
                  >
                    <option value="">自定义动作</option>
                    {SEMANTIC_ACTIONS.map((id) => {
                      const existing = motions.find((entry) => entry.id === id);
                      return (
                        <option key={id} value={id} disabled={!!existing}>
                          {id === "idle_neutral" ? "自然待机（循环）" : ACTION_LABELS[id]}
                          {existing ? `（${existing.label} 已使用）` : ""}
                        </option>
                      );
                    })}
                  </select>
                </label>
                <label>
                  作者署名
                  <input
                    className="motions__input"
                    aria-label="素材署名"
                    placeholder="按素材说明填写作者"
                    maxLength={300}
                    value={form.credit}
                    onChange={(e) => setForm((old) => ({ ...old, credit: e.target.value }))}
                  />
                </label>
                <label className="motions__check">
                  <input
                    type="checkbox"
                    checked={form.idle}
                    disabled={form.actionId === "idle_neutral"}
                    onChange={(e) => setForm((old) => ({ ...old, idle: e.target.checked }))}
                  />
                  待机时随机播放
                </label>
                <label className="motions__check">
                  <input
                    type="checkbox"
                    checked={form.agentSelectable}
                    disabled={!form.actionId || form.actionId === "idle_neutral"}
                    onChange={(e) =>
                      setForm((old) => ({ ...old, agentSelectable: e.target.checked }))
                    }
                  />
                  允许 AI 使用所选用途
                </label>
                <div className="motions__form-actions">
                  <button
                    className="motions__link"
                    disabled={importing}
                    onClick={() => setShowImport(false)}
                  >
                    取消
                  </button>
                  <button
                    className="motions__add"
                    disabled={!file || !ready || importing}
                    onClick={() => void importMotion()}
                  >
                    {importing ? "导入中…" : "添加动作"}
                  </button>
                </div>
              </div>
              <a
                className="motions__resource-link"
                href="https://booth.pm/ja/items/5512385"
                target="_blank"
                rel="noreferrer"
              >
                前往 VRoid 官方动作资源 ↗
              </a>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function EditForm({
  entry,
  onSave,
  onCancel,
}: {
  entry: MotionEntry;
  onSave: (values: MotionPatch) => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(entry.label);
  const [credit, setCredit] = useState(entry.credit ?? "");
  const [idle, setIdle] = useState(entry.tags.includes("idle"));
  const [agentSelectable, setSelectable] = useState(entry.agentSelectable);
  return (
    <div className="motions__edit">
      <input
        className="motions__input"
        aria-label="编辑动作名称"
        maxLength={48}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
      />
      {entry.source !== "builtin" ? (
        <input
          className="motions__input"
          aria-label="编辑素材署名"
          placeholder="作者署名"
          value={credit}
          maxLength={300}
          onChange={(e) => setCredit(e.target.value)}
        />
      ) : null}
      <label className="motions__check">
        <input
          type="checkbox"
          checked={idle}
          disabled={entry.id === "idle_neutral"}
          onChange={(e) => setIdle(e.target.checked)}
        />
        待机时随机播放
      </label>
      <label className="motions__check">
        <input
          type="checkbox"
          checked={agentSelectable}
          disabled={!(entry.id in ACTION_LABELS) || entry.id === "idle_neutral"}
          onChange={(e) => setSelectable(e.target.checked)}
        />
        允许 AI 使用
      </label>
      <div className="motions__form-actions">
        <button
          className="motions__add"
          onClick={() =>
            onSave({
              label: label.trim() || entry.label,
              credit,
              agentSelectable,
              tags: [...entry.tags.filter((tag) => tag !== "idle"), ...(idle ? ["idle"] : [])],
            })
          }
        >
          保存
        </button>
        <button className="motions__link" onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}
