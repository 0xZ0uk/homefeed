/** The loading window's page, as a data: URL (no files to ship, no scripts). */

const SPLASH_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Homefeed</title>
<style>
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 16px; background: #0f0f0f; color: #f1f1f1;
    font: 15px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    user-select: none; -webkit-app-region: drag;
  }
  h1 { margin: 0; font-size: 22px; font-weight: 600; }
  p { margin: 0; color: #aaa; }
  .spinner {
    width: 28px; height: 28px; border-radius: 50%;
    border: 3px solid #333; border-top-color: #f00;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 3s; } }
</style>
</head>
<body>
  <h1>Homefeed</h1>
  <div class="spinner" role="progressbar" aria-label="Starting"></div>
  <p>Starting…</p>
</body>
</html>`;

export const SPLASH_URL = `data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`;
