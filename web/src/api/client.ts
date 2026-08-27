// Thin typed client. Vite proxies /api -> http://127.0.0.1:8000

export interface Satellite {
  id: string;
  designator: string;
  bus_design?: string | null;
  launch_date?: string | null;
}

export interface Subsystem {
  id: string;
  satellite_id: string;
  code: string;
  name?: string | null;
  channel_count?: number | null;
}

export interface Channel {
  id: string;
  subsystem_id: string;
  subsystem_code?: string | null;
  mnemonic: string;
  display_name?: string | null;
  units?: string | null;
}

/**
 * One rendered point. For aggregate tiers this summarises a whole bucket:
 * v is the mean, lo/hi the extremes, p05/p95 the percentiles, and n how many
 * raw readings were aggregated. Only v is set on the raw tier.
 */
export interface Point {
  t: string;
  v: number | null;
  lo: number | null;
  hi: number | null;
  p05: number | null;
  p95: number | null;
  n: number | null;
}

export interface Series {
  channel_id: string;
  mnemonic: string;
  units?: string | null;
  tier: string;
  bucket_seconds: number | null;
  points: Point[];
}

export interface TimeseriesResponse {
  start: string;
  end: string;
  tier: string;
  series: Series[];
}

export interface GroupMember {
  channel_id: string;
  mnemonic: string;
  units?: string | null;
  display_order: number;
  axis: number;
}

export interface Group {
  id: string;
  satellite_id: string;
  name: string;
  description?: string | null;
  members: GroupMember[];
}

export interface Label {
  id: string;
  group_id: string | null;
  channel_ids: string[];
  start: string;
  end: string;
  label_class: string;
  scope: string;
  tier: string;
  /** human | model | rule | imported - what an analyst needs to know first. */
  source: string;
  taxonomy_code?: string | null;
  taxonomy_name?: string | null;
  color?: string | null;
  review_status: string;
  severity?: number | null;
  confidence?: number | null;
  note?: string | null;
  model_name?: string | null;
  algorithm?: string | null;
  model_version?: number | null;
  proposed_by_version?: string | null;
  detection_run_id?: string | null;
  ruleset_id?: string | null;
  author_id?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  promoted_by?: string | null;
  promoted_at?: string | null;
  created_at: string;
}

/**
 * Migration 013 dropped taxonomy.label_class: the same event type can be an
 * anomaly or an expected nominal event depending on context, so an entry
 * declares which classes it may carry rather than belonging to one.
 */
export interface TaxonomyItem {
  id: string;
  code: string;
  name: string;
  allowed_classes: string[];
  parent_code?: string | null;
  description?: string | null;
  color?: string | null;
  approved: boolean;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.status === 204 ? (undefined as T) : res.json();
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.json();
}

export const api = {
  satellites: () => get<Satellite[]>("/catalog/satellites"),

  subsystems: (satelliteId: string) =>
    get<Subsystem[]>(`/catalog/satellites/${satelliteId}/subsystems`),

  channels: (params: { q?: string; subsystem_id?: string; satellite_id?: string }) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.subsystem_id) qs.set("subsystem_id", params.subsystem_id);
    if (params.satellite_id) qs.set("satellite_id", params.satellite_id);
    return get<Channel[]>(`/catalog/channels?${qs}`);
  },

  extent: (channelId: string) =>
    get<{ first: string | null; last: string | null; n: number }>(
      `/timeseries/extent?channel_id=${channelId}`
    ),

  timeseries: (channelIds: string[], start: string, end: string, tier?: string) => {
    const qs = new URLSearchParams();
    channelIds.forEach((id) => qs.append("channel_ids", id));
    qs.set("start", start);
    qs.set("end", end);
    if (tier) qs.set("tier", tier);
    return get<TimeseriesResponse>(`/timeseries?${qs}`);
  },

  groups: (satelliteId?: string) =>
    get<Group[]>(`/groups${satelliteId ? `?satellite_id=${satelliteId}` : ""}`),

  group: (groupId: string) => get<Group>(`/groups/${groupId}`),

  createGroup: (payload: {
    satellite_id: string;
    name: string;
    description?: string;
    channel_ids: string[];
  }) => post<Group>("/groups", payload),

  taxonomy: () => get<TaxonomyItem[]>("/labels/taxonomy"),

  labels: (
    groupId: string,
    start?: string,
    end?: string,
    opts?: {
      source?: string;
      review_status?: string;
      tier?: string;
      taxonomy_code?: string;
      algorithm?: string;
      min_confidence?: number;
    }
  ) => {
    const qs = new URLSearchParams({ group_id: groupId });
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    if (opts?.source) qs.set("source", opts.source);
    if (opts?.review_status) qs.set("review_status", opts.review_status);
    if (opts?.tier) qs.set("tier", opts.tier);
    if (opts?.taxonomy_code) qs.set("taxonomy_code", opts.taxonomy_code);
    if (opts?.algorithm) qs.set("algorithm", opts.algorithm);
    if (opts?.min_confidence != null)
      qs.set("min_confidence", String(opts.min_confidence));
    return get<Label[]>(`/labels?${qs}`);
  },

  createLabel: (payload: {
    group_id: string;
    start: string;
    end: string;
    label_class: string;
    taxonomy_code: string;
    channel_ids: string[];
    scope?: string;
    severity?: number;
    note?: string;
    missed?: boolean;
  }) => post<Label>("/labels", payload),

  reviewLabel: (
    labelId: string,
    review_status: "accepted" | "rejected",
    note?: string
  ) =>
    patch<Label>(`/labels/${labelId}/review`, { review_status, note }),
};