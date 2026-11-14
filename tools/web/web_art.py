"""web_art.py - builds the picture library inside the browser from the player's own game files.
Runs in a Web Worker (see artworker.js). Reuses extract_art_from_game.py unchanged, so the browser and the
downloadable version produce the same pictures and descriptions. Nothing is uploaded anywhere."""
import io
import extract_art_from_game as X


class RangeFile:
    """A read-only file made from a function read_range(offset, length) -> bytes-like. Written in plain Python so
    offsets above 2 GB work (the game data file is about 2.1 GB) and the browser's File can be read in pieces."""
    BLOCK = 1 << 20

    def __init__(self, size, read_range):
        self.size, self.rr, self.pos = size, read_range, 0
        self.bo, self.bd = -1, b""

    def _get(self, off, n):
        r = self.rr(off, n)
        if hasattr(r, "to_py"):
            r = r.to_py()
        return bytes(r)

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if n >= self.BLOCK:
            d = self._get(self.pos, n)
            self.pos += len(d)
            return d
        out = []
        while n > 0:
            bo = self.pos - self.pos % self.BLOCK
            if bo != self.bo:
                self.bo, self.bd = bo, self._get(bo, min(self.BLOCK, self.size - bo))
            a = self.pos - bo
            chunk = self.bd[a:a + n]
            if not chunk:
                break
            out.append(chunk)
            self.pos += len(chunk)
            n -= len(chunk)
        return b"".join(out)


def build(pck_file, dll_path, progress):
    """pck_file: file-like object for SlayTheSpire2.pck. dll_path: sts2.dll on the in-memory disk, or None.
    Returns ({"name.webp": bytes}, descriptions dict)."""
    progress("Reading the game's file list...")
    pck = X.Pck(pck_file)
    jobs = X.collect_jobs(pck)
    files, n = {}, len(jobs)
    for i, (kind, p, stem) in enumerate(jobs):
        try:
            img = X.texture_for(pck, p)
            if img is not None:
                if img.width > X.MAXW:
                    img = img.resize((X.MAXW, round(img.height * X.MAXW / img.width)), X.Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "WEBP", quality=88)
                files[stem + ".webp"] = buf.getvalue()
        except Exception:
            pass
        if i % 25 == 0:
            progress(f"Making pictures {i} / {n}")
    progress("Reading card numbers (this part takes about a minute)...")
    cards = X.load_card_data(None, dll_path) if dll_path else {}
    progress("Writing descriptions...")
    return files, X.build_info(pck, cards)
