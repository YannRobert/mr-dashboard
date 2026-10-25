"""The fictional team and merge requests of the demo, around the git history of history.py.

Everything here is invented: Folio is an imaginary online bookshop (the same as in Camelopard's demo), and its
team does not exist. Times are hours before the demo starts; a review comment points at a line of the
repository by a piece of its text, found at the commit the comment was made on.
"""
from dataclasses import dataclass, field

from . import history
from .history import days

PROJECT_ID = 12
PROJECT_PATH = "folio/storefront"
PROJECT_NAME = "Storefront"
EMAIL_DOMAIN = "folio.example"
PIPELINE_BRANCH = "main"

# The person looking at the dashboard (GET /user).
ME = "alice"

PEOPLE = {
    "alice": "Alice Bernard",
    "bruno": "Bruno Costa",
    "chloe": "Chloé Dubois",
    "dmitri": "Dmitri Ivanov",
    "emma": "Emma Schultz",
    "farid": "Farid Haddad",
    "grace": "Grace Okafor",
    # The project access token the mutation testing job posts its report with: the dashboard leaves its notes
    # out of the last comments and of the review chart.
    "project_12_bot_mutation": "Mutation report",
}

SONAR_PROJECT = "folio-storefront"
SONAR_JOB = "sonar"
PIT_JOB = "mutation_test"
PIT_MARKER = "<!-- mutation-report -->"
BOT = "project_12_bot_mutation"

# Jobs of a merge request pipeline, in stage order: (name, stage, minutes).
JOBS = (
    ("lint", "build", 0.7),
    ("unit_tests", "test", 2.5),
    ("sonar", "quality", 1.8),
    ("mutation_test", "quality", 4.2),
)


@dataclass
class Thread:
    """A review comment on a line (path and a piece of the line's text) or, without a path, on the merge request.
    A comment on several lines covers `lines` lines ending at that one; on the "old" side, it sits on a line the
    merge request removes."""
    author: str
    at: float
    body: str
    path: str = None
    line: str = None
    replies: list = field(default_factory=list)
    resolved: bool = False
    lines: int = 1
    side: str = "new"


@dataclass
class Pipeline:
    """The head pipeline: every job succeeds, except the failed one, which skips the jobs after it; a running
    pipeline started that many hours before the demo."""
    status: str = "success"
    failed_job: str = None
    running_since: float = None


@dataclass
class Sonar:
    gate: str = "OK"
    coverage: float = 100.0
    issues: int = 0
    # Sonar lost the analysis although the job ran: the dashboard says "not found".
    missing: bool = False


@dataclass
class Mutation:
    mutants: int
    killed: int
    survived: int = 0
    no_coverage: int = 0
    errors: int = 0
    # The job posted a report the dashboard cannot read (no table).
    unreadable: bool = False


@dataclass
class MergeRequest:
    title: str
    author: str
    reviewers: tuple = ()
    labels: tuple = ()
    draft: bool = False
    # Who approved, and when.
    approvals: tuple = ()
    # Reviewer: GitLab's review state (REVIEWED, REQUESTED_CHANGES); the others are UNREVIEWED or APPROVED.
    review_states: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)
    pipeline: Pipeline = field(default_factory=Pipeline)
    sonar: Sonar = field(default_factory=Sonar)
    mutation: Mutation = None
    # Assignees, when not only the author.
    assignees: tuple = None
    # Merge requests that must be merged before this one (GitLab's "blocked by").
    blocked_by: tuple = ()


# Review comments of several paragraphs, lists, quotes and code blocks, as reviews really are: the diff and comments
# pages show them as GitLab renders them.
STOCK_ORDER = """\
Could the list be sorted by stock, scarcest first?

The restocking is ordered every morning before opening, and whoever orders reads the list from the top. In the
current order, a book with one copy left can sit below ten books with three copies.

```python
return sorted(books, key=lambda book: book.stock)
```"""

