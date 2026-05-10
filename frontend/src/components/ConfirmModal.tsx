import { ReactNode } from "react";

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
  confirmLabel = "OK",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <h3>{title}</h3>
        <div style={{ marginBottom: 16, lineHeight: 1.6 }}>{message}</div>
        <div className="form-actions">
          <button type="button" className="btn-secondary" onClick={onCancel}>{cancelLabel}</button>
          <button
            type="button"
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
