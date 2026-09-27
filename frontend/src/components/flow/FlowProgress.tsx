const STEPS = [
  "Фото",
  "AI",
  "Адрес",
  "Подрядчик",
  "Подача",
  "Готово",
] as const;

type Props = {
  current: number;
};

export default function FlowProgress({ current }: Props) {
  return (
    <nav className="flow-progress" aria-label="Шаги подачи жалобы">
      {STEPS.map((label, index) => {
        const step = index + 1;
        const done = step < current;
        const active = step === current;
        return (
          <div
            key={label}
            className={`flow-step ${done ? "flow-step-done" : ""} ${active ? "flow-step-active" : ""}`}
          >
            <span className="flow-step-dot">{done ? "✓" : step}</span>
            <span className="flow-step-label">{label}</span>
          </div>
        );
      })}
    </nav>
  );
}
