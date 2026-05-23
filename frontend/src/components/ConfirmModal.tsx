import { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = false,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const resolvedConfirmLabel = confirmLabel ?? t("confirmModal.defaultConfirm");
  const resolvedCancelLabel = cancelLabel ?? t("confirmModal.defaultCancel");
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "var(--max-width-modal-sm)" }}>
        <h3>{title}</h3>
        <div style={{ marginBottom: "var(--space-4)", lineHeight: 1.6 }}>{message}</div>
        <div className="form-actions">
          <button type="button" className="btn-secondary" onClick={onCancel}>{resolvedCancelLabel}</button>
          <button
            type="button"
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={onConfirm}
            autoFocus
          >
            {resolvedConfirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
