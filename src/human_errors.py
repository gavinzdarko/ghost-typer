"""Human-realistic typos, misspellings, and grammar errors.

Provides three error types that mimic real human typing:
1. Common misspellings (teh -> the, wierd -> weird, etc.)
2. Adjacent-key misclicks (QWERTY proximity errors)
3. Teen grammar/punctuation errors (your/you're, there/their, etc.)
"""

from __future__ import annotations

import random
import re
from typing import Optional

# ── 1. Common human misspellings ──
# word -> list of plausible misspellings a human would make
COMMON_MISSPELLINGS: dict[str, list[str]] = {
    "the": ["teh", "hte", "th"],
    "that": ["taht", "tath"],
    "this": ["tihs", "thsi"],
    "they": ["tehy", "thye"],
    "their": ["thier", "theri"],
    "there": ["theer", "tehre"],
    "these": ["thees", "tehse"],
    "them": ["tehm", "thme"],
    "then": ["tehn", "hten"],
    "than": ["tahn", "htan"],
    "think": ["thikn", "thnk"],
    "thing": ["thign", "tihng"],
    "things": ["thigns", "tihngs"],
    "through": ["throught", "throuhg", "trhough"],
    "thought": ["thougth", "thougt"],
    "though": ["thougth", "thouhg"],
    "would": ["woudl", "wuold", "wolud"],
    "could": ["coudl", "cuold"],
    "should": ["shoudl", "shuold"],
    "about": ["baout", "abotu", "abuot"],
    "because": ["becuase", "becasue", "beacuse"],
    "before": ["beofre", "befoer"],
    "after": ["aftre", "atfer"],
    "again": ["agian", "agin"],
    "against": ["agianst", "aganist"],
    "actually": ["acutally", "actualy"],
    "always": ["alwyas", "alwasy"],
    "another": ["anohter", "anotehr"],
    "around": ["aroudn", "aorund"],
    "available": ["avaliable", "avaialble"],
    "between": ["bewteen", "betwen"],
    "different": ["diffrent", "diferent", "differnt"],
    "does": ["dose", "deos"],
    "during": ["durign", "druign"],
    "enough": ["enouhg", "enought"],
    "every": ["evrey", "eveyr"],
    "example": ["exmaple", "exapmle"],
    "experience": ["experiance", "expereince"],
    "first": ["frist", "fisrt"],
    "friend": ["freind", "firend"],
    "from": ["form", "fomr", "frome"],
    "going": ["goign", "giong"],
    "great": ["gerat", "graet"],
    "have": ["ahve", "hvae"],
    "here": ["heer", "ehre"],
    "just": ["jsut", "juts"],
    "know": ["knwo", "konw"],
    "like": ["liek", "lkie"],
    "little": ["littel", "litle"],
    "look": ["lokk", "loook"],
    "make": ["maek", "mkae"],
    "many": ["mny", "mnay"],
    "more": ["moer", "mroe"],
    "much": ["muhc", "mcuh"],
    "never": ["nver", "nevr"],
    "only": ["olny", "onyl"],
    "other": ["ohter", "otehr"],
    "over": ["oevr", "voer"],
    "people": ["poeple", "peopel", "ppl"],
    "place": ["palce", "plcae"],
    "probably": ["probalby", "probaly", "prolly"],
    "really": ["realy", "relly", "raelly"],
    "right": ["rigth", "rihgt"],
    "said": ["siad", "sadi"],
    "same": ["smae", "saem"],
    "since": ["sinec", "sicne"],
    "some": ["soem", "smoe"],
    "something": ["somethign", "somehting"],
    "sometimes": ["sometimse", "soetimes"],
    "still": ["sitll", "stlil"],
    "take": ["taek", "tkae"],
    "time": ["tiem", "tmie"],
    "together": ["togehter", "togather"],
    "too": ["tto", "oto"],
    "until": ["untill", "unitl"],
    "very": ["vrey", "vrey"],
    "want": ["wnat", "watn"],
    "water": ["watre", "waetr"],
    "well": ["wlel", "weell"],
    "were": ["wree", "weer"],
    "what": ["waht", "whta"],
    "when": ["wehn", "whne"],
    "where": ["wehre", "whree"],
    "which": ["whihc", "wich"],
    "while": ["whiel", "whlile"],
    "with": ["wiht", "wtih"],
    "work": ["wrok", "owrk"],
    "world": ["wrold", "wolrd"],
    "write": ["wirte", "wrtie"],
    "writing": ["wirting", "wrtiting"],
    "your": ["yuor", "yoru"],
    "also": ["aslo", "alse"],
    "even": ["eevn", "evne"],
    "come": ["ocme", "coem"],
    "back": ["bakc", "abck"],
    "good": ["godo", "goood"],
    "need": ["nede", "neeed"],
    "being": ["beingg", "beign"],
    "into": ["itno", "inot"],
    "most": ["msot", "mots"],
    "each": ["eahc", "ecah"],
    "made": ["maed", "mdae"],
    "done": ["dnoe", "donn"],
    "keep": ["kepe", "keeep"],
    "help": ["hlep", "hepl"],
    "sure": ["srue", "suer"],
    "feel": ["fele", "fele"],
    "start": ["strat", "steart"],
    "might": ["migth", "mihgt"],
    "already": ["alredy", "alreayd"],
    "believe": ["beleive", "belive"],
    "receive": ["recieve", "recive"],
    "definitely": ["definately", "definitly", "defintely"],
    "necessary": ["neccessary", "necessery", "neccesary"],
    "separate": ["seperate", "seprate"],
    "environment": ["enviroment", "enviornment"],
    "government": ["goverment", "govenment"],
    "tomorrow": ["tommorow", "tomorow"],
    "wednesday": ["wendsday", "wensday"],
    "beautiful": ["beautifull", "beatiful"],
    "beginning": ["begining", "beggining"],
    "remember": ["remeber", "remmeber"],
    "occurred": ["occured", "ocurred"],
    "immediately": ["immediatly", "imediately"],
    "apparently": ["apparantly", "aparently"],
    "interesting": ["intresting", "intersting"],
    "especially": ["especailly", "espically"],
}

