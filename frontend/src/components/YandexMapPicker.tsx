import { useEffect, useRef, useState } from "react";
import {
  loadYmaps,
  type YMap,
  type YMapEvent,
  type YPlacemark,
  type YPolyline,
} from "../ymaps";
import type { WarrantyRoadSegment } from "../api";

type Props = {
  lat: number;
  lng: number;
  segments: WarrantyRoadSegment[];
  onChange: (lat: number, lng: number) => void;
};

const API_KEY = import.meta.env.VITE_YANDEX_MAPS_API_KEY ?? "";

function segmentStyle(active: boolean) {
  if (active) {
    return {
      strokeColor: "#1d4ed8",
      strokeOpacity: 0.85,
      strokeWidth: 6,
      strokeStyle: "solid" as const,
      lineCap: "round" as const,
      lineJoin: "round" as const,
    };
  }
  return {
    strokeColor: "#94a3b8",
    strokeOpacity: 0.55,
    strokeWidth: 4,
    strokeStyle: "solid" as const,
    lineCap: "round" as const,
  };
}

export default function YandexMapPicker({ lat, lng, segments, onChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<YMap | null>(null);
  const placemarkRef = useRef<YPlacemark | null>(null);
  const polylinesRef = useRef<YPolyline[]>([]);
  const ymapsRef = useRef<Awaited<ReturnType<typeof loadYmaps>> | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [mapError, setMapError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);

  useEffect(() => {
    if (!API_KEY) {
      setMapError("Укажите VITE_YANDEX_MAPS_API_KEY в frontend/.env");
      return;
    }
    let cancelled = false;

    loadYmaps(API_KEY)
      .then((ym) => {
        if (cancelled || !containerRef.current) return;
        ymapsRef.current = ym;

        const map = new ym.Map(
          containerRef.current,
          {
            center: [lat, lng],
            zoom: 12,
            controls: ["zoomControl", "geolocationControl"],
          },
          { suppressMapOpenBlock: true }
        );
        mapRef.current = map;

        const placemark = new ym.Placemark(
          [lat, lng],
          { iconCaption: "Дефект", balloonContent: "Отметьте место дефекта" },
          { preset: "islands#redIcon", draggable: true, zIndex: 2000 }
        );
        placemarkRef.current = placemark;
        map.geoObjects.add(placemark);

        map.events.add("click", (e: YMapEvent) => {
          const coords = e.get("coords");
          if (!coords || coords.length < 2) return;
          placemark.geometry.setCoordinates(coords);
          onChangeRef.current(coords[0], coords[1]);
        });

        placemark.events.add("dragend", () => {
          const coords = placemark.geometry.getCoordinates();
          onChangeRef.current(coords[0], coords[1]);
        });

        setMapReady(true);
      })
      .catch((err) => {
        setMapError(err instanceof Error ? err.message : "Карта недоступна");
      });

    return () => {
      cancelled = true;
      setMapReady(false);
      polylinesRef.current = [];
      mapRef.current?.destroy();
      mapRef.current = null;
      placemarkRef.current = null;
      ymapsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!placemarkRef.current) return;
    placemarkRef.current.geometry.setCoordinates([lat, lng]);
  }, [lat, lng]);

  useEffect(() => {
    const map = mapRef.current;
    const ym = ymapsRef.current;
    if (!mapReady || !map || !ym) return;

    for (const line of polylinesRef.current) {
      map.geoObjects.remove(line);
    }
    polylinesRef.current = [];

    for (const seg of segments) {
      if (seg.coordinates.length < 2) continue;
      const line = new ym.Polyline(
        seg.coordinates,
        {
          hintContent: seg.label,
          balloonContentHeader: seg.label,
          balloonContentBody: `Договоров: <b>${seg.contract_count}</b>`,
        },
        { ...segmentStyle(seg.warranty_active), zIndex: 500 }
      );
      polylinesRef.current.push(line);
      map.geoObjects.add(line);
    }
  }, [segments, mapReady]);

  if (mapError) {
    return <div className="map map-error">{mapError}</div>;
  }

  return (
    <div className="map-container">
      <div ref={containerRef} className="map" />
      <div className="map-legend">
        <span className="legend-item">
          <i className="line line-active" /> Гарантия на дороге
        </span>
        <span className="legend-item">
          <i className="line line-expired" /> Гарантия истекла
        </span>
        <span className="legend-item">
          <i className="dot dot-defect" /> Ваш дефект
        </span>
      </div>
    </div>
  );
}
