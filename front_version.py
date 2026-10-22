"""Version of the files the page loads (HTML, JS, CSS), so that a browser left open since the morning
switches by itself to the code served today.

Each file has its tag, the hash of its content: it serves as the ETag and as a suffix (?v=) on every
reference to a JS or CSS file in the HTML sent. An unchanged file therefore keeps its URL and comes out of
the browser cache without even asking the server; a modified file changes URL and only it is downloaded
again. The version of the whole, the hash of all tags, is written into the HTML and returned by
GET /version: version.js reloads the page when they differ.

The files are reread on every computation: a page modified without restarting the server is seen too.
"""

import hashlib
import re

# Relative reference to a JS or CSS file served by this server, without any parameter already present.
ASSET_REFERENCE = re.compile(r'(?P<attribute>(?:src|href)=")(?P<path>[^"?:#]+\.(?:js|css))"')
VERSION_META_NAME = "mr-dashboard-version"


def tag(content):
    """Tag of a content: short, but long enough for two versions not to collide."""
    return hashlib.sha256(content).hexdigest()[:16]


class FrontVersion:

    def __init__(
            self,
            static_dir,
            front_paths
    ):
        self.static_dir = static_dir
        self.front_paths = front_paths

    def file_tag(self, path):
        return tag((self.static_dir / path.lstrip("/")).read_bytes())

    def version(self):
        tags = "".join(path + self.file_tag(path) for path in sorted(self.front_paths))
        return tag(tags.encode())

    def versioned_html(self, html):
        """HTML in which each served JS or CSS carries its file's tag, and which carries the version of
        the whole for version.js."""
        def versioned(match):
            path = "/" + match["path"]
            if path not in self.front_paths:
                return match[0]
            return f'{match["attribute"]}{match["path"]}?v={self.file_tag(path)}"'

        text = ASSET_REFERENCE.sub(versioned, html.decode())
        meta = f'<meta name="{VERSION_META_NAME}" content="{self.version()}">'
        return text.replace("<head>", "<head>\n" + meta, 1).encode()
