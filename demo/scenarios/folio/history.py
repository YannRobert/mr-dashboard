"""The git history of Folio's storefront: the code on main, and the commits of every merge request, push by push.

Times are hours before the demo starts (see ../../fakegitlab/repository.py, which builds the repository). A commit
gives full contents (`files`, None to delete), replacements in a file (`edits`: path, old text, new text, each old
text found exactly once) and renames (`moves`).
"""
import random
from dataclasses import dataclass, field


def days(count):
    return count * 24.0


@dataclass
class Commit:
    author: str
    title: str
    files: dict = field(default_factory=dict)
    edits: list = field(default_factory=list)
    moves: dict = field(default_factory=dict)
    # Hours before the push that publishes it; on main, hours before the demo starts.
    before: float = 0.0


@dataclass
class Push:
    at: float
    commits: list


@dataclass
class Branch:
    name: str
    # The source branch leaves its target (or the source branch of another merge request, for a stacked one) as
    # it was at this time.
    created_at: float
    pushes: list
    # Merged into the target by this person at this time, with a merge commit, or squashed into a single commit
    # (GitLab then gives no merge commit).
    merged_at: float = None
    merged_by: str = None
    target: str = "main"
    parent: int = None
    squash: bool = False


CI = """\
stages: [build, test, quality]

lint:
  stage: build
  script: python -m ruff check .

unit_tests:
  stage: test
  script: python -m pytest --junitxml=report.xml

sonar:
  stage: quality
  script: sonar-scanner -Dsonar.pullrequest.key=$CI_MERGE_REQUEST_IID

mutation_test:
  stage: quality
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script: ./ci/mutation-report.sh
"""

README = """\
# Folio storefront

The online bookshop of Folio: its catalogue, its cart and the chekout, wich turns a cart into an order.

    python -m pytest
"""

AI_ACTIONS = '''\
[[action]]
id = "review"
label = "Review"
tab = "Review !{iid}"
model = "sonnet"
prompt = """
Review merge request !{iid} ({title}), {source_branch} into {target_branch}: {web_url}
Read the diff with git diff origin/{target_branch}...origin/{source_branch}, then list what should change
before it is merged, most important first.
"""

[[action]]
id = "explain"
label = "Explain"
tab = "Explain !{iid}"
prompt = """
Explain merge request !{iid} ({title}) to someone who has not read it: what it changes, why, and what to
check when testing it. The diff is git diff origin/{target_branch}...origin/{source_branch}.
"""

[[action]]
id = "fix"
label = "Fix"
tab = "Fix !{iid}"
when = "to-fix"
prompt = """
{fix_context}
Run python -m pytest before every push.
"""
'''

CATALOGUE = '''\
"""The books on sale, and how customers find them."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    isbn: str
    title: str
    author: str
    price_cents: int
    stock: int = 0


class Catalogue:

    def __init__(self):
        self._books = {}

    def add(self, book):
        self._books[book.isbn] = book

    def get(self, isbn):
        return self._books.get(isbn)

    def search(self, words):
        """Books whose title or author contains every word, case-insensitive."""
        terms = words.lower().split()
        return [
            book for book in self._books.values()
            if all(term in f"{book.title} {book.author}".lower() for term in terms)
        ]

    def in_stock(self):
        return [book for book in self._books.values() if book.stock > 0]
'''

PRICES = '''\
"""Money, in cents: no float ever holds a price."""
VAT_RATE = 0.055  # reduced rate on books


def vat_cents(amount_cents):
    return int(amount_cents * VAT_RATE)


def format_price(amount_cents):
    return f"€{amount_cents // 100}.{amount_cents % 100:02d}"
'''

CART = '''\
"""A customer's cart, before checkout."""
from .prices import vat_cents


class Cart:

    def __init__(self, catalogue):
        self._catalogue = catalogue
        self._lines = {}

    def add(self, isbn, quantity=1):
        book = self._catalogue.get(isbn)
        if book is None:
            raise KeyError(f"unknown book: {isbn}")
        if quantity > book.stock:
            raise ValueError(f"only {book.stock} left of {book.title}")
        self._lines[isbn] = self._lines.get(isbn, 0) + quantity

    def remove(self, isbn):
        self._lines.pop(isbn, None)

    def lines(self):
        return [(self._catalogue.get(isbn), quantity) for isbn, quantity in self._lines.items()]

    def subtotal_cents(self):
        return sum(book.price_cents * quantity for book, quantity in self.lines())

    def total_cents(self):
        subtotal = self.subtotal_cents()
        return subtotal + vat_cents(subtotal)
'''

CHECKOUT = '''\
"""Turning a cart into an order."""
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Order:
    number: int
    lines: list
    total_cents: int
    address: str
    placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Checkout:

    def __init__(self):
        self._next_number = 1000

    def place(self, cart, address):
        if not cart.lines():
            raise ValueError("empty cart")
        if not address.strip():
            raise ValueError("missing address")
        order = Order(self._next_number, cart.lines(), cart.total_cents(), address)
        self._next_number += 1
        return order
'''

