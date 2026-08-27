import { useCallback, useEffect, useState } from "react";
import { api, type Channel, type Group } from "../../api/client";

/**
 * Groups are the analytical working set, and labels attach to one. Until a
 * group is loaded the chart has nothing to ask for labels about, so this is
 * also what makes model proposals visible.
 *
 * Saving works from the channels already on the chart rather than from a blank
 * form: picking channels in the finder is the gesture users already make, so
 * "save what I am looking at" is the shorter path to the same result.
 */
export function GroupPicker({
  selected,
  activeGroup,
  onLoad,
  onClear,
}: {
  selected: Channel[];
  activeGroup: Group | null;
  onLoad: (group: Group) => void;
  onClear: () => void;
}) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // subsystem -> satellite, so a group can be saved without asking the user
  // which satellite they meant. Channels know their subsystem; groups need the
  // satellite, and nothing in between carries both.
  const [satelliteOf, setSatelliteOf] = useState<Record<string, string>>({});

  const refresh = useCallback(() => {
    api.groups().then(setGroups).catch(() => setGroups([]));
  }, []);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    let cancelled = false;
    api
      .satellites()
      .then((sats) =>
        Promise.all(
          sats.map((s) =>
            api
              .subsystems(s.id)
              .then((subs) => subs.map((sub) => [sub.id, s.id] as const))
              .catch(() => [] as (readonly [string, string])[])
          )
        )
      )
      .then((pairs) => {
        if (!cancelled) setSatelliteOf(Object.fromEntries(pairs.flat()));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleLoad(groupId: string) {
    if (!groupId) {
      onClear();
      return;
    }
    setError(null);
    try {
      onLoad(await api.group(groupId));
    } catch {
      setError("could not load that group");
    }
  }

  function resolveSatellite(): string | null {
    for (const channel of selected) {
      const satelliteId = channel.subsystem_id
        ? satelliteOf[channel.subsystem_id]
        : undefined;
      if (satelliteId) return satelliteId;
    }
    return null;
  }

  /**
   * A starting point, not a decision. Mnemonics are what the user just picked,
   * so they recognise the name immediately - but it stays selected in the
   * input so typing over it costs one keystroke.
   */
  function suggestName(): string {
    const names = selected.map((c) => c.mnemonic);
    if (names.length === 1) return names[0];
    if (names.length <= 3) return names.join(" + ");
    const prefixes = new Set(names.map((n) => n.slice(0, 3)));
    return prefixes.size === 1
      ? `${[...prefixes][0]} \u00d7 ${names.length}`
      : `${names[0]} +${names.length - 1} more`;
  }

  function beginSave() {
    setName(suggestName());
    setSaving(true);
  }

  async function handleSave() {
    const satelliteId = resolveSatellite();
    if (!satelliteId) {
      setError("could not work out which satellite these channels belong to");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const group = await api.createGroup({
        satellite_id: satelliteId,
        name: name.trim(),
        channel_ids: selected.map((c) => c.id),
      });
      setSaving(false);
      setName("");
      refresh();
      onLoad(group);
    } catch {
      // the API upserts on (satellite_id, name), so a clash is not the usual
      // failure here - more likely the request never landed
      setError("could not save the group");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="group-picker">
      <div className="panel-head">
        <span className="panel-title">Group</span>
        {activeGroup && (
          <button className="link-btn" onClick={onClear} title="Stop using this group">
            Clear
          </button>
        )}
      </div>

      <select
        value={activeGroup?.id ?? ""}
        onChange={(e) => handleLoad(e.target.value)}
        aria-label="Telemetry group"
      >
        <option value="">No group &middot; labels hidden</option>
        {groups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.name} ({group.members.length})
          </option>
        ))}
      </select>

      {saving ? (
        <div className="group-save">
          <input
            autoFocus
            onFocus={(e) => e.currentTarget.select()}
            value={name}
            placeholder="Group name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) handleSave();
              if (e.key === "Escape") setSaving(false);
            }}
          />
          <button disabled={!name.trim() || busy} onClick={handleSave}>
            {busy ? "Saving\u2026" : "Save"}
          </button>
          <button className="link-btn" onClick={() => setSaving(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button
          disabled={selected.length === 0}
          title={
            selected.length === 0
              ? "Select channels first"
              : `Save the ${selected.length} channel(s) on the chart as a group`
          }
          onClick={beginSave}
        >
          Save {selected.length || ""} as group
        </button>
      )}

      {error && <div className="group-error">{error}</div>}
    </div>
  );
}