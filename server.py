import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg


PUBLIC_FILES = {"/", "/index.html", "/favicon.svg"}
DATABASE_URL = os.environ.get("DATABASE_URL")
MAX_BODY_BYTES = 16_384
MAX_RESULTS = 100
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60
rate_lock = threading.Lock()
rate_buckets = {}


class AppHandler(SimpleHTTPRequestHandler):
    def _path(self):
        return urlsplit(self.path).path

    def _is_rate_limited(self):
        now = time.monotonic()
        client = self.client_address[0]
        with rate_lock:
            recent = [stamp for stamp in rate_buckets.get(client, []) if now - stamp < RATE_WINDOW_SECONDS]
            if len(recent) >= RATE_LIMIT:
                rate_buckets[client] = recent
                return True
            recent.append(now)
            rate_buckets[client] = recent
        return False

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        content_length = self.headers.get("Content-Length")
        if not content_length:
            raise ValueError("Request body is required.")
        try:
            size = int(content_length)
        except ValueError as exc:
            raise ValueError("Invalid request body.") from exc
        if size < 1 or size > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete request body.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")
        return payload

    @staticmethod
    def _validate_result(payload):
        age_range = payload.get("ageRange")
        profile = payload.get("profile")
        score = payload.get("score")
        reaction_ms = payload.get("reactionMs")

        allowed_age_ranges = {"under-18", "18-24", "25-34", "35-44", "45-54", "55-plus"}
        if age_range not in allowed_age_ranges:
            raise ValueError("Age range is invalid.")
        if profile not in {"monolingual", "multilingual"}:
            raise ValueError("Language profile is invalid.")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 20:
            raise ValueError("Memory score must be between 0 and 20.")
        if isinstance(reaction_ms, bool) or not isinstance(reaction_ms, int) or not 1 <= reaction_ms <= 60_000:
            raise ValueError("Reaction time must be between 1 and 60000 milliseconds.")
        return age_range, profile, score, reaction_ms

    def _get_results(self):
        with psycopg.connect(DATABASE_URL) as connection:
            rows = connection.execute(
                """
                SELECT id, age_range, language_profile, memory_score, reaction_ms, created_at
                FROM public.memory_results
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (MAX_RESULTS,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "userLabel": f"User {index}",
                "ageRange": row[1],
                "profile": row[2],
                "score": row[3],
                "reactionMs": row[4],
                "createdAt": row[5].isoformat(),
            }
            for index, row in enumerate(rows, start=1)
        ]

    def _create_result(self, payload):
        age_range, profile, score, reaction_ms = self._validate_result(payload)
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """
                INSERT INTO public.memory_results
                    (participant_name, age_range, language_profile, memory_score, reaction_ms)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, age_range, language_profile, memory_score, reaction_ms, created_at
                """,
                ("anonymous", age_range, profile, score, reaction_ms),
            ).fetchone()
        return {
            "id": row[0],
            "userLabel": "User",
            "ageRange": row[1],
            "profile": row[2],
            "score": row[3],
            "reactionMs": row[4],
            "createdAt": row[5].isoformat(),
        }

    def do_GET(self):
        path = self._path()
        if path == "/api/results":
            try:
                self._send_json(200, {"results": self._get_results()})
            except Exception:
                self._send_json(503, {"error": "Results are temporarily unavailable."})
            return
        if path not in PUBLIC_FILES:
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        if self._path() != "/api/results":
            self.send_error(404)
            return
        if self._is_rate_limited():
            self._send_json(429, {"error": "Too many submissions. Please try again shortly."})
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._send_json(415, {"error": "Content-Type must be application/json."})
            return
        try:
            result = self._create_result(self._read_json_body())
            self._send_json(201, {"result": result})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:
            self._send_json(503, {"error": "Result could not be saved right now."})

    def do_HEAD(self):
        if self._path() not in PUBLIC_FILES:
            self.send_error(404)
            return
        super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
        super().end_headers()


if __name__ == "__main__":
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required to run the results API.")
    ThreadingHTTPServer(("0.0.0.0", 5000), AppHandler).serve_forever()