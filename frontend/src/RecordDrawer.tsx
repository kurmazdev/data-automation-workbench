import { useLayoutEffect, useRef } from "react";
import { Icon, val } from "./components";
import type { RecordResult, Rule } from "./types";

export function RecordDrawer({
  selected,
  fields,
  onClose,
}: {
  selected: RecordResult;
  fields: Rule[];
  onClose: () => void;
}) {
  const container = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = container.current!;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
    };
  }, []);
  return (
    <dialog
      ref={container}
      className="drawer"
      aria-labelledby="record-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onKeyDown={(e) => {
        if (e.key !== "Tab") return;
        const controls = Array.from(
          e.currentTarget.querySelectorAll<HTMLElement>(
            "button, summary, [href], input, select, textarea, [tabindex='0']",
          ),
        ).filter(
          (control) =>
            !control.hasAttribute("disabled") &&
            control.getClientRects().length > 0,
        );
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        } else if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const bounds = e.currentTarget.getBoundingClientRect();
        if (
          e.clientX < bounds.left ||
          e.clientX > bounds.right ||
          e.clientY < bounds.top ||
          e.clientY > bounds.bottom
        )
          onClose();
      }}
    >
      <div className="drawer-heading">
        <div>
          <div className="eyebrow">SOURCE RECORD {selected.row}</div>
          <h2 id="record-title">Record details</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close record details"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <span className={`status ${selected.status}`}>{selected.status}</span>
      {selected.reasons.length > 0 && (
        <div className="rejection-box">
          <strong>Why it was rejected</strong>
          <ul>
            {selected.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <h3>Original → cleaned</h3>
      <div className="comparison-heading" aria-hidden="true">
        <span>Field</span>
        <span>Original</span>
        <span></span>
        <span>Cleaned</span>
      </div>
      <div className="comparison">
        {fields.map((field) => {
          const changed = selected.events.some(
            (event) =>
              event.field === field.target && event.action === "transform",
          );
          const invalid = selected.events.some(
            (event) =>
              event.field === field.target && event.action === "reject",
          );
          return (
            <div
              key={field.target}
              className={
                invalid ? "invalid-field" : changed ? "changed-field" : ""
              }
            >
              <strong>
                {field.target}
                <small>from {field.source}</small>
              </strong>
              <span>{val(selected.original[field.source])}</span>
              <span className="muted">→</span>
              <span>
                {val(selected.cleaned[field.target])}
                {(changed || invalid) && (
                  <small className="comparison-status">
                    {invalid ? "Invalid" : "Changed"}
                  </small>
                )}
              </span>
            </div>
          );
        })}
      </div>
      <details className="original-details">
        <summary>All original source values</summary>
        {Object.entries(selected.original).map(([key, value]) => (
          <div key={key}>
            <strong>{key}</strong>
            {val(value)}
          </div>
        ))}
      </details>
      <h3>
        Audit trail <span className="muted">({selected.events.length})</span>
      </h3>
      <div className="events">
        {selected.events.map((event, index) => (
          <div className={`event ${event.action}`} key={index}>
            <span className="event-dot" />
            <div>
              <strong>
                {event.field || "Record"}{" "}
                <small>
                  {{
                    transform: "Changed",
                    reject: "Rejected",
                    accept: "Unchanged",
                    duplicate_kept: "Duplicate kept",
                  }[event.action] ?? event.action}
                </small>
              </strong>
              <p>{event.reason}</p>
              {event.action === "transform" && (
                <div className="event-values">
                  {val(event.before)}
                  <span>→</span>
                  {val(event.after)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </dialog>
  );
}
