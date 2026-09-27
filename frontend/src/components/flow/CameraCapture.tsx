import { useCallback, useEffect, useRef, useState } from "react";

type Props = {
  onCapture: (dataUrl: string, file: File) => void;
  onGps: (lat: number, lng: number) => void;
};

export default function CameraCapture({ onCapture, onGps }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gpsStatus, setGpsStatus] = useState<"pending" | "ok" | "denied">("pending");

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.geolocation) {
        setGpsStatus("denied");
      } else {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            onGps(pos.coords.latitude, pos.coords.longitude);
            setGpsStatus("ok");
          },
          () => setGpsStatus("denied"),
          { enableHighAccuracy: true, timeout: 12000 }
        );
      }

      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Камера недоступна. Откройте сайт на смартфоне.");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setReady(true);
      } catch {
        setError("Нужен доступ к камере. Галерея отключена — только съёмка здесь и сейчас.");
      }
    }

    start();
    return () => {
      cancelled = true;
      stopStream();
    };
  }, [onGps, stopStream]);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], `talap-${Date.now()}.jpg`, {
          type: "image/jpeg",
        });
        const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
        stopStream();
        onCapture(dataUrl, file);
      },
      "image/jpeg",
      0.92
    );
  }, [onCapture, stopStream]);

  return (
    <div className="camera-stage">
      <div className="camera-frame">
        {error ? (
          <div className="camera-error">{error}</div>
        ) : (
          <>
            <video ref={videoRef} className="camera-video" playsInline muted />
            <div className="camera-grid" aria-hidden="true" />
            <div className="camera-hint">
              <p>Сфотографируйте дефект прямо сейчас</p>
              <span>Загрузка из галереи недоступна</span>
            </div>
          </>
        )}
      </div>

      <div className="camera-meta">
        <span className={`gps-pill gps-${gpsStatus}`}>
          {gpsStatus === "pending" && "Определяем GPS…"}
          {gpsStatus === "ok" && "GPS зафиксирован"}
          {gpsStatus === "denied" && "GPS недоступен — укажете на карте"}
        </span>
      </div>

      <button
        type="button"
        className="camera-shutter"
        onClick={capture}
        disabled={!ready || !!error}
        aria-label="Сделать снимок"
      >
        <span className="camera-shutter-ring" />
      </button>
    </div>
  );
}
