"""Version des fichiers que la page charge (HTML, JS, CSS), pour qu'un navigateur ouvert depuis le matin
passe de lui-même au code servi aujourd'hui.

Chaque fichier a son étiquette, l'empreinte de son contenu : elle sert d'ETag et suffixe (?v=) chaque
référence à un JS ou un CSS dans le HTML envoyé. Un fichier inchangé garde donc son URL et sort du cache
du navigateur sans même interroger le serveur ; un fichier modifié change d'URL et lui seul est
retéléchargé. La version de l'ensemble, l'empreinte de toutes les étiquettes, est écrite dans le HTML
et donnée par GET /version : version.js recharge la page quand elles diffèrent.

Les fichiers sont relus à chaque calcul : une page modifiée sans redémarrage du serveur est vue aussi.
"""

import hashlib
import re

# Référence relative à un JS ou un CSS servi par ce serveur, sans paramètre déjà présent.
ASSET_REFERENCE = re.compile(r'(?P<attribute>(?:src|href)=")(?P<path>[^"?:#]+\.(?:js|css))"')
VERSION_META_NAME = "mr-dashboard-version"


def tag(content):
    """Étiquette d'un contenu : courte, mais assez longue pour que deux versions ne se confondent pas."""
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
        """HTML dont chaque JS ou CSS servi porte l'étiquette de son fichier, et qui porte la version
        de l'ensemble pour version.js."""
        def versioned(match):
            path = "/" + match["path"]
            if path not in self.front_paths:
                return match[0]
            return f'{match["attribute"]}{match["path"]}?v={self.file_tag(path)}"'

        text = ASSET_REFERENCE.sub(versioned, html.decode())
        meta = f'<meta name="{VERSION_META_NAME}" content="{self.version()}">'
        return text.replace("<head>", "<head>\n" + meta, 1).encode()
