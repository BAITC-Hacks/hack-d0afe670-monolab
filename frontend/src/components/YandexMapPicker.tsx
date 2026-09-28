import { useEffect, useRef, useState } from "react";
import {
  loadYmaps,
  type YMap,
  type YMapEvent,
  type YPlacemark,
} from "../ymaps";

export type WarrantyMapSegment = {
  coordinates: number[][];
  warranty_active?: boolean;
  label?: string;
  contract_count?: number;
  center_lat?: number;
  center_lng?: number;
};

type Props = {
  lat: number;
  lng: number;
  segments?: WarrantyMapSegment[];
  defectDraggable?: boolean;
  onChange: (lat: number, lng: number) => void;
};

const API_KEY = import.meta.env.VITE_YANDEX_MAPS_API_KEY ?? "";

function segmentCenter(seg: WarrantyMapSegment): [number, number] | null {
  if (seg.center_lat != null && seg.center_lng != null) {
    return [seg.center_lat, seg.center_lng];
  }
  if (seg.coordinates.length === 0) return null;
  const mid = seg.coordinates[Math.floor(seg.coordinates.length / 2)];
  return [mid[0], mid[1]];
}

function warrantyBalloon(seg: WarrantyMapSegment): string {
  const status = seg.warranty_active
    ? "Гарантия действует"
    : "Гарантия истекла";
  const count = seg.contract_count
    ? `<br/>Договоров: <b>${seg.contract_count}</b>`
    : "";
  return `${status}${count}`;
}

export default function YandexMapPicker({
  lat,
  lng,
  segments = [],
  defectDraggable = true,
  onChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<YMap | null>(null);
  const placemarkRef = useRef<YPlacemark | null>(null);
  const warrantyMarksRef = useRef<YPlacemark[]>([]);
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
          {
            preset: "islands#redIcon",
            draggable: defectDraggable,
            zIndex: 2000,
          }
        );
        placemarkRef.current = placemark;
        map.geoObjects.add(placemark);

        if (defectDraggable) {
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
        }

        setMapReady(true);
      })
      .catch((err) => {
        setMapError(err instanceof Error ? err.message : "Карта недоступна");
      });

    return () => {
      cancelled = true;
      setMapReady(false);
      warrantyMarksRef.current = [];
      mapRef.current?.destroy();
      mapRef.current = null;
      placemarkRef.current = null;
      ymapsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defectDraggable]);

  useEffect(() => {
    if (!placemarkRef.current) return;
    placemarkRef.current.geometry.setCoordinates([lat, lng]);
  }, [lat, lng]);

  useEffect(() => {
    const map = mapRef.current;
    const ym = ymapsRef.current;
    if (!mapReady || !map || !ym) return;

    for (const mark of warrantyMarksRef.current) {
      map.geoObjects.remove(mark);
    }
    warrantyMarksRef.current = [];

    for (const seg of segments) {
      const active = seg.warranty_active ?? false;
      const label = seg.label ?? "Участок";
      const center = segmentCenter(seg);
      if (!center) continue;

      const mark = new ym.Placemark(
        center,
        {
          iconCaption: active ? "Гарантия" : undefined,
          hintContent: label,
          balloonContentHeader: label,
          balloonContentBody: warrantyBalloon(seg),
        },
        {
          preset: active ? "islands#blueCircleDotIcon" : "islands#grayCircleDotIcon",
          zIndex: 800,
        }
      );

      if (defectDraggable) {
        mark.events.add("click", () => {
          if (!placemarkRef.current) return;
          placemarkRef.current.geometry.setCoordinates(center);
          onChangeRef.current(center[0], center[1]);
        });
      }

      warrantyMarksRef.current.push(mark);
      map.geoObjects.add(mark);
    }
  }, [segments, mapReady, defectDraggable]);

  if (mapError) {
    return <div className="map map-error">{mapError}</div>;
  }

  const activeCount = segments.filter((s) => s.warranty_active).length;

  return (
    <div className="map-container">
      <div ref={containerRef} className="map" />
      <div className="map-legend">
        {segments.length > 0 && (
          <span className="legend-item">
            <i className="dot dot-warranty" />
            Гарантия ({activeCount} точек) — нажмите, чтобы поставить дефект
          </span>
        )}
        <span className="legend-item">
          <i className="dot dot-defect" /> Ваш дефект
        </span>
      </div>
    </div>
  );
}
