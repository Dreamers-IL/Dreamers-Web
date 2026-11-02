# -*- coding: utf-8 -*-
"""
Builds a single self-contained HTML file holding the whole site, so it can be
handed to a reviewer as one attachment. Every image, video and script is
embedded, so the file needs no server, no unzip and no internet.

Each page is stored verbatim in a <script type="text/html"> block and rendered
into an iframe via srcdoc, which keeps the four stylesheets from colliding.
Cross-page links are intercepted and routed through the location hash, so the
browser Back button behaves normally.
"""
import base64, datetime, hashlib, io, json, mimetypes, os, re, subprocess, sys

# resolve against the repo root so the script runs from anywhere
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".preview-cache")
PAGES = ["index", "program", "business", "education", "mental-health", "practice", "learning", "about", "contact"]
# every build is dated (DDMMYY, matching this project's own commit-message and
# working-doc convention) so a new preview never silently overwrites the one
# handed over for a previous round of review
OUT_NAME = "Dreamers-Site-Preview-%s.html" % datetime.date.today().strftime("%d%m%y")

os.chdir(ROOT)
os.makedirs(CACHE, exist_ok=True)

from PIL import Image

MAX_EDGE = 1500          # px, long edge for photographic assets
JPEG_Q = 80
BIG = 350 * 1024         # bytes: anything above this gets re-encoded
KEEP_PNG = {             # logos / marks where transparency matters
    "assets/img/logo-beit-holmim-white.png",
    "assets/img/logo-beit-holmim.png",
    "assets/img/GALLUP logo.png",
    "assets/img/The Slogan.png",
    "assets/img/The Slogan - Light.png",
    "assets/img/Bird.png",
    "assets/img/16 המעלות - 110826.png",
    "assets/img/Gradient blue.png",
}

log = []