CONFTEST = '''\
import pytest

from storefront.catalogue import Book, Catalogue


@pytest.fixture
def catalogue():
    catalogue = Catalogue()
    catalogue.add(Book("9780141439518", "Pride and Prejudice", "Jane Austen", 899, stock=12))
    catalogue.add(Book("9780140449136", "Crime and Punishment", "Fyodor Dostoevsky", 1250, stock=3))
    catalogue.add(Book("9782070360024", "L'Étranger", "Albert Camus", 750, stock=0))
    return catalogue
'''

TEST_CATALOGUE = '''\
from storefront.catalogue import Book


def test_search_matches_every_word(catalogue):
    assert [book.title for book in catalogue.search("jane pride")] == ["Pride and Prejudice"]


def test_search_ignores_case(catalogue):
    assert len(catalogue.search("CRIME")) == 1


def test_in_stock_leaves_sold_out_books(catalogue):
    assert "L'Étranger" not in [book.title for book in catalogue.in_stock()]


def test_add_replaces_a_book_with_the_same_isbn(catalogue):
    catalogue.add(Book("9780141439518", "Pride and Prejudice", "Jane Austen", 999, stock=1))
    assert catalogue.get("9780141439518").price_cents == 999
'''

TEST_CART = '''\
import pytest

from storefront.cart import Cart


def test_total_adds_vat(catalogue):
    cart = Cart(catalogue)
    cart.add("9780141439518", 2)
    assert cart.subtotal_cents() == 1798
    assert cart.total_cents() == 1896


def test_cannot_add_more_than_the_stock(catalogue):
    with pytest.raises(ValueError):
        Cart(catalogue).add("9780140449136", 4)


def test_remove_drops_the_line(catalogue):
    cart = Cart(catalogue)
    cart.add("9780141439518")
    cart.remove("9780141439518")
    assert cart.lines() == []
'''

TEST_PRICES = '''\
from storefront.prices import format_price, vat_cents


def test_format_price_pads_cents():
    assert format_price(705) == "€7.05"


def test_vat_on_a_book():
    assert vat_cents(1000) == 55
'''

TEST_CHECKOUT = '''\
import pytest

from storefront.cart import Cart
from storefront.checkout import Checkout


def test_orders_are_numbered(catalogue):
    cart = Cart(catalogue)
    cart.add("9780141439518")
    checkout = Checkout()
    assert checkout.place(cart, "12 rue des Lilas, Lyon").number == 1000
    assert checkout.place(cart, "12 rue des Lilas, Lyon").number == 1001


def test_empty_cart_is_refused(catalogue):
    with pytest.raises(ValueError):
        Checkout().place(Cart(catalogue), "12 rue des Lilas, Lyon")
'''

# The catalogue, one CSV per shelf, is there for the diff viewer on large changes: merge request !47 reprices it
# across 25 files and about 10,000 changed lines, one of the files holding 15,000 lines. That shows the file list
# scrolling, each file's diff highlighted only as it comes into view, and how the page holds up on a large file and
# a large diff. The rows need no meaning: they are generated, so that the repository of MisteR Dashboard stays small.
SHELVES = (
    "fiction", "poetry", "history", "science", "sci-fi", "crime", "romance", "biography", "travel", "cooking",
    "art", "music", "philosophy", "religion", "kids", "comics", "classics", "economics", "politics", "health",
    "sports", "nature", "languages", "computing", "essays",
)
# Rows of each shelf file: fiction is the large file.
SHELF_ROWS = {"fiction": 15000}
DEFAULT_SHELF_ROWS = 600
RENAMED_SHELVES = {"sci-fi": "science-fiction", "kids": "children"}
# Share of the rows each change touches, slice of 250 rows by slice: dense stretches, untouched ones and lone
# changes far apart, so that the diff shows hunks close together, hunks far apart and folded lines between them.
REPRICED_SHARE = (1 / 3, 0, 0.02, 0, 0.15, 0.6, 0, 0.004)
RECOUNTED_SHARE = (0.1, 0, 0, 0.3, 0, 0.01, 0.05, 0)
SLICE_ROWS = 250
SHELF_WORDS = ("Silent", "Northern", "Garden", "Letters", "Winter", "Harbour", "Paper", "Glass", "River", "Night",
               "Orchard", "Archive", "Salt", "Bridge", "Lighthouse", "Island", "Clock", "Market", "Station", "Forest")
SHELF_AUTHORS = ("Ada Morel", "Hugo Lind", "Mina Sato", "Paul Okoro", "Rosa Marin", "Tomas Weber", "Lea Novak",
                 "Omar Benali", "Ines Duarte", "Kai Andersen", "Nora Field", "Jonas Berg")


def shelf(name, version):
    """The CSV of a shelf, generated rather than stored, with the same rows at every start. Version 0 is the
    import, 1 the spring repricing, 2 the stock count after it, each touching the rows REPRICED_SHARE and
    RECOUNTED_SHARE say."""
    generator = random.Random(name)
    rows = ["isbn,title,author,price_cents,stock"]
    for index in range(SHELF_ROWS.get(name, DEFAULT_SHELF_ROWS)):
        slice_ = index // SLICE_ROWS
        isbn = f"978{generator.randrange(10 ** 10):010d}"
        title = " ".join(generator.sample(SHELF_WORDS, 3))
        author = generator.choice(SHELF_AUTHORS)
        price = generator.randrange(500, 3500)
        stock = generator.randrange(0, 40)
        repriced = generator.random() < REPRICED_SHARE[slice_ % len(REPRICED_SHARE)]
        recounted = generator.random() < RECOUNTED_SHARE[slice_ % len(RECOUNTED_SHARE)]
        increase = generator.choice((105, 108, 110, 112))
        change = generator.choice((-5, -2, 3, 7, 12))
        if version >= 1 and repriced:
            price = price * increase // 100
        if version >= 2 and recounted:
            stock = max(0, stock + change)
        rows.append(f"{isbn},{title},{author},{price},{stock}")
    return "\n".join(rows) + "\n"


