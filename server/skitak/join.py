"""
/join/<token> landing page — the URL guides share with clients.

When a client taps the invite link:
  - If the SkiTAK native app is installed, the deep link opens it directly
    (handled by the iOS URL scheme / associated domain before this page loads)
  - If not installed, Safari shows this page with two clear options:
      1. Download SkiTAK app (App Store)
      2. Download enrollment package for iTAK/ATAK
"""
from flask import Blueprint, abort, render_template_string

from .common import valid_token

bp = Blueprint("skitak_join", __name__, url_prefix="/join")

_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Join SkiTAK</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#0f1117;color:#f1f5f9;min-height:100vh;
         display:flex;align-items:center;justify-content:center;padding:24px}
    .card{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;
          padding:32px 28px;max-width:380px;width:100%;text-align:center}
    .logo{font-size:48px;margin-bottom:12px}
    h1{font-size:24px;font-weight:700;margin-bottom:6px}
    .sub{color:#94a3b8;font-size:14px;margin-bottom:32px}
    .btn{display:block;width:100%;padding:14px 20px;border-radius:12px;
         font-size:15px;font-weight:600;text-decoration:none;border:none;
         cursor:pointer;margin-bottom:12px;transition:opacity .15s}
    .btn:hover{opacity:.85}
    .btn-primary{background:#3b82f6;color:#fff}
    .btn-secondary{background:#1e293b;color:#f1f5f9;
                   border:1px solid #2a2d3a}
    .divider{color:#475569;font-size:12px;margin:4px 0 16px;
             position:relative}
    .note{color:#64748b;font-size:12px;margin-top:20px;line-height:1.5}
    a.note-link{color:#3b82f6;text-decoration:none}
  </style>
  <!-- Try to open the native app immediately if installed -->
  <script>
    window.addEventListener('DOMContentLoaded', function() {
      // Attempt silent deep link — if app is installed it opens; if not, nothing happens
      var frame = document.createElement('iframe');
      frame.style.display = 'none';
      frame.src = 'skitak://join/{{ token }}';
      document.body.appendChild(frame);
      setTimeout(function() { document.body.removeChild(frame); }, 1500);
    });
  </script>
</head>
<body>
  <div class="card">
    <div class="logo">🗺️</div>
    <h1>Join SkiTAK</h1>
    <p class="sub">You've been invited to a session.<br/>Choose how to connect:</p>

    <!-- Option 1: Native SkiTAK app (best experience) -->
    <a href="skitak://join/{{ token }}" class="btn btn-primary">
      Open in SkiTAK App
    </a>

    <div class="divider">or</div>

    <!-- Option 2: TAK data package for iTAK/ATAK -->
    <a href="/api/skitak/enroll/{{ token }}/package" class="btn btn-secondary"
       download>
      Download for iTAK / ATAK
    </a>

    <p class="note">
      No SkiTAK app yet?
      <a class="note-link" href="https://apps.apple.com/app/skitak" target="_blank">
        Download from the App Store
      </a><br/>
      Using Android? Download the package above and import it in ATAK.
    </p>
  </div>
</body>
</html>"""


@bp.get("/<token>")
def join_page(token: str):
    # Tokens are URL-safe base64 — anything else never reaches the template
    if not valid_token(token):
        abort(404)
    return render_template_string(_PAGE, token=token)
