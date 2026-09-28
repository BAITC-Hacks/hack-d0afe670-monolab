import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  detectDefect,
  fetchWarrantyMapMarkers,
  submitComplaint,
  type CVDetectionResponse,
  type WarrantyRoadSegment,
} from "../api";
import CameraCapture from "../components/flow/CameraCapture";
import FlowProgress from "../components/flow/FlowProgress";
import PhotoScanView from "../components/flow/PhotoScanView";
import StepLoader from "../components/flow/StepLoader";
import YandexMapPicker from "../components/YandexMapPicker";
import { defectLabel } from "../labels";

const DEFAULT_LAT = 43.2404;
const DEFAULT_LNG = 76.9078;

type Step = 1 | 2 | 3 | 4;

function buildDefaultDescription(cv: CVDetectionResponse, address: string): string {
  const cls = cv.primary_defect ?? "pothole";
  return `Зафиксирован дефект: ${defectLabel(cls)}. Адрес: ${address}.`;
}

export default function CitizenApp() {
  const [step, setStep] = useState<Step>(1);
  const [lat, setLat] = useState(DEFAULT_LAT);
  const [lng, setLng] = useState(DEFAULT_LNG);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [cvLoading, setCvLoading] = useState(false);
  const [cvResult, setCvResult] = useState<CVDetectionResponse | null>(null);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [regNumber, setRegNumber] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warrantySegments, setWarrantySegments] = useState<WarrantyRoadSegment[]>([]);

  const hasDetection = (cvResult?.detections?.length ?? 0) > 0;

  useEffect(() => {
    fetchWarrantyMapMarkers()
      .then((data) => setWarrantySegments(data.markers))
      .catch(() => {
        /* map still works without warranty overlay */
      });
  }, []);

  const runCv = useCallback(async (file: File) => {
    setCvLoading(true);
    setCvResult(null);
    setError(null);
    try {
      const cv = await detectDefect(file);
      setCvResult(cv);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка распознавания");
    } finally {
      setCvLoading(false);
    }
  }, []);

  const onCapture = useCallback(
    (dataUrl: string, file: File) => {
      setPhotoPreview(dataUrl);
      setPhotoFile(file);
      setStep(2);
      runCv(file);
    },
    [runCv]
  );

  const onGps = useCallback((newLat: number, newLng: number) => {
    setLat(newLat);
    setLng(newLng);
  }, []);

  const onConfirmScan = () => {
    setStep(3);
  };

  const onConfirmAddress = () => {
    const addr = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    if (cvResult) {
      setDescription(buildDefaultDescription(cvResult, addr));
    }
    setStep(4);
  };

  const onSubmit = async () => {
    if (!photoFile) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitComplaint(photoFile, lat, lng, description);
      setRegNumber(result.service_request_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось отправить заявку");
    } finally {
      setSubmitting(false);
    }
  };

  const restart = () => {
    setStep(1);
    setPhotoPreview(null);
    setPhotoFile(null);
    setCvResult(null);
    setRegNumber(null);
    setError(null);
    setDescription("");
  };

  const primaryDefect = cvResult?.primary_defect ?? null;
  const confidence =
    primaryDefect != null
      ? cvResult?.detections.find((d) => d.defect_class === primaryDefect)?.confidence ??
        cvResult?.detections[0]?.confidence
      : undefined;

  return (
    <div className="app app-flow">
      <header className="header header-flow">
        <div className="flow-shell header-inner">
          <div className="brand">
            <span className="logo">Talap</span>
            <p className="tagline">Сообщите о дефекте за 2 минуты</p>
          </div>
        </div>
      </header>

      <div className="flow-shell">
        <FlowProgress current={step} />
      </div>

      <main className="flow-main">
        <div className="flow-shell">
          {error && <div className="panel panel-error flow-error">{error}</div>}

          {step === 1 && (
            <section className="flow-panel flow-panel-step1">
              <div className="flow-panel-copy">
                <h1 className="flow-title">Зафиксируйте дефект</h1>
                <p className="flow-subtitle">
                  Сфотографируйте яму или повреждение дороги — мы передадим заявку в акимат.
                </p>
              </div>
              <CameraCapture onCapture={onCapture} onGps={onGps} />
            </section>
          )}

          {step === 2 && photoPreview && (
            <section className="flow-panel flow-panel-split">
              <div className="flow-panel-media">
                <h1 className="flow-title">Проверка снимка</h1>
                <PhotoScanView photoUrl={photoPreview} scanning={cvLoading} result={cvResult} />
              </div>
              <div className="flow-panel-side">
                {cvLoading && (
                  <StepLoader title="Анализируем снимок" subtitle="Модель ищет дефекты" />
                )}
                {!cvLoading && cvResult && (
                  <div className="flow-actions scan-summary">
                    {hasDetection && primaryDefect && (
                      <p className="scan-summary-meta">
                        Обнаружено: <strong>{defectLabel(primaryDefect)}</strong>
                        {confidence != null && ` · ${Math.round(confidence * 100)}%`}
                      </p>
                    )}
                    {!hasDetection && (
                      <p className="scan-result-text scan-result-warn">
                        Дефект не распознан — снимите ближе к дороге.
                      </p>
                    )}
                    <button
                      type="button"
                      className="cta"
                      onClick={onConfirmScan}
                      disabled={!hasDetection}
                    >
                      Далее — указать место
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
                  Подтвердите точку на карте или сдвиньте маркер.
                </p>
                <p className="coords-line coords-line-block">
                  {lat.toFixed(5)}, {lng.toFixed(5)}
                </p>
              </div>
              <div className="flow-map-compact flow-map-wide">
                <YandexMapPicker
                  lat={lat}
                  lng={lng}
                  segments={warrantySegments}
                  onChange={(a, b) => { setLat(a); setLng(b); }}
                />
              </div>
              <div className="flow-actions flow-actions-row">
                <button type="button" className="cta" onClick={onConfirmAddress}>
                  Подтвердить адрес
                </button>
              </div>
            </section>
          )}

          {step === 4 && !regNumber && (
            <section className="flow-panel">
              <h1 className="flow-title">Текст обращения</h1>
              <p className="flow-subtitle">
                Проверьте описание — его увидит специалист акимата.
              </p>
              <textarea
                className="complaint-textarea"
                rows={6}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <button
                type="button"
                className="cta"
                onClick={onSubmit}
                disabled={submitting || description.trim().length < 10}
              >
                {submitting ? "Отправляем…" : "Отправить в акимат"}
              </button>
            </section>
          )}

          {step === 4 && regNumber && (
            <section className="flow-panel">
              <div className="success-card">
                <span className="success-icon" aria-hidden="true">✓</span>
                <h1 className="flow-title">Заявка принята</h1>
                <p className="success-ticket">
                  Номер обращения: <strong>{regNumber}</strong>
                </p>
                <p className="flow-subtitle">
                  Ваша заявка передана в акимат. Отслеживайте статус по номеру.
                </p>
              </div>
              <Link className="cta" to={`/track/${regNumber}`}>
                Отслеживать статус
              </Link>
              <button type="button" className="cta cta-secondary" onClick={restart}>
                Сообщить о другом дефекте
              </button>
            </section>
          )}
        </div>
      </main>

      <footer className="footer footer-flow">
        <div className="flow-shell">Talap · GovTech Camp 2026</div>
      </footer>
    </div>
  );
}
