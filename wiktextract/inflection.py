# Code for parsing inflection tables.
#
# Copyright (c) 2021 Tatu Ylonen.  See file LICENSE and https://ylonen.org.

import re
import copy
import enum
import html
import collections
import unicodedata
from wikitextprocessor import Wtp, WikiNode, NodeKind, ALL_LANGUAGES
from wiktextract.config import WiktionaryConfig
from wiktextract.tags import valid_tags
from wiktextract.inflectiondata import infl_map, infl_start_map, infl_start_re
from wiktextract.datautils import (data_append, data_extend, freeze,
                                   split_at_comma_semi)
from wiktextract.form_descriptions import (classify_desc, decode_tags,
                                           parse_head_final_tags,
                                           merge_tagsets)
from wiktextract.parts_of_speech import PARTS_OF_SPEECH

# Column texts that are interpreted as an empty column.
IGNORED_COLVALUES = set([
    "-", "־", "᠆", "‐", "‑", "‒", "–", "—", "―", "−",
    "⸺", "⸻", "﹘", "﹣", "－", "/", "?"])

# These tags are never inherited from above
noinherit_tags = set([
    "infinitive-i",
    "infinitive-i-long",
    "infinitive-ii",
    "infinitive-iii",
    "infinitive-iv",
    "infinitive-v",
])

# Words in title that cause addition of tags in all entries
title_contains_global_map = {
    "possessive": "possessive",
    "negative": "negative",
    "future": "future",
    "pf": "perfective",
    "impf": "imperfective",
    "comparative": "comparative",
    "superlative": "superlative",
    "combined forms": "combined-form",
    "mutation": "mutation",
    "definite article": "definite",
    "indefinite article": "indefinite",
    "pre-reform": "dated",
    "personal pronouns": "personal pronoun",
    "composed forms of": "multiword-construction",
    "subordinate-clause forms of": "subordinate-clause",
    "western lombard": "Western-Lombard",
    "eastern lombard": "Eastern-Lombard",
}
for k, v in title_contains_global_map.items():
    if any(t not in valid_tags for t in v.split()):
        print("TITLE_CONTAINS_GLOBAL_MAP UNRECOGNIZED TAG: {}: {}"
              .format(k, v))
title_contains_global_re = re.compile(
    r"(?i)(^|\b)({})($|\b)"
    .format("|".join(re.escape(x)
                     for x in title_contains_global_map.keys())))

# Words in title that cause addition of tags to word-tags "form"
title_contains_wordtags_map = {
    "strong": "strong",
    "weak": "weak",
    "countable": "countable",
    "uncountable": "uncountable",
    "inanimate": "inanimate",
    "animate": "animate",
    "transitive": "transitive",
    "intransitive": "intransitive",
    "ditransitive": "ditransitive",
    "ambitransitive": "ambitransitive",
    "proper noun": "proper-noun",
    "no plural": "no-plural",
    "imperfective": "imperfective",
    "perfective": "perfective",
    "no supine stem": "no-supine",
    "no perfect stem": "no-perfect",
    "deponent": "deponent",
    "no short forms": "no-short-form",
    "iō-variant": "iō-variant",
    "1st declension": "declension-1",
    "2nd declension": "declension-2",
    "3rd declension": "declension-3",
    "4th declension": "declension-4",
    "5th declension": "declension-5",
    "first declension": "declension-1",
    "second declension": "declension-2",
    "third declension": "declension-3",
    "fourth declension": "declension-4",
    "fifth declension": "declension-5",
    "1st conjugation": "conjugation-1",
    "2nd conjugation": "conjugation-2",
    "3rd conjugation": "conjugation-3",
    "4th conjugation": "conjugation-4",
    "5th conjugation": "conjugation-5",
    "6th conjugation": "conjugation-6",
    "7th conjugation": "conjugation-7",
    "first conjugation": "conjugation-1",
    "second conjugation": "conjugation-2",
    "third conjugation": "conjugation-3",
    "fourth conjugation": "conjugation-4",
    "fifth conjugation": "conjugation-5",
    "sixth conjugation": "conjugation-6",
    "seventh conjugation": "conjugation-7",
}
for k, v in title_contains_wordtags_map.items():
    if any(t not in valid_tags for t in v.split()):
        print("TITLE_CONTAINS_WORDTAGS_MAP UNRECOGNIZED TAG: {}: {}"
              .format(k, v))
title_contains_wordtags_re = re.compile(
    r"(?i)(^|\b)({})($|\b)"
    .format("|".join(re.escape(x)
                     for x in title_contains_wordtags_map.keys())))

# Parenthesized elements in title that are converted to tags in "word-tags" form
title_elements_map = {
    "weak": "weak",
    "strong": "strong",
    "masculine": "masculine",
    "feminine": "feminine",
    "neuter": "neuter",
    "singular": "singular",
    "plural": "plural",
}
for k, v in title_elements_map.items():
    if any(t not in valid_tags for t in v.split()):
        print("TITLE_ELEMENTS_MAP UNRECOGNIZED TAG: {}: {}"
              .format(k, v))

# Parenthized element starts to map them to tags for form for the rest of
# the element
title_elemstart_map = {
    "auxiliary": "auxiliary",
    "Kotus type": "class",
    "class": "class",
    "short class": "class",
    "type": "class",
    "strong class": "class",
    "weak class": "class",
    "accent paradigm": "accent-paradigm",
}
for k, v in title_elemstart_map.items():
    if any(t not in valid_tags for t in v.split()):
        print("TITLE_ELEMSTART_MAP UNRECOGNIZED TAG: {}: {}"
              .format(k, v))
title_elemstart_re = re.compile(
    r"^({}) "
    .format("|".join(re.escape(x) for x in title_elemstart_map.keys())))