def shelves(version):
    return {f"data/catalogue/{name}.csv": shelf(name, version) for name in SHELVES}


MAIN = [
    Commit("alice", "Start the storefront: README and CI", {
        "README.md": README,
        ".gitlab-ci.yml": CI,
        "storefront/__init__.py": "",
        ".mr-dashboard/ai-actions.toml": AI_ACTIONS,
    }, before=days(62)),
    Commit("bruno", "Add the catalogue and its search", {
        "storefront/catalogue.py": CATALOGUE,
        "tests/conftest.py": CONFTEST,
        "tests/test_catalogue.py": TEST_CATALOGUE,
    }, before=days(60)),
    Commit("alice", "Add prices in cents, with the reduced VAT on books", {
        "storefront/prices.py": PRICES,
        "tests/test_prices.py": TEST_PRICES,
    }, before=days(58)),
    Commit("chloe", "Add the cart", {
        "storefront/cart.py": CART,
        "tests/test_cart.py": TEST_CART,
    }, before=days(55)),
    Commit("dmitri", "Add the checkout", {
        "storefront/checkout.py": CHECKOUT,
        "tests/test_checkout.py": TEST_CHECKOUT,
    }, before=days(52)),
    Commit("dmitri", "Import the catalogue from the old shop, one file per shelf", shelves(0), before=days(40)),
]

STOCK = '''\
"""Books running out, for the morning restocking."""

LOW_STOCK = 3


def low_stock(catalogue, threshold=LOW_STOCK):
    """Books in stock but at or below the threshold."""
    return [book for book in catalogue.in_stock() if book.stock <= threshold]
'''

TEST_STOCK = '''\
from storefront.stock import low_stock


def test_low_stock_leaves_sold_out_books(catalogue):
    assert [book.title for book in low_stock(catalogue)] == ["Crime and Punishment"]


def test_threshold_can_be_raised(catalogue):
    assert len(low_stock(catalogue, threshold=20)) == 2
'''

SHIPPING = '''\
"""Shipping costs: free above a threshold, to keep baskets growing."""

SHIPPING_CENTS = 499
FREE_SHIPPING_FROM_CENTS = 3500


def shipping_cents(subtotal_cents):
    return 0 if subtotal_cents >= FREE_SHIPPING_FROM_CENTS else SHIPPING_CENTS
'''

NOTIFICATIONS = '''\
"""Mails sent to customers."""


def confirmation_mail(order, customer_name):
    lines = "\\n".join(f"- {book.title} x{quantity}" for book, quantity in order.lines)
    return (
        f"Hello {customer_name},\\n\\n"
        f"Thank you for your order {order.number}:\\n{lines}\\n\\n"
        f"It will be shipped to {order.address}.\\n"
    )
'''

TEST_NOTIFICATIONS = '''\
from storefront.cart import Cart
from storefront.checkout import Checkout
from storefront.notifications import confirmation_mail


def test_confirmation_lists_the_books(catalogue):
    cart = Cart(catalogue)
    cart.add("9780141439518", 2)
    order = Checkout().place(cart, "12 rue des Lilas, Lyon")
    assert "- Pride and Prejudice x2" in confirmation_mail(order, "Inès")
'''

WISHLIST = '''\
"""Books a customer keeps for later."""


class Wishlist:

    def __init__(self, catalogue):
        self._catalogue = catalogue
        self._isbns = []

    def add(self, isbn):
        if self._catalogue.get(isbn) is None:
            raise KeyError(f"unknown book: {isbn}")
        if isbn not in self._isbns:
            self._isbns.append(isbn)

    def books(self):
        return [self._catalogue.get(isbn) for isbn in self._isbns]
'''

TEST_WISHLIST = '''\
from storefront.wishlist import Wishlist


def test_a_book_is_kept_once(catalogue):
    wishlist = Wishlist(catalogue)
    wishlist.add("9780141439518")
    wishlist.add("9780141439518")
    assert len(wishlist.books()) == 1
'''

GIFT_WRAP = '''\
"""Gift wrapping, offered at checkout."""

GIFT_WRAP_CENTS = 350


def gift_wrap_cents(lines, wrapped):
    """One wrapping per book when asked for, whatever the quantity of each."""
    if not wrapped:
        return 0
    return GIFT_WRAP_CENTS * len(lines)
'''

TEST_GIFT_WRAP = '''\
from storefront.cart import Cart
from storefront.checkout import Checkout


def test_gift_wrap_is_charged_per_book(catalogue):
    cart = Cart(catalogue)
    cart.add("9780141439518", 2)
    order = Checkout().place(cart, "12 rue des Lilas, Lyon", gift_wrap=True)
    assert order.total_cents == cart.total_cents() + 700
'''


