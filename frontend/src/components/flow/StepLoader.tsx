type Props = {
  title: string;
  subtitle?: string;
};

export default function StepLoader({ title, subtitle }: Props) {
  return (
    <div className="step-loader" role="status" aria-live="polite">
      <div className="step-loader-ring" aria-hidden="true">
        <div className="step-loader-spinner" />
      </div>
      <p className="step-loader-title">{title}</p>
      {subtitle && <p className="step-loader-subtitle">{subtitle}</p>}
    </div>
  );
}
