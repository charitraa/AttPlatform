/** Turn a DRF error envelope's details into a flat {field: message} map, including nested `config` / `secrets`. */
export function fieldErrors(details: unknown): Record<string, string> {
  if (!details || typeof details !== 'object' || Array.isArray(details)) return {}
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(details as Record<string, unknown>)) {
    if (Array.isArray(v)) out[k] = String(v[0])
    else if (v && typeof v === 'object') for (const [ik, iv] of Object.entries(v)) out[ik] = Array.isArray(iv) ? String(iv[0]) : String(iv)
  }
  return out
}
