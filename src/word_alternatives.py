"""Word alternatives for realistic rewrite simulation.

When a human types, they sometimes write a simpler/rougher version of a phrase
first, then go back and replace it with better wording. This module generates
those "rough draft" alternatives by swapping words with simpler synonyms.
"""

from __future__ import annotations

import random
import re

# Maps a word (lowercase) to simpler/rougher alternatives a human might type first.
# The idea: someone thinks of the simple word first, types it, then remembers
# the better word and rewrites.
WORD_ALTERNATIVES: dict[str, list[str]] = {
    # Adjectives: fancy -> simple
    "remarkable": ["good", "cool", "nice", "great"],
    "excellent": ["good", "great", "nice", "really good"],
    "outstanding": ["great", "really good", "amazing"],
    "magnificent": ["great", "amazing", "really cool"],
    "extraordinary": ["amazing", "really cool", "crazy"],
    "exceptional": ["great", "really good", "super good"],
    "phenomenal": ["amazing", "insane", "crazy good"],
    "spectacular": ["amazing", "awesome", "crazy"],
    "tremendous": ["huge", "big", "really big"],
    "substantial": ["big", "a lot of", "major"],
    "significant": ["big", "important", "major"],
    "considerable": ["a lot of", "big", "pretty big"],
    "magnificent": ["beautiful", "amazing", "gorgeous"],
    "beautiful": ["pretty", "nice", "good looking"],
    "gorgeous": ["pretty", "beautiful", "really pretty"],
    "stunning": ["pretty", "amazing", "gorgeous"],
    "elegant": ["nice", "fancy", "pretty"],
    "sophisticated": ["fancy", "complex", "advanced"],
    "fascinating": ["cool", "interesting", "really cool"],
    "intriguing": ["interesting", "cool", "weird"],
    "compelling": ["interesting", "strong", "good"],
    "crucial": ["important", "key", "big"],
    "essential": ["important", "needed", "key"],
    "fundamental": ["basic", "key", "important"],
    "paramount": ["important", "key", "critical"],
    "inevitable": ["gonna happen", "unavoidable", "bound to happen"],
    "peculiar": ["weird", "strange", "odd"],
    "absurd": ["stupid", "dumb", "ridiculous"],
    "ridiculous": ["stupid", "dumb", "crazy"],
    "adequate": ["enough", "fine", "ok"],
    "sufficient": ["enough", "fine", "ok"],
    "meticulous": ["careful", "detailed", "thorough"],
    "diligent": ["hardworking", "careful", "dedicated"],
    "proficient": ["good at", "skilled", "experienced"],
    "accomplished": ["skilled", "experienced", "good"],
    "formidable": ["tough", "scary", "hard"],
    "daunting": ["scary", "hard", "tough"],
    "tedious": ["boring", "annoying", "long"],
    "monotonous": ["boring", "repetitive", "dull"],
    "exquisite": ["beautiful", "amazing", "perfect"],
    "impeccable": ["perfect", "flawless", "great"],
    "atrocious": ["terrible", "awful", "horrible"],
    "abysmal": ["terrible", "awful", "really bad"],
    "mediocre": ["ok", "average", "meh"],
    "superb": ["great", "amazing", "awesome"],
    "splendid": ["great", "wonderful", "awesome"],
    "marvelous": ["great", "amazing", "awesome"],
    "dreadful": ["terrible", "awful", "horrible"],
    "horrific": ["terrible", "horrible", "awful"],
    "enormous": ["huge", "really big", "massive"],
    "immense": ["huge", "massive", "really big"],
    "minuscule": ["tiny", "small", "really small"],
    "diminutive": ["small", "tiny", "little"],
    "abundant": ["a lot of", "tons of", "plenty of"],
    "scarce": ["rare", "hard to find", "not many"],
    "ample": ["enough", "plenty of", "a lot of"],
    "rapid": ["fast", "quick", "speedy"],
    "swift": ["fast", "quick", "speedy"],
    "sluggish": ["slow", "lazy", "dragging"],
    "lethargic": ["tired", "slow", "lazy"],
    "vigorous": ["strong", "energetic", "intense"],
    "resilient": ["tough", "strong", "bouncing back"],
    "vulnerable": ["weak", "exposed", "at risk"],
    "courageous": ["brave", "bold", "gutsy"],
    "compassionate": ["caring", "kind", "nice"],
    "benevolent": ["kind", "generous", "nice"],
    "malevolent": ["evil", "mean", "bad"],

    # Nouns: fancy -> simple
    "creature": ["animal", "thing", "being"],
    "residence": ["house", "home", "place"],
    "dwelling": ["house", "home", "place"],
    "establishment": ["place", "business", "building"],
    "institution": ["place", "organization", "group"],
    "phenomenon": ["thing", "event", "occurrence"],
    "endeavor": ["attempt", "try", "effort"],
    "accomplishment": ["achievement", "win", "success"],
    "predicament": ["problem", "situation", "mess"],
    "dilemma": ["problem", "choice", "situation"],
    "conundrum": ["puzzle", "problem", "mystery"],
    "catastrophe": ["disaster", "mess", "nightmare"],
    "adversity": ["hardship", "difficulty", "trouble"],
    "prosperity": ["success", "wealth", "good times"],
    "abundance": ["a lot", "plenty", "tons"],
    "scarcity": ["shortage", "lack", "not enough"],
    "magnitude": ["size", "scale", "extent"],
    "vicinity": ["area", "neighborhood", "nearby"],
    "inhabitants": ["people", "residents", "folks"],
    "colleagues": ["coworkers", "teammates", "peers"],
    "acquaintance": ["someone I know", "contact", "person"],
    "individual": ["person", "someone", "guy"],
    "methodology": ["method", "approach", "way"],
    "perspective": ["view", "opinion", "take"],
    "circumstances": ["situation", "conditions", "things"],
    "consequences": ["results", "effects", "outcomes"],

    # Verbs: fancy -> simple
    "demonstrate": ["show", "prove", "display"],
    "illustrate": ["show", "explain", "display"],
    "utilize": ["use", "work with", "apply"],
    "implement": ["do", "set up", "put in place"],
    "comprehend": ["understand", "get", "grasp"],
    "contemplate": ["think about", "consider", "wonder"],
    "acknowledge": ["admit", "recognize", "accept"],
    "accomplish": ["do", "finish", "achieve"],
    "facilitate": ["help", "make easier", "enable"],
    "eliminate": ["remove", "get rid of", "cut"],
    "investigate": ["look into", "check out", "examine"],
    "communicate": ["talk", "tell", "share"],
    "anticipate": ["expect", "predict", "see coming"],
    "appreciate": ["like", "value", "enjoy"],
    "deteriorate": ["get worse", "decline", "fall apart"],
    "exaggerate": ["overdo", "overstate", "stretch"],
    "elaborate": ["explain more", "go into detail", "expand"],
    "contribute": ["help", "add", "give"],
    "distinguish": ["tell apart", "separate", "spot"],
    "emphasize": ["stress", "highlight", "focus on"],
    "manufacture": ["make", "build", "produce"],
    "accumulate": ["collect", "gather", "pile up"],
    "collaborate": ["work together", "team up", "partner"],
    "negotiate": ["talk it out", "discuss", "work out"],
    "persuade": ["convince", "talk into", "win over"],
    "recommend": ["suggest", "say to try", "advise"],
    "guarantee": ["promise", "make sure", "ensure"],
    "necessitate": ["require", "need", "call for"],
    "participate": ["join", "take part", "be in"],
    "concentrate": ["focus", "pay attention", "zero in"],
    "deteriorate": ["get worse", "break down", "fall apart"],
    "predominate": ["dominate", "lead", "be main"],
    "approximate": ["guess", "estimate", "roughly"],

    # Adverbs: fancy -> simple
    "subsequently": ["then", "after", "later"],
    "consequently": ["so", "therefore", "because of that"],
    "furthermore": ["also", "plus", "and"],
    "nevertheless": ["but", "still", "anyway"],
    "nonetheless": ["but", "still", "anyway"],
    "approximately": ["about", "around", "roughly"],
    "predominantly": ["mostly", "mainly", "usually"],
    "simultaneously": ["at the same time", "together", "at once"],
    "occasionally": ["sometimes", "now and then", "once in a while"],
    "frequently": ["often", "a lot", "usually"],
    "immediately": ["right away", "now", "instantly"],
    "ultimately": ["in the end", "finally", "eventually"],
    "essentially": ["basically", "pretty much", "really"],
    "particularly": ["especially", "really", "specifically"],
    "significantly": ["a lot", "really", "majorly"],
    "undoubtedly": ["definitely", "for sure", "no doubt"],
    "presumably": ["probably", "I guess", "likely"],
    "apparently": ["seemingly", "I guess", "it looks like"],
    "precisely": ["exactly", "right", "perfectly"],
    "thoroughly": ["completely", "fully", "totally"],

    # Phrases / transitions
    "however": ["but", "though", "still"],
    "therefore": ["so", "because of that", "thus"],
    "moreover": ["also", "plus", "and"],
    "although": ["even though", "though", "but"],
    "whereas": ["while", "but", "on the other hand"],
    "regarding": ["about", "on", "for"],
    "concerning": ["about", "regarding", "on"],
    "despite": ["even with", "regardless of", "in spite of"],
    "whether": ["if", "regardless if"],
    "numerous": ["many", "a lot of", "tons of"],
    "various": ["different", "several", "many"],
    "prior": ["before", "earlier", "previous"],
    "subsequent": ["next", "following", "after"],
    "initial": ["first", "starting", "beginning"],
    "primary": ["main", "first", "key"],
    "secondary": ["second", "other", "backup"],
    "possess": ["have", "own", "got"],
    "obtain": ["get", "grab", "pick up"],
    "acquire": ["get", "buy", "pick up"],
    "commence": ["start", "begin", "kick off"],
    "terminate": ["end", "stop", "finish"],
    "sufficient": ["enough", "plenty", "adequate"],
    "utilize": ["use"],
    "assist": ["help", "aid", "support"],
    "attempt": ["try", "go for", "take a shot"],
    "desire": ["want", "wish", "hope for"],
    "require": ["need", "have to have", "must have"],
    "inquire": ["ask", "wonder", "question"],
    "purchase": ["buy", "get", "pick up"],
    "indicate": ["show", "point to", "suggest"],
    "provide": ["give", "offer", "supply"],
    "additional": ["more", "extra", "other"],
}


