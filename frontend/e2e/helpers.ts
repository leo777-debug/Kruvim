import type { APIRequestContext } from "@playwright/test";

export const API = "http://127.0.0.1:8016/api/v1";

export async function token(request: APIRequestContext) {
  const r = await request.post(`${API}/auth/login`, { data: { email: "demo@kruvim.local", password: "kruvim-demo-2026" } });
  return { Authorization: `Bearer ${(await r.json()).access_token}` };
}

export async function completedSimulation(request: APIRequestContext) {
  const h = await token(request);
  const projects = await (await request.get(`${API}/projects`, { headers: h })).json();
  const existing = await (await request.get(`${API}/simulations`, { headers: h })).json();
  const done = (existing.items || existing).find?.((s: any) => s.status === "completed" && s.report_status === "done");
  if (done) return { sim: done.id, project: projects[0].id, h };
  const body = { name: "Accessibility tour", requirement: "How will young Gulf professionals react to this routine?",
    content: { type: "video", title: "Apartment workout", platform: "tiktok", transcript: "Three minutes, no equipment. Squats, plank, done. Consistency beats intensity. Follow for part two." },
    audience: { regions: ["AE"] }, overrides: { voice: 10, crowd: 500, stakeholders: 1, hours: 2, minutes_per_round: 60, listening: false } };
  const sim = await (await request.post(`${API}/projects/${projects[0].id}/simulations`, { headers: h, data: body })).json();
  const wait = async (field: string, want: string) => {
    for (let i = 0; i < 240; i++) {
      const s = await (await request.get(`${API}/simulations/${sim.id}`, { headers: h })).json();
      if (s[field] === want) return;
      if (s.status === "failed") throw new Error(s.error);
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`timed out waiting for ${field}=${want}`);
  };
  await request.post(`${API}/simulations/${sim.id}/graph`, { headers: h }); await wait("status", "graph_ready");
  await request.post(`${API}/simulations/${sim.id}/environment`, { headers: h }); await wait("status", "ready");
  await request.post(`${API}/simulations/${sim.id}/start`, { headers: h }); await wait("report_status", "done");
  return { sim: sim.id, project: projects[0].id, h };
}

