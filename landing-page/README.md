# Kruvim landing page

Standalone Next.js landing page. The main Kruvim application remains in the repository's existing `frontend/` and `backend/` directories.

## Run locally

Use Node.js 20.9 or newer. From this directory:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm ci
npm run dev -- --port 3100
```

Open http://localhost:3100. For a production build, run `npm run build`, then `npm run start -- --port 3100` from `frontend/`.

When configuring hosting, use `landing-page/frontend` as the project root and set the two environment variables in `.env.example` before building. The included publishable key is intended for browser use. Never add a Supabase secret or service-role key to a `NEXT_PUBLIC_` variable or commit a local environment file.

## Forms and ANE storage

The signup and feedback forms use the existing ANE Supabase project, `jrdgxbdglmpynbyfmamf`. Keep this project URL and publishable key when deploying the website. Early-access signups are leads, not authenticated accounts.

The browser submits to the deployed `kruvim-forms` Edge Function. Signups are stored in `public.landing_signups`, feedback in `public.feedback_messages`. Source is included in `supabase/functions/kruvim-forms/index.ts`; `supabase/landing.sql` records the existing schema. **The ANE schema and function are already deployed. Do not rerun the table-creation SQL against that project.** Neither copying nor deploying this website requires creating another Supabase project.

The function validates submissions and uses Supabase's server-side service-role environment variable. Row-level security is enabled; public roles cannot directly read or write the submission tables. Spam controls include a honeypot, minimum form age, payload limits, unique signup emails, and atomic limits of five submissions per ten minutes per hashed IP/email. No CAPTCHA provider is configured.

## Content and demo

- `frontend/components/KruvimLanding.tsx`: page, navigation and both forms.
- `frontend/components/landing.css`: responsive design and reduced-motion support.
- `frontend/components/DemoVideo.tsx`: demo playback and accessible description.
- `frontend/lib/site-info.ts`: contact email and Instagram URL.
- `frontend/public/kruvim-demo.mp4`: supplied recording, 1280 × 800, about 2:47, recorded at 3× speed with no audio.

Contact is `shrafimtech@gmail.com`; Instagram is `@shrafimtech`. TikTok is pending. Terms and Privacy Policy references are removed from the displayed page as requested. No recording download link is displayed, and the video controls use `nodownload`.

The current design uses a local Inter font, serif headings and restrained Motion animations. The included Inter license is in `frontend/public/INTER-LICENSE.txt`.
