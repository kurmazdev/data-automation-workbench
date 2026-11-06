import type { ReactNode } from "react";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    upload: (
      <>
        <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H5v20h14V7l-5-5Z M14 2v6h5M8 12h8M8 16h8" />
      </>
    ),
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    download: <path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" />,
    shield: (
      <>
        <path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z" />
        <path d="m8 11 3 3 5-5" />
      </>
    ),
    rules: (
      <>
        <path d="M3 6h18M3 12h18M3 18h18M8 3v6M16 9v6M9 15v6" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6M12 7v1" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? paths.file}
    </svg>
  );
}

export const val = (value: string | null | undefined) =>
  value === null || value === undefined || value === "" ? (
    <span className="blank">blank</span>
  ) : (
    <span className="cell-value">{value}</span>
  );
export function Pager({
  offset,
  count,
  busy,
  onPage,
}: {
  offset: number;
  count: number;
  busy: boolean;
  onPage: (next: number) => Promise<void>;
}) {
  return (
    <div className="pager">
      <span>
        {count
          ? `${offset + 1}–${Math.min(offset + 25, count)} of ${count.toLocaleString()} records`
          : "0 records"}{" "}
        <small>· 25 per page</small>
      </span>
      <div>
        <button
          className="button compact secondary"
          disabled={busy || offset === 0}
          onClick={() => void onPage(Math.max(0, offset - 25))}
        >
          ← Previous
        </button>
        <button
          className="button compact secondary"
          disabled={busy || offset + 25 >= count}
          onClick={() => void onPage(offset + 25)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}