# Multi-word phrase alternatives (matched case-insensitively)
# Maps a phrase to simpler rough-draft versions
PHRASE_ALTERNATIVES: dict[str, list[str]] = {
    "in order to": ["to", "so I can", "so we can"],
    "as a result": ["so", "because of that", "thats why"],
    "on the other hand": ["but", "then again", "but also"],
    "in addition to": ["besides", "on top of", "plus"],
    "with regard to": ["about", "for", "on"],
    "in the event that": ["if", "in case"],
    "due to the fact that": ["because", "since", "cause"],
    "at this point in time": ["now", "right now", "currently"],
    "for the purpose of": ["to", "for"],
    "in spite of the fact that": ["even though", "although", "despite"],
    "it is important to note that": ["also", "notably", "keep in mind"],
    "take into consideration": ["consider", "think about", "keep in mind"],
    "a large number of": ["many", "a lot of", "tons of"],
    "the vast majority of": ["most", "almost all", "most of"],
    "in the near future": ["soon", "pretty soon", "before long"],
    "at the present time": ["now", "currently", "right now"],
    "is able to": ["can"],
    "was able to": ["could", "managed to"],
    "has the ability to": ["can", "is able to"],
    "make a decision": ["decide", "choose", "pick"],
    "come to the conclusion": ["conclude", "figure out", "decide"],
    "give consideration to": ["consider", "think about"],
    "has an impact on": ["affects", "changes", "impacts"],
    "is indicative of": ["shows", "means", "suggests"],
    "in the process of": ["currently", "working on", "doing"],
    "on a daily basis": ["every day", "daily"],
    "each and every": ["every", "all"],
    "first and foremost": ["first", "mainly", "most importantly"],
    "few and far between": ["rare", "uncommon", "not many"],
    "by and large": ["mostly", "generally", "usually"],
    "time and time again": ["repeatedly", "over and over", "again and again"],
}