# ── 2. Teen grammar/punctuation errors ──
# (wrong_word, correct_word, context_hint)
# context_hint helps decide when to apply: "before_verb" means wrong form before a verb, etc.
GRAMMAR_SWAPS: list[dict] = [
    # your / you're
    {"find": r"\byou're\b", "replace": "your", "prob": 0.3},
    {"find": r"\byou are\b", "replace": "your", "prob": 0.15},
    # their / there / they're
    {"find": r"\bthey're\b", "replace": "their", "prob": 0.25},
    {"find": r"\bthere\b(?=\s+(?:is|are|was|were|will|would|could|should))", "replace": "their", "prob": 0.15},
    # its / it's
    {"find": r"\bit's\b", "replace": "its", "prob": 0.3},
    {"find": r"\bit is\b", "replace": "its", "prob": 0.15},
    # could have / could of
    {"find": r"\bcould have\b", "replace": "could of", "prob": 0.4},
    {"find": r"\bwould have\b", "replace": "would of", "prob": 0.4},
    {"find": r"\bshould have\b", "replace": "should of", "prob": 0.4},
    {"find": r"\bcould've\b", "replace": "could of", "prob": 0.35},
    {"find": r"\bwould've\b", "replace": "would of", "prob": 0.35},
    {"find": r"\bshould've\b", "replace": "should of", "prob": 0.35},
    # a lot / alot
    {"find": r"\ba lot\b", "replace": "alot", "prob": 0.35},
    # than / then confusion
    {"find": r"\bthan\b", "replace": "then", "prob": 0.15},
    # affect / effect
    {"find": r"\baffect\b", "replace": "effect", "prob": 0.2},
    # lose / loose
    {"find": r"\blose\b", "replace": "loose", "prob": 0.25},
    # to / too
    {"find": r"\btoo\b", "replace": "to", "prob": 0.15},
    # were / where
    {"find": r"\bwere\b", "replace": "where", "prob": 0.1},
]