# Specification for language-specific processing.  Each entry starts
# with a list of languages that it applies to (a language can be
# specified in multiple entries) and then a list of parts-of-speech.
# It is then followed by any number of pattern-tags pairs, where
# pattern will be escaped, except ^ at the beginning is interpreted as
# restricting it to the beginning.  The matched parts will be removed
# from the word.
lang_specific_data = [
    [["German"], ["verb"],
     ["^ich ", "first-person singular"],
     ["^du ", "second-person singular"],
     ["^er ", "third-person singular"],
     ["^wir ", "first-person plural"],
     ["^ihr ", "second-person plural"],
     ["^sie ", "third-person plural"],
     ["^dass ich ", "first-person singular subordinate-clause"],
     ["^dass du ", "second-person singular subordinate-clause"],
     ["^dass er ", "third-person singular subordinate-clause"],
     ["^dass wir ", "first-person plural subordinate-clause"],
     ["^dass ihr ", "second-person plural subordinate-clause"],
     ["^dass sie ", "third-person plural subordinate-clause"],
     [" (du)", "second-person singular"],
     [" (ihr)", "second-person plural"],
     ],
]
specific_by_lang = collections.defaultdict(list)
for lst in lang_specific_data:
    assert isinstance(lst, list)
    assert len(lst) >= 3
    for rule_lang in lst[0]:
        assert isinstance(rule_lang, str)
        for rule_pos in lst[1]:
            assert isinstance(rule_pos, str)
            for rule in lst[2:]:
                assert isinstance(rule, list)
                rule_pattern, rule_tags = rule
                assert isinstance(rule_pattern, str)
                assert isinstance(rule_tags, str)
                for t in rule_tags.split():
                    assert t in valid_tags
                specific_by_lang[rule_lang, rule_pos].append(
                    [rule_pattern, rule_tags])
specific_by_lang_re = {}
specific_by_lang_map = {}
for (rule_lang, rule_pos), lst in specific_by_lang.items():
    starts = list(x[0][1:] for x in lst if x[0].startswith("^"))
    others = list(x[0] for x in lst if not x[0].startswith("^"))
    rs = []
    if starts:
        rs.append(r"^(" + "|".join(re.escape(x) for x in starts) + ")")
    if others:
        rs.append(r"(" + "|".join(re.escape(x) for x in others) + ")")
    specific_by_lang_re[rule_lang, rule_pos] = re.compile("|".join(rs))
    ht = {}
    specific_by_lang_map[rule_lang, rule_pos] = ht
    for k, v in lst:
        if k.startswith("^"):
            k = k[1:]
        assert k not in ht
        ht[k] = v.split()


# Tag combination mappings for specific languages/part-of-speech.  These are
# used as a post-processing step for forms extracted from tables.  Each
# element has list of languages, list of part-of-speech, and one or more
# source set - replacement set pairs.
lang_tag_mappings = [
    [["Armenian"], ["noun"],
     [["possessive", "singular"], ["possessive", "possessive-single"]],
     [["possessive", "plural"], ["possessive", "possessive-many"]],
    ],
]
for lst in lang_tag_mappings:
    assert len(lst) >= 3
    assert all(isinstance(x, str) for x in lst[0])  # languages
    assert all(x in PARTS_OF_SPEECH for x in lst[1])  # parts of speech
    for src, dst in lst[2:]:
        assert all(t in valid_tags for t in src)
        assert all(t in valid_tags for t in dst)


class InflCell(object):
    """Cell in an inflection table."""
    __slots__ = (
        "text",
        "is_title",
        "start",
        "colspan",
        "rowspan",
    )
    def __init__(self, text, is_title, start, colspan, rowspan):
        assert isinstance(text, str)
        assert is_title in (True, False)
        assert isinstance(start, int)
        assert isinstance(colspan, int) and colspan >= 1
        assert isinstance(rowspan, int) and rowspan >= 1
        self.text = text.strip()
        self.is_title = text and is_title
        self.colspan = colspan
        self.rowspan = rowspan
    def __str__(self):
        return "{}/{}/{}/{}".format(
            self.text, self.is_title, self.colspan, self.rowspan)
    def __repr__(self):
        return str(self)


class HdrSpan(object):
    """Saved information about a header cell/span during the parsing
    of a table."""
    __slots__ = (
        "start",
        "colspan",
        "rownum",      # Row number where this occurred
        "tagsets",  # set of tuples
        "used",  # At least one text cell after this
        "text",  # For debugging
    )
    def __init__(self, start, colspan, rownum, tagsets, text):
        assert isinstance(start, int) and start >= 0
        assert isinstance(colspan, int) and colspan >= 1
        assert isinstance(rownum, int)
        assert isinstance(tagsets, set)
        for x in tagsets:
            assert isinstance(x, tuple)
        self.start = start
        self.colspan = colspan
        self.rownum = rownum
        self.tagsets = set(tuple(sorted(set(tags))) for tags in tagsets)
        self.used = False
        self.text = text


def is_superscript(ch):
    """Returns True if the argument is a superscript character."""
    assert isinstance(ch, str) and len(ch) == 1
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False
    return re.match(r"SUPERSCRIPT |MODIFIER LETTER SMALL ", name) is not None


def clean_header(word, col, skip_paren):
    """Cleans a row/column header for later processing."""
    hdr_tags = []
    orig_col = col
    col = re.sub(r"(?s)\s*➤\s*$", "", col)
    col = re.sub(r"(?s)\s*,\s*$", "", col)
    col = re.sub(r"(?s)\s*•\s*$", "", col)
    if col not in infl_map and skip_paren:
        col = re.sub(r"[,/]?\s+\([^)]*\)\s*$", "", col)
    col = col.strip()
    if re.search(r"^(There are |"
                 r"\*|"
                 r"see |"
                 r"Use |"
                 r"use the |"
                 r"Only used |"
                 r"The forms in |"
                 r"these are also written |"
                 r"The genitive can be |"
                 r"Genitive forms are rare or non-existant|"
                 r"Accusative Note: |"
                 r"Classifier Note: |"
                 r"Noun: Assamese nouns are |"
                 r"the active conjugation|"
                 r"the instrumenal singular|"
                 r"Note:|"
                 r"\^* Note:|"
                 r"Notes:)",
                col):
        return "", [], [], []
    refs = []
    ref_symbols = "*△†0123456789"
    while True:
        m = re.search(r"\^(.|\([^)]*\))$", col)
        if not m:
            break
        r = m.group(1)
        if r.startswith("(") and r.endswith(")"):
            r = r[1:-1]
        if r == "rare":
            hdr_tags.append("rare")
        elif r == "vos":
            hdr_tags.append("formal")
        elif r == "tú":
            hdr_tags.append("informal")
        else:
            # XXX handle refs from m.group(1)
            pass
        col = col[:m.start()]
    if col.endswith("ʳᵃʳᵉ"):
        hdr_tags.append("rare")
        col = col[:-4].strip()
    if col.endswith("ᵛᵒˢ"):
        hdr_tags.append("formal")
        col = col[:-3].strip()
    while col and is_superscript(col[0]):
        if len(col) > 1 and col[1] in ("⁾", " ", ":"):
            # Note definition
            return "", [], [[col[0], col[2:].strip()]], []
        refs.append(col[0])
        col = col[1:]
    while col and (is_superscript(col[-1]) or col[-1] in ("†",)):
        # Numbers and H/L/N are useful information
        refs.append(col[-1])
        col = col[:-1]
    if len(col) > 2 and col[1] in (")", " ", ":") and col[0].isdigit():
        # Another form of note definition
        return "", [], [[col[0], col[2:].strip()]], []
    col = col.strip()
    if col.endswith("*"):
        col = col[:-1].strip()
        refs.append("*")
    if col.endswith("(*)"):
        col = col[:-3].strip()
        refs.append("*")
    # print("CLEAN_HEADER: orig_col={!r} col={!r} refs={!r} hdr_tags={}"
    #       .format(orig_col, col, refs, hdr_tags))
    return col.strip(), refs, [], hdr_tags


