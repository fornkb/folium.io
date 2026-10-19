"""Folium's loopback-only HTTP server. Run with: python app.py"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from core import Store, clean, grade, module_state, review_card, validate_outline, safe_text, assessment_evidence
from generation import Gemini, Jobs, Settings
from configuration import configured_values, env_path
from pdfview import render_page

ROOT = Path(__file__).resolve().parent
MAX_BODY = 80 * 1024 * 1024


def create_server(data_dir, port=8765, seed=True, env_file=None):
    store = Store(data_dir)
    settings = Settings(store.root, env_file=env_file)
    jobs = Jobs(store, Gemini(store, settings))
    if seed:
        from sample import seed_sample
        seed_sample(store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Folium/1.0"

        def log_message(self, fmt, *args):
            # Deliberately omit request details, user content, and provider responses.
            pass

        def send(self, status, body, mime="application/json; charset=utf-8", filename=None):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; connect-src 'self'")
            if filename:
                safe = re.sub(r"[^a-zA-Z0-9._ -]", "_", filename)
                self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def valid_host(self):
            hostname = urlparse("http://" + self.headers.get("Host", "")).hostname
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                raise PermissionError("Use the local Folium address.")
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                raise PermissionError("This action must come from your local Folium app.")

        def body(self):
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > MAX_BODY:
                raise ValueError("This upload is too large. Keep the total below 80 MB.")
            raw = self.rfile.read(length)
            if "multipart/form-data" in self.headers.get("Content-Type", ""):
                parsed = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
                fields, files = {}, []
                for part in parsed.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    filename = part.get_filename()
                    data = part.get_payload(decode=True) or b""
                    if filename:
                        files.append(dict(field=name, name=filename, content=data))
                    else:
                        fields[name] = data.decode("utf-8")
                return fields, files
            if not raw:
                return {}
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ValueError("Use a JSON request for this action.")
            return json.loads(raw)

        def public(self, cid):
            course = store.public(cid)
            for m in course["modules"]:
                m["state"] = module_state(m)
                m["evidence"] = assessment_evidence(m)
            return course

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def handle_request(self, method):
            try:
                self.valid_host()
                path = unquote(urlparse(self.path).path)
                if method == "GET":
                    if path == "/api/health":
                        return self.send(200, dict(ok=True, app="Folium"))
                    if path == "/api/settings":
                        return self.send(200, settings.public())
                    if path == "/api/courses":
                        return self.send(200, [self.public(c["id"]) for c in store.courses()])
                    match = re.fullmatch(r"/api/courses/([a-f0-9]{16})(/export)?", path)
                    if match:
                        cid = match[1]
                        if match[2]:
                            return self.send(200, store.export(cid), "application/zip", clean(store.course(cid)["title"], 80) + ".folium.zip")
                        return self.send(200, self.public(cid))
                    match = re.fullmatch(r"/api/documents/([a-f0-9]{16})", path)
                    if match:
                        file_path, _ = store.document(match[1])
                        return self.send(200, file_path.read_bytes(), "application/pdf")
                    match = re.fullmatch(r"/api/documents/([a-f0-9]{16})/pages/(\d+)(\.png)?", path)
                    if match:
                        file_path,name = store.document(match[1])
                        page = int(match[2])
                        if match[3]:
                            return self.send(200, render_page(file_path, page, store.root / "page_previews"), "image/png")
                        with store.lock:
                            pages = json.loads(store.db.execute("SELECT pages FROM documents WHERE id=?",(match[1],)).fetchone()[0])
                        if not 1 <= page <= len(pages):
                            raise ValueError("Choose a valid source page.")
                        text = safe_text(pages[page-1])
                        return self.send(200,dict(name=name,page=page,text=text,
                            warning="Some PDF symbols could not be extracted. Check the original page for exact notation." if "\ufffd" in text else ""))
                    if path.startswith("/api/"):
                        return self.send(404, dict(error="This page could not be found."))
                    relative = path.lstrip("/") or "index.html"
                    target = (ROOT / "web" / relative).resolve()
                    if not target.is_relative_to((ROOT / "web").resolve()) or not target.is_file():
                        return self.send(404, dict(error="This page could not be found."))
                    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    if target.suffix == ".js":
                        mime = "text/javascript"
                    return self.send(200, target.read_bytes(), mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
                body = self.body()
                if path == "/api/settings":
                    return self.send(200, settings.save(body))
                if path == "/api/import":
                    _, files = body
                    if len(files) != 1:
                        raise ValueError("Choose one Folium course backup.")
                    course = store.import_course(files[0]["content"])
                    return self.send(201, self.public(course["id"]))
                if path == "/api/courses":
                    fields, files = body
                    if not clean(fields.get("title")):
                        raise ValueError("Give your course a name.")
                    if not files or len(files) > 30:
                        raise ValueError("Upload between 1 and 30 course PDFs.")
                    roles = json.loads(fields.get("roles", "[]"))
                    course = store.create(fields["title"])
                    try:
                        for i,f in enumerate(files):
                            store.add_pdf(course["id"], f["name"], roles[i] if i < len(roles) else "material", f["content"])
                        if not any(d["role"] != "pyq" for d in store.docs(course["id"])):
                            raise ValueError("Add a syllabus or learning material alongside your past papers.")
                    except Exception:
                        # Roll back the newly created course; never leave a half-uploaded workspace.
                        with store.lock, store.db:
                            for d in store.docs(course["id"]):
                                (store.root / "documents" / (d["id"] + ".pdf")).unlink(missing_ok=True)
                            store.db.execute("DELETE FROM documents WHERE course_id=?", (course["id"],))
                            store.db.execute("DELETE FROM courses WHERE id=?", (course["id"],))
                        raise
                    warnings = []
                    for d in store.docs(course["id"]):
                        blank = sum(not p.strip() for p in d["pages"])
                        if blank:
                            warnings.append(f"{d['name']}: {blank} page(s) had no readable text and will be skipped.")
                    course["warnings"] = warnings
                    store.save(course)
                    return self.send(201, self.public(course["id"]))
                match = re.fullmatch(r"/api/courses/([a-f0-9]{16})/(outline|extend|prepare|modules/([^/]+)/(progress|quiz|review))", path)
                if match:
                    cid, action, mid, subaction = match[1], match[2], match[3], match[4]
                    course = store.course(cid)
                    if action == "extend":
                        if cid in jobs.active:
                            raise ValueError("Wait for preparation to pause or finish before adding a module.")
                        store.extend(cid, body.get("modules", []))
                        return self.send(200, self.public(cid))
                    if action == "prepare":
                        jobs.start(cid, body.get("action", "generate"))
                        return self.send(202, self.public(cid))
                    if action == "outline":
                        if cid in jobs.active or any(m.get("package") for m in course["modules"]):
                            raise ValueError("The outline is locked once lesson generation starts. Create a new course to change its materials or structure.")
                        modules = validate_outline(body.get("modules"))
                        store.update(cid, lambda c: c.update(modules=modules, status="outline"))
                        return self.send(200, self.public(cid))
                    if not any(m["id"] == mid for m in course["modules"]):
                        raise ValueError("Module not found.")
                    result = {}
                    def mutate(c):
                        module = next(m for m in c["modules"] if m["id"] == mid)
                        if subaction == "progress":
                            for flag in ("read", "bookmarked"):
                                if flag in body:
                                    module[flag] = bool(body[flag])
                            if "notes" in body:
                                module["notes"] = clean(body["notes"], 30000)
                        elif subaction == "quiz":
                            result.update(grade(module, body.get("answers", {}), body.get("question_ids")))
                        elif subaction == "review":
                            result.update(review_card(c, mid, int(body.get("index", -1)), body.get("rating")))
                    store.update(cid, mutate)
                    return self.send(200, dict(course=self.public(cid), result=result))
                self.send(404, dict(error="This action could not be found."))
            except PermissionError as exc:
                self.send(403, dict(error=str(exc)))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "This request is incomplete or invalid."
                self.send(400, dict(error=message))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, dict(error="Something could not be saved. Please try again."))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store, server.settings, server.jobs = store, settings, jobs
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Folium locally.")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--env-file", type=Path, default=None, help="Optional path to a .env configuration file.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    configured, _ = configured_values(env_path(args.env_file))
    port = args.port if args.port is not None else int(configured.get("FOLIUM_PORT", 8765))
    server = create_server(args.data_dir, port, env_file=args.env_file)
    print(f"\n  Folium is ready at http://127.0.0.1:{server.server_port}\n  Your courses are saved in {args.data_dir.resolve()}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFolium stopped. Your saved courses are safe.")
    finally:
        server.server_close()
