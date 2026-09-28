import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { trackComplaint, type CitizenTrackResponse } from "../api";
import { STATUS_LABELS } from "../labels";

const TIMELINE_STEPS = [
  "SUBMITTED",
  "REGISTERED",
  "IN_REVIEW",
  "FORWARDED",
  "RESOLVED",
] as const;

function stepIndex(status: string): number {
  const idx = TIMELINE_STEPS.indexOf(status as (typeof TIMELINE_STEPS)[number]);
  if (idx >= 0) return idx;
  if (status === "REJECTED") return 1;
  return 0;
}

export default function TrackPage() {
  const { reg } = useParams<{ reg: string }>();
  const [data, setData] = useState<CitizenTrackResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!reg) return;
    setLoading(true);
    trackComplaint(reg)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [reg]);

  const activeIdx = data ? stepIndex(data.status) : 0;

  return (
    <div className="app app-flow">
      <header className="header header-flow">
        <div className="flow-shell header-inner">
          <Link to="/" className="logo">Talap</Link>
        </div>
      </header>

      <main className="flow-main">
        <div className="flow-shell flow-panel">
          <h1 className="flow-title">Статус заявки</h1>
          {loading && <p className="flow-subtitle">Загрузка…</p>}
          {error && <div className="panel panel-error">{error}</div>}
          {data && (
            <>
              <p className="success-ticket">
                № <strong>{data.service_request_id}</strong>
              </p>
              <p className="flow-subtitle">{data.service_name} · {data.address}</p>
              <ol className="track-timeline">
                {TIMELINE_STEPS.map((code, index) => {
                  const event = data.events.find((e) => e.to_status === code);
                  const done = index <= activeIdx;
                  const active = index === activeIdx;
                  return (
                    <li
                      key={code}
                      className={`track-step ${done ? "track-step-done" : ""} ${active ? "track-step-active" : ""}`}
                    >
                      <span className="track-step-dot">{done ? "✓" : index + 1}</span>
                      <div>
                        <strong>{STATUS_LABELS[code] ?? code}</strong>
                        {event && (
                          <p className="track-step-time">
                            {new Date(event.created_at).toLocaleString("ru-RU")}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>

              {data.status === "REJECTED" && (
                <p className="scan-result-warn">Заявка отклонена специалистом.</p>
              )}

              {data.response_deadline && (
                <p className="flow-subtitle">
                  Срок ответа: {new Date(data.response_deadline).toLocaleDateString("ru-RU")}
                </p>
              )}
            </>
          )}
          <Link className="cta cta-secondary" to="/">На главную</Link>
        </div>
      </main>
    </div>
  );
}
