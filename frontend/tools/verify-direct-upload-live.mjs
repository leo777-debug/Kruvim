import { chromium } from 'playwright';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const [base, output] = process.argv.slice(2);
if (!base || !output) throw new Error('Usage: node verify-direct-upload-live.mjs BASE_URL OUTPUT_DIRECTORY');
await mkdir(output, { recursive: true });
const evidence = { base_url: base, started_at: new Date().toISOString(), checks: [], uploads: [], browser_errors: [] };
const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'msedge' : undefined, headless: true });
const context = await browser.newContext();
const page = await context.newPage();
let projectId, session, headers;
function check(response, status, step) {
  evidence.checks.push({ step, status: response.status(), expected: status });
  if (response.status() !== status) throw new Error(`${step}: expected HTTP ${status}, received ${response.status()}`);
  return response;
}
page.on('pageerror', (error) => evidence.browser_errors.push(error.name));
page.on('requestfinished', (request) => {
  const url = new URL(request.url());
  if (url.pathname.includes('/assets/upload') || url.pathname.includes('/assets/complete')) {
    evidence.uploads.push({ target: 'app metadata', method: request.method(), bytes: request.postDataBuffer()?.length || 0 });
  } else if (url.hostname.endsWith('.supabase.co') && request.method() === 'PUT') {
    evidence.uploads.push({ target: 'private storage', method: 'PUT', captured_body_bytes: request.postDataBuffer()?.length || null,
      carried_app_authorization: !!request.headers().authorization, carried_workspace_header: !!request.headers()['x-org-id'] });
  }
});
try {
  session = await (check(await context.request.post(`${base}/api/v1/auth/register`, { data: {
    email: `media-browser-${randomUUID()}@example.com`, password: randomBytes(32).toString('base64url'),
    name: 'Upload browser verification', org_name: 'Temporary browser verification',
  } }), 200, 'register ordinary browser test account')).json();
  evidence.test_user_id = session.user.id;
  evidence.test_org_id = session.orgs[0].id;
  headers = { Authorization: `Bearer ${session.access_token}`, 'X-Org-Id': session.orgs[0].id };
  const project = await (check(await context.request.post(`${base}/api/v1/projects`, {
    headers, data: { name: 'Temporary browser upload verification' },
  }), 200, 'create browser test project')).json();
  projectId = project.id;
  await page.goto(`${base}/app/login`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ refresh, org }) => {
    localStorage.setItem('kruvim.rt', refresh);
    localStorage.setItem('kruvim.org', org);
  }, { refresh: session.refresh_token, org: session.orgs[0].id });
  await page.goto(`${base}/app/projects/${projectId}`, { waitUntil: 'domcontentloaded' });
  const input = page.locator('input[type="file"]');
  await input.waitFor({ state: 'attached', timeout: 60_000 });
  const filename = 'browser-upload-research.md';
  await input.setInputFiles({ name: filename, mimeType: 'text/markdown', buffer: Buffer.alloc(6_000_000, 'a') });
  await page.getByText(filename, { exact: true }).waitFor({ state: 'visible', timeout: 120_000 });
  await page.screenshot({ path: path.join(output, 'live-project-upload.png'), fullPage: true });
  const projectAfter = await (check(await context.request.get(`${base}/api/v1/projects/${projectId}`, { headers }),
    200, 'read browser uploaded attachment')).json();
  if (projectAfter.assets.length !== 1 || projectAfter.assets[0].size !== 6_000_000) throw new Error('Unexpected saved attachment');
  evidence.stored_bytes = projectAfter.assets[0].size;
  const direct = evidence.uploads.find((upload) => upload.target === 'private storage');
  if (!direct || direct.carried_app_authorization || direct.carried_workspace_header)
    throw new Error('Browser direct-storage transfer validation failed');
  if (evidence.uploads.some((upload) => upload.target === 'app metadata' && upload.bytes > 4096)) throw new Error('Large API payload');
  if (evidence.browser_errors.length) throw new Error('Browser runtime error');
  evidence.result = 'passed';
} catch (error) {
  evidence.result = 'failed';
  evidence.failure_type = error.name;
  // Playwright errors can contain signed URLs or page contents; keep them out of persisted evidence.
} finally {
  if (projectId) check(await context.request.delete(`${base}/api/v1/projects/${projectId}`, { headers }), 200, 'delete browser test project and file');
  if (session) check(await context.request.post(`${base}/api/v1/auth/logout`, { data: { refresh_token: session.refresh_token } }), 200, 'revoke browser test session');
  await context.clearCookies();
  await browser.close();
  evidence.finished_at = new Date().toISOString();
  await writeFile(path.join(output, 'live-browser-evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
}
process.exitCode = evidence.result === 'passed' ? 0 : 1;