def catalogue_fixture():
    """A large catalogue, generated once for the pagination tests: a big diff for the demo too."""
    firsts = ("The", "A", "Our", "Their", "No", "Every", "Last", "First")
    nouns = ("Garden", "River", "Winter", "Lighthouse", "Archive", "Orchard", "Harbour", "Library", "Mountain",
             "Station", "Island", "Letter", "Clock", "Bridge", "Forest", "Market")
    tails = ("of Glass", "at Dawn", "in the Rain", "of Salt", "Beyond", "Remembered", "of Paper", "Unseen")
    authors = ("Ada Morel", "Hugo Lind", "Mina Sato", "Paul Okoro", "Rosa Marin", "Tomas Weber", "Lea Novak",
               "Omar Benali", "Ines Duarte", "Kai Andersen")
    rows = ["isbn,title,author,price_cents,stock"]
    for index in range(640):
        title = f"{firsts[index % 8]} {nouns[index // 8 % 16]} {tails[index // 128 % 8]}"
        isbn = f"978{index * 7919 % 10 ** 10:010d}"
        rows.append(f"{isbn},{title},{authors[index * 3 % 10]},{500 + index * 37 % 2500},{index * 11 % 17}")
    return "\n".join(rows) + "\n"


# Release branches, cut from main at that time: hotfixes target them.
RELEASES = {"release/2.4": days(6)}

NEWSLETTER = """\
\"\"\"Customers who asked for the monthly newsletter.\"\"\"
import re

EMAIL = re.compile(r"[^@\\s]+@[^@\\s]+\\.[a-z]{2,}")


class Newsletter:

    def __init__(self):
        self._emails = set()

    def subscribe(self, email):
        email = email.strip().lower()
        if not EMAIL.fullmatch(email):
            raise ValueError(f"not an email address: {email}")
        self._emails.add(email)

    def unsubscribe(self, email):
        self._emails.discard(email.strip().lower())

    def recipients(self):
        return sorted(self._emails)
"""

TEST_NEWSLETTER = """\
import pytest

from storefront.newsletter import Newsletter


def test_addresses_are_kept_lower_case():
    newsletter = Newsletter()
    newsletter.subscribe("Ines.Duarte@Example.org ")
    assert newsletter.recipients() == ["ines.duarte@example.org"]


def test_a_wrong_address_is_refused():
    with pytest.raises(ValueError):
        Newsletter().subscribe("ines.duarte")
"""

LOYALTY = """\
\"\"\"Loyalty points: one point per euro spent, books only.\"\"\"


class LoyaltyAccount:

    def __init__(self):
        self.points = 0

    def earn(self, order):
        self.points += order.total_cents // 100
"""

DARK_THEME = """\
/* The shop pages in dark colours, following the reader's system setting. */
@media (prefers-color-scheme: dark) {
  :root {
    --background: #16181d;
    --text: #e6e6e6;
    --accent: #f2a65a;
    --muted: #8a8f98;
  }
  .book-card { background: #1f2229; border-color: #2c3038; }
  .price { color: var(--accent); }
}
"""

ONIX = """\
\"\"\"The catalogue as an ONIX 3.0 feed, the format distributors read.\"\"\"
from xml.sax.saxutils import escape


def onix(books):
    products = "".join(
        f"<Product><RecordReference>{book.isbn}</RecordReference>"
        f"<ProductIdentifier><ProductIDType>15</ProductIDType><IDValue>{book.isbn}</IDValue></ProductIdentifier>"
        f"<DescriptiveDetail><TitleDetail><TitleElement><TitleText>{escape(book.title)}</TitleText>"
        f"</TitleElement></TitleDetail></DescriptiveDetail></Product>"
        for book in books
    )
    return f'<ONIXMessage release="3.0">{products}</ONIXMessage>'
"""

