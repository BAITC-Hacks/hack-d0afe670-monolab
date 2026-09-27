import { useCallback, useEffect, useState } from "react";
import {
  cvClassToDefectType,
  detectDefect,
  fetchWarrantyMarkers,
  generateComplaint,
  matchDefect,
  type ComplaintResponse,
  type CVDetectionResponse,
  type MatchResponse,
  type WarrantyRoadSegment,
} from "./api";
import CameraCapture from "./components/flow/CameraCapture";
import FlowProgress from "./components/flow/FlowProgress";
import PhotoScanView from "./components/flow/PhotoScanView";
import StepLoader from "./components/flow/StepLoader";
import YandexMapPicker from "./components/YandexMapPicker";
import { copyText, eOtinishHint, openEOtinish } from "./eOtinish";
import {
  defectLabel,
  demoDetectDefect,
  demoGenerateComplaint,
  demoMatchDefect,
  demoSubmitTicket,
  isDemoMode,
  MOCK_DEDUP,
  MOCK_TENDER_AMOUNT,
  MOCK_TICKET_ID,
} from "./mock/demoFlow";

const DEFAULT_LAT = 43.2404;
const DEFAULT_LNG = 76.9078;

type Step = 1 | 2 | 3 | 4 | 5 | 6;
type SubmissionMode = "warranty" | "general";