HALF_TO_EVEN = """\
Python's `round()` rounds half to even, not half up:

```python
>>> round(0.5), round(1.5), round(2.5)
(0, 2, 2)
```

So on a €3.00 item, 16.5 cents of VAT become 16, not 17. Is that what accounting expects? If not,
`decimal.Decimal` with `ROUND_HALF_UP` would do it."""

HALF_TO_EVEN_ANSWER = """\
I checked with accounting: their software rounds half to even too, so the totals match theirs.

Keeping `round()`, with a comment if you think it helps."""

WRAPPING_PER_COPY = """\
Should a wrapped order of two copies of the same book get two wrappings?

Right now `gift_wrap_cents` counts the lines of the cart, not the copies:

- 2 × *Pride and Prejudice*: one line, so one wrapping, €3.50
- 1 × *Pride and Prejudice* and 1 × *L'Étranger*: two lines, two wrappings, €7.00

If each copy is wrapped on its own, the first case should cost €7.00 too."""

WRAPPING_TEST_FAILS = """\
The new test fails on the pipeline, as expected: `gift_wrap_cents` still multiplies by `len(lines)`.
Counting the copies should fix it:

```python
return GIFT_WRAP_CENTS * sum(quantity for _, quantity in lines)
```"""

MOBILE_ALIAS = """\
The mobile app still imports `storefront.cart.Cart`, and its version 3.2, which moves to `Basket`, is only planned
for next sprint.

Could we keep an alias until then? Something like:

```python
# The mobile app still imports Cart: to be removed once its version 3.2 is out.
Cart = Basket
```

That way this merge request can go in now, without waiting for the mobile team."""

MOBILE_ALIAS_ANSWER = """\
Added at the end of `basket.py`, with the comment, so that we remember to remove it.

I also asked the mobile team to tell us when 3.2 is out."""

EMPTY_BASKET = """\
This message reaches customers as is, on the checkout page:

> empty basket

It reads like an error code. "your basket is empty" is what the shop says everywhere else, in the header and in
the mails.

```suggestion:-0+0
            raise ValueError("your basket is empty")
```"""

ALIAS_TEST = """\
Worth a test that the alias still imports, since nothing else covers it: if someone removes `Cart = Basket` by
mistake, only the mobile app would notice, in production."""

MOBILE_TEAM = (
    "Looks good to me once Alice's last thread is closed. I talked with the mobile team today: they know about the "
    "alias, and they will tell us when version 3.2 is in the stores, so that we remove it in a follow-up merge request "
    "rather than keep it forever. I also checked that nothing else in the storefront still imports `storefront.cart`: "
    "`git grep storefront.cart` only finds the comment above the alias."
)

GERMAN_PRICES = """\
In German the euro sign also goes after the amount, with a non-breaking space between them, as in French:

- `en`: €7.05
- `fr`: 7,05 €
- `de`: 7,05 €

With a plain space, a narrow screen can break the line between the amount and the sign. `\\u00a0` avoids it."""

REBASE = """\
@bruno this conflicts with FOL-104, merged a few hours ago, which changed `format_price` to show refunds with a minus
sign. Please rebase on main and keep both behaviours:

1. the minus sign for refunds
2. the separator and the position of the sign per locale

A test for a French refund (`-7,05 €`) would cover the two together."""

PREVIOUS_PRICE = """\
Could the files keep the previous price in a column, so that the shop can show the discount?

For the spring campaign, marketing wants the product pages to show the old price struck through next to the new
one. Without the column, we would have to dig it out of the git history when the campaign is published."""


# Answers quoting the comment they answer, as GitLab's "Quote reply" writes them.
WRAPPING_ANSWER = """\
> If each copy is wrapped on its own, the first case should cost €7.00 too.

Yes: Grace says customers often offer two copies to two different people, and the shop wraps each copy anyway.
I'll write the test first, then fix the count."""

GERMAN_PRICES_ANSWER = """\
> With a plain space, a narrow screen can break the line between the amount and the sign.

Good catch, I had only checked on a desktop. I'll use a no-break space for French and German."""