BRANCHES = {
    35: Branch("fol-101-stock-alerts", days(30), [
        Push(days(29), [
            Commit("dmitri", "Add low stock alerts", {"storefront/stock.py": STOCK}, before=2.5),
            Commit("dmitri", "Test low stock alerts", {"tests/test_stock.py": TEST_STOCK}, before=0.5),
        ]),
        Push(days(26), [
            Commit("dmitri", "Sort low stock alerts, scarcest first", edits=[
                ("storefront/stock.py", '    """Books in stock but at or below the threshold."""\n    return [book for book in catalogue.in_stock() if book.stock <= threshold]\n',
                 '    """Books in stock but at or below the threshold, the scarcest first."""\n    books = [book for book in catalogue.in_stock() if book.stock <= threshold]\n    return sorted(books, key=lambda book: book.stock)\n'),
            ]),
        ]),
    ], merged_at=days(25), merged_by="alice"),
    36: Branch("fol-103-free-shipping", days(21), [
        Push(days(20), [
            Commit("chloe", "Add shipping costs, free from €35", {"storefront/shipping.py": SHIPPING}, before=1),
            Commit("chloe", "Charge shipping in the cart total", edits=[
                ("storefront/cart.py", "from .prices import vat_cents\n", "from .prices import vat_cents\nfrom .shipping import shipping_cents\n"),
                ("storefront/cart.py", "        return subtotal + vat_cents(subtotal)\n",
                 "        return subtotal + vat_cents(subtotal) + shipping_cents(subtotal)\n"),
                ("tests/test_cart.py", "    assert cart.total_cents() == 1896\n", "    assert cart.total_cents() == 2395\n"),
            ]),
        ]),
    ], merged_at=days(18), merged_by="bruno"),
    37: Branch("fol-104-vat-rounding", days(14), [
        Push(days(13), [
            Commit("bruno", "Round VAT to the nearest cent instead of truncating it", edits=[
                ("storefront/prices.py", "    return int(amount_cents * VAT_RATE)\n", "    return round(amount_cents * VAT_RATE)\n"),
                ("tests/test_cart.py", "    assert cart.total_cents() == 2395\n", "    assert cart.total_cents() == 2396\n"),
            ], before=3),
            Commit("bruno", "Format refunds with a minus sign", edits=[
                ("storefront/prices.py", '    return f"€{amount_cents // 100}.{amount_cents % 100:02d}"\n',
                 '    sign = "-" if amount_cents < 0 else ""\n    cents = abs(amount_cents)\n    return f"{sign}€{cents // 100}.{cents % 100:02d}"\n'),
                ("tests/test_prices.py", "def test_vat_on_a_book():\n",
                 'def test_refunds_are_negative():\n    assert format_price(-705) == "-€7.05"\n\n\ndef test_vat_on_a_book():\n'),
            ]),
        ]),
    ], merged_at=days(10), merged_by="alice"),
    46: Branch("fol-110-price-per-locale", days(12.2), [
        Push(days(12), [
            Commit("bruno", "Format prices for the customer's locale", edits=[
                ("storefront/prices.py", 'def format_price(amount_cents):\n    return f"€{amount_cents // 100}.{amount_cents % 100:02d}"\n',
                 'SEPARATORS = {"en": ".", "fr": ",", "de": ","}\n\n\ndef format_price(amount_cents, locale="en"):\n    separator = SEPARATORS.get(locale, ".")\n    euros, cents = divmod(amount_cents, 100)\n    if locale == "en":\n        return f"€{euros}{separator}{cents:02d}"\n    return f"{euros}{separator}{cents:02d} €"\n'),
            ], before=1),
            Commit("bruno", "Test prices in French and German", edits=[
                ("tests/test_prices.py", "def test_vat_on_a_book():\n",
                 'def test_format_price_in_french():\n    assert format_price(705, "fr") == "7,05 €"\n\n\ndef test_format_price_in_german():\n    assert format_price(705, "de") == "7,05 €"\n\n\ndef test_vat_on_a_book():\n'),
            ]),
        ]),
        Push(days(11), [
            Commit("bruno", "Fall back to English for an unknown locale", edits=[
                ("storefront/prices.py", '    if locale == "en":\n', '    if locale not in SEPARATORS or locale == "en":\n'),
            ]),
        ]),
    ]),
    38: Branch("fol-105-author-pages", days(9), [
        Push(days(8), [
            Commit("farid", "List an author's books, newest additions last", edits=[
                ("storefront/catalogue.py", "    def in_stock(self):\n",
                 '    def by_author(self, author):\n        return [book for book in self._books.values() if book.author == author]\n\n    def in_stock(self):\n'),
                ("tests/test_catalogue.py", "def test_in_stock_leaves_sold_out_books(catalogue):\n",
                 'def test_by_author(catalogue):\n    assert [book.title for book in catalogue.by_author("Albert Camus")] == ["L\'Étranger"]\n\n\ndef test_in_stock_leaves_sold_out_books(catalogue):\n'),
            ]),
        ]),
    ], merged_at=days(7), merged_by="alice"),
    43: Branch("fol-118-paginate-catalogue", days(5.3), [
        Push(days(5), [
            Commit("dmitri", "Paginate the catalogue", edits=[
                ("storefront/catalogue.py", "    def in_stock(self):\n",
                 '    def page(self, number, size=24):\n        """Books of the given page, from 1, sorted by title."""\n        books = sorted(self._books.values(), key=lambda book: book.title)\n        start = (number - 1) * size\n        return books[start:start + size]\n\n    def in_stock(self):\n'),
            ], before=4),
            Commit("dmitri", "Add a large catalogue to test pagination on", {"tests/fixtures/catalogue.csv": catalogue_fixture()}, before=1),
        ]),
        Push(days(4), [
            Commit("dmitri", "Count the pages", edits=[
                ("storefront/catalogue.py", "    def in_stock(self):\n",
                 "    def page_count(self, size=24):\n        return max(1, -(-len(self._books) // size))\n\n    def in_stock(self):\n"),
            ]),
        ]),
        Push(0.15, [
            Commit("dmitri", "Keep the page size between 12 and 96", edits=[
                ("storefront/catalogue.py", '        """Books of the given page, from 1, sorted by title."""\n',
                 '        """Books of the given page, from 1, sorted by title."""\n        size = min(max(size, 12), 96)\n'),
            ]),
        ]),
    ]),
    39: Branch("fol-107-accent-insensitive-search", days(4.5), [
        Push(days(4), [
            Commit("alice", "Search without accents: etranger finds L'Étranger", edits=[
                ("storefront/catalogue.py", '"""The books on sale, and how customers find them."""\nfrom dataclasses import dataclass\n',
                 '"""The books on sale, and how customers find them."""\nimport unicodedata\nfrom dataclasses import dataclass\n'),
                ("storefront/catalogue.py", '        terms = words.lower().split()\n        return [\n            book for book in self._books.values()\n            if all(term in f"{book.title} {book.author}".lower() for term in terms)\n        ]\n',
                 '        terms = folded(words).split()\n        return [\n            book for book in self._books.values()\n            if all(term in folded(f"{book.title} {book.author}") for term in terms)\n        ]\n'),
                ("storefront/catalogue.py", "    def in_stock(self):\n        return [book for book in self._books.values() if book.stock > 0]\n",
                 '    def in_stock(self):\n        return [book for book in self._books.values() if book.stock > 0]\n\n\ndef folded(text):\n    """Lower case, without accents."""\n    decomposed = unicodedata.normalize("NFD", text.lower())\n    return "".join(char for char in decomposed if not unicodedata.combining(char))\n'),
                ("tests/test_catalogue.py", "def test_in_stock_leaves_sold_out_books(catalogue):\n",
                 'def test_search_ignores_accents(catalogue):\n    assert len(catalogue.search("etranger")) == 1\n\n\ndef test_in_stock_leaves_sold_out_books(catalogue):\n'),
            ]),
        ]),
    ], merged_at=days(3), merged_by="bruno"),
    40: Branch("fol-108-order-confirmation", days(3.5), [
        Push(days(3), [
            Commit("dmitri", "Write the order confirmation mail", {"storefront/notifications.py": NOTIFICATIONS}, before=2),
            Commit("dmitri", "Test the order confirmation mail", {"tests/test_notifications.py": TEST_NOTIFICATIONS}),
        ]),
    ], merged_at=days(1.2), merged_by="alice"),
    44: Branch("fol-109-rename-cart-to-basket", days(4.2), [
        Push(days(4), [
            Commit("farid", "Rename the cart module to basket", moves={"storefront/cart.py": "storefront/basket.py"}, edits=[
                ("storefront/checkout.py", '"""Turning a cart into an order."""\n', '"""Turning a basket into an order."""\n'),
            ], before=3),
            Commit("farid", "Rename Cart to Basket", edits=[
                ("storefront/basket.py", '"""A customer\'s cart, before checkout."""\n', '"""A customer\'s basket, before checkout."""\n'),
                ("storefront/basket.py", "class Cart:\n", "class Basket:\n"),
                ("storefront/checkout.py", "    def place(self, cart, address):\n        if not cart.lines():\n            raise ValueError(\"empty cart\")\n",
                 "    def place(self, basket, address):\n        if not basket.lines():\n            raise ValueError(\"empty basket\")\n"),
                ("storefront/checkout.py", "        order = Order(self._next_number, cart.lines(), cart.total_cents(), address)\n",
                 "        order = Order(self._next_number, basket.lines(), basket.total_cents(), address)\n"),
            ], before=1.5),
            Commit("farid", "Rename the cart tests", moves={"tests/test_cart.py": "tests/test_basket.py"}, edits=[
                ("tests/test_basket.py", "from storefront.cart import Cart\n", "from storefront.basket import Basket\n"),
                ("tests/test_basket.py", "def test_total_adds_vat(catalogue):\n    cart = Cart(catalogue)\n    cart.add(\"9780141439518\", 2)\n    assert cart.subtotal_cents() == 1798\n    assert cart.total_cents() == 2396\n",
                 "def test_total_adds_vat(catalogue):\n    basket = Basket(catalogue)\n    basket.add(\"9780141439518\", 2)\n    assert basket.subtotal_cents() == 1798\n    assert basket.total_cents() == 2396\n"),
                ("tests/test_basket.py", "        Cart(catalogue).add(\"9780140449136\", 4)\n", "        Basket(catalogue).add(\"9780140449136\", 4)\n"),
                ("tests/test_basket.py", "    cart = Cart(catalogue)\n    cart.add(\"9780141439518\")\n    cart.remove(\"9780141439518\")\n    assert cart.lines() == []\n",
                 "    basket = Basket(catalogue)\n    basket.add(\"9780141439518\")\n    basket.remove(\"9780141439518\")\n    assert basket.lines() == []\n"),
                ("tests/test_checkout.py", "from storefront.cart import Cart\n", "from storefront.basket import Basket\n"),
                ("tests/test_checkout.py", "    cart = Cart(catalogue)\n    cart.add(\"9780141439518\")\n    checkout = Checkout()\n    assert checkout.place(cart, \"12 rue des Lilas, Lyon\").number == 1000\n    assert checkout.place(cart, \"12 rue des Lilas, Lyon\").number == 1001\n",
                 "    basket = Basket(catalogue)\n    basket.add(\"9780141439518\")\n    checkout = Checkout()\n    assert checkout.place(basket, \"12 rue des Lilas, Lyon\").number == 1000\n    assert checkout.place(basket, \"12 rue des Lilas, Lyon\").number == 1001\n"),
                ("tests/test_checkout.py", "        Checkout().place(Cart(catalogue), \"12 rue des Lilas, Lyon\")\n", "        Checkout().place(Basket(catalogue), \"12 rue des Lilas, Lyon\")\n"),
            ]),
        ]),
        Push(days(2.6), [
            Commit("farid", "Keep Cart as a deprecated alias for the mobile app", edits=[
                ("storefront/basket.py", "    def total_cents(self):\n        subtotal = self.subtotal_cents()\n        return subtotal + vat_cents(subtotal) + shipping_cents(subtotal)\n",
                 "    def total_cents(self):\n        subtotal = self.subtotal_cents()\n        return subtotal + vat_cents(subtotal) + shipping_cents(subtotal)\n\n\n# The mobile app still imports Cart: to be removed once its version 3.2 is out.\nCart = Basket\n"),
            ], before=1),
            Commit("farid", "Name the empty basket error as the shop says it", edits=[
                ("storefront/checkout.py", "            raise ValueError(\"empty basket\")\n", "            raise ValueError(\"your basket is empty\")\n"),
            ]),
        ]),
        Push(days(1), [
            Commit("farid", "Test the deprecated Cart alias", edits=[
                ("tests/test_basket.py", "from storefront.basket import Basket\n", "from storefront.basket import Basket, Cart\n"),
                ("tests/test_basket.py", "def test_cannot_add_more_than_the_stock(catalogue):\n",
                 "def test_cart_is_still_importable(catalogue):\n    assert Cart is Basket\n\n\ndef test_cannot_add_more_than_the_stock(catalogue):\n"),
            ]),
        ]),
    ]),
    42: Branch("fol-115-gift-wrapping", days(2.2), [
        Push(days(2), [
            Commit("chloe", "Price gift wrapping per book", {"storefront/gift_wrap.py": GIFT_WRAP}, before=2),
            Commit("chloe", "Offer gift wrapping at checkout", edits=[
                ("storefront/checkout.py", "from datetime import datetime, timezone\n", "from datetime import datetime, timezone\n\nfrom .gift_wrap import gift_wrap_cents\n"),
                ("storefront/checkout.py", "    def place(self, cart, address):\n", "    def place(self, cart, address, gift_wrap=False):\n"),
                ("storefront/checkout.py", "        order = Order(self._next_number, cart.lines(), cart.total_cents(), address)\n",
                 "        total = cart.total_cents() + gift_wrap_cents(cart.lines(), gift_wrap)\n        order = Order(self._next_number, cart.lines(), total, address)\n"),
            ]),
        ]),
        Push(6, [
            Commit("chloe", "Test gift wrapping at checkout", {"tests/test_gift_wrap.py": TEST_GIFT_WRAP}),
        ]),
    ]),
    41: Branch("fol-112-search-by-isbn", 22, [
        Push(20, [
            Commit("bruno", "Find a book by its ISBN in the search box", edits=[
                ("storefront/catalogue.py", '        """Books whose title or author contains every word, case-insensitive."""\n',
                 '        """The book of an ISBN typed with or without hyphens, else the books whose title or author contains every\n        word, case-insensitive."""\n        isbn = words.replace("-", "").strip()\n        if isbn.isdigit() and len(isbn) == 13:\n            book = self.get(isbn)\n            return [book] if book else []\n'),
            ], before=1),
            Commit("bruno", "Test the search by ISBN", edits=[
                ("tests/test_catalogue.py", "def test_search_ignores_case(catalogue):\n",
                 'def test_search_by_isbn_with_hyphens(catalogue):\n    assert [book.title for book in catalogue.search("978-0-14-044913-6")] == ["Crime and Punishment"]\n\n\ndef test_search_ignores_case(catalogue):\n'),
            ]),
        ]),
        Push(3, [
            Commit("bruno", "Accept ISBN-10 in the search box", edits=[
                ("storefront/catalogue.py", "        if isbn.isdigit() and len(isbn) == 13:\n",
                 "        if len(isbn) == 10 and isbn[:9].isdigit():\n            isbn = isbn13(isbn)\n        if isbn.isdigit() and len(isbn) == 13:\n"),
                ("storefront/catalogue.py", "\n\ndef folded(text):\n",
                 '\n\ndef isbn13(isbn10):\n    """The ISBN-13 of an ISBN-10: prefix 978, then a new check digit."""\n    digits = "978" + isbn10[:9]\n    total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(digits))\n    return digits + str(-total % 10)\n\n\ndef folded(text):\n'),
            ]),
        ]),
    ]),
    45: Branch("fol-121-wishlist", 30, [
        Push(26, [
            Commit("alice", "Keep books for later in a wishlist", {"storefront/wishlist.py": WISHLIST, "tests/test_wishlist.py": TEST_WISHLIST}),
        ]),
        Push(2, [
            Commit("alice", "Leave sold-out books in the wishlist, flagged", edits=[
                ("storefront/wishlist.py", "    def books(self):\n        return [self._catalogue.get(isbn) for isbn in self._isbns]\n",
                 '    def books(self):\n        return [self._catalogue.get(isbn) for isbn in self._isbns]\n\n    def sold_out(self):\n        """Books kept but out of stock: the shop mails the customer when they come back."""\n        return [book for book in self.books() if book.stock == 0]\n'),
            ]),
        ]),
    ]),
    47: Branch("fol-126-spring-repricing", days(1.6), [
        Push(days(1.5), [
            Commit("chloe", "Reprice the catalogue for spring", shelves(1), before=0.5),
        ]),
        Push(9, [
            Commit("chloe", "Count the stock after the repricing", shelves(2), before=0.3),
            Commit("chloe", "Name the shelves as the shop signs do",
                   moves={f"data/catalogue/{old}.csv": f"data/catalogue/{new}.csv" for old, new in RENAMED_SHELVES.items()}),
        ]),
    ]),
    34: Branch("fol-099-readme-typos", days(4), [
        Push(days(3.8), [
            Commit("grace", "Fix the typos of the README", edits=[
                ("README.md", "its catalogue, its cart and the chekout, wich turns", "its catalogue, its cart and the checkout, which turns"),
            ]),
        ]),
    ], merged_at=days(2.5), merged_by="alice", squash=True),
    48: Branch("fol-127-ebook-vat", days(2), [
        Push(days(1.8), [
            Commit("bruno", "Charge e-books the full VAT rate", edits=[
                ("storefront/prices.py", "VAT_RATE = 0.055  # reduced rate on books\n",
                 "VAT_RATE = 0.055  # reduced rate on printed books\nEBOOK_VAT_RATE = 0.20\n"),
                ("storefront/prices.py", "def vat_cents(amount_cents):\n    return round(amount_cents * VAT_RATE)\n",
                 "def vat_cents(amount_cents, ebook=False):\n    return round(amount_cents * (EBOOK_VAT_RATE if ebook else VAT_RATE))\n"),
            ]),
        ]),
    ], target="release/2.4"),
    49: Branch("fol-128-newsletter", days(3), [
        Push(days(2.8), [
            Commit("farid", "Keep the newsletter subscribers", {"storefront/newsletter.py": NEWSLETTER}, before=1),
            Commit("farid", "Test the newsletter subscriptions", {"tests/test_newsletter.py": TEST_NEWSLETTER}),
        ]),
        Push(7, [
            Commit("farid", "Refuse the addresses without a domain", edits=[
                ("storefront/newsletter.py", r'EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}")', r'EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)*\.[a-z]{2,}")'),
            ]),
        ]),
    ]),
    50: Branch("fol-130-earn-loyalty-points", days(2.5), [
        Push(days(2.3), [
            Commit("dmitri", "Earn loyalty points on every order", {"storefront/loyalty.py": LOYALTY}),
        ]),
    ]),
    51: Branch("fol-131-spend-loyalty-points", days(1.9), [
        Push(days(1.7), [
            Commit("farid", "Spend loyalty points at checkout, 100 points for €5", edits=[
                ("storefront/loyalty.py", "    def earn(self, order):\n        self.points += order.total_cents // 100\n",
                 "    def earn(self, order):\n        self.points += order.total_cents // 100\n\n    def spend(self, points):\n        \"\"\"The discount, in cents, for points spent by hundreds.\"\"\"\n        if points % 100 or points > self.points:\n            raise ValueError(f\"cannot spend {points} points\")\n        self.points -= points\n        return points // 100 * 500\n"),
            ]),
        ]),
    ], parent=50),
    52: Branch("fol-132-dark-theme", 30, [
        Push(28, [
            Commit("chloe", "Draft a dark theme for the shop pages", {"static/theme-dark.css": DARK_THEME}),
        ]),
    ]),
    53: Branch("fol-133-pin-test-tools", 12, [
        Push(11, [
            Commit("alice", "Pin the test tools, so that the CI and our machines agree", {"requirements-dev.txt": "pytest==8.4.1\nruff==0.12.7\n"}, edits=[
                ("README.md", "    python -m pytest\n", "    pip install -r requirements-dev.txt\n    python -m pytest\n"),
            ]),
        ]),
    ]),
    54: Branch("fol-098-onix-export", days(41), [
        Push(days(40), [
            Commit("dmitri", "Export the catalogue as ONIX for distributors", {"storefront/onix.py": ONIX}),
        ]),
        Push(days(35), [
            Commit("dmitri", "Escape the titles in the ONIX feed", edits=[
                ("storefront/onix.py", '"""The catalogue as an ONIX 3.0 feed, the format distributors read."""\n',
                 '"""The catalogue as an ONIX 3.0 feed, the format distributors read: titles escaped, since they hold\nampersands ("Pride & Prejudice")."""\n'),
            ]),
        ]),
    ]),
}


# Commits pushed while the demo runs (see dataset.ACTIVITY), by merge request: built with the rest, dated at the
# start, and published when the activity gets to them.
LATER = {
    42: [
        Commit("chloe", "Wrap each copy, not each line", edits=[
            ("storefront/gift_wrap.py", '    """One wrapping per book when asked for, whatever the quantity of each."""\n',
             '    """One wrapping per copy when asked for: copies are often offered to different people."""\n'),
            ("storefront/gift_wrap.py", "    return GIFT_WRAP_CENTS * len(lines)\n",
             "    return GIFT_WRAP_CENTS * sum(quantity for _, quantity in lines)\n"),
        ]),
    ],
}
