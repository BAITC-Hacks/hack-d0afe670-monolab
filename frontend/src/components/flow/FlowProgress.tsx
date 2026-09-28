type Props = {
  current: number;
  steps?: readonly string[];
};

const DEFAULT_STEPS = ["Фото", "Проверка", "Адрес", "Подача"] as const;

export default function FlowProgress({ current, steps = DEFAULT_STEPS }: Props) {
  return (
    <nav className="flow-progress" aria-label="Шаги подачи жалобы">
      {steps.map((label, index) => {
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
