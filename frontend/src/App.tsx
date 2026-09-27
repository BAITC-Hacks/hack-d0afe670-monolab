import { useCallback, useEffect, useRef, useState } from "react";
import {
  cvClassToDefectType,
  detectDefect,
  fetchHealth,
  fetchWarrantyMarkers,
  generateComplaint,
  matchDefect,
  type ComplaintResponse,
  type CVDetectionResponse,
  type MatchResponse,
  type WarrantyRoadSegment,
} from "./api";
import YandexMapPicker from "./components/YandexMapPicker";
import {
  copyText,
  downloadPdfFromBase64,
  eOtinishHint,
  openEOtinish,
} from "./eOtinish";

const DEFAULT_LAT = 43.2404;
const DEFAULT_LNG = 76.9078;

const DEFECT_TYPES = [
  { value: "pothole", label: "Выбоина / яма" },
  { value: "manhole", label: "Повреждённый люк" },
  { value: "crack", label: "Трещина покрытия" },
  { value: "marking", label: "Стертая разметка" },
  { value: "subsidence", label: "Просадка покрытия" },
];

function formatContractDate(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export default function App() {
  const [lat, setLat] = useState(DEFAULT_LAT);
  const [lng, setLng] = useState(DEFAULT_LNG);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchResponse | null>(null);
  const [contractsCount, setContractsCount] = useState<number | null>(null);
  const [warrantySegments, setWarrantySegments] = useState<WarrantyRoadSegment[]>([]);

  const [defectType, setDefectType] = useState("pothole");
  const [userName, setUserName] = useState("");
  const [userIin, setUserIin] = useState("");
  const [userPhone, setUserPhone] = useState("");
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [cvResult, setCvResult] = useState<CVDetectionResponse | null>(null);
  const [cvLoading, setCvLoading] = useState(false);
  const [cvError, setCvError] = useState<string | null>(null);
  const photoInputRef = useRef<HTMLInputElement>(null);

  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState<string | null>(null);
  const [complaint, setComplaint] = useState<ComplaintResponse | null>(null);
  const [submitHint, setSubmitHint] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchHealth()
      .then((h) => setContractsCount(h.tenderai_contracts ?? h.contracts_count ?? null))
      .catch(() => setContractsCount(null));
    fetchWarrantyMarkers()
      .then((data) => setWarrantySegments(data.markers))
      .catch(() => setWarrantySegments([]));
  }, []);

  const onSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setComplaint(null);
    setDocError(null);
    setSubmitHint(null);
    try {
      const data = await matchDefect(lat, lng);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка запроса");
    } finally {
      setLoading(false);
    }
  }, [lat, lng]);

  const onPhotoChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const dataUrl = await readFileAsDataUrl(file);
    setPhotoPreview(dataUrl);
    setPhotoBase64(dataUrl);
    setCvResult(null);
    setCvError(null);
    setCvLoading(true);
    try {
      const cv = await detectDefect(file);
      setCvResult(cv);
      if (cv.primary_defect) {
        setDefectType(cvClassToDefectType(cv.primary_defect));
      }
      if (cv.message === "no_defect_detected") {
        setCvError("Дефект на фото не распознан — выберите тип вручную.");
      }
    } catch (err) {
      setCvError(
        err instanceof Error
          ? err.message.includes("503")
            ? "CV-модель не загружена на сервере (нужен best.pt)"
            : err.message
          : "Ошибка распознавания фото"
      );
    } finally {
      setCvLoading(false);
    }
  }, []);

  const buildPayload = useCallback(() => {
    if (!result?.match_found || !result.supplier?.name) return null;
    return {
      user_info: {
        name: userName || undefined,
        iin: userIin || undefined,
        phone: userPhone || undefined,
      },
      defect_info: {
        address_description: result.address_display || result.street_name || "Адрес не определён",
        gps: { lat, lng },
        defect_type: defectType,
        severity: "high",
        photo_urls: [],
        photo_base64: photoBase64 || undefined,
      },
      contract_info: {
        contract_number: result.trd_buy_id || result.contract_id || undefined,
        trd_buy_id: result.trd_buy_id || undefined,
        contract_date: formatContractDate(result.completed_on),
        customer_name: result.customer_name || undefined,
        supplier_name: result.supplier.name,
        supplier_bin: result.supplier.bin || undefined,
        warranty_ends: result.warranty_ends || undefined,
        warranty_active: result.warranty_active,
      },
    };
  }, [result, lat, lng, defectType, userName, userIin, userPhone, photoBase64]);

  const onGenerateDoc = useCallback(async () => {
    const payload = buildPayload();
    if (!payload) return;
    setDocLoading(true);
    setDocError(null);
    setComplaint(null);
    setSubmitHint(null);
    try {
      const data = await generateComplaint(payload);
      setComplaint(data);
    } catch (e) {
      setDocError(e instanceof Error ? e.message : "Не удалось сформировать заявление");
    } finally {
      setDocLoading(false);
    }
  }, [buildPayload]);

  const onCopyDoc = useCallback(async () => {
    if (!complaint) return;
    await copyText(complaint.document_body);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [complaint]);

  const onSubmitEOtinish = useCallback(async () => {
    if (!complaint) return;
    await copyText(complaint.document_body);
    if (complaint.pdf_base64 && complaint.pdf_filename) {
      downloadPdfFromBase64(complaint.pdf_base64, complaint.pdf_filename);
    }
    openEOtinish(complaint);
    setSubmitHint(eOtinishHint());
  }, [complaint]);

  const canGenerate =
    result?.match_found && result.supplier?.name && result.warranty_active;

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">Talap</span>
          <p className="tagline">Гарантия на дорогу — заявление в e-Otinish за 2 минуты</p>
        </div>
        {contractsCount !== null && (
          <div className="stat-pill">
            <span className="stat-value">{contractsCount.toLocaleString("ru-RU")}</span>
            <span className="stat-label">гарантий · Алматы / Астана</span>
          </div>
        )}
      </header>

      <main className="hero">
        <div className="map-wrap">
          <YandexMapPicker
            lat={lat}
            lng={lng}
            segments={warrantySegments}
            onChange={(newLat, newLng) => {
              setLat(newLat);
              setLng(newLng);
            }}
          />
          <div className="map-overlay">
            <p>Отметьте дефект</p>
            <code>{lat.toFixed(5)}, {lng.toFixed(5)}</code>
          </div>
        </div>

        <aside className="sidebar">
          <div className="sidebar-inner">
            <button className="cta" onClick={onSearch} disabled={loading}>
              {loading ? "Ищем подрядчика…" : "Проверить гарантию"}
            </button>

            {error && <div className="panel panel-error">{error}</div>}

            {!error && !result && !loading && (
              <div className="panel panel-empty">
                <h2>Как это работает</h2>
                <ol>
                  <li>Сфотографируйте дефект и отметьте точку на карте</li>
                  <li>Найдём подрядчика по базе TenderAI (549+ договоров)</li>
                  <li>Сформируем PDF и откроем e-Otinish для подачи</li>
                </ol>
              </div>
            )}

            {result && (
              <div className={`panel ${result.match_found ? "panel-hit" : "panel-miss"}`}>
                <div className="panel-head">
                  <h2>{result.match_found ? "Подрядчик найден" : "Договор не найден"}</h2>
                  {result.warranty_active !== null && result.warranty_active !== undefined && (
                    <span
                      className={`status-chip ${
                        result.warranty_active ? "status-ok" : "status-bad"
                      }`}
                    >
                      {result.warranty_active ? "Гарантия действует" : "Гарантия истекла"}
                    </span>
                  )}
                </div>

                {result.address_display && (
                  <p className="address">{result.address_display}</p>
                )}

                {result.supplier && (
                  <div className="info-block">
                    <h3>Подрядчик</h3>
                    <p className="info-main">{result.supplier.name}</p>
                    <p className="info-sub">БИН {result.supplier.bin || "—"}</p>
                  </div>
                )}

                {result.customer_name && (
                  <div className="info-block">
                    <h3>Адресат (акимат / управление)</h3>
                    <p className="info-main">{result.customer_name}</p>
                  </div>
                )}

                {result.warranty_ends && (
                  <p className="warranty-line">
                    {result.warranty_active
                      ? `Гарантия до ${result.warranty_ends}`
                      : `Истекла ${result.warranty_ends}`}
                    {result.days_remaining != null && result.warranty_active && (
                      <span> · {result.days_remaining} дн.</span>
                    )}
                  </p>
                )}

                {canGenerate && (
                  <div className="doc-form">
                    <h3 className="doc-form-title">Фиксация дефекта</h3>

                    <label className="photo-upload">
                      <input
                        ref={photoInputRef}
                        type="file"
                        accept="image/*"
                        capture="environment"
                        onChange={onPhotoChange}
                        hidden
                      />
                      <span className="photo-upload-btn">
                        {photoPreview ? "Сменить фото" : "Сфотографировать дефект"}
                      </span>
                      {photoPreview && (
                        <img src={photoPreview} alt="Дефект" className="photo-preview" />
                      )}
                    </label>

                    {cvLoading && <p className="cv-hint">Распознаём дефект на фото…</p>}
                    {cvError && <p className="cv-hint cv-hint-warn">{cvError}</p>}
                    {cvResult?.primary_defect && (
                      <p className="cv-hint cv-hint-ok">
                        AI: {cvResult.primary_defect}
                        {cvResult.severity_tier === "HAZARD_FASTTRACK" && " · срочно"}
                        {cvResult.detections[0] &&
                          ` (${Math.round(cvResult.detections[0].confidence * 100)}%)`}
                      </p>
                    )}

                    <label className="field">
                      <span>Тип дефекта</span>
                      <select
                        value={defectType}
                        onChange={(e) => setDefectType(e.target.value)}
                      >
                        {DEFECT_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </label>

                    <label className="field">
                      <span>ФИО</span>
                      <input
                        type="text"
                        placeholder="Иванов Иван Иванович"
                        value={userName}
                        onChange={(e) => setUserName(e.target.value)}
                      />
                    </label>

                    <div className="field-row">
                      <label className="field">
                        <span>ИИН</span>
                        <input
                          type="text"
                          inputMode="numeric"
                          placeholder="12 цифр"
                          value={userIin}
                          onChange={(e) => setUserIin(e.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Телефон</span>
                        <input
                          type="tel"
                          placeholder="+7 ..."
                          value={userPhone}
                          onChange={(e) => setUserPhone(e.target.value)}
                        />
                      </label>
                    </div>

                    <button
                      type="button"
                      className="cta cta-secondary"
                      onClick={onGenerateDoc}
                      disabled={docLoading}
                    >
                      {docLoading ? "Формируем PDF…" : "Сформировать заявление"}
                    </button>
                  </div>
                )}

                {result.match_found && !result.warranty_active && (
                  <p className="doc-hint">
                    Гарантия истекла — заявление по гарантии сформировать нельзя.
                  </p>
                )}

                {docError && <div className="panel panel-error doc-error">{docError}</div>}
              </div>
            )}

            {complaint && (
              <div className="panel panel-doc">
                <div className="panel-head">
                  <h2>Готово к подаче</h2>
                  {complaint.llm_enhanced && (
                    <span className="status-chip status-ok">LLM</span>
                  )}
                </div>
                <p className="doc-subject">
                  <strong>Тема:</strong> {complaint.subject}
                </p>
                <p className="doc-target">
                  <strong>Адресат:</strong> {complaint.target_department}
                </p>
                <pre className="doc-body">{complaint.document_body}</pre>

                <div className="doc-actions">
                  <button type="button" className="copy-btn" onClick={onCopyDoc}>
                    {copied ? "Скопировано" : "Копировать текст"}
                  </button>
                  {complaint.pdf_base64 && complaint.pdf_filename && (
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() =>
                        downloadPdfFromBase64(
                          complaint.pdf_base64!,
                          complaint.pdf_filename!
                        )
                      }
                    >
                      Скачать PDF
                    </button>
                  )}
                </div>

                <button
                  type="button"
                  className="cta cta-eotinish"
                  onClick={onSubmitEOtinish}
                >
                  Подать в e-Otinish
                </button>
                {submitHint && <p className="submit-hint">{submitHint}</p>}
              </div>
            )}
          </div>
        </aside>
      </main>

      <footer className="footer">
        Talap · база TenderAI · карта Яндекс · Goszakup только по необходимости
      </footer>
    </div>
  );
}