TEST_NAME_ANSWER = """\
> This test checks shipping too now: should its name say so?

The total includes shipping by definition, as on the checkout page, so I'd keep the name. If shipping ever gets
its own line on the receipt, it will deserve its own test anyway."""


PAGE_SORT = """\
These lines sort the whole catalogue on every page view: with the 15,000 books of the fiction shelf alone, that is
a sort of the whole list each time someone clicks "next".

Could the catalogue keep its books sorted once, when a book is added? Then a page is only a slice:

```python
def page(self, number, size=24):
    size = min(max(size, 12), 96)
    start = (number - 1) * size
    return self._sorted[start:start + size]
```"""

PAGE_SORT_ANSWER = """\
> Could the catalogue keep its books sorted once, when a book is added?

Yes, but `add` then costs a `bisect.insort` instead of a dict write, and the import of the old shop adds the
books one by one. I'll measure both on the full catalogue before choosing."""

OLD_SIGNATURE = "Removing this signature is fine: `gift_wrap` defaults to `False`, so every `place(cart, address)` call keeps working. :+1:"

WISHLIST_CHECKLIST = """\
Before I mark it ready:

- [x] keep the books for later
- [x] flag the sold-out ones
- [ ] mail the customer when a sold-out book is back
- [ ] cap a wishlist at 100 books"""

STAGING_TEST = """\
Tested on staging with the mobile app 3.1: the alias works, and the checkout now says it the shop's way.

![The empty basket on staging](/uploads/4c2a91e0f5d8b37a6e1c09d2b8f47a13/empty-basket.svg)

:white_check_mark: ready for me once the last thread is closed."""

HOTFIX = """\
The 2.4 release goes to the shops on Thursday: this has to be in it, @alice, since e-books sold at the reduced
rate since FOL-104 would be a tax adjustment for us.

I'll port it to main right after, the code there is the same."""

ONIX_PING = "@dmitri is this still needed? The distributor's deadline was last month, and the branch is 40 days behind main."

# Screenshots attached to comments, served under the project's uploads.
UPLOADS = {
    "empty-basket.svg": """\
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="300" viewBox="0 0 640 300" font-family="sans-serif">
  <rect width="640" height="300" fill="#faf7f2"/>
  <rect width="640" height="48" fill="#2f4858"/>
  <text x="24" y="31" fill="#fff" font-size="20" font-weight="bold">Folio</text>
  <text x="540" y="31" fill="#fff" font-size="15">Basket (0)</text>
  <text x="320" y="150" text-anchor="middle" fill="#2f4858" font-size="26">Your basket is empty</text>
  <rect x="235" y="185" width="170" height="44" rx="6" fill="#f2a65a"/>
  <text x="320" y="213" text-anchor="middle" fill="#fff" font-size="16">Browse the shelves</text>
</svg>
""",
}