# Punctuation errors teens make
# Research: run-on sentences, comma splices, missing commas after introductory phrases,
# missing commas before conjunctions are top student essay errors (Grammarly study)
PUNCTUATION_ERRORS: list[dict] = [
    # No comma before "but", "and", "so" in compound sentences (top essay error)
    {"find": r",\s*(but|and|so|or)\b", "replace_fn": lambda m: " " + m.group(1), "prob": 0.45},
    # No apostrophe in contractions: don't -> dont, can't -> cant, won't -> wont
    {"find": r"\bdon't\b", "replace": "dont", "prob": 0.40},
    {"find": r"\bcan't\b", "replace": "cant", "prob": 0.40},
    {"find": r"\bwon't\b", "replace": "wont", "prob": 0.40},
    {"find": r"\bdidn't\b", "replace": "didnt", "prob": 0.40},
    {"find": r"\bdoesn't\b", "replace": "doesnt", "prob": 0.35},
    {"find": r"\bisn't\b", "replace": "isnt", "prob": 0.35},
    {"find": r"\bwasn't\b", "replace": "wasnt", "prob": 0.35},
    {"find": r"\baren't\b", "replace": "arent", "prob": 0.35},
    {"find": r"\bweren't\b", "replace": "werent", "prob": 0.35},
    {"find": r"\bI'm\b", "replace": "im", "prob": 0.45},
    {"find": r"\bI'll\b", "replace": "ill", "prob": 0.35},
    {"find": r"\bI've\b", "replace": "ive", "prob": 0.40},
    {"find": r"\bI'd\b", "replace": "id", "prob": 0.35},
    {"find": r"\bthere's\b", "replace": "theres", "prob": 0.30},
    {"find": r"\bthat's\b", "replace": "thats", "prob": 0.30},
    {"find": r"\blet's\b", "replace": "lets", "prob": 0.30},
    {"find": r"\bwhat's\b", "replace": "whats", "prob": 0.30},
    {"find": r"\bhere's\b", "replace": "heres", "prob": 0.30},
    # Sentence boundary errors — mutually exclusive (run-on, no cap, or comma splice)
    # Only one of these fires per occurrence since they all match ". [A-Z]"
    {"find": r"\.\s+([A-Z])", "replace_fn": lambda m: " " + m.group(1).lower(), "prob": 0.10,
     "group": "sentence_boundary"},  # run-on sentence
    {"find": r"\.\s+([A-Z])", "replace_fn": lambda m: ". " + m.group(1).lower(), "prob": 0.10,
     "group": "sentence_boundary"},  # no capitalization
    {"find": r"\.\s+([A-Z])", "replace_fn": lambda m: ", " + m.group(1).lower(), "prob": 0.06,
     "group": "sentence_boundary"},  # comma splice
    # Missing period at end of sentence before newline
    {"find": r"([a-z])\.\n", "replace_fn": lambda m: m.group(1) + "\n", "prob": 0.25},
    # Lowercase "i" instead of "I" (research: extremely common in teen writing)
    {"find": r"\bI\b", "replace": "i", "prob": 0.30},
    # Missing comma after introductory phrase (top essay error)
    {"find": r"^(However|Therefore|Furthermore|Meanwhile|Afterwards|Finally|Actually|Basically),\s",
     "replace_fn": lambda m: m.group(1) + " ", "prob": 0.3},
]

# Textese that leaks into schoolwork (research: 64% of teens do this occasionally)
TEXTESE_LEAKS: list[dict] = [
    {"find": r"\bbecause\b", "replace": "bc", "prob": 0.08},
    {"find": r"\bto be honest\b", "replace": "tbh", "prob": 0.10},
    {"find": r"\bright now\b", "replace": "rn", "prob": 0.06},
    {"find": r"\bI don't know\b", "replace": "idk", "prob": 0.08},
    {"find": r"\bin my opinion\b", "replace": "imo", "prob": 0.10},
    {"find": r"\bthrough\b", "replace": "thru", "prob": 0.05},
    {"find": r"\bgoing to\b", "replace": "gonna", "prob": 0.10},
    {"find": r"\bwant to\b", "replace": "wanna", "prob": 0.08},
    {"find": r"\bprobably\b", "replace": "prolly", "prob": 0.06},
]