def parse_title(title, source):
    """Parses inflection table title.  This returns (global_tags, word_tags,
    extra_forms), where ``global_tags`` is tags to be added to each inflection
    entry, ``word_tags`` are tags for the word but not to be added to every
    form, and ``extra_forms`` is dictionary describing additional forms to be
    included in the part-of-speech entry)."""
    assert isinstance(title, str)
    assert isinstance(source, str)
    title = html.unescape(title)
    title = re.sub(r"(?i)<[^>]*>", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    # print("PARSE_TITLE:", title)
    global_tags = []
    word_tags = []
    extra_forms = []
    # Check for the case that the title is in infl_map
    if title in infl_map:
        return infl_map[title].split(), [], []
    if title.lower() in infl_map:
        return infl_map[title.lower()].split(), [], []
    # Add certain global tags based on contained words
    for m in re.finditer(title_contains_global_re, title):
        global_tags.extend(title_contains_global_map[
            m.group(0).lower()].split())
    # Add certain tags to word-tags "form" based on contained words
    for m in re.finditer(title_contains_wordtags_re, title):
        word_tags.extend(title_contains_wordtags_map[
            m.group(0).lower()].split())
    # Check for <x>-type at the beginning of title (e.g., Armenian)
    m = re.search(r"\b(\w+-type|accent-\w+|\w+-stem|[^ ]+ gradation)\b", title)
    if m:
        dt = {"form": m.group(1),
              "source": source + " title",
              "tags": ["class"]}
        extra_forms.append(dt)
    # Parse parenthesized part from title
    for m in re.finditer(r"\(([^)]*)\)", title):
        for elem in m.group(1).split(","):
            elem = elem.strip()
            if elem in title_elements_map:
                word_tags.extend(title_elements_map[elem].split())
            else:
                m = re.match(title_elemstart_re, elem)
                if m:
                    tags = title_elemstart_map[m.group(1)].split()
                    dt = {"form": elem[m.end():],
                          "source": source + " title",
                          "tags": tags}
                    extra_forms.append(dt)
    # For titles that contains no parenthesized parts, do some special
    # handling to still interpret parts from them
    if title.find("(") < 0:
        # No parenthesized parts
        m = re.search(r"\b(Portuguese) (-.* verb) ", title)
        if m is not None:
            dt = {"form": m.group(2),
                  "tags": ["class"],
                  "source": source + " title"}
            extra_forms.append(dt)
        for elem in title.split(","):
            elem = elem.strip()
            if elem in title_elements_map:
                word_tags.extend(title_elements_map[elem].split())
            elif elem.endswith("-stem"):
                dt = {"form": elem,
                      "tags": ["class"],
                      "source": source + " title"}
                extra_forms.append(dt)
    return global_tags, word_tags, extra_forms


def expand_header(ctx, word, lang, text, tags0, silent=False):
    """Expands a cell header to tags, handling conditional expressions
    in infl_map.  This returns list of tuples of tags, each list element
    describing an alternative interpretation.  ``tags0`` is combined
    column and row tags for the cell in which the text is being interpreted
    (conditional expressions in inflection data may depend on it)."""
    assert isinstance(ctx, Wtp)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert isinstance(text, str)
    assert isinstance(tags0, (list, tuple, set))
    assert silent in (True, False)
    # print("EXPAND_HDR:", text)
    # First map the text using the inflection map
    if text in infl_map:
        v = infl_map[text]
    else:
        m = re.match(infl_start_re, text)
        if m is None:
            return []  # Unrecognized header
        v = infl_start_map[m.group(1)]
        # print("INFL_START {} -> {}".format(text, v))

    # Then loop interpreting the value, until the value is a simple string.
    # This may evaluate nested conditional expressions.
    while True:
        # If it is a string, we are done.
        if isinstance(v, str):
            return [tuple(sorted(v.split()))]
        # For a list, just interpret it as alternatives.  (Currently the
        # alternatives must directly be strings.)
        if isinstance(v, (list, tuple)):
            lst = []
            return list(tuple(sorted(x.split())) for x in v)
        # Otherwise the value should be a dictionary describing a conditional
        # expression.
        if not isinstance(v, dict):
            ctx.debug("inflection table: internal: "
                      "UNIMPLEMENTED INFL_MAP VALUE: {}"
                      .format(infl_map[text]))
            return [()]
        # Evaluate the conditional expression.
        assert isinstance(v, dict)
        cond = "default-true"
        # Handle "lang" condition.  The value must be either a single language
        # or a list of languages, and the condition evaluates to True if
        # the table is in one of those languages.
        if cond and "lang" in v:
            c = v["lang"]
            if isinstance(c, str):
                cond = c == lang
            else:
                assert isinstance(c, (list, tuple, set))
                cond = lang in c
        # Handle "if" condition.  The value must be a string containing
        # a space-separated list of tags.  The condition evaluates to True
        # if ``tags0`` contains all of the listed tags.  If the condition
        # is of the form "any: ...tags...", then any of the tags will be
        # enough.
        if cond and "if" in v:
            c = v["if"]
            assert isinstance(c, str)
            # "if" condition is true if any of the listed tags is present
            if c.startswith("any: "):
                cond = any(t in tags0 for t in c[5:].split())
            else:
                cond = all(t in tags0 for t in c.split())
        # Warning message about missing conditions for debugging.
        if cond == "default-true" and not silent:
            print("IF MISSING COND: word={} lang={} text={} tags0={} "
                  "c={} cond={}"
                  .format(word, lang, text, tags0, c, cond))
        # Based on the result of evaluating the condition, select either
        # "then" part or "else" part.
        if cond:
            v = v.get("then", "")
        else:
            v = v.get("else")
            if v is None:
                if not silent:
                    print("IF WITHOUT ELSE EVALS False: {}/{} {!r} tags0={}"
                          .format(word, lang, text, tags0))
                v = ""


def compute_coltags(hdrspans, start, colspan, mark_used, celltext):
    """Computes column tags for a column of the given width based on the
    current header spans."""
    assert isinstance(hdrspans, list)
    assert isinstance(start, int) and start >= 0
    assert isinstance(colspan, int) and colspan >= 1
    assert mark_used in (True, False)
    assert isinstance(celltext, str)  # For debugging only
    # For debugging, set this to the form for whose cell you want debug prints
    debug_word = None  # None to disable
    if celltext == debug_word:
        print("COMPUTE_COLTAGS CALLED start={} colspan={} celltext={!r}"
              .format(start, colspan, celltext))
        for hdrspan in hdrspans:
            print("  row={} start={} colspans={} tagsets={}"
                  .format(hdrspan.rownum, hdrspan.start, hdrspan.colspan,
                          hdrspan.tagsets))
    used = set()
    coltags = None
    # Iterate through the headers in reverse order, i.e., headers lower in the
    # table (closer to the cell) first.
    for hdrspan in reversed(hdrspans):
        tagsets = hdrspan.tagsets
        if (hdrspan.start > start or
            hdrspan.start + hdrspan.colspan < start + colspan):
            # Special case: we sometimes have cells covering two out of
            # three genders.  Also, sometimes we have multiple genders for
            # plural and a form for several; we must then take the common tags.
            if (hdrspan.start >= start and
                hdrspan.start + hdrspan.colspan <= start + colspan and
                any(x is not hdrspan and x.rownum == hdrspan.rownum and
                    x.start >= start and
                    x.start + x.colspan <= start + colspan
                    for x in hdrspans) and
                all(x.rownum != hdrspan.rownum or
                    x.start < hdrspan.start or
                    x.start + x.colspan > hdrspan.start + hdrspan.colspan or
                    all(valid_tags[t] in ("number", "gender", "case")
                        for ts in x.tagsets
                        for t in ts)
                    for x in hdrspans)):
                # Multiple columns apply to the current cell, only
                # gender/number/case tags present
                # If there are no tags outside the range in any of the
                # categories included in these cells, don't add anything
                # (assume all choices valid in the language are possible).
                in_cats = set(valid_tags[t]
                              for x in hdrspans
                              if x.rownum == hdrspan.rownum and
                              x.start >= start and
                              x.start + x.colspan <= start + colspan
                              for tt in x.tagsets
                              for t in tt)
                # For limited categories, if the category doesn't appear
                # outside, we won't include the category
                if not in_cats - set(("gender", "number", "person", "case")):
                    # Sometimes we have masc, fem, neut and plural, so treat
                    # number and gender as the same here (if one given, look for
                    # the other too)
                    if "number" in in_cats or "gender" in in_cats:
                        in_cats.update(("number", "gender"))
                        # Determine which categories occur outside on
                        # the same row
                        out_cats = set(valid_tags[t]
                                       for x in hdrspans
                                       if x.rownum == hdrspan.rownum and
                                       (x.start < start or
                                        x.start + x.colspan > start + colspan)
                                       for tt in x.tagsets
                                       for t in tt)
                        # print("in_cats={} out_cats={}"
                        #       .format(in_cats, out_cats))
                        if not (out_cats & in_cats):
                            tagsets = set([()])
                # # Merge the tagsets into existing tagsets.  This merges
                # # alternatives into the same tagset if there is only one
                # # category different; otherwise this splits the tagset into
                # # more alternatives.
                # for x in hdrspans:
                #     if (x is hdrspan or x.rownum != hdrspan.rownum or
                #         x.start < start or
                #         x.start + x.colspan >= start + colspan):
                #         continue
                #     tagsets = merge_tagsets(tagsets, x.tagsets)
            else:
                # Ignore this hdrspan
                if celltext == debug_word:
                    print("Ignoring row={} start={} tagsets={}"
                          .format(hdrspan.rownum, hdrspan.start,
                                  hdrspan.tagsets))
                continue
        key = (hdrspan.start, hdrspan.colspan)
        if key in used:
            if celltext == debug_word:
                print("Cellspan already used: start={} key={} rownum={}"
                      .format(hdrspan.start, hdrspan.colspan, hdrspan.rownum))
            continue
        used.add(key)
        if mark_used:
            hdrspan.used = True
        # Merge into coltags
        if coltags is None:
            coltags = tagsets
            if celltext == debug_word:
                print("initial row={} start={} coltags={}"
                      .format(hdrspan.rownum, hdrspan.start, coltags))
        else:
            # new_cats is for the new tags (higher up in the table)
            new_cats = set(valid_tags[t]
                          for tt in tagsets
                          for t in tt)
            # cur_cats is for the tags already collected (lower in the table)
            cur_cats = set(valid_tags[t]
                           for tt in coltags
                           for t in tt)
            if celltext == debug_word:
                print("tagsets={} coltags={} new_cats={} cur_cats={}"
                      .format(tagsets, coltags, new_cats, cur_cats))
            if "detail" in new_cats:
                if not any(coltags):  # Only if no tags so far
                    coltags = merge_tagsets(coltags, tagsets)
                if celltext == debug_word:
                    print("stopping on detail after merge")
                break
            elif ("non-finite" in new_cats and
                  cur_cats & set(("mood", "tense", "non-finite", "person",
                                  "number"))):
                if celltext == debug_word:
                    print("stopping on non-finite")
                break
            elif ("mood" in new_cats and
                  "mood" in cur_cats):
                if celltext == debug_word:
                    print("stopping on mood-mood")
                break
            elif "number" in cur_cats and "number" in new_cats:
                if celltext == debug_word:
                    print("stopping on number-number")
                break
            elif "number" in cur_cats and "gender" in new_cats:
                if celltext == debug_word:
                    print("stopping on number-gender")
                break
            else:
                # Merge tags and continue to next header up/left in the table
                coltags = merge_tagsets(coltags, tagsets)
                if celltext == debug_word:
                    print("merged: {}".format(coltags))
    if coltags is None:
        coltags = set([()])
    #print("HDRSPANS:", list((x.start, x.colspan, x.tagsets) for x in hdrspans))
    if celltext == debug_word:
        print("COMPUTE_COLTAGS {} {} {}: {}"
              .format(start, colspan, mark_used, coltags))
    assert isinstance(coltags, set)
    assert all(isinstance(x, tuple) for x in coltags)
    return coltags


def lang_specific_tags(lang, pos, form):
    """Extracts tags from the word form itself in a language-specific way.
    This may also adjust the word form.
    For example, German inflected verb forms don't have person and number
    specified in the table, but include a pronoun.  This returns adjusted
    form and a list of tags."""
    assert isinstance(lang, str)
    assert isinstance(pos, str)
    assert isinstance(form, str)
    key = (lang, pos)
    r = specific_by_lang_re.get(key)
    if r is None:
        return form, []
    m = re.search(r, form)
    if m is None:
        return form, []
    v = specific_by_lang_map[key][m.group(0)]
    form = form[:m.start()] + form[m.end():]
    return form, v


def parse_simple_table(ctx, word, lang, pos, rows, titles, source):
    """This is the default table parser.  Despite its name, it can parse
    complex tables.  This returns a list of forms to be added to the
    part-of-speech, or None if the table could not be parsed."""
    assert isinstance(ctx, Wtp)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert isinstance(pos, str)
    assert isinstance(rows, list)
    assert isinstance(source, str)
    for row in rows:
        for col in row:
            assert isinstance(col, InflCell)
    assert isinstance(titles, list)
    for x in titles:
        assert isinstance(x, str)
    # print("PARSE_SIMPLE_TABLE: TITLES:", titles)
    # print("ROWS:")
    # for row in rows:
    #     print("  ", row)
    ret = []
    hdrspans = []
    col_has_text = []
    rownum = 0
    title = None
    global_tags = []
    word_tags = []
    for title in titles:
        more_global_tags, more_word_tags, extra_forms = \
            parse_title(title, source)
        global_tags.extend(more_global_tags)
        word_tags.extend(more_word_tags)
        ret.extend(extra_forms)
    cell_rowcnt = collections.defaultdict(int)
    for row in rows:
        # print("ROW:", row)
        if not row:
            continue  # Skip empty rows without incrementing i
        if (row[0].is_title and
            row[0].text and
            not is_superscript(row[0].text[0]) and
            row[0].text not in infl_map and
            not re.match(infl_start_re, row[0].text) and
            all(x.is_title == row[0].is_title and
                x.text == row[0].text
                for x in row)):
            if row[0].text and title is None:
                title = row[0].text
                if re.match(r"(Note:|Notes:)", title):
                    continue
                more_global_tags, more_word_tags, extra_forms = \
                    parse_title(title, source)
                global_tags.extend(more_global_tags)
                word_tags.extend(more_word_tags)
                ret.extend(extra_forms)
            continue  # Skip title rows without incrementing i
        rowtags = set([()])
        have_hdr = False
        have_text = False
        samecell_cnt = 0
        col0_hdrspan = None
        col0_followed_by_nonempty = False
        for j, cell in enumerate(row):
            colspan = cell.colspan
            if samecell_cnt == 0:
                # First column of a (possible multi-column) cell
                samecell_cnt = colspan - 1
            else:
                assert samecell_cnt > 0
                cell_initial = False
                samecell_cnt -= 1
                continue
            first_row_of_cell = cell_rowcnt[id(cell)] == 0
            cell_rowcnt[id(cell)] += 1
            # print("  COL:", col)
            col = cell.text
            if not col:
                continue
            # print(rownum, j, col)
            if cell.is_title:
                # It is a header cell
                col = re.sub(r"\s+", " ", col)
                text, refs, defs, hdr_tags = clean_header(word, col, True)
                if not text:
                    continue
                if text not in infl_map:
                    text1 = re.sub(r"\s*\([^)]*\)", "", text)
                    if text1 in infl_map:
                        text = text1
                    else:
                        text1 = re.sub(r"\s*,+\s+", " ", text)
                        text1 = re.sub(r"\s+", " ", text1)
                        if text1 in infl_map:
                            text = text1
                        elif not re.match(infl_start_re, text):
                            if text not in IGNORED_COLVALUES:
                                ctx.debug("inflection table: "
                                          "unhandled header: {!r}"
                                          .format(col))
                                text = "error-unrecognized-form"
                            continue
                # Mark that the column has text (we are not at top)
                while len(col_has_text) <= j:
                    col_has_text.append(False)
                col_has_text[j] = True
                # Check if the header expands to reset hdrspans
                v = expand_header(ctx, word, lang, text, [], silent=True)
                if any("!" in tt for tt in v):
                    # Reset column headers (only on first row of cell)
                    if first_row_of_cell:
                        # print("RESET HDRSPANS on: {}".format(text))
                        hdrspans = []
                    continue
                # Text between headers on a row causes earlier headers to
                # be reset
                if have_text:
                    #print("  HAVE_TEXT BEFORE HDR:", col)
                    # Reset rowtags if new title column after previous
                    # text cells
                    # XXX beware of header "—": "" - must not clear on that if
                    # it expands to no tags
                    rowtags = set([()])
                have_hdr = True
                # print("HAVE_HDR:", col)
                # Update rowtags and coltags
                new_rowtags = set()
                new_coltags = set()
                all_hdr_tags = set()
                for rt0 in rowtags:
                    for ct0 in compute_coltags(hdrspans, j, colspan, False,
                                               col):
                        tags0 = set(rt0) | set(ct0) | set(global_tags)
                        alt_tags = expand_header(ctx, word, lang, text, tags0)
                        all_hdr_tags.update(alt_tags)
                        for tt in alt_tags:
                            new_coltags.add(tt)
                            # XXX which ones need to be removed?
                            tags = tuple(sorted(set(tt) | set(rt0) |
                                                set(hdr_tags)))
                            new_rowtags.add(tags)
                rowtags = new_rowtags
                new_coltags = set(x for x in new_coltags
                                  if not any(t in noinherit_tags for t in x))
                if any(new_coltags):
                    hdrspan = HdrSpan(j, colspan, rownum, new_coltags, col)
                    hdrspans.append(hdrspan)
                    # Handle headers that are above left-side header
                    # columns and are followed by personal pronouns in
                    # remaining columns (basically headers that
                    # evaluate to no tags).  In such cases widen the
                    # left-side header to the full row.
                    if j == 0:
                        assert col0_hdrspan is None
                        col0_hdrspan = hdrspan
                    elif (col0_hdrspan is not None and
                          any(all_hdr_tags) and
                          not (all(valid_tags[t] in ("person", "gender",
                                                     "number")
                                   for ts in all_hdr_tags
                                   for t in ts) and
                               all(valid_tags[t] in ("number", "mood",
                                                     "aspect", "tense",
                                                     "voice", "non-finite",
                                                     "case", "possession")
                                   for ts in col0_hdrspan.tagsets
                                   for t in ts))):
                        # if col0_hdrspan is not None:
                        #     print("COL0 FOLLOWED HDR: {!r} by {!r} TAGS {}"
                        #           .format(col0_hdrspan.text, col,
                        #                   all_hdr_tags))
                        col0_followed_by_nonempty = True
                continue

            # It is a normal text cell
            if col in IGNORED_COLVALUES:
                continue

            # These values are ignored, at least form now
            if re.match(r"^(# |\(see )", col):
                continue

            if j == 0 and (not col_has_text or not col_has_text[0]):
                continue  # Skip text at top left, as in Icelandic, Faroese
            # if col0_hdrspan is not None:
            #     print("COL0 FOLLOWED NONHDR: {!r} by {!r}"
            #           .format(col0_hdrspan.text, col))
            col0_followed_by_nonempty = True
            have_text = True
            while len(col_has_text) <= j:
                col_has_text.append(False)
            col_has_text[j] = True
            # Determine column tags for the multi-column cell
            combined_coltags = compute_coltags(hdrspans, j, colspan, True, col)
            # print("HAVE_TEXT:", repr(col))
            # Split the text into separate forms
            col = re.sub(r"[ \t\r]+", " ", col)
            # Split the cell text into alternatives
            if col and is_superscript(col[0]):
                alts = [col]
            else:
                separators = [";", "•", r"\n", " or "]
                if col.find(" + ") < 0:
                    separators.append(",")
                    if not col.endswith("/"):
                        separators.append("/")
                alts = split_at_comma_semi(col, separators=separators)
            # Handle the special case where romanization is given under
            # normal form, e.g. in Russian.  There can be multiple
            # comma-separated forms in each case.
            if (len(alts) % 2 == 0 and
                all(classify_desc(re.sub(r"\^.*$", "",
                                         "".join(xx for xx in x
                                                 if not is_superscript(xx))))
                    == "other"
                    for x in alts[:len(alts) // 2]) and
                all(classify_desc(re.sub(r"\^.*$", "",
                                         "".join(xx for xx in x
                                                 if not is_superscript(xx))))
                    in ("romanization", "english")
                    for x in alts[len(alts) // 2:])):
                alts = list(zip(alts[:len(alts) // 2],
                                alts[len(alts) // 2:]))
            else:
                alts = list((x, "") for x in alts)
            # Generate forms from the alternatives
            for form, base_roman in alts:
                form = form.strip()
                extra_tags = []
                form, refs, defs, hdr_tags = clean_header(word, form, False)
                extra_tags.extend(hdr_tags)
                if base_roman:
                    base_roman, _, _, hdr_tags = clean_header(word, base_roman,
                                                              False)
                    extra_tags.extend(hdr_tags)
                ipas = []
                if form.find("/") >= 0:
                    for m in re.finditer(r"/[^/]*/", form):
                        ipas.append(m.group(0))
                    form = re.sub(r"/[^/]*/", "", form)
                form = re.sub(r"^\s*,\s*", "", form)
                form = re.sub(r"\s*,\s*$", "", form)
                form = re.sub(r"\s*(,\s*)+", ", ", form)
                form = re.sub(r"(?i)^Main:", "", form)
                form = re.sub(r"\s+", " ", form)
                form = form.strip()
                if form.startswith("*"):
                    form = form[1:]
                roman = base_roman
                # Handle parentheses in the table element.  We parse
                # tags anywhere and romanizations anywhere but beginning.
                m = re.search(r"\s*\(([^)]*)\)", form)
                if m is not None:
                    paren = m.group(1)
                    if classify_desc(paren) == "tags":
                        tagsets1, topics1 = decode_tags(paren)
                        if not topics1:
                            for ts in tagsets1:
                                extra_tags.extend(ts)
                            form = (form[:m.start()] + " " +
                                    form[m.end():]).strip()
                    elif (m.start() > 0 and not roman and
                          classify_desc(form[:m.start()]) == "other" and
                          classify_desc(paren) in ("romanization", "english")):
                        roman = paren
                        form = (form[:m.start()] + " " + form[m.end():]).strip()
                # Ignore certain forms that are not really forms
                if form in ("", "not used", "not applicable", "unchanged"):
                    continue
                # print("ROWTAGS:", rowtags)
                # print("COLTAGS:", combined_coltags)
                # print("FORM:", repr(form))
                # Merge column tags and row tags.  We give preference
                # to moods etc coming from rowtags (cf. austteigen/German/Verb
                # imperative forms).
                for rt in rowtags:
                    for ct in combined_coltags:
                        tags = set(global_tags)
                        tags.update(extra_tags)
                        tags.update(rt)
                        # Merge tags from column.  For certain kinds of tags,
                        # those coming from row take precedence.
                        old_tags = set(tags)
                        for t in ct:
                            c = valid_tags[t]
                            if (c in ("mood",) and
                                any(valid_tags[tt] == c
                                    for tt in old_tags)):
                                continue
                            tags.add(t)

                        # Extract language-specific tags from the
                        # form.  This may also adjust the form.
                        form, lang_tags = lang_specific_tags(lang, pos, form)
                        tags.update(lang_tags)
                        # For non-finite verb forms, see if they would have
                        # a gender/class suffix
                        if pos == "verb" and any(valid_tags[t] == "non-finite"
                               for t in tags):
                            form, tt = parse_head_final_tags(ctx, lang, form)
                            tags.update(tt)

                        # Many Russian (and other Slavic?) inflection tables
                        # have animate/inanimate distinction that generates
                        # separate entries for neuter/feminine, but the
                        # distinction only applies to masculine.  Remove them
                        # form neuter/feminine and eliminate duplicates.
                        if lang in ["Russian"]:
                            for t1 in ("animate", "inanimate"):
                                for t2 in ("neuter", "feminine"):
                                    if (t1 in tags and t2 in tags and
                                        "masculine" not in tags and
                                        "plural" not in tags):
                                        tags.remove(t1)

                        # Remove "personal" tag if have nth person; these
                        # come up with e.g. reconhecer/Portuguese/Verb.  But
                        # not if we also have "pronoun"
                        if ("personal" in tags and
                            "pronoun" not in tags and
                            any(x in tags for x in
                               ["first-person", "second-person",
                                "third-person"])):
                            tags.remove("personal")

                        # If we have impersonal, remove person and number.
                        # This happens with e.g. viajar/Portuguese/Verb
                        if "impersonal" in tags:
                            tags = tags - set(["first-person", "second-person",
                                               "third-person",
                                               "singular", "plural"])

                        # Remove unnecessary "positive" tag from verb forms
                        if pos == "verb" and "positive" in tags:
                            if "negative" in tags:
                                tags.remove("negative")
                            tags.remove("positive")

                        # Remove the dummy mood tag that we sometimes
                        # use to block adding other mood and related
                        # tags
                        tags = tags - set(["dummy-mood"])

                        # Perform language-specific tag replacements according
                        # to rules in a table.
                        changed = True
                        while changed:
                            changed = False
                            for lst in lang_tag_mappings:
                                assert isinstance(lst, (list, tuple))
                                assert len(lst) >= 3
                                if lang not in lst[0] or pos not in lst[1]:
                                    continue
                                for src, dst in lst[2:]:
                                    assert isinstance(src, (list, tuple))
                                    assert isinstance(dst, (list, tuple))
                                    if all(t in tags for t in src):
                                        tags = (tags - set(src)) | set(dst)
                                        changed = True

                        # Add the form
                        tags = list(sorted(tags))
                        dt = {"form": form, "tags": tags,
                              "source": source}
                        if roman:
                            dt["roman"] = roman
                        if ipas:
                            dt["ipa"] = ", ".join(ipas)
                        ret.append(dt)
        # End of row
        if col0_hdrspan is not None and not col0_followed_by_nonempty:
            # If a column-0 header is only followed by headers that yield
            # no tags, expand it to entire row
            # print("EXPANDING COL0: {} from {} to {} cols"
            #       .format(col0_hdrspan.text, col0_hdrspan.colspan,
            #               len(row)))
            col0_hdrspan.colspan = len(row)
        rownum += 1
    # XXX handle refs and defs
    # for x in hdrspans:
    #     print("  HDRSPAN {} {} {} {!r}"
    #           .format(x.start, x.colspan, x.tagsets, x.text))

    # Post-process German nouns with articles
    if any("noun" in x["tags"] for x in ret):
        if lang in ("Alemannic German", "Cimbrian", "German",
                    "German Low German", "Hunsrik", "Luxembourish",
                    "Pennsylvania German"):
            new_ret = []
            for dt in ret:
                tags = dt["tags"]
                if "noun" in tags:
                    tags = list(t for t in tags if t != "noun")
                elif "indefinite" in tags or "definite" in tags:
                    continue  # Skip the articles
                # XXX remove: alternative code that adds "article" tag
                #     tags = list(sorted(set(tags) | set(["article"])))
                dt = dt.copy()
                dt["tags"] = tags
                new_ret.append(dt)
            ret = new_ret

    if word_tags:
        word_tags = list(sorted(set(word_tags)))
        dt = {"form": " ".join(word_tags),
              "source": source + " title",
              "tags": ["word-tags"]}
        ret.append(dt)

    return ret


def handle_generic_table(ctx, data, word, lang, pos, rows, titles, source):
    assert isinstance(ctx, Wtp)
    assert isinstance(data, dict)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert isinstance(pos, str)
    assert isinstance(rows, list)
    assert isinstance(source, str)
    for row in rows:
        assert isinstance(row, list)
        for x in row:
            assert isinstance(x, InflCell)
    assert isinstance(titles, list)
    for x in titles:
        assert isinstance(x, str)

    # Try to parse the table as a simple table
    ret = parse_simple_table(ctx, word, lang, pos, rows, titles, source)
    if ret is None:
        # XXX handle other table formats
        # We were not able to handle the table
        return

    # Add the returned forms but eliminate duplicates.
    have_forms = set()
    for dt in data.get("forms", ()):
        have_forms.add(freeze(dt))
    for dt in ret:
        fdt = freeze(dt)
        if fdt in have_forms:
            continue  # Don't add duplicates Some Russian words have
        # Declension and Pre-reform declension partially duplicating
        # same data.  Don't add "dated" tags variant if already have
        # the same without "dated" from the modern declension table
        tags = dt.get("tags", [])
        for dated_tag in ("dated",):
            if dated_tag in tags:
                dt2 = dt.copy()
                tags2 = list(x for x in tags if x != dated_tag)
                dt2["tags"] = tags2
                if tags2 and freeze(dt2) in have_forms:
                    break  # Already have without archaic
        else:
            have_forms.add(fdt)
            data_append(ctx, data, "forms", dt)


def handle_wikitext_table(config, ctx, word, lang, pos,
                          data, tree, titles, source):
    """Parses a table from parsed Wikitext format into rows and columns of
    InflCell objects and then calls handle_generic_table() to parse it into
    forms.  This adds the forms into ``data``."""
    assert isinstance(config, WiktionaryConfig)
    assert isinstance(ctx, Wtp)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert isinstance(pos, str)
    assert isinstance(data, dict)
    assert isinstance(tree, WikiNode)
    assert tree.kind == NodeKind.TABLE
    assert isinstance(titles, list)
    assert isinstance(source, str)
    for x in titles:
        assert isinstance(x, str)
    # Imported here to avoid a circular import
    from wiktextract.page import clean_node, recursively_extract
    # print("HANDLE_WIKITEXT_TABLE", titles)

    cols_fill = []    # Filling for columns with rowspan > 1
    cols_filled = []  # Number of remaining rows for which to fill the column
    cols_headered = []  # True when column contains headers even if normal fmt
    rows = []
    assert tree.kind == NodeKind.TABLE
    for node in tree.children:
        if not isinstance(node, WikiNode):
            continue
        kind = node.kind
        # print("  {}".format(node))
        if kind == NodeKind.TABLE_CAPTION:
            # print("  CAPTION:", node)
            pass
        elif kind == NodeKind.TABLE_ROW:
            if "vsShow" in node.attrs.get("class", "").split():
                # vsShow rows are those that are intially shown in tables that
                # have more data.  The hidden data duplicates these rows, so
                # we skip it and just process the hidden data.
                continue

            # Parse a table row.
            row = []
            style = None
            for col in node.children:
                if not isinstance(col, WikiNode):
                    continue
                kind = col.kind
                if kind not in (NodeKind.TABLE_HEADER_CELL,
                                NodeKind.TABLE_CELL):
                    print("    UNEXPECTED ROW CONTENT: {}".format(col))
                    continue
                while len(row) < len(cols_filled) and cols_filled[len(row)] > 0:
                    cols_filled[len(row)] -= 1
                    row.append(cols_fill[len(row)])
                try:
                    rowspan = int(col.attrs.get("rowspan", "1"))
                    colspan = int(col.attrs.get("colspan", "1"))
                except ValueError:
                    rowspan = 1
                    colspan = 1
                # print("COL:", col)

                # Process any nested tables recursively.  XXX this
                # should also take prior text before nested tables as
                # headers, e.g., see anglais/Irish/Declension ("Forms
                # with the definite article" before the table)
                tables, rest = recursively_extract(col, lambda x:
                                                   isinstance(x, WikiNode) and
                                                   x.kind == NodeKind.TABLE)
                for tbl in tables:
                    handle_wikitext_table(config, ctx, word, lang, pos, data,
                                          tbl, titles, source)
                # print("REST:", rest)

                celltext = clean_node(config, ctx, None, rest)
                # print("CLEANED:", celltext)

                # This magic value is used as part of header detection
                cellstyle = (col.attrs.get("style", "") + "//" +
                             col.attrs.get("class", "") + "//" +
                             str(kind))
                if not row:
                    style = cellstyle
                target = None
                idx = celltext.find(": ")
                is_title = False
                if idx >= 0 and celltext[:idx] in infl_map:
                    target = celltext[idx + 2:].strip()
                    # XXX add tags from target
                    celltext = celltext[:idx]
                    is_title = True
                elif (kind == NodeKind.TABLE_HEADER_CELL or
                      (re.sub(r"\s+", " ", celltext) in infl_map and
                       celltext != word and
                       celltext not in ("I", "es")) or
                      (style == cellstyle and
                       celltext != word and
                       not style.startswith("////"))):
                    if celltext.find(" + ") < 0:
                        is_title = True
                if (not is_title and len(row) < len(cols_headered) and
                    cols_headered[len(row)]):
                    # Whole column has title suggesting they are headers
                    # (e.g. "Case")
                    is_title = True
                if re.match(r"Conjugation of |Declension of |Inflection of|"
                            r"Mutation of",
                            celltext):
                    is_title = True
                if is_title:
                    while len(cols_headered) <= len(row):
                        cols_headered.append(False)
                    v = expand_header(ctx, word, lang, celltext, [],
                                      silent=True)
                    if any("*" in tt for tt in v):
                        cols_headered[len(row)] = True
                        celltext = ""
                # XXX extra tags, see "target" above
                cell = InflCell(celltext, is_title, len(row), colspan, rowspan)
                for i in range(0, colspan):
                    if rowspan > 1:
                        while len(cols_fill) <= len(row):
                            cols_fill.append(None)
                            cols_filled.append(0)
                        cols_fill[len(row)] = cell
                        cols_filled[len(row)] = rowspan - 1
                    row.append(cell)
            if not row:
                continue
            while len(row) < len(cols_fill) and cols_filled[len(row)] > 0:
                cols_filled[len(row)] -= 1
                row.append(cols_fill[len(row)])
            # print("  ROW {!r}".format(row))
            rows.append(row)
        elif kind in (NodeKind.TABLE_HEADER_CELL, NodeKind.TABLE_CELL):
            # print("  TOP-LEVEL CELL", node)
            pass

    # Now we have a table that has been parsed into rows and columns of
    # InflCell objects.  Parse the inflection table from that format.
    handle_generic_table(ctx, data, word, lang, pos, rows, titles, source)


def handle_html_table(config, ctx, word, lang, pos, data, tree, titles, source):
    """Parses a table from parsed HTML format into rows and columns of
    InflCell objects and then calls handle_generic_table() to parse it into
    forms.  This adds the forms into ``data``."""
    assert isinstance(config, WiktionaryConfig)
    assert isinstance(ctx, Wtp)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert isinstance(pos, str)
    assert isinstance(data, dict)
    assert isinstance(tree, WikiNode)
    assert tree.kind == NodeKind.HTML and tree.args == "table"
    assert isinstance(titles, list)
    for x in titles:
        assert isinstance(x, str)
    assert isinstance(source, str)

    print("HTML TABLES NOT YET IMPLEMENTED at {}/{}"
          .format(word, lang))


def parse_inflection_section(config, ctx, data, word, lang, pos, section, tree):
    """Parses an inflection section on a page.  ``data`` should be the
    data for a part-of-speech, and inflections will be added to it."""

    # print("PARSE_INFLECTION_SECTION {}/{}/{}/{}"
    #       .format(word, lang, pos, section))
    assert isinstance(config, WiktionaryConfig)
    assert isinstance(ctx, Wtp)
    assert isinstance(data, dict)
    assert isinstance(word, str)
    assert isinstance(lang, str)
    assert pos in PARTS_OF_SPEECH
    assert isinstance(section, str)
    assert isinstance(tree, WikiNode)
    source = section

    def recurse_navframe(node, titles):
        titleparts = []

        def recurse1(node, in_navhead):
            if isinstance(node, (list, tuple)):
                for x in node:
                    recurse1(x, in_navhead)
                return
            if isinstance(node, str):
                titleparts.append(node)
                return
            if not isinstance(node, WikiNode):
                ctx.debug("inflection table: unhandled in NavFrame: {}"
                          .format(node))
                return
            kind = node.kind
            if kind == NodeKind.HTML:
                classes = node.attrs.get("class", "").split()
                if "NavToggle" in classes:
                    return
                if "NavHead" in classes:
                    # print("NAVHEAD:", node)
                    for x in node.children:
                        recurse1(x, True)
                    return
                if "NavContent" in classes:
                    title = "".join(titleparts).strip()
                    title = html.unescape(title)
                    title = title.strip()
                    new_titles = list(titles)
                    if not re.match(r"(Note:|Notes:)", title):
                        new_titles.append(title)
                    recurse(node, new_titles)
                    return
            elif kind == NodeKind.LINK:
                if len(node.args) > 1:
                    for x in node.args[1:]:
                        recurse1(x, in_navhead)
                else:
                    recurse1(node.args[0], in_navhead)
            for x in node.children:
                recurse1(x, in_navhead)
        recurse1(node, False)

    def recurse(node, titles):
        if not isinstance(node, WikiNode):
            return
        kind = node.kind
        if kind == NodeKind.TABLE:
            handle_wikitext_table(config, ctx, word, lang, pos,
                                  data, node, titles, source)
            return
        elif kind == NodeKind.HTML and node.args == "table":
            handle_html_table(config, ctx, word, lang, pos, data, node, titles,
                              source)
            return
        elif kind in (NodeKind.LEVEL2, NodeKind.LEVEL3, NodeKind.LEVEL4,
                      NodeKind.LEVEL5, NodeKind.LEVEL6):
            return  # Skip subsections
        if (kind == NodeKind.HTML and node.args == "div" and
            "NavFrame" in node.attrs.get("class", "").split()):
            recurse_navframe(node, titles)
            return
        for x in node.children:
            recurse(x, titles)

    assert tree.kind == NodeKind.ROOT
    for x in tree.children:
        recurse(x, [])

    # XXX this code is used for extracting tables for inflection tests
    with open("temp.XXX", "w") as f:
        f.write(word + "\n")
        f.write(lang + "\n")
        f.write(pos + "\n")
        f.write(section + "\n")
        text = ctx.node_to_wikitext(tree)
        f.write(text + "\n")

# XXX check interdecir/Spanish - singular/plural issues

# XXX viajar/Portuguese: gerund has singular+plural - check if all columns
# containing same tag category are included, and then don't include anything