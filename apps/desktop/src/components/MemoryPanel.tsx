/**
 * MemoryPanel —— 记忆管理面板（M1-S3，功能清单 6.4）。
 *
 * 用户隐私可控是验收红线：查看/编辑/删除任一条记忆，一键清空。
 * 列表按创建时间倒序，每条带类别标签（事实/偏好）和来源（自动/手动）。
 * 内联编辑（textarea + 保存/取消）与内联二次确认删除，与 HistoryPanel 同模式。
 */
import { useCallback, useEffect, useState } from "react";
import { memoryApi, type MemoryCategory, type MemoryItem } from "../api/memoryClient";
import { useI18n } from "../i18n";

interface MemoryPanelProps {
  onClose: () => void;
}

export function MemoryPanel({ onClose }: MemoryPanelProps) {
  const { t } = useI18n();
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const [newText, setNewText] = useState("");
  const [newCategory, setNewCategory] = useState<MemoryCategory>("fact");

  const load = useCallback(async () => {
    try {
      setMemories(await memoryApi.listMemories());
      setError(null);
    } catch {
      setError(t("memory.errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate() {
    const content = newText.trim();
    if (!content) return;
    try {
      await memoryApi.createMemory(content, newCategory);
      setNewText("");
      await load();
    } catch {
      setError(t("memory.errorSave"));
    }
  }

  function startEdit(m: MemoryItem) {
    setEditingId(m.id);
    setEditText(m.content);
    setConfirmDeleteId(null);
  }

  async function handleSaveEdit() {
    if (!editingId) return;
    try {
      await memoryApi.updateMemory(editingId, editText.trim());
      setEditingId(null);
      await load();
    } catch {
      setError(t("memory.errorSave"));
    }
  }

  async function handleDelete(id: string) {
    try {
      await memoryApi.deleteMemory(id);
    } catch {
      // 删除失败不阻断
    }
    setConfirmDeleteId(null);
    await load();
  }

  async function handleClearAll() {
    setConfirmClearAll(false);
    try {
      await memoryApi.clearAll();
      await load();
    } catch {
      setError(t("memory.errorSave"));
    }
  }

  const categoryLabel = (cat: MemoryCategory) =>
    cat === "preference" ? t("memory.categoryPreference") : t("memory.categoryFact");

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <header className="settings__header" data-tauri-drag-region>
          <h2>{t("memory.title")}</h2>
          <button className="settings__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </header>

        {error ? <p className="settings__error">{error}</p> : null}

        {/* 添加记忆 */}
        <div className="memory__add">
          <textarea
            className="memory__input"
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            placeholder={t("memory.addPlaceholder")}
            rows={2}
            maxLength={500}
          />
          <div className="memory__add-actions">
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value as MemoryCategory)}
              className="memory__category-select"
            >
              <option value="fact">{t("memory.categoryFact")}</option>
              <option value="preference">{t("memory.categoryPreference")}</option>
            </select>
            <button className="btn btn--primary" onClick={handleCreate} disabled={!newText.trim()}>
              {t("memory.add")}
            </button>
          </div>
        </div>

        {/* 清空全部 */}
        {memories.length > 0 ? (
          <div className="memory__toolbar">
            <span className="settings__item-sub">{t("memory.count", { n: memories.length })}</span>
            {confirmClearAll ? (
              <>
                <button className="btn btn--ghost settings__danger" onClick={handleClearAll}>
                  {t("memory.clearAllConfirm")}
                </button>
                <button className="btn btn--ghost" onClick={() => setConfirmClearAll(false)}>
                  {t("common.cancel")}
                </button>
              </>
            ) : (
              <button
                className="btn btn--ghost settings__danger"
                onClick={() => setConfirmClearAll(true)}
              >
                {t("memory.clearAll")}
              </button>
            )}
          </div>
        ) : null}

        {/* 记忆列表 */}
        {loading ? (
          <p className="settings__item-sub">{t("memory.loading")}</p>
        ) : memories.length === 0 ? (
          <p className="settings__item-sub history__empty">{t("memory.empty")}</p>
        ) : (
          <ul className="settings__list">
            {memories.map((m) => (
              <li key={m.id} className="settings__item memory__item">
                {editingId === m.id ? (
                  <div className="memory__edit">
                    <textarea
                      className="memory__input"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={2}
                      maxLength={500}
                      autoFocus
                    />
                    <div className="memory__edit-actions">
                      <button
                        className="btn btn--primary"
                        onClick={handleSaveEdit}
                        disabled={!editText.trim()}
                      >
                        {t("common.save")}
                      </button>
                      <button className="btn btn--ghost" onClick={() => setEditingId(null)}>
                        {t("common.cancel")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="memory__content">
                      <span className={`memory__badge memory__badge--${m.category}`}>
                        {categoryLabel(m.category)}
                      </span>
                      <span className="memory__source">
                        {m.source === "auto" ? t("memory.sourceAuto") : t("memory.sourceManual")}
                      </span>
                      <p className="memory__text">{m.content}</p>
                    </div>
                    <div className="settings__item-actions">
                      {confirmDeleteId === m.id ? (
                        <>
                          <button
                            className="btn btn--ghost settings__danger"
                            onClick={() => handleDelete(m.id)}
                          >
                            {t("common.delete")}
                          </button>
                          <button
                            className="btn btn--ghost"
                            onClick={() => setConfirmDeleteId(null)}
                          >
                            {t("common.cancel")}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="btn btn--ghost"
                            onClick={() => startEdit(m)}
                            aria-label={t("common.edit")}
                          >
                            ✏️
                          </button>
                          <button
                            className="btn btn--ghost settings__danger"
                            onClick={() => setConfirmDeleteId(m.id)}
                            aria-label={t("common.delete")}
                          >
                            🗑
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