class HumanErrors:
    """Applies realistic human errors to text before it gets typed."""

    def __init__(
        self,
        misspelling_rate: float = 0.03,
        grammar_error_rate: float = 0.15,
        punctuation_error_rate: float = 0.2,
        seed: int | None = None,
    ):
        self._rng = random.Random(seed)
        self.misspelling_rate = misspelling_rate
        self.grammar_error_rate = grammar_error_rate
        self.punctuation_error_rate = punctuation_error_rate

    def apply_misspellings(self, text: str) -> list[tuple[str, str, int]]:
        """Find words to misspell. Returns list of (wrong, correct, position)."""
        misspellings: list[tuple[str, str, int]] = []
        for match in re.finditer(r"\b(\w+)\b", text):
            word = match.group(1)
            lower = word.lower()
            if lower in COMMON_MISSPELLINGS and self._rng.random() < self.misspelling_rate:
                wrong = self._rng.choice(COMMON_MISSPELLINGS[lower])
                # Preserve original capitalization
                if word[0].isupper():
                    wrong = wrong[0].upper() + wrong[1:]
                if word.isupper():
                    wrong = wrong.upper()
                misspellings.append((wrong, word, match.start()))
        return misspellings

    def apply_grammar_errors(self, text: str) -> str:
        """Apply teen-style grammar errors to the text. These are NOT corrected."""
        if self._rng.random() > self.grammar_error_rate:
            return text

        for swap in GRAMMAR_SWAPS:
            if self._rng.random() < swap["prob"]:
                text = re.sub(swap["find"], swap["replace"], text, count=1)

        return text

    def apply_punctuation_errors(self, text: str) -> str:
        """Apply teen-style punctuation errors. These are NOT corrected."""
        if self._rng.random() > self.punctuation_error_rate:
            return text

        fired_groups: set[str] = set()
        for rule in PUNCTUATION_ERRORS:
            # Mutually exclusive groups — only one rule per group fires
            group = rule.get("group")
            if group and group in fired_groups:
                continue
            if self._rng.random() < rule["prob"]:
                if "replace_fn" in rule:
                    text = re.sub(rule["find"], rule["replace_fn"], text, count=1)
                else:
                    text = re.sub(rule["find"], rule["replace"], text, count=1)
                if group:
                    fired_groups.add(group)

        return text

    def apply_textese(self, text: str) -> str:
        """Occasionally leak texting abbreviations into the text.

        Research: 64% of teens admit to using textese in schoolwork occasionally.
        We apply it sparingly so it looks natural — just a slip here and there.
        """
        if self._rng.random() > 0.3:  # only 30% of segments get textese treatment
            return text

        for rule in TEXTESE_LEAKS:
            if self._rng.random() < rule["prob"]:
                text = re.sub(rule["find"], rule["replace"], text, count=1, flags=re.IGNORECASE)

        return text

    def process_text(self, text: str) -> tuple[str, list[tuple[str, str, int]]]:
        """Apply all human errors to text.

        Returns:
            (modified_text, misspellings_to_fix)
            - modified_text has grammar/punctuation/textese errors baked in (not corrected)
            - misspellings_to_fix is a list of (wrong, correct, pos) that the
              typing engine should type wrong then fix
        """
        # Grammar errors are permanent (teen doesn't notice)
        text = self.apply_grammar_errors(text)

        # Textese slips before punctuation (so punctuation rules can affect textese output)
        text = self.apply_textese(text)

        # Punctuation errors applied last (after textese modifies contractions etc.)
        text = self.apply_punctuation_errors(text)

        # Misspellings are temporary (typed wrong, then corrected)
        misspellings = self.apply_misspellings(text)

        return text, misspellings
