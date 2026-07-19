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
  group_id: string;
  channel_id?: string | null;
  start: string;
  end: string;
  label_class: string;
  taxonomy_code?: string | null;
  taxonomy_name?: string | null;
  color?: string | null;
  review_status: string;
  note?: string | null;
  created_at: string;
}

export interface TaxonomyItem {
  id: string;
  label_class: string;
  code: string;
  name: string;
  description?: string | null;
  color?: string | null;
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

  createGroup: (payload: {
    satellite_id: string;
    name: string;
    description?: string;
    channel_ids: string[];
  }) => post<Group>("/groups", payload),

  taxonomy: () => get<TaxonomyItem[]>("/labels/taxonomy"),

  labels: (groupId: string, start?: string, end?: string) => {
    const qs = new URLSearchParams({ group_id: groupId });
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    return get<Label[]>(`/labels?${qs}`);
  },

  createLabel: (payload: {
    group_id: string;
    start: string;
    end: string;
    label_class: string;
    taxonomy_code?: string;
    note?: string;
  }) => post<Label>("/labels", payload),
};