async function withMinDelay(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function formatContractDate(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}.${m}.${y}`;
}

export default function App() {
  const [step, setStep] = useState<Step>(1);
  const [lat, setLat] = useState(DEFAULT_LAT);
  const [lng, setLng] = useState(DEFAULT_LNG);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [cvLoading, setCvLoading] = useState(false);
  const [cvResult, setCvResult] = useState<CVDetectionResponse | null>(null);
  const [defectType, setDefectType] = useState("pothole");
  const [submissionMode, setSubmissionMode] = useState<SubmissionMode>("warranty");
  const [addressConfirmed, setAddressConfirmed] = useState(false);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchResult, setMatchResult] = useState<MatchResponse | null>(null);
  const [complaint, setComplaint] = useState<ComplaintResponse | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [ticketId, setTicketId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showQr, setShowQr] = useState(false);
  const [transition, setTransition] = useState<string | null>(null);
  const [mapSegments, setMapSegments] = useState<WarrantyRoadSegment[]>([]);

  const demo = isDemoMode();

  useEffect(() => {
    if (demo) return;
    fetchWarrantyMarkers()
      .then((data) => setMapSegments(data.markers ?? []))
      .catch(() => setMapSegments([]));
  }, [demo]);

  const runCv = useCallback(async (file: File) => {
    setCvLoading(true);
    setCvResult(null);
    setError(null);
    try {
      const cv = demo ? await demoDetectDefect() : await detectDefect(file);
      setCvResult(cv);
      if (cv.primary_defect) {
        setDefectType(cvClassToDefectType(cv.primary_defect));
      }
    } catch (e) {
      if (demo) {
        const cv = await demoDetectDefect();
        setCvResult(cv);
      } else {
        setError(e instanceof Error ? e.message : "Ошибка распознавания");
      }
    } finally {
      setCvLoading(false);
    }
  }, [demo]);

  const onCapture = useCallback(
    (dataUrl: string, file: File) => {
      setPhotoPreview(dataUrl);
      setStep(2);
      runCv(file);
    },
    [runCv]
  );

  const onGps = useCallback((newLat: number, newLng: number) => {
    setLat(newLat);
    setLng(newLng);
  }, []);

  const onConfirmScan = useCallback(async () => {
    setTransition("Открываем карту…");
    await withMinDelay(700);
    setStep(3);
    setTransition(null);
  }, []);

  const onConfirmAddress = useCallback(async () => {
    setAddressConfirmed(true);
    setTransition("Сверяем GPS с базой goszakup…");
    await withMinDelay(500);
    setTransition(null);
    setStep(4);
    setMatchLoading(true);
    setMatchResult(null);
    setError(null);
    try {
      const data = demo
        ? await demoMatchDefect()
        : await matchDefect(lat, lng, defectType);
      setMatchResult(data);
      if (!data.match_found) {
        setSubmissionMode("general");
        setTransition("Готовим заявку в акимат…");
        await withMinDelay(700);
        setStep(5);
        setTransition(null);
      }
    } catch (e) {
      if (demo) {
        setMatchResult(await demoMatchDefect());
      } else {
        setError(e instanceof Error ? e.message : "Не удалось найти подрядчика");
      }
    } finally {
      setMatchLoading(false);
    }
  }, [demo, lat, lng, defectType]);

  const onProceedToSubmit = useCallback(async () => {
    setSubmissionMode("warranty");
    setTransition("Готовим форму претензии…");
    await withMinDelay(650);
    setStep(5);
    setTransition(null);
  }, []);

  const onProceedGeneral = useCallback(async () => {
    setSubmissionMode("general");
    setTransition("Готовим заявку в акимат…");
    await withMinDelay(650);
    setStep(5);
    setTransition(null);
  }, []);

  const onGenerateComplaint = useCallback(async () => {
    if (!matchResult) return;
    if (submissionMode === "warranty" && !matchResult.supplier?.name) return;

    const severity =
      cvResult?.severity_tier === "HAZARD_FASTTRACK" &&
      cvResult.primary_defect === "sunken_manhole"
        ? "critical"
        : cvResult?.severity_tier === "HAZARD_FASTTRACK"
          ? "high"
          : "medium";

    setDocLoading(true);
    setError(null);
    try {
      if (demo) {
        setComplaint(await demoGenerateComplaint());
      } else {
        const address =
          matchResult.address_display || matchResult.street_name || "Адрес";
        const payload = {
          complaint_mode: submissionMode,
          defect_info: {
            address_description: address,
            gps: { lat, lng },
            defect_type: defectType,
            severity,
            photo_urls: [],
            photo_base64: photoPreview || undefined,
          },
        };

        const data = await generateComplaint(
          submissionMode === "warranty" && matchResult.supplier?.name
            ? {
                ...payload,
                contract_info: {
                  contract_number:
                    matchResult.trd_buy_id || matchResult.contract_id || undefined,
                  trd_buy_id: matchResult.trd_buy_id || undefined,
                  contract_date: formatContractDate(matchResult.completed_on),
                  customer_name: matchResult.customer_name || undefined,
                  supplier_name: matchResult.supplier.name,
                  supplier_bin: matchResult.supplier.bin || undefined,
                  warranty_ends: matchResult.warranty_ends || undefined,
                  warranty_active: matchResult.warranty_active,
                },
              }
            : payload
        );
        setComplaint(data);
      }
      setShowQr(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сформировать претензию");
    } finally {
      setDocLoading(false);
    }
  }, [
    demo,
    matchResult,
    submissionMode,
    lat,
    lng,
    defectType,
    photoPreview,
    cvResult,
  ]);

  const onSubmitToAkimat = useCallback(async () => {
    setAuthLoading(true);
    setError(null);
    try {
      const id = demo ? await demoSubmitTicket() : MOCK_TICKET_ID;
      if (complaint) {
        await copyText(complaint.document_body);
        openEOtinish(complaint);
      }
      setTicketId(id);
      setStep(6);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка отправки");
    } finally {
      setAuthLoading(false);
    }
  }, [demo, complaint]);

  const restart = useCallback(() => {
    setStep(1);
    setPhotoPreview(null);
    setCvResult(null);
    setCvLoading(false);
    setAddressConfirmed(false);
    setMatchResult(null);
    setMatchLoading(false);
    setComplaint(null);
    setDocLoading(false);
    setAuthLoading(false);
    setTicketId(null);
    setError(null);
    setShowQr(false);
    setTransition(null);
    setDefectType("pothole");
    setSubmissionMode("warranty");
    setLat(DEFAULT_LAT);
    setLng(DEFAULT_LNG);
  }, []);

  const hasDetection = (cvResult?.detections?.length ?? 0) > 0;
  const primaryDefect = cvResult?.primary_defect ?? null;
  const confidence =
    primaryDefect != null
      ? cvResult?.detections.find((d) => d.defect_class === primaryDefect)?.confidence ??
        cvResult?.detections[0]?.confidence
      : undefined;
  const showHazard = cvResult?.severity_tier === "HAZARD_FASTTRACK";

  return (
    <div className="app app-flow">
      <header className="header header-flow">
        <div className="flow-shell header-inner">
          <div className="brand">
            <span className="logo">Talap</span>
            <p className="tagline">Сообщите о дефекте за 2 минуты</p>
          </div>
          {demo && <span className="demo-badge">Демо</span>}
        </div>
      </header>

      <div className="flow-shell">
        <FlowProgress current={step} />
      </div>

      <main className="flow-main">
        <div className="flow-shell">
          {transition && (
            <div className="flow-transition-overlay">
              <StepLoader title={transition} subtitle="Пожалуйста, подождите" />
            </div>
          )}

          {error && <div className="panel panel-error flow-error">{error}</div>}

        {step === 1 && (
          <section className="flow-panel flow-panel-step1">
            <div className="flow-panel-copy">
              <h1 className="flow-title">Зафиксируйте дефект</h1>
              <p className="flow-subtitle">
                Увидели яму? Снимите её прямо сейчас — только камера, без старых фото.
              </p>
              <ul className="flow-hints">
                <li>На десктопе можно использовать веб-камеру</li>
                <li>GPS подставится автоматически или укажете на карте</li>
                <li>AI проверит снимок перед подачей жалобы</li>
              </ul>
            </div>
            <CameraCapture onCapture={onCapture} onGps={onGps} />
          </section>
        )}

        {step === 2 && photoPreview && (
          <section className="flow-panel flow-panel-split">
            <div className="flow-panel-media">
              <h1 className="flow-title">AI-валидация</h1>
              <PhotoScanView
                photoUrl={photoPreview}
                scanning={cvLoading}
                result={cvResult}
              />
            </div>
            <div className="flow-panel-side">
              {cvLoading && (
                <StepLoader
                  title="Анализируем снимок"
                  subtitle="Модель YOLO26 ищет дефекты на дороге"
                />
              )}
              {!cvLoading && cvResult && (
                <div className="flow-actions scan-summary">
                  {hasDetection && primaryDefect && (
                    <p className="scan-summary-meta">
                      Класс: <strong>{defectLabel(primaryDefect)}</strong>
                      {confidence != null && ` · ${Math.round(confidence * 100)}%`}
                    </p>
                  )}
                  {!hasDetection && (
                    <p className="scan-result-text scan-result-warn">
                      Дефект не распознан — снимите ближе к дороге, без экрана телефона.
                    </p>
                  )}
                  {hasDetection && (
                    <>
                      <div
                        className={`severity-badge ${
                          showHazard ? "severity-badge-hazard" : "severity-badge-warranty"
                        }`}
                      >
                        {showHazard ? "⚠️ Опасный дефект" : "Заявка на содержание дороги"}
                      </div>
                      <p className="scan-result-text">
                        {showHazard
                          ? "Срочная обработка — открытый люк или крупная яма."
                          : "Дефект подтверждён. Переходим к геолокации."}
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    className="cta"
                    onClick={onConfirmScan}
                    disabled={!!transition || !hasDetection}
                  >
                    Далее — подтвердить место
                  </button>
                </div>
              )}
            </div>
          </section>
        )}

        {step === 3 && (
          <section className="flow-panel flow-panel-split">
            <div className="flow-panel-copy">
              <h1 className="flow-title">Где это произошло?</h1>
              <p className="flow-subtitle">
                Точка съёмки на карте. Подтвердите адрес или сдвиньте маркер на
                синюю линию гарантийного участка.
              </p>
              <p className="coords-line coords-line-block">
                {lat.toFixed(5)}, {lng.toFixed(5)}
              </p>
            </div>

            <div className="flow-map-compact flow-map-wide">
              <YandexMapPicker
                lat={lat}
                lng={lng}
                segments={mapSegments}
                onChange={(newLat, newLng) => {
                  setLat(newLat);
                  setLng(newLng);
                }}
              />
            </div>

            {demo && MOCK_DEDUP.isDuplicate && !addressConfirmed && (
              <div className="dedup-alert" role="alert">
                <strong>Об этой яме уже сообщили {MOCK_DEDUP.reportCount} человека.</strong>
                <p>Мы добавим ваш голос для повышения приоритета заявки.</p>
              </div>
            )}

            <div className="flow-actions flow-actions-row">
              <button
                type="button"
                className="cta"
                onClick={onConfirmAddress}
                disabled={!!transition}
              >
                📍 Подтвердить адрес
              </button>
            </div>
          </section>
        )}

        {step === 4 && (
          <section className="flow-panel">
            {matchLoading && (
              <div className="matching-loader">
                <div className="matching-spinner" aria-hidden="true" />
                <h1 className="flow-title">Ищем ответственного подрядчика…</h1>
                <p className="flow-subtitle">
                  Сверяем GPS с базой гарантийных договоров goszakup
                </p>
              </div>
            )}

            {!matchLoading && matchResult?.match_found && (
              <div className="triumph-card">
                <span className="triumph-badge">Бинго!</span>
                <h1 className="flow-title triumph-title">
                  Участок на гарантии
                </h1>
                <p className="triumph-lead">
                  Этот участок ремонтировало{" "}
                  <strong>{matchResult.supplier?.name}</strong>
                  {matchResult.completed_on && (
                    <>
                      {" "}
                      в {matchResult.completed_on.slice(0, 4)} году
                    </>
                  )}
                  .
                </p>
                <ul className="triumph-facts">
                  <li>
                    Гарантия до{" "}
                    <strong>{formatContractDate(matchResult.warranty_ends)}</strong>
                  </li>
                  <li>
                    Сумма тендера: <strong>{MOCK_TENDER_AMOUNT}</strong>
                  </li>
                  <li>
                    Дефект:{" "}
                    <strong>
                      {primaryDefect ? defectLabel(primaryDefect) : "—"}
                      {confidence != null && ` (${Math.round(confidence * 100)}%)`}
                    </strong>
                  </li>
                </ul>
                {matchResult.address_display && (
                  <p className="address">{matchResult.address_display}</p>
                )}
                <button
                  type="button"
                  className="cta"
                  onClick={onProceedToSubmit}
                  disabled={!!transition}
                >
                  Сформировать официальную претензию?
                </button>
              </div>
            )}

            {!matchLoading && matchResult && !matchResult.match_found && (
              <div className="panel panel-miss panel-general">
                <h2>Гарантийный договор не найден</h2>
                <p>
                  На этом участке нет активной гарантии подрядчика — это нормально для
                  большинства дорог. Talap всё равно сформирует заявку в акимат.
                </p>
                {matchResult.address_display && (
                  <p className="address">{matchResult.address_display}</p>
                )}
                <p className="scan-summary-meta">
                  Дефект: <strong>{primaryDefect ? defectLabel(primaryDefect) : "—"}</strong>
                </p>
                <button
                  type="button"
                  className="cta"
                  onClick={onProceedGeneral}
                  disabled={!!transition}
                >
                  Подать заявку в акимат
                </button>
                <button type="button" className="cta cta-secondary" onClick={restart}>
                  Начать заново
                </button>
              </div>
            )}
          </section>
        )}

        {step === 5 && matchResult && (
          <section className="flow-panel">
            <h1 className="flow-title">Подача в акимат</h1>

            {!showQr && (
              <div className="submit-intro">
                {submissionMode === "general" && !matchResult.match_found && (
                  <p className="general-path-note">
                    На этом участке нет активной гарантии подрядчика — оформляем обычную
                    заявку в акимат.
                  </p>
                )}
                <p className="flow-subtitle">
                  {submissionMode === "warranty"
                    ? "Сформируем претензию с данными подрядчика и откроем e-Otinish для подписи."
                    : "Сформируем стандартную заявку в акимат (без указания подрядчика) и откроем e-Otinish."}
                </p>
                <button
                  type="button"
                  className="cta"
                  onClick={onGenerateComplaint}
                  disabled={docLoading}
                >
                  {docLoading
                    ? "Формируем документ…"
                    : submissionMode === "warranty"
                      ? "Сформировать претензию"
                      : "Сформировать заявку"}
                </button>
              </div>
            )}

            {showQr && complaint && (
              <div className="auth-stage">
                <div className="egov-qr-card">
                  <div className="egov-qr-placeholder" aria-hidden="true">
                    <div className="qr-grid" />
                    <span>eGov</span>
                  </div>
                  <p className="egov-hint">
                    Отсканируйте QR в eGov Mobile или войдите через Mobile ID
                  </p>
                </div>

                <div className="complaint-preview">
                  <p><strong>Тема:</strong> {complaint.subject}</p>
                  <p><strong>Адресат:</strong> {complaint.target_department}</p>
                </div>

                <button
                  type="button"
                  className="cta cta-eotinish"
                  onClick={onSubmitToAkimat}
                  disabled={authLoading}
                >
                  {authLoading ? "Регистрируем…" : "Отправить в Акимат"}
                </button>
                <p className="submit-hint">{eOtinishHint()}</p>
              </div>
            )}
          </section>
        )}

        {step === 6 && (
          <section className="flow-panel">
            <div className="success-card">
              <span className="success-icon" aria-hidden="true">✓</span>
              <h1 className="flow-title">Жалоба зарегистрирована</h1>
              <p className="success-ticket">
                Номер заявки: <strong>{ticketId}</strong>
              </p>
              <p className="flow-subtitle">
                Мы пришлём уведомление, когда дефект устранят.
              </p>
            </div>

            <button type="button" className="cta cta-secondary" onClick={restart}>
              Сообщить о другом дефекте
            </button>
          </section>
        )}
        </div>
      </main>

      <footer className="footer footer-flow">
        <div className="flow-shell">
          Talap · GovTech Camp 2026{demo ? " · демо-режим без бэкенда" : ""}
        </div>
      </footer>
    </div>
  );
}
