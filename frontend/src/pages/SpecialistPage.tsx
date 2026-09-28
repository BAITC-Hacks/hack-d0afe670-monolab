import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  fetchSpecialistComplaints,
  fetchSpecialistDetail,
  fetchSpecialistPdf,
  fetchWarrantyMapMarkers,
  mediaUrl,
  specialistApprove,
  specialistReject,
  specialistResolve,
  type SpecialistDetail,
  type SpecialistSummary,
  type WarrantyRoadSegment,
} from "../api";
import YandexMapPicker from "../components/YandexMapPicker";
import { defectLabel, STATUS_LABELS, TIER_LABELS } from "../labels";

const ACTIVE_STATUSES = new Set(["REGISTERED", "IN_REVIEW", "FORWARDED"]);
const POLL_MS = 4000;

type ReportFilter = "all" | "repeat" | "mass";
type SortMode = "urgency" | "date";

function reportsLabel(count: number): string {
  if (count >= 5) return `${count} обращений — массовая жалоба`;
  if (count >= 2) return `${count} обращения на этом участке`;
  return "";
}

function filterMinReports(filter: ReportFilter): number {
  if (filter === "mass") return 5;
  if (filter === "repeat") return 2;
  return 1;
}

function isActionable(item: SpecialistSummary): boolean {
  return ACTIVE_STATUSES.has(item.status);
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ru-KZ", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function SpecialistPage() {
  const location = useLocation();
  const isAdmin = location.pathname.startsWith("/admin");
  const panelTitle = isAdmin ? "Talap · Админ-панель" : "Talap · Специалист";
  const loginTitle = isAdmin ? "Админ-панель" : "Кабинет специалиста";

  const [apiKey, setApiKey] = useState("");
  const [authed, setAuthed] = useState(false);
  const [list, setList] = useState<SpecialistSummary[]>([]);
  const [selected, setSelected] = useState<SpecialistDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const autoSelectedRef = useRef(false);
  const [warrantySegments, setWarrantySegments] = useState<WarrantyRoadSegment[]>([]);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const pdfUrlRef = useRef<string | null>(null);
  const [reportFilter, setReportFilter] = useState<ReportFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("urgency");

  const loadList = useCallback(async (key: string, silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await fetchSpecialistComplaints(key, {
        min_reports: filterMinReports(reportFilter),
        sort: sortMode,
      });
      setList((prev) => {
        if (prev.length > 0) {
          const prevIds = new Set(prev.map((p) => p.id));
          const arrived = data.filter((d) => !prevIds.has(d.id)).map((d) => d.id);
          if (arrived.length > 0) {
            setNewIds((n) => new Set([...n, ...arrived]));
          }
        }
        return data;
      });
      setAuthed(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Ошибка доступа";
      if (msg.includes("503") || msg.toLowerCase().includes("not configured")) {
        setError(
          "Сервер не настроен: добавьте SPECIALIST_API_KEY в backend/.env и перезапустите API."
        );
      } else if (msg.includes("Failed to fetch") || msg.includes("NetworkError")) {
        setError("Не удалось подключиться к API. Запустите backend на порту 8001 и Postgres (docker compose up -d).");
      } else if (msg.includes("401")) {
        setError("Неверный ключ доступа. Проверьте SPECIALIST_API_KEY на сервере.");
      } else {
        setError(msg);
      }
      if (!silent) setAuthed(false);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [reportFilter, sortMode]);

  const openDetail = async (id: number) => {
    if (!apiKey) return;
    setNewIds((n) => {
      const next = new Set(n);
      next.delete(id);
      return next;
    });
    setLoading(true);
    try {
      const detail = await fetchSpecialistDetail(apiKey, id);
      setSelected(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  const loadPdf = useCallback(async (id: number) => {
    if (!apiKey) return;
    setPdfLoading(true);
    setError(null);
    try {
      const blob = await fetchSpecialistPdf(apiKey, id);
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current);
      }
      const url = URL.createObjectURL(blob);
      pdfUrlRef.current = url;
      setPdfUrl(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить PDF");
      setPdfUrl(null);
    } finally {
      setPdfLoading(false);
    }
  }, [apiKey]);

  useEffect(() => {
    if (authed && apiKey) loadList(apiKey);
  }, [authed, apiKey, loadList, reportFilter, sortMode]);

  useEffect(() => {
    if (!authed || !apiKey) return;
    const timer = window.setInterval(() => {
      void loadList(apiKey, true);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [authed, apiKey, loadList]);

  useEffect(() => {
    if (!authed) return;
    fetchWarrantyMapMarkers()
      .then((data) => setWarrantySegments(data.markers))
      .catch(() => {});
  }, [authed]);

  useEffect(() => {
    if (!authed || !apiKey || list.length === 0 || autoSelectedRef.current) return;
    autoSelectedRef.current = true;
    void openDetail(list[0].id);
  }, [authed, apiKey, list]);

  useEffect(() => {
    if (!selected || !apiKey) {
      setPdfUrl(null);
      return;
    }
    void loadPdf(selected.id);
  }, [selected?.id, apiKey, loadPdf]);

  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
    };
  }, []);

  const onApprove = async () => {
    if (!selected || !apiKey) return;
    await specialistApprove(apiKey, selected.id, "Одобрено специалистом");
    await openDetail(selected.id);
    await loadList(apiKey, true);
    await loadPdf(selected.id);
  };

  const onReject = async () => {
    if (!selected || !apiKey || rejectReason.trim().length < 3) return;
    await specialistReject(apiKey, selected.id, rejectReason);
    await openDetail(selected.id);
    await loadList(apiKey, true);
  };

  const onResolve = async () => {
    if (!selected || !apiKey) return;
    await specialistResolve(apiKey, selected.id, "Дефект устранён");
    await openDetail(selected.id);
    await loadList(apiKey, true);
  };

  if (!authed) {
    return (
      <div className="app app-flow">
        <main className="flow-main">
          <div className="flow-shell flow-panel specialist-auth">
            <h1 className="flow-title">{loginTitle}</h1>
            <p className="flow-subtitle">
              Введите ключ доступа (значение <code>SPECIALIST_API_KEY</code> на сервере).
            </p>
            <input
              className="specialist-key-input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="X-Specialist-Key"
            />
            {error && <div className="panel panel-error">{error}</div>}
            <button type="button" className="cta" onClick={() => loadList(apiKey)} disabled={!apiKey}>
              Войти
            </button>
            <Link className="cta cta-secondary" to="/">← Гражданский портал</Link>
          </div>
        </main>
      </div>
    );
  }

  const pendingCount = list.filter(isActionable).length;
  const urgentCount = list.filter((i) => i.tier === "HAZARD_FASTTRACK" && isActionable(i)).length;

  return (
    <div className="app app-flow specialist-layout">
      <header className="header header-flow specialist-header">
        <div className="flow-shell header-inner specialist-header-inner">
          <div className="specialist-header-title">
            <span className="logo">{panelTitle}</span>
            {pendingCount > 0 && (
              <span className="specialist-live-pill">
                <span className="specialist-live-dot" aria-hidden="true" />
                {pendingCount} в работе
              </span>
            )}
          </div>
          {urgentCount > 0 && (
            <span className="specialist-urgent-pill">{urgentCount} срочных</span>
          )}
        </div>
      </header>

      <main className="flow-main">
        <div className="flow-shell specialist-grid">
          <aside className="specialist-list">
            <div className="specialist-inbox-head">
              <h2>Входящие заявки</h2>
              {list.length > 0 && (
                <span className="specialist-inbox-count">{list.length}</span>
              )}
            </div>
            <div className="specialist-filters">
              <div className="specialist-filter-group">
                <button
                  type="button"
                  className={`specialist-filter-btn ${reportFilter === "all" ? "specialist-filter-btn-active" : ""}`}
                  onClick={() => setReportFilter("all")}
                >
                  Все
                </button>
                <button
                  type="button"
                  className={`specialist-filter-btn ${reportFilter === "repeat" ? "specialist-filter-btn-active" : ""}`}
                  onClick={() => setReportFilter("repeat")}
                >
                  2+ на участке
                </button>
                <button
                  type="button"
                  className={`specialist-filter-btn ${reportFilter === "mass" ? "specialist-filter-btn-active" : ""}`}
                  onClick={() => setReportFilter("mass")}
                >
                  5+ массовые
                </button>
              </div>
              <select
                className="specialist-sort-select"
                value={sortMode}
                onChange={(e) => setSortMode(e.target.value as SortMode)}
              >
                <option value="urgency">Сначала срочные</option>
                <option value="date">Сначала новые</option>
              </select>
            </div>
            {loading && list.length === 0 && <p className="specialist-loading">Загрузка…</p>}
            {!loading && list.length === 0 && (
              <p className="specialist-empty">Новых заявок нет</p>
            )}
            {list.map((item) => {
              const actionable = isActionable(item);
              const urgent = item.tier === "HAZARD_FASTTRACK";
              const isNew = newIds.has(item.id);
              const reports = item.reports_at_location ?? 1;
              const mass = reports >= 5;
              const repeat = reports >= 2;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={[
                    "specialist-list-item",
                    selected?.id === item.id ? "specialist-list-item-active" : "",
                    actionable ? "specialist-list-item-pending" : "",
                    urgent && actionable ? "specialist-list-item-urgent" : "",
                    mass && actionable ? "specialist-list-item-mass" : "",
                    repeat && !mass && actionable ? "specialist-list-item-repeat" : "",
                    isNew ? "specialist-list-item-new" : "",
                  ].filter(Boolean).join(" ")}
                  onClick={() => openDetail(item.id)}
                >
                  <div className="specialist-list-top">
                    <strong>{item.service_request_id}</strong>
                    <span className={`status-chip status-${item.status}`}>
                      {STATUS_LABELS[item.status] ?? item.status}
                    </span>
                  </div>
                  {isNew && <span className="specialist-new-badge">Новая</span>}
                  {repeat && (
                    <span className={`specialist-reports-badge ${mass ? "specialist-reports-badge-mass" : ""}`}>
                      {reports} {reports === 1 ? "обращение" : reports < 5 ? "обращения" : "обращений"}
                    </span>
                  )}
                  <span className={`tier-badge tier-${item.tier}`}>
                    {TIER_LABELS[item.tier] ?? item.tier}
                  </span>
                  <span className="specialist-list-defect">{defectLabel(item.service_code)}</span>
                  <span className="specialist-list-meta">{formatTime(item.requested_datetime)}</span>
                </button>
              );
            })}
          </aside>

          <section className="specialist-detail">
            {!selected && !loading && (
              <div className="specialist-detail-empty">
                <p className="flow-subtitle">Выберите заявку из списка слева.</p>
              </div>
            )}
            {selected && (
              <>
                <div className="specialist-detail-head">
                  <div>
                    <h2>{selected.service_request_id}</h2>
                    <p className="specialist-detail-time">
                      Поступила {formatTime(selected.requested_datetime)}
                    </p>
                  </div>
                  <span className={`status-chip status-${selected.status} status-chip-lg`}>
                    {STATUS_LABELS[selected.status] ?? selected.status}
                  </span>
                </div>

                {(selected.reports_at_location ?? 1) >= 2 && (
                  <div className={`specialist-mass-alert ${(selected.reports_at_location ?? 1) >= 5 ? "specialist-mass-alert-high" : ""}`}>
                    <strong>{reportsLabel(selected.reports_at_location ?? 1)}</strong>
                    {selected.cluster_label && (
                      <span> — {selected.cluster_label}</span>
                    )}
                    {selected.related_service_request_ids && selected.related_service_request_ids.length > 0 && (
                      <p className="specialist-related-ids">
                        Связанные: {selected.related_service_request_ids.slice(0, 5).join(", ")}
                        {selected.related_service_request_ids.length > 5 ? "…" : ""}
                      </p>
                    )}
                  </div>
                )}

                {isActionable(selected) && (
                  <p className="ai-hint">Требуется решение специалиста</p>
                )}

                {selected.media_url && (
                  <img
                    className="specialist-photo"
                    src={mediaUrl(selected.media_url) ?? ""}
                    alt="Дефект"
                  />
                )}

                <ul className="specialist-facts">
                  <li>
                    Класс: <strong>{defectLabel(selected.service_code)}</strong>
                    {selected.cv_confidence != null &&
                      ` (${Math.round(selected.cv_confidence * 100)}%)`}
                  </li>
                  <li>Адрес: <strong>{selected.address}</strong></li>
                  <li>Уровень: <strong>{TIER_LABELS[selected.tier] ?? selected.tier}</strong></li>
                </ul>

                <div className="flow-map-compact">
                  <YandexMapPicker
                    lat={selected.lat}
                    lng={selected.long}
                    segments={warrantySegments}
                    defectDraggable={false}
                    onChange={() => {}}
                  />
                </div>

                {selected.warranty ? (
                  <div className="warranty-block">
                    <h3>Гарантийный договор</h3>
                    <p>Подрядчик: <strong>{selected.warranty.contractor_name}</strong></p>
                    {selected.warranty.contractor_bin && (
                      <p>БИН: <strong>{selected.warranty.contractor_bin}</strong></p>
                    )}
                    <p>Договор: <strong>{selected.warranty.trd_buy_id ?? selected.warranty.contract_id}</strong></p>
                    <p>Гарантия до: <strong>{selected.warranty.warranty_end}</strong></p>
                  </div>
                ) : (
                  <p className="general-maint-note">
                    Содержание дороги — гарантийный договор не найден
                  </p>
                )}

                <div className="specialist-pdf-block">
                  <div className="specialist-pdf-head">
                    <h3>Заявление (PDF)</h3>
                    <div className="specialist-pdf-actions">
                      {pdfUrl && (
                        <a className="cta cta-secondary cta-small" href={pdfUrl} target="_blank" rel="noreferrer">
                          Открыть в новой вкладке
                        </a>
                      )}
                      <button
                        type="button"
                        className="cta cta-secondary cta-small"
                        onClick={() => loadPdf(selected.id)}
                        disabled={pdfLoading}
                      >
                        {pdfLoading ? "Формируем…" : "Обновить PDF"}
                      </button>
                    </div>
                  </div>
                  {selected.generated_claim_subject && (
                    <p className="specialist-pdf-subject">
                      Тема: <strong>{selected.generated_claim_subject}</strong>
                    </p>
                  )}
                  {pdfUrl ? (
                    <iframe
                      className="specialist-pdf-frame"
                      src={pdfUrl}
                      title={`PDF ${selected.service_request_id}`}
                    />
                  ) : (
                    <p className="flow-subtitle">
                      {pdfLoading ? "Генерация PDF…" : "PDF недоступен"}
                    </p>
                  )}
                </div>

                <p className="complaint-preview-text">{selected.description}</p>

                {isActionable(selected) && (
                  <div className="specialist-actions">
                    <button type="button" className="cta" onClick={onApprove}>
                      Одобрить и передать
                    </button>
                    <input
                      className="specialist-key-input"
                      placeholder="Причина отклонения"
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                    />
                    <button type="button" className="cta cta-secondary" onClick={onReject}>
                      Отклонить
                    </button>
                    {selected.status === "FORWARDED" && (
                      <button type="button" className="cta cta-secondary" onClick={onResolve}>
                        Отметить устранённым
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
