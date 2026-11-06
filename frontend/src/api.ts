export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error(
      "Could not reach the server. Check your connection and make sure the backend is running.",
    );
  }
  if (!response.ok) {
    const body: {
      detail?: string | { msg: string; loc: (string | number)[] }[];
    } = await response.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : body.detail
            ?.map((item) => `${item.loc.slice(1).join(" → ")}: ${item.msg}`)
            .join(" ");
    throw new Error(
      detail || `Request failed (${response.status}). Please retry.`,
    );
  }
  return response.json() as Promise<T>;
}
