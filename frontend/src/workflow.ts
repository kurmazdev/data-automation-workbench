import type { Config, Rule } from "./types";

const makeRule = (source: string, target = source): Rule => ({
  source,
  target,
  kind: "text",
  required: false,
  trim: true,
  collapse_spaces: false,
  casing: "preserve",
  date_format: "%Y-%m-%d",
});

export function createConfig(columns: string[] = []): Config {
  const used = new Set<string>();
  const fields = columns.map((source) => {
    const base = Array.from(
      source.trim().replace(/^_+/, "").trim().replace(/\s+/g, " ") || "field",
    )
      .slice(0, 80)
      .join("")
      .trim();
    let target = base;
    let index = 2;
    while (used.has(target)) {
      const suffix = `_${index++}`;
      target =
        Array.from(base)
          .slice(0, 80 - suffix.length)
          .join("") + suffix;
    }
    used.add(target);
    return makeRule(source, target);
  });
  return {
    fields,
    duplicate_keys: [],
    duplicate_policy: "keep_all",
    null_markers: [],
  };
}

export function updateMappedRule(
  config: Config,
  source: string,
  patch: Partial<Rule>,
): Config {
  const previous = config.fields.find((field) => field.source === source);
  return {
    ...config,
    fields: config.fields.map((field) =>
      field.source === source ? { ...field, ...patch } : field,
    ),
    duplicate_keys: config.duplicate_keys.map((key) =>
      key === previous?.target && patch.target !== undefined
        ? patch.target
        : key,
    ),
  };
}

export function toggleColumn(
  config: Config,
  source: string,
  include: boolean,
): Config {
  const previous = config.fields.find((field) => field.source === source);
  if (include) {
    const fallback = createConfig([source]).fields[0];
    const used = new Set(config.fields.map((field) => field.target));
    let target = fallback.target;
    let suffix = 2;
    while (used.has(target))
      target = `${Array.from(fallback.target).slice(0, 75).join("")}_${suffix++}`;
    return { ...config, fields: [...config.fields, { ...fallback, target }] };
  }
  return {
    ...config,
    fields: config.fields.filter((field) => field.source !== source),
    duplicate_keys: config.duplicate_keys.filter(
      (key) => key !== previous?.target,
    ),
  };
}

export function mappingError(config: Config): string {
  if (!config.fields.length) return "Map at least one source column.";
  if (
    config.fields.some(
      (field) =>
        !field.target.trim() ||
        field.target !== field.target.trim() ||
        field.target.startsWith("_") ||
        Array.from(field.target).length > 80,
    )
  )
    return "Destination names must be 1–80 characters, have no surrounding spaces, and cannot begin with _.";
  if (
    new Set(config.fields.map((field) => field.target)).size !==
    config.fields.length
  )
    return "Each destination field needs a unique name.";
  return "";
}
