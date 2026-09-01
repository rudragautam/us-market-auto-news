import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]

CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
REDIRECT_URI = os.environ.get(
    "YOUTUBE_REDIRECT_URI",
    "http://localhost:3000/api/auth/google/callback"
)

client_config = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI],
    }
}

flow = Flow.from_client_config(
    client_config,
    scopes=SCOPES,
)

flow.redirect_uri = REDIRECT_URI

authorization_url, state = flow.authorization_url(
    access_type="offline",
    prompt="consent",
    include_granted_scopes="true",
)


class CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/api/auth/google/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)

        if "error" in params:
            error = params["error"][0]

            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                f"<h2>Authorization failed</h2><p>{error}</p>".encode()
            )
            return

        if "code" not in params:
            self.send_response(400)
            self.end_headers()
            return

        code = params["code"][0]

        try:
            flow.fetch_token(code=code)

            credentials = flow.credentials

            refresh_token = credentials.refresh_token

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"""
                <html>
                <body>
                    <h2>YouTube authorization successful.</h2>
                    <p>You can close this browser window.</p>
                </body>
                </html>
                """
            )

            print("\n" + "=" * 70)
            print("YOUTUBE REFRESH TOKEN")
            print("=" * 70)
            print(refresh_token)
            print("=" * 70)
            print("\nCopy this value into GitHub Secrets as:")
            print("YOUTUBE_REFRESH_TOKEN")
            print()

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                f"<h2>Token exchange failed</h2><pre>{e}</pre>".encode()
            )

            print("\nERROR:")
            print(e)


print("\nOpening Google authorization...")
print("\nIf browser does not open, use this URL:\n")
print(authorization_url)
print()

webbrowser.open(authorization_url)

print("Waiting for Google callback...")
print("Callback:", REDIRECT_URI)

server = HTTPServer(("localhost", 3000), CallbackHandler)

server.handle_request()

print("\nDone.")