def cache_key(path, ext):
    """A filename-safe, collision-free key.

    Slugifying alone is not enough: every Hebrew character is non-ASCII, so
    "שחף 1.png" and "קבוצות תרגול 1.png" both slugify to the same string and
    the second image would silently reuse the first one's cached file. The
    digest of the full path keeps them apart.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")[:48]
    digest = hashlib.md5(path.encode("utf-8")).hexdigest()[:10]
    return "%s_%s%s" % (slug, digest, ext)


def has_real_alpha(im):
    """True when the file actually relies on transparency."""
    if im.mode not in ("RGBA", "LA", "P"):
        return False
    a = im.convert("RGBA").getchannel("A")
    return a.getextrema()[0] < 255


def optimise_image(path):
    """Return (bytes, mime) for an image, shrinking the heavy ones."""
    raw = open(path, "rb").read()
    if len(raw) <= BIG or path in KEEP_PNG:
        return raw, mimetypes.guess_type(path)[0] or "image/png"

    src = Image.open(path)
    # An image that leans on transparency has to keep it: the page composites
    # it over a coloured backdrop, and flattening onto white here would show
    # the reviewer a different picture from the live site. WebP carries alpha
    # at a fraction of PNG's weight.
    keep_alpha = has_real_alpha(src)
    ext, fmt, mime = (".webp", "WEBP", "image/webp") if keep_alpha else (".jpg", "JPEG", "image/jpeg")

    cached = os.path.join(CACHE, cache_key(path, ext))
    if not os.path.exists(cached):
        im = src.convert("RGBA") if keep_alpha else None
        if im is None:
            im = src.convert("RGBA") if src.mode in ("RGBA", "LA", "P") else src
            if im.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > MAX_EDGE:
            scale = MAX_EDGE / float(max(w, h))
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        if fmt == "WEBP":
            im.save(cached, "WEBP", quality=JPEG_Q, method=5)
        else:
            im.save(cached, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
    out = open(cached, "rb").read()
    log.append("  image %-52s %7.2f MB -> %6.2f MB  %s"
               % (path[-52:], len(raw) / 1e6, len(out) / 1e6, "webp+alpha" if keep_alpha else "jpeg"))
    return out, mime


def optimise_video(path):
    cached = os.path.join(CACHE, cache_key(path, ".mp4"))
    if not os.path.exists(cached):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", path, "-an",
             "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "slow",
             "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", cached],
            check=True,
        )
    raw = open(path, "rb").read()
    out = open(cached, "rb").read()
    log.append("  video %-58s %7.2f MB -> %6.2f MB" % (path[-58:], len(raw) / 1e6, len(out) / 1e6))
    return out, "video/mp4"


AUDIO_BITRATE = "16k"  # 24k came to 103 MB, past GitHub's 100 MB file limit
# Recordings are not written into the page they play on: a page travels as one
# srcdoc string, and tens of MB of audio there would make every visit to it
# crawl. Each one sits in its own block in the outer shell instead, and the
# page asks the shell for it (window.parent.__audioUrl) only when clicked.
AUDIO_ATTR = re.compile(r'data-audio="(assets/Audio/[^"]+)"')
audio_paths = []


def optimise_audio(path):
    """A spoken recording, squeezed for the offline file.

    The learning page carries 17 recordings of 10-20 minutes each (~300 MB as
    delivered). Mono AAC at a speech bitrate keeps them clear enough to review
    while the bundle stays small enough to open and hand over; the live site
    still serves the original files."""
    cached = os.path.join(CACHE, cache_key(path, "-%s.m4a" % AUDIO_BITRATE))
    if not os.path.exists(cached):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1",
             "-ar", "16000", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
             "-movflags", "+faststart", cached],
            check=True,
        )
    raw = open(path, "rb").read()
    out = open(cached, "rb").read()
    log.append("  audio %-58s %7.2f MB -> %6.2f MB" % (path[-58:], len(raw) / 1e6, len(out) / 1e6))
    return out


_cache = {}


def data_uri(ref):
    path = ref.split("?")[0]
    if path in _cache:
        return _cache[path]
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp4",):
        blob, mime = optimise_video(path)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp"):
        blob, mime = optimise_image(path)
    else:
        blob = open(path, "rb").read()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    uri = "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode("ascii"))
    _cache[path] = uri
    return uri


NAV_HOOK = """
<script>
/* preview bundle: route cross-page links through the parent shell */
(function(){
  document.addEventListener('click', function(e){
    var a = e.target && e.target.closest ? e.target.closest('a') : null;
    if(!a) return;
    var href = a.getAttribute('href') || '';
    /* the footer's e-mail address: hand it to the top window, so the
       device's default mail app opens with the address in To: rather than
       the page's own frame trying to navigate to it */
    if(/^mailto:/i.test(href)){
      e.preventDefault();
      try { window.top.location.href = href; } catch(err) { window.open(href); }
      return;
    }
    /* a same-page anchor (#contact-form) would resolve against the shell's
       own address inside a srcdoc frame and reload the shell there instead
       of scrolling, so scroll to it here */
    if(href.charAt(0) === '#' && href.length > 1){
      var t = document.getElementById(decodeURIComponent(href.slice(1)));
      e.preventDefault();
      if(t) t.scrollIntoView({behavior: 'smooth'});
      return;
    }
    /* a query string has to survive the hop: contact.html?from=... is how the
       contact page knows which set of choices to offer */
    var m = href.match(/^([A-Za-z0-9_-]+)\\.html(\\?[^#]*)?(#.*)?$/);
    if(m && parent && parent.__nav){
      e.preventDefault();
      parent.__nav(m[1], (m[2] || '') + (m[3] || ''));
    }
  }, true);
  /* an outside link meant for the same tab (the mental-health page's
     source link on a phone) would load inside this frame, where many sites
     refuse to show; send the whole tab there instead so "back" returns.
     Listens on the way back up, after the page has set the link's target. */
  document.addEventListener('click', function(e){
    var a = e.target && e.target.closest ? e.target.closest('a') : null;
    if(!a || e.defaultPrevented) return;
    var href = a.getAttribute('href') || '';
    if(!/^https?:/i.test(href) || a.getAttribute('target') === '_blank') return;
    e.preventDefault();
    try { window.top.location.href = href; } catch(err) { window.open(href); }
  });
})();
</script>
"""


def build_page(name):
    s = io.open(name + ".html", encoding="utf-8").read()

    # drop the webm source; the mp4 covers every current browser and halves the file
    s = re.sub(r'\s*<source src="[^"]+\.webm" type="video/webm" />\n?', "", s)

    # inline the two local scripts as real script blocks
    for js in ["assets/js/no-orphans.js", "assets/js/accessibility-widget.js", "assets/js/contact-return.js"]:
        # the page may carry a cache-busting suffix on the src
        tag = next((t for t in ('<script src="%s" defer></script>' % js,
                                '<script src="%s?v=2" defer></script>' % js)
                    if t in s), None)
        if tag and os.path.exists(js):
            code = io.open(js, encoding="utf-8").read().replace("</script", "<\\/script")
            s = s.replace(tag, "<script>\n" + code + "\n</script>")

    # every remaining local reference becomes a data: URI
    def repl_src(m):
        uri = data_uri(m.group(1))
        return 'src="%s"' % uri if uri else m.group(0)

    def repl_url(m):
        uri = data_uri(m.group(1))
        return 'url("%s")' % uri if uri else m.group(0)

    s = re.sub(r'src="(?!https?:|data:|#)([^"]+)"', repl_src, s)
    s = re.sub(r'url\("(?!https?:|data:|#)([^"]+)"\)', repl_url, s)
    s = re.sub(r"url\('(?!https?:|data:|#)([^']+)'\)", lambda m: repl_url(m), s)

    # Some images are attached by page scripts rather than written into the
    # markup — the virtue tiles and the facilitator carousel both build their
    # <img> from a path held in a JS array. Catch any remaining complete,
    # quoted asset path so those reach the offline file too.
    def repl_literal(m):
        if m.group(2).startswith("assets/Audio/"):
            return m.group(0)  # served from the shell, see AUDIO_ATTR
        uri = data_uri(m.group(2))
        return m.group(1) + uri + m.group(1) if uri else m.group(0)

    # paths may contain spaces (several photo files are named in Hebrew), so
    # the only thing a path may not contain is its own quote character
    s = re.sub(
        r'(["\'])(assets/[^"\'<>]+\.(?:png|jpg|jpeg|webp|avif|gif|svg|mp4))\1',
        repl_literal,
        s,
    )

    for path in AUDIO_ATTR.findall(s):
        if path not in audio_paths and os.path.exists(path):
            audio_paths.append(path)

    s = s.replace("</body>", NAV_HOOK + "</body>")
    return s


SHELL = u"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>\u05d1\u05d9\u05ea \u05d7\u05d5\u05dc\u05de\u05d9\u05dd \u2014 \u05ea\u05e6\u05d5\u05d2\u05ea \u05d0\u05ea\u05e8</title>
<style>
  html, body { margin:0; padding:0; height:100%%; background:#002952; }
  #view { display:block; width:100%%; height:100%%; border:0; }
  #boot { position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
          font:600 1rem/1.6 system-ui, sans-serif; color:#fff; background:#002952; }
</style>
</head>
<body>
<div id="boot">Loading&nbsp;\u2026</div>
<iframe id="view" title="Dreamers Home preview"></iframe>
%(blocks)s
%(audio)s
<script>
(function(){
  /* recordings for the learning page: decoded into a playable blob the
     first time a page asks for one, then reused */
  var AUDIO = %(audio_map)s, audioUrls = {};
  window.__audioUrl = function(path){
    if (audioUrls[path]) return audioUrls[path];
    var el = document.getElementById(AUDIO[path]);
    if (!el) return encodeURI(path);
    var bin = atob(el.textContent), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return (audioUrls[path] = URL.createObjectURL(new Blob([buf], {type: 'audio/mp4'})));
  };

  var frame = document.getElementById('view');
  var boot  = document.getElementById('boot');
  var PAGES = %(pages)s;

  function render(name, hash, query){
    if (PAGES.indexOf(name) < 0) name = PAGES[0];
    // the stored markup has its closing script tags escaped so the holder
    // block survives HTML parsing; put them back before handing it to srcdoc
    var html = document.getElementById('p-' + name).textContent
                 .split('<\\\\/script').join('<\\/script');
    var inject = '';
    // srcdoc frames have no address of their own, so a ?from= travels in the
    // shell hash and is handed to the page as a global instead
    var from = query && /(?:^|&)from=([^&]*)/.exec(query);
    if (from) {
      inject += '<script>window.__contactFrom=' +
        JSON.stringify(decodeURIComponent(from[1])) + ';<\\/script>';
    }
    if (hash) {
      inject += '<script>window.addEventListener("load",function(){var t=document.querySelector(' +
        JSON.stringify(hash) + ');if(t)t.scrollIntoView();});<\\/script>';
    }
    if (inject) { html = html.replace('</head>', inject + '</head>'); }
    frame.srcdoc = html;
    if (boot) { boot.style.display = 'none'; }
  }

  window.__nav = function(name, hash){
    location.hash = '#' + name + (hash || '');
  };

  function fromHash(){
    var h = (location.hash || '').replace(/^#/, '');
    var anchor = '', query = '';
    var i = h.indexOf('#');
    if (i >= 0) { anchor = h.slice(i); h = h.slice(0, i); }
    var q = h.indexOf('?');
    if (q >= 0) { query = h.slice(q + 1); h = h.slice(0, q); }
    render(h || PAGES[0], anchor, query);
  }

  window.addEventListener('hashchange', fromHash);
  fromHash();
})();
</script>
</body>
</html>
"""

blocks = []
for name in PAGES:
    html = build_page(name)
    html = html.replace("</script", "<\\/script")
    blocks.append('<script type="text/html" id="p-%s">%s</script>' % (name, html))
    log.append("page %-14s %7.2f MB (embedded)" % (name, len(html) / 1e6))

audio_blocks, audio_map = [], {}
for i, path in enumerate(audio_paths):
    audio_map[path] = "au-%d" % i
    audio_blocks.append('<script type="text/plain" id="au-%d">%s</script>'
                        % (i, base64.b64encode(optimise_audio(path)).decode("ascii")))

out = SHELL % {
    "blocks": "\n".join(blocks),
    "audio": "\n".join(audio_blocks),
    "audio_map": json.dumps(audio_map, ensure_ascii=False),
    "pages": str(PAGES).replace("'", '"'),
}

dest = os.path.join(ROOT, OUT_NAME)
io.open(dest, "w", encoding="utf-8", newline="").write(out)

log.append("")
log.append("WROTE %s  (%.2f MB)" % (dest, os.path.getsize(dest) / 1e6))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(log))