MERGE_REQUESTS = {
    35: MergeRequest(
        "FOL-101: Low stock alerts for the morning restocking", "dmitri", ("alice",), ("feature",),
        approvals=(("alice", days(25.2)),),
        threads=[Thread("alice", days(27), STOCK_ORDER,
                        "storefront/stock.py", "return [book", replies=[("dmitri", days(26.5), "Makes sense, I'll sort them in the next push.")], resolved=True)],
        sonar=Sonar(coverage=100.0), mutation=Mutation(8, 8),
    ),
    36: MergeRequest(
        "FOL-103: Free shipping from €35", "chloe", ("bruno",), ("feature", "checkout"),
        approvals=(("bruno", days(18.3)),), sonar=Sonar(coverage=92.0), mutation=Mutation(6, 6),
    ),
    37: MergeRequest(
        "FOL-104: Round VAT to the cent, and show refunds", "bruno", ("alice", "dmitri"), ("bug",),
        approvals=(("alice", days(10.4)), ("dmitri", days(10.2))),
        threads=[Thread("dmitri", days(12), HALF_TO_EVEN,
                        "storefront/prices.py", "return round(", replies=[("bruno", days(11.8), HALF_TO_EVEN_ANSWER)], resolved=True)],
        sonar=Sonar(coverage=100.0), mutation=Mutation(9, 9),
    ),
    38: MergeRequest(
        "FOL-105: Author pages", "farid", ("alice",), ("feature",),
        approvals=(("alice", days(7.1)),), sonar=Sonar(coverage=100.0), mutation=Mutation(4, 4),
    ),
    39: MergeRequest(
        "FOL-107: Search without accents", "alice", ("bruno",), ("feature", "search"),
        approvals=(("bruno", days(3.1)),), sonar=Sonar(coverage=100.0), mutation=Mutation(7, 7),
    ),
    40: MergeRequest(
        "FOL-108: Order confirmation mail", "dmitri", ("alice", "chloe"), ("feature", "checkout"),
        approvals=(("alice", days(1.3)), ("chloe", days(1.25))), sonar=Sonar(coverage=95.0), mutation=Mutation(5, 5),
    ),
    41: MergeRequest(
        "FOL-112: Search by ISBN", "bruno", ("alice",), ("feature", "search"),
        sonar=Sonar(coverage=100.0), mutation=Mutation(14, 14),
    ),
    42: MergeRequest(
        "FOL-115: Gift wrapping at checkout", "chloe", ("alice", "dmitri"), ("feature", "checkout"),
        review_states={"dmitri": "REVIEWED"},
        threads=[
            Thread("dmitri", days(1.5), WRAPPING_PER_COPY,
                   "storefront/gift_wrap.py", "return GIFT_WRAP_CENTS", replies=[
                ("chloe", days(1.4), WRAPPING_ANSWER),
                ("dmitri", 5, WRAPPING_TEST_FAILS),
            ]),
            Thread("dmitri", days(1.6), "Can you add a test for a wrapped order? Nothing covers `gift_wrap_cents` yet, and checkout is where a wrong total costs the most.",
                   "storefront/checkout.py", "from .gift_wrap import", replies=[("chloe", 5.5, "Added in the last push, see `tests/test_gift_wrap.py`.")], resolved=True),
            Thread("alice", days(1.2), OLD_SIGNATURE, "storefront/checkout.py", "def place(self, cart, address):", side="old", resolved=True),
        ],
        pipeline=Pipeline("failed", "unit_tests"), mutation=Mutation(8, 7, survived=1),
    ),
    43: MergeRequest(
        "FOL-118: Paginate the catalogue", "dmitri", ("bruno",), ("feature",),
        threads=[
            Thread("bruno", days(3.8), PAGE_SORT, "storefront/catalogue.py", "return books[start:start + size]", lines=4,
                   replies=[("dmitri", days(3.6), PAGE_SORT_ANSWER)]),
        ],
        pipeline=Pipeline("running", running_since=0.12),
        sonar=Sonar("ERROR", coverage=72.0, issues=2), mutation=Mutation(11, 9, no_coverage=2),
    ),
    44: MergeRequest(
        "FOL-109: Rename the cart to basket, as the shop calls it", "farid", ("alice", "bruno"), ("refactoring",),
        review_states={"alice": "REVIEWED"},
        threads=[
            Thread("alice", days(3.4), MOBILE_ALIAS,
                   "storefront/basket.py", "class Basket:", replies=[("farid", days(2.55), MOBILE_ALIAS_ANSWER)], resolved=True),
            Thread("alice", days(3.3), EMPTY_BASKET,
                   "storefront/checkout.py", 'raise ValueError("empty basket")', replies=[("farid", days(2.55), "Done.")], resolved=True),
            Thread("alice", days(3.2), "This test checks shipping too now: should its name say so?",
                   "tests/test_basket.py", "def test_total_adds_vat", replies=[("farid", days(2.9), TEST_NAME_ANSWER)],
                   resolved=True),
            Thread("alice", days(2), ALIAS_TEST,
                   "storefront/basket.py", "Cart = Basket", replies=[("farid", days(0.9), "Test added: `test_cart_is_still_importable`.")]),
            Thread("bruno", 5, MOBILE_TEAM),
            Thread("grace", 3, STAGING_TEST),
        ],
        sonar=Sonar(coverage=100.0), mutation=Mutation(18, 16, survived=2),
    ),
    45: MergeRequest(
        "Draft: FOL-121: Wishlist", "alice", ("bruno",), ("feature",), draft=True,
        threads=[Thread("alice", 1.5, WISHLIST_CHECKLIST)],
        approvals=(("bruno", 0.6),),
        sonar=Sonar(coverage=88.0, issues=1), mutation=Mutation(6, 6),
    ),
    46: MergeRequest(
        "FOL-110: Prices in the customer's language", "bruno", ("alice",), ("feature",),
        review_states={"alice": "REQUESTED_CHANGES"},
        threads=[
            Thread("alice", days(10.5), GERMAN_PRICES,
                   "storefront/prices.py", 'return f"{euros}{separator}', replies=[("bruno", days(10.4), GERMAN_PRICES_ANSWER)]),
            Thread("alice", days(9.8), REBASE),
        ],
        # Left aside for twelve days: Sonar no longer has its analysis, and the mutation report went wrong.
        sonar=Sonar(missing=True), mutation=Mutation(0, 0, unreadable=True),
    ),
    47: MergeRequest(
        "FOL-126: Spring repricing of the catalogue", "chloe", ("alice", "emma"), ("catalogue",),
        review_states={"emma": "REVIEWED"},
        threads=[
            Thread("emma", 20, PREVIOUS_PRICE,
                   "data/catalogue/fiction.csv", "isbn,title"),
        ],
        sonar=Sonar(coverage=100.0), mutation=Mutation(3, 3),
    ),
    34: MergeRequest(
        "FOL-099: Fix the typos of the README", "grace", ("alice",), ("documentation",),
        approvals=(("alice", days(2.6)),), sonar=Sonar(coverage=100.0), mutation=Mutation(0, 0),
    ),
    48: MergeRequest(
        "FOL-127: Full VAT rate on e-books, for the 2.4 release", "bruno", ("alice",), ("bug", "release"),
        assignees=("bruno", "dmitri"),
        threads=[Thread("bruno", days(1.75), HOTFIX)],
        sonar=Sonar(coverage=100.0), mutation=Mutation(5, 5),
    ),
    49: MergeRequest(
        "FOL-128: Newsletter sign-up", "farid", ("chloe",), ("feature",),
        assignees=("farid", "grace"),
        pipeline=Pipeline("failed", "mutation_test"),
        sonar=Sonar(coverage=93.0), mutation=Mutation(12, 11, survived=1),
    ),
    50: MergeRequest(
        "FOL-130: Earn loyalty points", "dmitri", ("alice",), ("feature", "loyalty"),
        sonar=Sonar(coverage=100.0), mutation=Mutation(4, 4),
    ),
    51: MergeRequest(
        "FOL-131: Spend loyalty points at checkout", "farid", ("alice",), ("feature", "loyalty"),
        blocked_by=(50,),
        sonar=Sonar(coverage=85.0), mutation=Mutation(7, 6, survived=1),
    ),
    52: MergeRequest(
        "Draft: FOL-132: Dark theme for the shop pages", "chloe", (), ("design",), draft=True,
        sonar=Sonar(coverage=100.0), mutation=Mutation(0, 0),
    ),
    53: MergeRequest(
        "FOL-133: Pin the test tools", "alice", ("dmitri",), ("tooling",),
        approvals=(("dmitri", 9),),
        sonar=Sonar(coverage=100.0), mutation=Mutation(0, 0),
    ),
    54: MergeRequest(
        "FOL-098: ONIX export for distributors", "dmitri", ("bruno",), ("feature",),
        threads=[Thread("bruno", days(20), ONIX_PING)],
        # Pushed before the mutation testing job reported on merge requests: no report.
        sonar=Sonar(coverage=78.0, issues=3),
    ),
}

assert set(MERGE_REQUESTS) == set(history.BRANCHES)
