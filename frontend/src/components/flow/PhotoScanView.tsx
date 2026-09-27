import { useCallback, useEffect, useRef, useState } from "react";
import type { CVDetection, CVDetectionResponse } from "../../api";
import { defectLabel } from "../../mock/demoFlow";

type Props = {
  photoUrl: string;
  scanning: boolean;
  result: CVDetectionResponse | null;
};

type ImageLayout = {
  containerW: number;
  containerH: number;
  naturalW: number;
  naturalH: number;
};

function imageContentRect(layout: ImageLayout) {
  const { containerW, containerH, naturalW, naturalH } = layout;
  if (containerW <= 0 || containerH <= 0 || naturalW <= 0 || naturalH <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  const scale = Math.min(containerW / naturalW, containerH / naturalH);
  const width = naturalW * scale;
  const height = naturalH * scale;
  return {
    left: (containerW - width) / 2,
    top: (containerH - height) / 2,
    width,
    height,
  };
}

function bboxToPixels(bbox: number[], layout: ImageLayout) {
  const [x1, y1, x2, y2] = bbox;
  const rect = imageContentRect(layout);
  const { naturalW, naturalH } = layout;
  if (rect.width <= 0 || rect.height <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  return {
    left: rect.left + (x1 / naturalW) * rect.width,
    top: rect.top + (y1 / naturalH) * rect.height,
    width: ((x2 - x1) / naturalW) * rect.width,
    height: ((y2 - y1) / naturalH) * rect.height,
  };
}

function severityClass(tier?: CVDetectionResponse["severity_tier"]) {
  if (tier === "HAZARD_FASTTRACK") return "detection-box-hazard";
  return "detection-box-warranty";
}

export default function PhotoScanView({ photoUrl, scanning, result }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [layout, setLayout] = useState<ImageLayout>({
    containerW: 0,
    containerH: 0,
    naturalW: 1,
    naturalH: 1,
  });
  const [visibleBoxes, setVisibleBoxes] = useState(0);

  const detections = result?.detections ?? [];

  const syncLayout = useCallback(() => {
    const img = imgRef.current;
    if (!img || img.naturalWidth <= 0) return;
    setLayout({
      containerW: img.clientWidth,
      containerH: img.clientHeight,
      naturalW: img.naturalWidth,
      naturalH: img.naturalHeight,
    });
  }, []);

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    const observer = new ResizeObserver(() => syncLayout());
    observer.observe(img);
    return () => observer.disconnect();
  }, [photoUrl, syncLayout]);

  useEffect(() => {
    if (scanning || !result?.detections.length) {
      setVisibleBoxes(0);
      return;
    }
    setVisibleBoxes(0);
    const timers: ReturnType<typeof setTimeout>[] = [];
    result.detections.forEach((_, index) => {
      timers.push(setTimeout(() => setVisibleBoxes(index + 1), 120 + index * 180));
    });
    return () => timers.forEach(clearTimeout);
  }, [scanning, result]);

  const onImageLoad = () => {
    syncLayout();
  };

  return (
    <div className="scan-stage">
      <div className="scan-photo-wrap">
        <img
          ref={imgRef}
          src={photoUrl}
          alt="Снимок дефекта"
          className="scan-photo"
          onLoad={onImageLoad}
        />

        {scanning && (
          <div className="scan-overlay" aria-live="polite">
            <div className="scan-grid" aria-hidden="true" />
            <div className="scan-laser" aria-hidden="true" />
            <div className="scan-hud">
              <span className="scan-hud-dot" />
              <p className="scan-status">YOLO26 анализирует изображение…</p>
              <p className="scan-status-sub">Поиск ям, трещин, люков</p>
            </div>
          </div>
        )}

        {!scanning &&
          detections.slice(0, visibleBoxes).map((det: CVDetection, index: number) => {
            const box = bboxToPixels(det.bbox, layout);
            return (
              <div
                key={`${det.defect_class}-${index}`}
                className={`detection-box ${severityClass(result?.severity_tier)}`}
                style={{
                  left: `${box.left}px`,
                  top: `${box.top}px`,
                  width: `${box.width}px`,
                  height: `${box.height}px`,
                  animationDelay: `${index * 0.08}s`,
                }}
              >
                <span className="detection-label">
                  {defectLabel(det.defect_class)} · {Math.round(det.confidence * 100)}%
                </span>
                <span className="detection-corner detection-corner-tl" />
                <span className="detection-corner detection-corner-br" />
              </div>
            );
          })}
      </div>

      {!scanning && result && detections.length > 0 && (
        <ul className="scan-detection-list">
          {detections.map((det, index) => (
            <li key={`${det.defect_class}-row-${index}`}>
              <span className="scan-detection-class">{defectLabel(det.defect_class)}</span>
              <span className="scan-detection-conf">{Math.round(det.confidence * 100)}%</span>
            </li>
          ))}
        </ul>
      )}

      {!scanning && result && detections.length === 0 && (
        <p className="scan-no-detection">Дефект не распознан — попробуйте другой ракурс.</p>
      )}
    </div>
  );
}