def generate_rough_draft(text: str, rng: random.Random | None = None) -> str:
    """Replace words/phrases in `text` with simpler/rougher alternatives.

    Simulates a human's first-draft wording before they revise to the final version.
    For longer text (sentence-length), swaps more words and tries phrase-level replacements.
    """
    if rng is None:
        rng = random.Random()

    # First, try multi-word phrase replacements
    text = _apply_phrase_swaps(text, rng)

    # Then do word-level swaps
    words = re.findall(r"\S+|\s+", text)  # preserve spacing
    swappable: list[int] = []

    for i, token in enumerate(words):
        clean = re.sub(r"[^a-zA-Z]", "", token).lower()
        if clean in WORD_ALTERNATIVES:
            swappable.append(i)

    if not swappable:
        return text

    # Scale swaps with text length: 1-3 for short, up to 5 for sentence-length
    word_count = sum(1 for w in words if w.strip())
    if word_count > 10:
        max_swaps = min(len(swappable), rng.randint(2, 5))
    else:
        max_swaps = min(len(swappable), rng.randint(1, 3))
    chosen = rng.sample(swappable, max_swaps)

    result = list(words)
    for i in chosen:
        token = result[i]
        # Extract the clean word and any surrounding punctuation
        m = re.match(r"^(\W*?)([a-zA-Z]+)(\W*?)$", token)
        if not m:
            continue
        prefix, word, suffix = m.groups()
        lower = word.lower()
        alt = rng.choice(WORD_ALTERNATIVES[lower])

        # Preserve capitalization
        if word[0].isupper():
            alt = alt[0].upper() + alt[1:]
        if word.isupper():
            alt = alt.upper()

        result[i] = prefix + alt + suffix

    return "".join(result)


def _apply_phrase_swaps(text: str, rng: random.Random) -> str:
    """Replace multi-word phrases with simpler alternatives."""
    lower_text = text.lower()
    for phrase, alts in PHRASE_ALTERNATIVES.items():
        if phrase in lower_text and rng.random() < 0.6:
            # Find the phrase case-insensitively and replace once
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            alt = rng.choice(alts)
            # Preserve capitalization of first char
            m = pattern.search(text)
            if m and m.group(0)[0].isupper():
                alt = alt[0].upper() + alt[1:]
            text = pattern.sub(alt, text, count=1)
    return text
