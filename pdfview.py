"""Render local PDF pages without relying on browser PDF plug-ins."""
import io
import threading

import pypdfium2 as pdfium

# PDFium calls are serialized because the underlying library is not thread-safe.
RENDER_LOCK = threading.Lock()


def render_page(path, page, cache_dir):
    if page < 1:
        raise ValueError("Choose a valid source page.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{path.stem}-{page}.png"
    with RENDER_LOCK:
        if cached.exists():
            return cached.read_bytes()
        document = pdfium.PdfDocument(str(path))
        try:
            if page > len(document):
                raise ValueError("This page is outside the source document.")
            pdf_page = document[page-1]
            try:
                width,height = pdf_page.get_size()
                scale = min(1.7, 1600 / max(1,width,height))
                bitmap = pdf_page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    stream = io.BytesIO()
                    image.save(stream, format="PNG")
                    content = stream.getvalue()
                finally:
                    bitmap.close()
            finally:
                pdf_page.close()
        finally:
            document.close()
        cached.write_bytes(content)
        return content
