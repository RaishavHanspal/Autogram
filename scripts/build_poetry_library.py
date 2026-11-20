"""Build config/poetry.md: ~10,000 short, highly "likeable" poetry excerpts.

Downloads public-domain poetry books from a Project Gutenberg mirror (Rumi,
Tagore, Gibran, Khayyam, Hafiz, Kabir, Iqbal, Dickinson, Shakespeare, Keats,
Wilcox, Teasdale ...), cuts them into 2-4 line excerpts, scores each for
social-media likeability (universal emotional words, a complete thought,
modern diction, the right length, a well-loved poet), de-duplicates, and
writes the best N, plus the hand-picked "featured" couplets, as Markdown that
autogram/poetry.py reads at runtime.

Usage:
    python scripts/build_poetry_library.py                   # 10,000 entries
    python scripts/build_poetry_library.py --count 5000 --cache .cache/gutenberg

Only public-domain sources are downloaded. The featured couplets come from
FEATURED below (edit freely).
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

MIRROR = "https://gutenberg.pglaf.org/cache/epub/{id}/pg{id}.txt"

# (gutenberg id, poet credit shown on the post, popularity weight 0..1)
BOOKS: list[tuple[int, str, float]] = [
    (7164, "Tagore", 1.0),  # Gitanjali
    (6524, "Tagore", 1.0),  # Stray Birds
    (6686, "Tagore", 1.0),  # The Gardener
    (6522, "Tagore", 0.95),  # Fruit-Gathering
    (6520, "Tagore", 0.9),  # The Crescent Moon
    (6519, "Kabir", 1.0),  # Songs of Kabir (Tagore tr.)
    (58585, "Kahlil Gibran", 1.0),  # The Prophet
    (54580, "Kahlil Gibran", 0.95),  # The Forerunner
    (61724, "Rumi", 1.0),  # The Mesnevi (Redhouse tr.)
    (246, "Omar Khayyam", 1.0),  # Rubaiyat (FitzGerald tr.)
    (74883, "Hafiz", 0.95),  # Poems from the Divan of Hafiz
    (77453, "Hafiz", 0.95),  # Songs of Hafiz
    (57317, "Iqbal", 0.9),  # The Secrets of the Self (Nicholson tr.)
    (12242, "Emily Dickinson", 0.95),
    (1041, "Shakespeare", 0.95),  # Sonnets
    (2002, "Elizabeth Barrett Browning", 0.9),  # Sonnets from the Portuguese
    (69866, "Sara Teasdale", 0.9),
    (74968, "Ella Wheeler Wilcox", 0.9),  # Poems of Love
    (74967, "Ella Wheeler Wilcox", 0.85),  # Poems of Life
    (74873, "Ella Wheeler Wilcox", 0.85),  # Poems of Reflection
    (51614, "Ella Wheeler Wilcox", 0.85),  # Poems of Pleasure
    (23684, "John Keats", 0.85),
    (2490, "John Keats", 0.8),
    (4800, "Percy Bysshe Shelley", 0.6),
    (1322, "Walt Whitman", 0.7),  # Leaves of Grass
    (1934, "William Blake", 0.8),
    (79363, "William Blake", 0.8),
    (10031, "Edgar Allan Poe", 0.65),
    (16950, "Christina Rossetti", 0.8),
    (19188, "Christina Rossetti", 0.8),
    (77809, "Christina Rossetti", 0.75),
    (49608, "W. B. Yeats", 0.85),
    (72985, "W. B. Yeats", 0.85),
    (72987, "W. B. Yeats", 0.85),
    (56913, "Tennyson", 0.6),
    (70950, "Tennyson", 0.6),
    (9622, "Wordsworth", 0.6),
    (53335, "Robert Browning", 0.55),
    (1279, "Robert Burns", 0.5),
    (75462, "Robert Burns", 0.5),
]

# Hand-picked couplets, always included at the top of the library.
FEATURED: list[tuple[str, list[str]]] = [
    ("Rumi", ["Lovers don't finally meet somewhere.", "They're in each other all along."]),
    ("Rumi", ["The wound is the place", "where the Light enters you."]),
    ("Rumi", ["Let the beauty of what you love", "be what you do."]),
    ("Rumi", ["Wherever you stand,", "be the soul of that place."]),
    ("Rumi", ["Don't grieve. Anything you lose", "comes round in another form."]),
    (
        "Faiz",
        [
            "Aur bhi dukh hain zamaane mein mohabbat ke siva",
            "Raahatein aur bhi hain vasl ki raahat ke siva",
        ],
    ),
    (
        "Faiz",
        [
            "Gulon mein rang bhare baad-e-naubahaar chale",
            "Chale bhi aao ke gulshan ka kaarobaar chale",
        ],
    ),
    (
        "Faiz",
        [
            "Dil na-umeed to nahin, naakaam hi to hai",
            "Lambi hai gham ki shaam, magar shaam hi to hai",
        ],
    ),
    (
        "Faiz",
        [
            "Raat yun dil mein teri khoyi hui yaad aayi",
            "Jaise veeraane mein chupke se bahaar aa jaaye",
        ],
    ),
    ("Faiz", ["Aaye kuchh abr, kuchh sharaab aaye", "Is ke baad aaye jo azaab aaye"]),
    (
        "Ghalib",
        [
            "Hazaaron khwahishen aisi ke har khwahish pe dam nikle",
            "Bahut nikle mere armaan lekin phir bhi kam nikle",
        ],
    ),
    ("Ghalib", ["Ishq ne Ghalib nikamma kar diya", "Varna hum bhi aadmi the kaam ke"]),
    ("Ghalib", ["Dil-e-naadaan tujhe hua kya hai", "Aakhir is dard ki dawa kya hai"]),
    (
        "Ghalib",
        [
            "Unke dekhe se jo aa jaati hai munh par raunaq",
            "Wo samajhte hain ke beemaar ka haal achchha hai",
        ],
    ),
    ("Mir", ["Naazuki us ke lab ki kya kahiye", "Pankhudi ek gulaab ki si hai"]),
    (
        "Mir",
        [
            "Patta patta boota boota haal hamaara jaane hai",
            "Jaane na jaane gul hi na jaane, baagh to saara jaane hai",
        ],
    ),
    ("Iqbal", ["Sitaaron se aage jahaan aur bhi hain", "Abhi ishq ke imtihaan aur bhi hain"]),
    ("Iqbal", ["Tu shaheen hai, parvaaz hai kaam tera", "Tere saamne aasmaan aur bhi hain"]),
    (
        "Kabir",
        [
            "Pothi padh padh jag mua, pandit bhaya na koy",
            "Dhai aakhar prem ka, padhe so pandit hoy",
        ],
    ),
    (
        "Kabir",
        ["Kabira khada bazaar mein, maange sabki khair", "Na kahu se dosti, na kahu se bair"],
    ),
    (
        "Kabir",
        [
            "Jaise til mein tel hai, jyon chakmak mein aag",
            "Tera saain tujh mein hai, tu jaag sake to jaag",
        ],
    ),
    (
        "Tagore",
        [
            "Clouds come floating into my life,",
            "no longer to carry rain or usher storm,",
            "but to add color to my sunset sky.",
        ],
    ),
    ("Tagore", ["The butterfly counts not months but moments,", "and has time enough."]),
    ("Tagore", ["Let life be beautiful like summer flowers", "and death like autumn leaves."]),
    (
        "Tagore",
        ["Faith is the bird that feels the light", "and sings when the dawn is still dark."],
    ),
    ("Tagore", ["The traveller has to knock at every alien door", "to come to his own."]),
    ("Kahlil Gibran", ["Love gives naught but itself", "and takes naught but from itself."]),
    (
        "Kahlil Gibran",
        ["The earth delights to feel your bare feet", "and the winds long to play with your hair."],
    ),
]

# Tag -> trigger words. Written into the .md so it can be edited there.
KEYWORDS: dict[str, list[str]] = {
    "love": "love lover lovers loved loving beloved couple romance romantic proposal ring kiss kisses embrace heart hearts together tender wedding bride darling sweetheart".split(),
    "longing": "alone lonely longing memory remember waiting wait distance far miss missing apart parting farewell tears weep sorrow sad wistful".split(),
    "journey": "travel traveller traveler road roads path paths train station journey wander wandering street bridge boat trail ferry walk walking way voyage roam".split(),
    "nature": "garden flower flowers rose roses tree trees forest leaves leaf field meadow valley mountain mountains bloom spring blossom grass bird birds".split(),
    "sky": "sky skies cloud clouds sunset sunrise dawn dusk horizon stars star moon golden twilight sun heaven".split(),
    "night": "night nights moonlit lantern lamp candle candles dark darkness evening midnight shadow shadows dream dreams sleep".split(),
    "rain": "rain rains monsoon storm storms wet umbrella mist fog drizzle thunder".split(),
    "sea": "sea seas ocean beach shore wave waves coast river rivers lake water waters harbor harbour tide".split(),
    "city": "city market bazaar crowd crowds alley rooftop cafe shop festival people town streets".split(),
    "hope": "hope joy smile smiles laughter laugh light bright warm morning glad happy happiness delight courage".split(),
    "time": "old ancient time years age ages yesterday tomorrow ruins temple autumn season seasons forever".split(),
    "soul": "soul spirit prayer god divine silence still stillness peace calm serene truth faith".split(),
}

LIKEABLE = set(
    """love loved lover beloved heart hearts soul souls light dream dreams hope joy
    beauty beautiful smile tears night star stars moon sun sky sea rose flower flowers
    life live kiss eyes home road path wings fire song songs silence spring rain
    world forever alone free freedom truth peace laugh sorrow wild wonder rise
    together within kind gentle tender bloom morning dawn faith longing remember
    yourself breath wind ocean river garden happiness grief broken whole open""".split()
)

ARCHAIC = set(
    """thee thou thy thine hath doth ye wilt shalt art'st o'er e'er ne'er 'tis 'twas
    oft ere hast dost wouldst couldst shouldst canst didst whence thence hither thither
    nay yea alas anon methinks prithee mayst""".split()
)

CONTINUATION = {
    "and",
    "but",
    "or",
    "nor",
    "for",
    "so",
    "yet",
    "that",
    "which",
    "who",
    "whose",
    "then",
}

_TERMINAL = (".", "!", "?")


def fetch(book_id: int, cache: Path) -> str:
    path = cache / f"pg{book_id}.txt"
    if not path.exists():
        url = MIRROR.format(id=book_id)
        req = urllib.request.Request(url, headers={"User-Agent": "autogram-poetry-builder/1.0"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    path.write_bytes(resp.read())
                break
            except OSError as exc:
                print(f"  retry {book_id}: {exc}")
                time.sleep(3 * (attempt + 1))
        else:
            return ""
        time.sleep(1.0)  # be polite to the mirror
    return path.read_text(encoding="utf-8", errors="replace")


def strip_boilerplate(text: str) -> str:
    text = text.replace("\r\n", "\n")
    start = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    end = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", text)
    return text[start.end() if start else 0 : end.start() if end else len(text)]


def clean_line(line: str) -> str:
    line = re.sub(r"\[[^\]]*\]", "", line)  # footnotes / illustrations
    line = re.sub(r"[_*]", "", line)  # italics markup
    line = re.sub(r"\s+", " ", line).strip()
    line = line.replace("--", "—")
    return line


def is_junk(line: str) -> bool:
    if not line or len(line) < 3:
        return True
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return True
    if sum(c.isupper() for c in letters) / len(letters) > 0.6:  # headings
        return True
    if re.fullmatch(r"[IVXLC]+\.?|\d+\.?", line):
        return True
    if re.search(
        r"\d|https?:|gutenberg|chapter|contents|footnote|translat|edition|copyright|page",
        line,
        re.I,
    ):
        return True
    return bool(re.search(r"[<>{}|#@=~^]", line))


def paragraphs(body: str) -> list[list[str]]:
    out: list[list[str]] = []
    for block in re.split(r"\n\s*\n", body):
        raw = [ln for ln in block.split("\n") if ln.strip()]
        if not raw:
            continue
        out.append(raw)
    return out


def is_prose(raw: list[str]) -> bool:
    """Hard-wrapped prose (Gitanjali, Stray Birds, The Prophet ...), not verse."""
    lens = [len(ln.strip()) for ln in raw]
    long = sum(1 for n in lens if n >= 58)
    if len(raw) == 1:
        return lens[0] >= 58
    # Short paragraphs (aphorisms) wrap once: a long line then a short tail.
    if len(raw) <= 3 and lens[0] >= 58:
        return True
    return long / len(raw) >= 0.5


def split_display(sentence: str, per_line: int = 8) -> list[str]:
    """Break a prose sentence into balanced display lines, preferring commas."""
    words = sentence.split()
    n = max(1, round(len(words) / per_line))
    if n == 1:
        return [sentence]
    target = len(words) / n
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(lines) < n - 1 and (
            (len(cur) >= target * 0.7 and w.endswith((",", ";", ":", "—")))
            or len(cur) >= target * 1.25
        ):
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return lines


def candidates(text: str) -> list[list[str]]:
    """Yield excerpts (lists of display lines) from one book."""
    out: list[list[str]] = []
    for raw in paragraphs(strip_boilerplate(text)):
        if is_prose(raw):
            para = clean_line(" ".join(r.strip() for r in raw))
            if is_junk(para) and len(para) < 40:
                continue
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'“])", para)
            for i, s in enumerate(sentences):
                for chunk in (s, " ".join(sentences[i : i + 2])):
                    words = len(chunk.split())
                    if 7 <= words <= 30 and not is_junk(chunk):
                        out.append(split_display(chunk))
        else:
            lines = [clean_line(r) for r in raw]
            lines = [ln for ln in lines if not is_junk(ln)]
            for size in (2, 4):
                # Quatrains only as whole stanzas (Rubaiyat, ballads).
                starts = (
                    range(0, max(0, len(lines) - size + 1))
                    if size == 2
                    else ([0] if len(lines) == 4 else [])
                )
                for i in starts:
                    win = lines[i : i + size]
                    if all(4 <= len(ln) <= 70 for ln in win):
                        out.append(win)
    return out


def norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower())


_DANGLING = {
    "the", "a", "an", "of", "my", "his", "her", "their", "our", "your", "thy", "to",
    "and", "in", "with", "that", "from", "by", "at", "for", "its", "as", "or", "is",
}  # fmt: skip


def score(lines: list[str], popularity: float) -> float:
    text = " ".join(lines).replace("’", "'").replace("‘", "'")
    words = re.findall(r"[A-Za-z']+", text)
    lw = [w.lower().strip("'") for w in words]
    n = len(words)
    max_words = 40 if len(lines) == 4 else 30
    if n < 6 or n > max_words:
        return -1
    # Must be a complete thought, and free of transliterated names / notes.
    if not text.rstrip("\"' ”)").endswith(_TERMINAL):
        return -1
    if re.search(r"[^\x00-\x7f—“”]", text):
        return -1
    s = 15.0
    # Sweet spot: 10-22 words reads in one glance on a phone.
    s += 12 if 10 <= n <= 22 else (6 if n <= 28 else 0)
    # A complete thought.
    first = lw[0]
    if text.rstrip("\"' ”)").endswith(_TERMINAL):
        s += 14
    elif text.rstrip().endswith((",", ";", ":", "—", "-")):
        s -= 15
    if words[0][0].isupper() and first not in CONTINUATION:
        s += 6
    else:
        s -= 12
    if first in {"he", "she", "it", "they", "his", "her", "its", "their", "this", "these"}:
        s -= 6  # pronoun with no antecedent
    # Lines that break mid-phrase ("my / songs") read as fragments.
    s -= 8 * sum(1 for ln in lines[:-1] if ln.split()[-1].lower() in _DANGLING)
    # Universal emotional vocabulary.
    hits = sum(1 for w in lw if w in LIKEABLE)
    s += min(hits, 5) * 5
    # Relatable address.
    if {"you", "your", "we", "our", "i", "my"} & set(lw):
        s += 4
    # Archaic / dialect diction ("thee", "o'er", "pass'd", "wi'") reads poorly.
    archaic = sum(
        1
        for w in re.findall(r"[A-Za-z']+", text.lower())
        if w.strip("'") in ARCHAIC
        or re.search(r"[a-z]'d$|'$|^'|o'$", w)
        or (w.endswith("est") and len(w) > 5)
        or w.endswith("eth")
    )
    s -= archaic * 8
    # Proper nouns (mid-line capitals) tie the excerpt to its source context.
    proper = sum(
        1
        for ln in lines
        for i, w in enumerate(ln.split())
        if i > 0
        and w[:1].isupper()
        and w.strip(",.;:!?\"'").lower() not in {"i", "god", "love", "thou", "o"}
    )
    s -= proper * 5
    if re.search(r"[\"“”]", text) or "?" in text[:-1]:
        s -= 6  # dialogue fragments / rhetorical question chains
    s += popularity * 20
    return round(max(0.0, min(100.0, s)), 1)


def tag(lines: list[str]) -> list[str]:
    words = set(re.findall(r"[a-z]+", " ".join(lines).lower()))
    return [t for t, kws in KEYWORDS.items() if words & set(kws)]


def build(count: int, cache: Path, per_poet_cap: float) -> list[tuple[float, str, list[str]]]:
    cache.mkdir(parents=True, exist_ok=True)
    pool: list[tuple[float, str, list[str]]] = []
    seen: set[str] = set()
    for book_id, poet, pop in BOOKS:
        text = fetch(book_id, cache)
        if not text:
            print(f"  skip {book_id} ({poet}): download failed")
            continue
        got = 0
        for lines in candidates(text):
            key = norm(" ".join(lines))
            if key in seen:
                continue
            sc = score(lines, pop)
            if sc < 0:
                continue
            seen.add(key)
            pool.append((sc, poet, lines))
            got += 1
        print(f"  {book_id:>6} {poet:<28} {got:>6} excerpts")

    pool.sort(key=lambda x: -x[0])
    # Overlapping windows: once an excerpt is taken, skip others sharing a line.
    used_lines: set[str] = set()
    per_poet: Counter[str] = Counter()
    # Best-loved poets may fill a bigger share of the library.
    pop = {poet: p for _, poet, p in BOOKS}
    caps = {poet: int(count * per_poet_cap * p * p) for poet, p in pop.items()}
    chosen: list[tuple[float, str, list[str]]] = []
    for sc, poet, lines in pool:
        keys = {norm(ln) for ln in lines}
        if keys & used_lines or per_poet[poet] >= caps[poet]:
            continue
        used_lines |= keys
        per_poet[poet] += 1
        chosen.append((sc, poet, lines))
        if len(chosen) >= count:
            break
    print(f"pool {len(pool)} -> chosen {len(chosen)}; by poet: {dict(per_poet.most_common())}")
    return chosen


def write_md(path: Path, chosen: list[tuple[float, str, list[str]]]) -> None:
    out: list[str] = [
        "# Autogram poetry library",
        "",
        "Short verses overlaid (stationary, top of frame) on every photo, carousel",
        "slide and reel. Generated by `scripts/build_poetry_library.py` from",
        "public-domain Project Gutenberg texts, ranked by a likeability score",
        "(♥ 0-100). Featured couplets are hand-picked. Edit freely: each entry is a",
        "`### <id> · <poet> · ♥ <score>` heading, a `tags:` line and `>` quote lines.",
        "",
        "## Tag keywords",
        "",
    ]
    out += [f"- {t}: {', '.join(kws)}" for t, kws in KEYWORDS.items()]
    out += ["", "## Poems", ""]
    entries = [(100.0, poet, lines) for poet, lines in FEATURED] + chosen
    for i, (sc, poet, lines) in enumerate(entries, 1):
        out.append(f"### {i:05d} · {poet} · ♥ {sc:g}")
        out.append(f"tags: {', '.join(tag(lines))}")
        out.append("")
        out += [f"> {ln}" for ln in lines]
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {len(entries)} poems to {path} ({path.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=10_000, help="harvested entries (plus featured)")
    ap.add_argument("--cache", default=".cache/gutenberg", help="download cache dir")
    ap.add_argument("--out", default="config/poetry.md")
    ap.add_argument("--per-poet-cap", type=float, default=0.14, help="max share per poet")
    args = ap.parse_args()
    chosen = build(args.count - len(FEATURED), Path(args.cache), args.per_poet_cap)
    write_md(Path(args.out), chosen)
    if len(chosen) < args.count - len(FEATURED):
        print("warning: fewer excerpts than requested; lower --per-poet-cap limits or add BOOKS")


if __name__ == "__main__":
    main()
