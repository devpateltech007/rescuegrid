async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T>(u: string) => req<T>("GET", u),
  post: <T>(u: string, b?: unknown) => req<T>("POST", u, b),
  mission: () => req<any>("GET", "/api/mission"),
  start: () => req("POST", "/api/mission/start"),
  pause: () => req("POST", "/api/mission/pause"),
  resume: () => req("POST", "/api/mission/resume"),
  reset: () => req("POST", "/api/mission/reset"),
  step: (n = 1) => req("POST", `/api/mission/step?n=${n}`),
  speed: (s: number) => req("POST", "/api/mission/speed", { speed: s }),
  autoPause: (enabled: boolean) => req("POST", "/api/mission/auto-pause", { enabled }),
  status: () => req<any>("GET", "/api/system/status"),
  verify: (id: string, operator: string, outcome: "BLOCKED" | "PASSABLE", evidence: string[], note = "") =>
    req<any>("POST", `/api/incidents/${id}/verify`, { operator, outcome, evidence_reviewed: evidence, note }),
  reject: (id: string, operator: string, evidence: string[], note = "") =>
    req<any>("POST", `/api/incidents/${id}/reject`, { operator, evidence_reviewed: evidence, note }),
  reinspect: (id: string, operator: string, evidence: string[], note = "") =>
    req<any>("POST", `/api/incidents/${id}/request-inspection`, { operator, evidence_reviewed: evidence, note }),
  approve: (rid: string, operator: string, evidence: string[], note = "") =>
    req<any>("POST", `/api/routes/${rid}/approve`, { operator, evidence_reviewed: evidence, note }),
  briefing: (operator: string) => req<any>("POST", "/api/briefings/generate", { operator }),
  retask: (droneId: string, operator: string, body: Record<string, unknown>) =>
    req<any>("POST", `/api/drones/${droneId}/retask`, { operator, ...body }),
  analyze: (oid: string) => req("POST", `/api/observations/${oid}/analyze`),
};
