import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import { Icon, val, Pager } from "./components";
import { RecordDrawer } from "./RecordDrawer";
import {
  createConfig,
  updateMappedRule,
  toggleColumn,
  mappingError as getMappingError,
} from "./workflow";
import type {
  Config,
  Dataset,
  DatasetInfo,
  Filter,
  RecordResult,
  Rule,
  Run,
  RunInfo,
  RunMetadata,
} from "./types";
import "./styles.css";

const labels = [
  "Upload & inspect",
  "Map fields",
  "Cleaning rules",
  "Review & export",
];
const dateLabel = (date: string) =>
  new Date(date).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

function App() {
  const [step, setStep] = useState(0);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [config, setConfig] = useState<Config>(() => createConfig());
  const [run, setRun] = useState<Run | null>(null);
  const [history, setHistory] = useState<RunInfo[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [busy, setBusy] = useState("");
  const [delimiter, setDelimiter] = useState(",");
  const [dragging, setDragging] = useState(false);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<RecordResult | null>(null);
  const [nullText, setNullText] = useState("");
  const [query, setQuery] = useState("");
  const [searchText, setSearchText] = useState("");
  const [downloadNotice, setDownloadNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    api<RunInfo[]>("/runs")
      .then((items) => {
        setHistory((current) =>
          [
            ...current,
            ...items.filter(
              (item) => !current.some((saved) => saved.id === item.id),
            ),
          ]
            .sort((a, b) => b.created.localeCompare(a.created))
            .slice(0, 20),
        );
        setHistoryError("");
      })
      .catch((e) => setHistoryError(String(e.message)));
  }, []);
  useEffect(() => {
    heading.current?.focus();
  }, [step]);

  async function task(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Something went wrong. Please retry.",
      );
    } finally {
      setBusy("");
    }
  }
  function resetReview() {
    setOffset(0);
    setFilter("all");
    setQuery("");
    setSearchText("");
    setSelected(null);
    setDownloadNotice("");
  }
  async function loadFile(file: File, preset?: Config) {
    if (!/\.(csv|xlsx)$/i.test(file.name))
      throw new Error("Choose a CSV or XLSX file.");
    if (file.size > 10 * 1024 * 1024)
      throw new Error("This file exceeds the 10 MB limit.");
    const data = new FormData();
    data.append("file", file);
    data.append("delimiter", preset ? "," : delimiter);
    const info = await api<DatasetInfo>("/datasets", {
      method: "POST",
      body: data,
    });
    const loaded = await api<Dataset>(`/datasets/${info.id}`);
    const next = preset ?? createConfig(loaded.columns);
    setDataset(loaded);
    setConfig(next);
    setNullText(next.null_markers.join("\n"));
    setRun(null);
    setStep(0);
    resetReview();
  }
  async function upload(file: File) {
    await task("Reading your spreadsheet…", () => loadFile(file));
  }
  async function loadSample() {
    await task("Loading sample…", async () => {
      const [response, preset] = await Promise.all([
        fetch("/api/sample"),
        api<Config>("/sample/config"),
      ]);
      if (!response.ok)
        throw new Error("Sample could not be loaded. Please retry.");
      await loadFile(
        new File([await response.blob()], "messy_customers.csv", {
          type: "text/csv",
        }),
        preset,
      );
    });
  }
  const updateRule = (source: string, patch: Partial<Rule>) =>
    setConfig((old) => updateMappedRule(old, source, patch));
  const mappingError = getMappingError(config);
  const draftConfig = {
    ...config,
    null_markers: nullText.split("\n").filter((value) => value !== ""),
  };
  const ruleError =
    config.duplicate_policy === "reject_later" && !config.duplicate_keys.length
      ? "Choose a duplicate key, or keep all duplicate records."
      : draftConfig.null_markers.length > 30 ||
          draftConfig.null_markers.some((marker) => marker.length > 100)
        ? "Use up to 30 blank markers, with at most 100 characters each."
        : "";
  const rulesChanged =
    run !== null && JSON.stringify(draftConfig) !== JSON.stringify(run.config);
  async function processData() {
    if (!dataset) return;
    await task("Applying rules and recording changes…", async () => {
      const validConfig = draftConfig;
      const info = await api<RunMetadata>(`/datasets/${dataset.id}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(validConfig),
      });
      const loaded = await api<Run>(`/runs/${info.id}`);
      setRun(loaded);
      resetReview();
      setStep(3);
      setConfig(validConfig);
      setHistory((old) => [info, ...old].slice(0, 20));
      setHistoryError("");
    });
  }
  async function page(next: number, nextFilter = filter, nextQuery = query) {
    await task("Loading records…", async () => {
      if (step === 3 && run)
        setRun(
          await api<Run>(
            `/runs/${run.id}?offset=${next}&status=${nextFilter}&q=${encodeURIComponent(nextQuery)}`,
          ),
        );
      else if (dataset)
        setDataset(
          await api<Dataset>(`/datasets/${dataset.id}?offset=${next}`),
        );
      setOffset(next);
      setFilter(nextFilter);
      setQuery(nextQuery);
      setSelected(null);
    });
  }
  async function openRun(info: RunInfo) {
    await task("Opening saved run…", async () => {
      const [loaded, source] = await Promise.all([
        api<Run>(`/runs/${info.id}`),
        api<Dataset>(`/datasets/${info.dataset_id}`),
      ]);
      setRun(loaded);
      setDataset(source);
      setConfig(loaded.config);
      setNullText(loaded.config.null_markers.join("\n"));
      setStep(3);
      resetReview();
    });
  }
  async function download() {
    if (!run) return;
    await task("Preparing Excel workbook…", async () => {
      const response = await fetch(`/api/runs/${run.id}/export`);
      if (!response.ok)
        throw new Error("The workbook could not be exported. Please retry.");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `cleaned-${run.filename.replace(/\.[^.]+$/, "")}-${run.id.slice(0, 8)}.xlsx`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      setDownloadNotice("Workbook ready. Check your downloads.");
    });
  }
  function navigate(next: number) {
    function commit() {
      setStep(next);
      setOffset(0);
      setSelected(null);
      setError("");
    }
    if (next === 0 && dataset) {
      void task("Loading source preview…", async () => {
        const loaded = await api<Dataset>(`/datasets/${dataset.id}`);
        setDataset(loaded);
        commit();
      });
    } else if (next === 3 && run) {
      void task("Loading run…", async () => {
        const loaded = await api<Run>(`/runs/${run.id}`);
        setRun(loaded);
        setFilter("all");
        setQuery("");
        setSearchText("");
        commit();
      });
    } else commit();
  }
  const titles = [
    dataset ? "Inspect data" : "Upload spreadsheet",
    "Map fields",
    "Configure rules",
    "Review results",
  ];
  const descriptions = [
    dataset
      ? "Preview the source before mapping columns."
      : "Import a CSV or XLSX file.",
    "Choose the fields to keep, name them, and set their expected types.",
    "Choose how to normalize values and handle invalid records.",
    "Check changes and rejections, then export your workbook.",
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          aria-label="Data Automation Workbench home"
        >
          <img src="/mark.svg" alt="" />
          <span>
            Data Automation<span>Workbench</span>
          </span>
        </a>
        <div className="sidebar-label">WORKFLOW</div>
        <nav aria-label="Processing workflow">
          {labels.map((label, index) => (
            <button
              key={label}
              className={`step ${step === index ? "active" : ""}`}
              aria-current={step === index ? "step" : undefined}
              disabled={
                !!busy ||
                (index > 0 && !dataset) ||
                (index === 3 && !run) ||
                (index === 2 && !!mappingError)
              }
              onClick={() => navigate(index)}
            >
              <span className="step-num">
                {index < step ? (
                  <Icon name="check" size={14} />
                ) : (
                  `0${index + 1}`
                )}
              </span>
              {label}
            </button>
          ))}
        </nav>
        <div className="history">
          <div className="sidebar-label">RECENT RUNS</div>
          {historyError && (
            <p className="small muted">
              Saved runs unavailable. {historyError}
            </p>
          )}
          {history.length
            ? (historyExpanded ? history : history.slice(0, 3)).map((item) => (
                <button
                  className={`history-item ${item.id === run?.id ? "current" : ""}`}
                  key={item.id}
                  title={`${item.filename} · ${item.summary.accepted} accepted, ${item.summary.rejected} rejected`}
                  onClick={() => void openRun(item)}
                  disabled={!!busy}
                >
                  <Icon name="file" size={16} />
                  <span>
                    <strong>{item.filename}</strong>
                    <small>{dateLabel(item.created)}</small>
                  </span>
                </button>
              ))
            : !historyError && <p className="small muted">No runs yet.</p>}
          {history.length > 3 && (
            <button
              className="history-toggle text-button"
              aria-expanded={historyExpanded}
              disabled={!!busy}
              onClick={() => setHistoryExpanded((expanded) => !expanded)}
            >
              {historyExpanded
                ? "Show fewer"
                : `Show all ${history.length} runs`}
            </button>
          )}
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            <strong>{labels[step]}</strong>
          </span>
          {history.length > 0 && (
            <select
              className="mobile-history"
              aria-label="Open a saved run"
              value=""
              disabled={!!busy}
              onChange={(e) => {
                const item = history.find((run) => run.id === e.target.value);
                if (item) void openRun(item);
              }}
            >
              <option value="">Recent runs</option>
              {history.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.filename} · {dateLabel(item.created)}
                </option>
              ))}
            </select>
          )}
        </header>
        <main aria-busy={!!busy}>
          <fieldset
            className="workflow-content"
            disabled={!!busy}
            aria-label="Spreadsheet cleanup workflow"
          >
            <div className="page-heading">
              <div>
                <h1 ref={heading} tabIndex={-1}>
                  {titles[step]}
                </h1>
                <p>{descriptions[step]}</p>
              </div>
              {dataset && (
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() => {
                    setDataset(null);
                    setRun(null);
                    setConfig(createConfig());
                    setStep(0);
                    setError("");
                    resetReview();
                    setNullText("");
                  }}
                >
                  New upload <span>+</span>
                </button>
              )}
            </div>
            {error && (
              <div role="alert" className="alert error">
                <Icon name="info" />
                <span>{error}</span>
                <button aria-label="Dismiss error" onClick={() => setError("")}>
                  <Icon name="close" size={16} />
                </button>
              </div>
            )}
            {busy && (
              <div role="status" className="loading">
                <span className="spinner" />
                {busy}
              </div>
            )}

            {step === 0 && !dataset && (
              <>
                <section className="panel upload-panel">
                  <div className="panel-heading">
                    <span className="section-icon">
                      <Icon name="upload" />
                    </span>
                    <div>
                      <h2>Source file</h2>
                    </div>
                    <span className="tag">CSV / XLSX</span>
                  </div>
                  <div
                    className={`dropzone ${dragging ? "dragging" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragging(false);
                      if (busy) return;
                      if (e.dataTransfer.files.length !== 1) {
                        setError("Upload one spreadsheet at a time.");
                        return;
                      }
                      void upload(e.dataTransfer.files[0]);
                    }}
                  >
                    <div className="upload-symbol">
                      <Icon name="upload" size={28} />
                    </div>
                    <h3>Drop your spreadsheet here</h3>
                    <p>or choose a file from your computer</p>
                    <button
                      className="button primary"
                      disabled={!!busy}
                      onClick={() => input.current?.click()}
                    >
                      Choose file <Icon name="arrow" size={17} />
                    </button>
                    <input
                      ref={input}
                      type="file"
                      hidden
                      tabIndex={-1}
                      aria-label="Upload spreadsheet"
                      accept=".csv,.xlsx"
                      className="sr-only"
                      onChange={(e) => {
                        if (e.target.files?.[0]) void upload(e.target.files[0]);
                        e.target.value = "";
                      }}
                    />
                    <small>Up to 10 MB · 10,000 rows · 100 columns</small>
                  </div>
                  <div className="upload-options">
                    <label>
                      CSV delimiter{" "}
                      <select
                        value={delimiter}
                        onChange={(e) => setDelimiter(e.target.value)}
                      >
                        <option value=",">Comma (,)</option>
                        <option value=";">Semicolon (;)</option>
                        <option value={"\t"}>Tab</option>
                      </select>
                    </label>
                    <span>XLSX: first worksheet only · CSV: UTF-8</span>
                  </div>
                </section>
                <section className="sample-card">
                  <div className="sample-icon">
                    <Icon name="file" size={25} />
                  </div>
                  <div>
                    <h3>Sample customer data</h3>
                    <p>
                      Includes duplicate IDs, mixed dates, and blank values.
                    </p>
                    <a href="/api/sample" download>
                      Download sample CSV ↗
                    </a>
                  </div>
                  <button
                    className="button secondary"
                    disabled={!!busy}
                    onClick={() => void loadSample()}
                  >
                    Use sample data <Icon name="arrow" size={17} />
                  </button>
                </section>
              </>
            )}

            {dataset && (
              <>
                <div className="file-strip">
                  <span className="file-icon">
                    <Icon name="file" />
                  </span>
                  <strong>{dataset.filename}</strong>
                  <span>{dataset.row_count.toLocaleString()} records</span>
                  <span>{dataset.columns.length} columns</span>
                </div>
                {step === 0 && (
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Inspect the source</h2>
                        <p>Original values, before cleaning.</p>
                      </div>
                      <span className="tag">READ ONLY</span>
                    </div>
                    {dataset.notes.map((note) => (
                      <div className="notice" key={note}>
                        <Icon name="info" size={17} />
                        {note}
                      </div>
                    ))}
                    <div
                      className="table-scroll"
                      role="region"
                      aria-label="Source preview"
                      tabIndex={0}
                    >
                      <table>
                        <thead>
                          <tr>
                            <th scope="col" className="row-number">
                              Record
                            </th>
                            {dataset.columns.map((column) => (
                              <th key={column}>{column}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {dataset.rows.map((row) => (
                            <tr key={row.row}>
                              <td className="row-number">
                                {row.row}
                                {row.issues.length > 0 && (
                                  <span
                                    title={row.issues.join(" ")}
                                    className="issue-dot"
                                  >
                                    {" "}
                                    !
                                  </span>
                                )}
                              </td>
                              {dataset.columns.map((column) => (
                                <td key={column}>
                                  {val(row.original[column])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Pager
                      offset={offset}
                      count={dataset.row_count}
                      busy={!!busy}
                      onPage={page}
                    />
                    <div className="panel-footer">
                      <span>
                        Identifiers stay as text. Zero is a value; blank is
                        blank.
                      </span>
                      <button
                        className="button primary"
                        disabled={!!busy}
                        onClick={() => navigate(1)}
                      >
                        Map fields <Icon name="arrow" size={17} />
                      </button>
                    </div>
                  </section>
                )}
                {step === 1 && (
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Column mapping</h2>
                        <p>Name the fields to keep in your clean workbook.</p>
                      </div>
                      <span className="tag">
                        {config.fields.length} OF {dataset.columns.length}{" "}
                        MAPPED
                      </span>
                    </div>
                    <div className="notice">
                      <Icon name="info" size={17} />
                      Keep IDs and codes as text to preserve leading zeros.
                      Unmapped columns stay in the export’s original values.
                    </div>
                    <div
                      className="table-scroll"
                      role="region"
                      aria-label="Column mapping"
                      tabIndex={0}
                    >
                      <table className="mapping">
                        <thead>
                          <tr>
                            <th scope="col">Keep</th>
                            <th scope="col">Source column</th>
                            <th scope="col" aria-label="Maps to">
                              →
                            </th>
                            <th scope="col">Destination field</th>
                            <th scope="col">Data type</th>
                            <th scope="col">Required</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dataset.columns.map((column) => {
                            const rule = config.fields.find(
                              (field) => field.source === column,
                            );
                            return (
                              <tr
                                key={column}
                                className={!rule ? "excluded" : ""}
                              >
                                <td>
                                  <input
                                    type="checkbox"
                                    aria-label={`Include ${column}`}
                                    checked={!!rule}
                                    onChange={(e) =>
                                      setConfig((old) =>
                                        toggleColumn(
                                          old,
                                          column,
                                          e.target.checked,
                                        ),
                                      )
                                    }
                                  />
                                </td>
                                <td>
                                  <strong>{column}</strong>
                                  <small className="source-example">
                                    {val(dataset.rows[0]?.original[column])}
                                  </small>
                                </td>
                                <td className="muted">→</td>
                                <td>
                                  <input
                                    aria-label={`Destination for ${column}`}
                                    disabled={!rule}
                                    value={rule?.target ?? ""}
                                    placeholder="Excluded from clean data"
                                    onChange={(e) =>
                                      updateRule(column, {
                                        target: e.target.value,
                                      })
                                    }
                                  />
                                </td>
                                <td>
                                  <select
                                    aria-label={`Type for ${column}`}
                                    disabled={!rule}
                                    value={rule?.kind ?? "text"}
                                    onChange={(e) =>
                                      updateRule(column, {
                                        kind: e.target.value as Rule["kind"],
                                      })
                                    }
                                  >
                                    <option value="text">
                                      Text / identifier
                                    </option>
                                    <option value="email">Email</option>
                                    <option value="decimal">Decimal</option>
                                    <option value="date">Date</option>
                                  </select>
                                </td>
                                <td>
                                  <input
                                    type="checkbox"
                                    aria-label={`Require ${column}`}
                                    checked={rule?.required ?? false}
                                    disabled={!rule}
                                    onChange={(e) =>
                                      updateRule(column, {
                                        required: e.target.checked,
                                      })
                                    }
                                  />
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {mappingError && (
                      <p className="validation" role="alert">
                        {mappingError}
                      </p>
                    )}
                    <div className="panel-footer">
                      <button
                        className="button secondary"
                        disabled={!!busy}
                        onClick={() => navigate(0)}
                      >
                        Back to inspect
                      </button>
                      <button
                        className="button primary"
                        disabled={!!mappingError || !!busy}
                        onClick={() => navigate(2)}
                      >
                        Configure rules <Icon name="arrow" size={17} />
                      </button>
                    </div>
                  </section>
                )}
                {step === 2 && (
                  <>
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Field normalization</h2>
                          <p>Expand a field to adjust its cleaning rules.</p>
                        </div>
                        <Icon name="rules" />
                      </div>
                      <div className="rules-list">
                        {config.fields.map((rule) => (
                          <details
                            className="field-rule"
                            key={rule.source}
                            open={rule.kind === "date"}
                          >
                            <summary>
                              <span>
                                <strong>{rule.target}</strong>
                                <small>
                                  {rule.source} → {rule.kind}
                                  {rule.required
                                    ? " · required"
                                    : " · optional"}
                                </small>
                              </span>
                              <span className="rule-summary">
                                {[
                                  rule.trim && "Trim",
                                  rule.collapse_spaces && "Collapse spaces",
                                  rule.casing !== "preserve" && rule.casing,
                                ]
                                  .filter(Boolean)
                                  .join(" · ") || "Validate only"}{" "}
                                <span className="chevron">⌄</span>
                              </span>
                            </summary>
                            <div className="rule-controls">
                              <label className="check-label">
                                <input
                                  type="checkbox"
                                  checked={rule.trim}
                                  onChange={(e) =>
                                    updateRule(rule.source, {
                                      trim: e.target.checked,
                                    })
                                  }
                                />
                                Trim surrounding whitespace
                              </label>
                              <label className="check-label">
                                <input
                                  type="checkbox"
                                  checked={rule.collapse_spaces}
                                  onChange={(e) =>
                                    updateRule(rule.source, {
                                      collapse_spaces: e.target.checked,
                                    })
                                  }
                                />
                                Collapse repeated whitespace
                              </label>
                              <label>
                                Letter case
                                <select
                                  value={rule.casing}
                                  onChange={(e) =>
                                    updateRule(rule.source, {
                                      casing: e.target.value as Rule["casing"],
                                    })
                                  }
                                >
                                  <option value="preserve">
                                    Preserve original case
                                  </option>
                                  <option value="lower">Lowercase</option>
                                  <option value="upper">Uppercase</option>
                                </select>
                              </label>
                              {rule.kind === "date" && (
                                <label>
                                  Exact input date format
                                  <select
                                    value={rule.date_format}
                                    onChange={(e) =>
                                      updateRule(rule.source, {
                                        date_format: e.target
                                          .value as Rule["date_format"],
                                      })
                                    }
                                  >
                                    <option value="%Y-%m-%d">
                                      YYYY-MM-DD (2026-04-03)
                                    </option>
                                    <option value="%m/%d/%Y">
                                      MM/DD/YYYY (04/03/2026)
                                    </option>
                                    <option value="%d/%m/%Y">
                                      DD/MM/YYYY (03/04/2026)
                                    </option>
                                  </select>
                                </label>
                              )}
                              <p className="small muted rule-hint">
                                {rule.kind === "date"
                                  ? "Text must match the selected format; date order is never inferred. Typed Excel dates at midnight are accepted. Output uses YYYY-MM-DD."
                                  : rule.kind === "decimal"
                                    ? "Dot decimals only. Currency symbols, thousands separators, and exponents are rejected. No rounding."
                                    : rule.kind === "email"
                                      ? "Checks basic email structure. Does not verify whether an address exists."
                                      : "Text stays text, including leading zeros. No numeric conversion."}
                              </p>
                            </div>
                          </details>
                        ))}
                      </div>
                    </section>
                    <div className="rules-bottom">
                      <section className="panel">
                        <div className="panel-heading">
                          <div>
                            <h2>Duplicate records</h2>
                            <p>Compare cleaned values of valid records.</p>
                          </div>
                        </div>
                        <div className="panel-body">
                          <label>
                            When a key repeats
                            <select
                              value={config.duplicate_policy}
                              onChange={(e) =>
                                setConfig((old) => ({
                                  ...old,
                                  duplicate_policy: e.target
                                    .value as Config["duplicate_policy"],
                                }))
                              }
                            >
                              <option value="keep_all">
                                Keep all, flag matching keys in audit
                              </option>
                              <option value="reject_later">
                                Keep first valid record, reject later matches
                              </option>
                            </select>
                          </label>
                          <div className="label" id="duplicate-fields">
                            Key fields <small>(combine one or more)</small>
                          </div>
                          <div
                            className="key-fields"
                            role="group"
                            aria-labelledby="duplicate-fields"
                          >
                            {config.fields.map((rule) => (
                              <label key={rule.target} className="check-label">
                                <input
                                  type="checkbox"
                                  checked={config.duplicate_keys.includes(
                                    rule.target,
                                  )}
                                  onChange={(e) =>
                                    setConfig((old) => ({
                                      ...old,
                                      duplicate_keys: e.target.checked
                                        ? [...old.duplicate_keys, rule.target]
                                        : old.duplicate_keys.filter(
                                            (key) => key !== rule.target,
                                          ),
                                    }))
                                  }
                                />
                                {rule.target}
                              </label>
                            ))}
                          </div>
                          <p className="small muted">
                            {config.duplicate_keys.length
                              ? "Exact, case-sensitive comparison after normalization. Blank keys do not match."
                              : "No key selected: records will not be compared for duplicates."}
                          </p>
                        </div>
                      </section>
                      <section className="panel">
                        <div className="panel-heading">
                          <div>
                            <h2>Blank & null values</h2>
                            <p>Keep blank values explicit.</p>
                          </div>
                        </div>
                        <div className="panel-body">
                          <label>
                            Also treat these exact values as blank
                            <textarea
                              value={nullText}
                              onChange={(e) => setNullText(e.target.value)}
                              placeholder={
                                "One per line, for example:\nN/A\nNULL"
                              }
                              rows={4}
                            />
                          </label>
                          <p className="small muted">
                            Optional. Case-sensitive, after whitespace and case
                            rules. Empty cells are always blank; text “0” is
                            only blank if explicitly listed here.
                          </p>
                        </div>
                      </section>
                    </div>
                    {ruleError && (
                      <p className="validation" role="alert">
                        {ruleError}
                      </p>
                    )}
                    <div className="action-bar">
                      <span>
                        <Icon name="shield" size={17} />
                        Changes will be recorded in the audit sheet.
                      </span>
                      <button
                        className="button primary"
                        disabled={!!busy || !!mappingError || !!ruleError}
                        onClick={() => void processData()}
                      >
                        Process {dataset.row_count.toLocaleString()} records{" "}
                        <Icon name="arrow" size={17} />
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
            {step === 3 && run && (
              <>
                {rulesChanged && (
                  <div className="notice draft-notice">
                    <Icon name="info" size={17} />
                    <span>
                      These results use your saved rules. Process your edits to
                      update them.
                    </span>
                    <button
                      className="text-button"
                      onClick={() => navigate(mappingError ? 1 : 2)}
                    >
                      Review edits →
                    </button>
                  </div>
                )}
                {downloadNotice && (
                  <div className="notice" role="status">
                    <Icon name="check" size={17} />
                    {downloadNotice}
                  </div>
                )}
                <div className="result-heading">
                  <span className="success-label">
                    <Icon name="check" size={17} /> Processing complete{" "}
                    <span>· {dateLabel(run.created)}</span>
                  </span>
                  <button
                    className="button primary"
                    disabled={!!busy}
                    onClick={() => void download()}
                  >
                    <Icon name="download" size={17} />{" "}
                    {rulesChanged
                      ? "Export saved result"
                      : "Export Excel workbook"}
                  </button>
                </div>
                <div className="metrics">
                  {[
                    [
                      "Source records",
                      run.summary.total,
                      "In the source file",
                      "",
                    ],
                    ["Accepted", run.summary.accepted, "Ready to use", "green"],
                    [
                      "Changed",
                      run.summary.changed,
                      "Accepted with changes",
                      "blue",
                    ],
                    ["Rejected", run.summary.rejected, "Need attention", "red"],
                  ].map(([title, count, subtitle, color]) => (
                    <div className={`metric ${color}`} key={title}>
                      <span>{title}</span>
                      <strong>{Number(count).toLocaleString()}</strong>
                      <small>{subtitle}</small>
                    </div>
                  ))}
                </div>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Record review</h2>
                      <p>
                        Open a record to compare values and see what changed.
                      </p>
                    </div>
                  </div>
                  <div className="tabs" role="group" aria-label="Record status">
                    {(
                      ["all", "accepted", "changed", "rejected"] as Filter[]
                    ).map((item) => (
                      <button
                        aria-pressed={filter === item}
                        key={item}
                        className={filter === item ? "selected" : ""}
                        disabled={!!busy}
                        onClick={() => void page(0, item)}
                      >
                        {item === "all"
                          ? "All records"
                          : item[0].toUpperCase() + item.slice(1)}
                        <span>
                          {item === "all"
                            ? run.summary.total
                            : run.summary[item]}
                        </span>
                      </button>
                    ))}
                  </div>
                  <form
                    className="review-search"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void page(0, filter, searchText);
                    }}
                  >
                    <label className="sr-only" htmlFor="record-search">
                      Search records
                    </label>
                    <input
                      id="record-search"
                      type="search"
                      maxLength={200}
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                      placeholder="Search values or rejection reasons"
                    />
                    <button className="button compact secondary" type="submit">
                      Search
                    </button>
                    {query && (
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => {
                          setSearchText("");
                          void page(0, filter, "");
                        }}
                      >
                        Clear search
                      </button>
                    )}
                  </form>
                  <div
                    className="table-scroll"
                    role="region"
                    aria-label="Record results"
                    tabIndex={0}
                  >
                    <table className="record-results">
                      <thead>
                        <tr>
                          <th scope="col">Record</th>
                          <th scope="col">Status</th>
                          {run.config.fields.map((field) => (
                            <th key={field.target}>{field.target}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {run.records.map((record) => (
                          <tr
                            key={record.row}
                            className={
                              selected?.row === record.row ? "selected-row" : ""
                            }
                          >
                            <td className="row-number record-link">
                              <button
                                className="text-button"
                                aria-label={`Review record ${record.row}`}
                                onClick={() => setSelected(record)}
                              >
                                {record.row} ↗
                              </button>
                            </td>
                            <td>
                              <span className={`status ${record.status}`}>
                                {record.status === "rejected"
                                  ? "Rejected"
                                  : record.changed
                                    ? "Accepted · changed"
                                    : "Accepted"}
                              </span>
                            </td>
                            {run.config.fields.map((field) => (
                              <td
                                key={field.target}
                                className={`kind-${field.kind}`}
                              >
                                {val(record.cleaned[field.target])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {run.filtered_count === 0 && (
                      <div className="empty">
                        <Icon name="check" size={26} />
                        <h3>
                          {query
                            ? "No matching records"
                            : `No ${filter} records`}
                        </h3>
                        <p>
                          {query
                            ? "Try another value or clear your search."
                            : filter === "rejected"
                              ? "Every record passed the configured rules."
                              : "No records match this filter."}
                        </p>
                      </div>
                    )}
                  </div>
                  <Pager
                    offset={offset}
                    count={run.filtered_count}
                    busy={!!busy}
                    onPage={page}
                  />
                </section>
                <div className="export-note">
                  <Icon name="file" />
                  <div>
                    <strong>Included in your workbook</strong>
                    <p>
                      Summary · Accepted · Rejected · Audit. Includes all{" "}
                      {run.summary.total} records and their original values,
                      regardless of review filters. Values export as text to
                      preserve IDs and precision.
                    </p>
                  </div>
                  <button
                    className="text-button"
                    disabled={!!busy}
                    onClick={() => navigate(mappingError ? 1 : 2)}
                  >
                    Adjust rules & rerun →
                  </button>
                </div>
              </>
            )}
          </fieldset>
        </main>
      </div>
      {selected && run && (
        <RecordDrawer
          selected={selected}
          fields={run.config.fields}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
