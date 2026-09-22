"""Trilingual lexicon: every concept has English, Tanglish and Tamil-script surface
forms side by side. There is no translation step — a Tamil-script token, a Tanglish
token and an English token all resolve to the *same concept* directly.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

from .normalize import is_tamil_token, skeleton, stems

# concept -> (english, tanglish, tamil-script), space-separated
_RAW: dict[str, tuple[str, str, str]] = {
    "remind": ("remind reminder reminders remainder", "ninaivootu ninaivu nyabagam gnabagam ninaivupaduthu ninaivuoottu ninaivootri",
               "நினைவூட்டு நினைவூட்டல் ஞாபகம் நினைவுபடுத்து நினைவு"),
    "schedule": ("schedule calendar agenda timetable", "scheduleu attavanai", "அட்டவணை ஷெட்யூல் காலண்டர்"),
    "meeting": ("meeting meetings meet mtg standup sync appointment appt interview", "sandhippu santhippu meetingu",
                "சந்திப்பு மீட்டிங் கூட்டம்"),
    "mail": ("mail email emails e-mail gmail mails", "mailu minanjal", "மெயில் மின்னஞ்சல்"),
    "message": ("message msg text whatsapp", "", "செய்தி மெசேஜ்"),
    "task": ("task tasks todo todos to-do", "velai velaigal pani", "வேலை வேலைகள் டாஸ்க்"),
    "note": ("note notes memo jot", "kurippu kurippugal", "குறிப்பு குறிப்புகள் நோட்"),
    "goal": ("goal goals target objective", "ilakku ilakkugal", "இலக்கு இலக்குகள்"),
    "call": ("call phone dial ring", "koopidu koopudu koopitu call", "அழை கூப்பிடு போன்"),
    "tired": ("tired exhausted fatigue drained sleepy weary", "sorvu sorvaga sorvaa kalaippu kalaippaa kalaichuten kalaichi alasal thoongaren thoonguthu tiredu",
              "சோர்வு சோர்வா களைப்பு களைப்பா தூக்கம்"),
    "stressed": ("stressed stress overwhelmed anxious worried busy", "tension kavalai stressu bayam", "கவலை பயம் டென்ஷன்"),
    "happy": ("happy great awesome good excellent fine", "santhosham nalla mass semma", "மகிழ்ச்சி சந்தோஷம் நல்லா"),
    "greet": ("hi hello hey hai hola sup wassup", "vanakkam vannakam hai", "வணக்கம்"),
    "ate_q": ("", "saptiya saptingala sapitiya saapitiya saapitingala saptacha saapteengala saptengala", "சாப்பிட்டியா சாப்பிட்டீங்களா சாப்பாடு"),
    "howru": ("", "", ""),  # matched by phrase in the NLU: a lone "epdi" just means "how"
    "yes": ("yes yeah yep yup ok okay sure confirm proceed fine", "aama ama aamam seri sari sarii kandippa kandipaa", "ஆமா ஆம் சரி கண்டிப்பா"),
    "no": ("no nope nah dont don't never", "illa illai venam venaam venda vendam vendaam", "இல்ல இல்லை வேண்டாம் வேணாம் வேண்டா"),
    "stop": ("stop cancel abort forget nevermind", "vidu vittudu vidunga", "விடு நிறுத்து"),
    "when": ("when", "eppo eppodhu eppothu epo eppa", "எப்போ எப்பொழுது எப்போது எப்ப"),
    "what": ("what whats what's which", "enna ena yenna edhu ethu", "என்ன எது"),
    "who": ("who whom", "yaar yaaru yaarukku", "யார் யாரு"),
    "where": ("where", "enga enge", "எங்க எங்கே"),
    "why": ("why", "yen yean aen", "ஏன்"),
    "how": ("how", "epdi eppadi", "எப்படி"),
    "show": ("show list display view see open read", "kaattu kaamu", "காட்டு"),
    "add": ("add create new make set put append", "podu potu serthu sethu puthusa", "சேர் போடு புதுசா"),
    "done": ("done complete completed finish finished", "mudinchidichu mudinchuthu mudichiten mudichitten mudinjathu mudinjidichu", "முடிந்தது முடிஞ்சது முடிச்சேன்"),
    "delete": ("delete remove erase clear", "neekku neeku azhi azhichidu", "நீக்கு அழி"),
    "update": ("update change reschedule edit modify shift postpone move", "maatru maathu matru maattu", "மாற்று மாத்து"),
    "send": ("send forward dispatch", "anuppu anupu anuppidu", "அனுப்பு"),
    "draft": ("draft write compose reply", "eluthu ezhuthu", "எழுது"),
    "summarize": ("summarize summarise summary recap gist", "surukkam surukku", "சுருக்கம் சுருக்கு"),
    "plan": ("plan prioritize prioritise organise organize", "plan planu", "திட்டம் முன்னுரிமை"),
    "search": ("search find lookup look", "thedu theadu", "தேடு"),
    "review": ("review check proofread verify", "paakanum paathutu", "பார்க்கணும்"),
    "direct": ("direct directly immediately straight now", "udane udanae ippove nera neraa", "உடனே இப்பவே"),
    "office": ("office work workplace ofc", "alugalagam", "அலுவலகம் ஆபீஸ்"),
    "home": ("home house", "veedu veetuku", "வீடு வீட்டுக்கு"),
    "place": ("gym college school market hospital temple bank airport station mall shop", "kadai koil palli kalloori", "கடை கோயில் பள்ளி கல்லூரி"),
    "self": ("i me my mine i'm im ive", "naa naan na nan en enaku enakku ennaku", "நான் எனக்கு என்"),
    "you": ("you your u ur", "nee neenga nenga unga ungaluku", "நீ நீங்க உங்க"),
    "please": ("please pls plz kindly", "konjam dhayavu", "தயவு கொஞ்சம் தயவுசெய்து"),
    "thanks": ("thanks thank thx tq thanku", "nandri nanri", "நன்றி"),
    "bye": ("bye goodbye tata", "paakalam", "பார்க்கலாம்"),
    "help": ("help assist", "udhavi uthavi", "உதவி"),
    "time": ("time clock", "neram time", "நேரம்"),
    "date": ("date day", "thethi naal", "தேதி நாள்"),
    "weather": ("weather rain temperature forecast", "mazhai veyil", "மழை வெயில்"),
    "today_word": ("today tonight", "inniku innaiku inikku innaikku indru inniki", "இன்று இன்னிக்கு இன்னைக்கு"),
    "tomorrow_word": ("tomorrow tmrw tomo", "nalaiku naalaiku nalaikku naalai nalai naale", "நாளை நாளைக்கு"),
    "note_taking": ("", "eduthuko eduthukko", "எடுத்துக்கோ"),
    "coach": ("motivate motivation coach habit streak focus", "ookkam", "ஊக்கம்"),
    "goalprog": ("progress status", "", "முன்னேற்றம்"),
    "and": ("and then also", "aprom apuram appuram mattum matrum", "மற்றும் அப்புறம்"),
    "mention": ("mention say saying tell inform state", "sollu solli mention", "சொல்லு"),
    "ready": ("ready prepared", "ready readyaa", "தயார்"),
    # exact-match only (see _EXACT_ONLY): "amma" (mother) must not fuzzy-match "aama" (yes)
    "kin": ("mom dad mother father", "amma appa anna akka thambi thangai thatha paati", "அம்மா அப்பா அண்ணா அக்கா தம்பி தங்கை தாத்தா பாட்டி"),
    "filler": ("wensday wednesday hey the a an of for to at on in by with this that it is are am be do does can could would should will shall just really", "da di pa ma dei machan bro ah ne nga la nu nnu ku kku", "டா டி பா மா"),
}

_EXACT_ONLY = {"kin"}

# Words that only ever appear in Tanglish (used by language detection, not for concepts).
_TG_EXTRA = (
    "naa naan nee neenga nenga enaku enakku unaku ungaluku avanga avan aval ivan ival idhu adhu edhu enna ena eppo epdi eppadi "
    "illa illai irukken iruken irukka iruka irukinga irukkanga irukku iruku irundhuchu irunthuchu aagum aagudhu aachu aayiduchu aanadhu "
    "venum venuma venduma vendam venam pannu panu pannunga panunga panren panra pannuren pannitiya panniten pannitten pannirukken pannalam pannanum "
    "seri sari aama ama illa da di pa machan dei konjam romba semma mass nalla ketta "
    "poitu poyitu poren pogiren varen varuven vandhutten vanthuten vaanga vaa poga pogalam "
    "sapdu saptiya saptingala saapten saaptiya kudu kudunga sollu sollunga solren solli kelu kelunga paaru paarunga paakalam paathiya "
    "nalaiku naalaiku nalai inniku innaiku mani neram nimisham kaalai kalaila maalai sayangalam mathiyam iravu raatri "
    "eduthuko vechuko vachuko podu potu podunga anuppu anupu anuppunga kaattu maathu maatru mudinjidichu mudichiten mudinjathu "
    "ah ku kku la nu nnu oda uh aprom apuram appuram ippo ipo appo eppovum ellam ellarum ungalukku yaaru yaar yen "
    "sollu ponnu paiyan amma appa anna akka thambi thangai thatha paati vandhu vandhutu irundhu pannitu senjutu senjachu seiyanum "
    "kalaichi tension bayam kavalai velai vela kadai veedu alugalagam oor"
).split()

_EN_STOP = set(
    "the a an is are was were be been am i you he she it we they me my your his her our their this that these those and or but if then so "
    "to of in on at by for with from up down out over under again further once here there when where why how all any both each few more most "
    "other some such no nor not only own same than too very can will just don should now please send mail email remind reminder meeting "
    "tomorrow today tonight morning afternoon evening night what which who whom do does did have has had having would could may might must "
    "about into through during before after above below between what's it's i'm let lets ready tell show add create schedule note task list".split()
)

# Pure English function words. Only these count as evidence *for English* when detecting language:
# content words like "task" or "remind" are routinely borrowed into Tanglish, so they prove nothing.
_EN_FUNC = frozenset(
    "the a an is are was were be been am i you he she it we they me my your his her our their this that these those and or but if then so "
    "to of in on at by for with from up down out over under here there when where why how all any both each few more most other some such nor not "
    "only own same than too very can will just should now please do does did have has had would could may might must about into through during "
    "before after above below between what which who whom what's it's i'm let lets".split())


def english_function_words() -> frozenset[str]:
    return _EN_FUNC


# ------------------------------------------------------------------ verb families
# Tanglish verb morphology is productive (pannu/panren/panniten/pannitiya/pannunga...),
# so verbs are matched by pattern instead of enumerating every form.
_TG_VERBS: dict[str, re.Pattern] = {
    "do": re.compile(r"^pann?(u|i|ren|ra|rom|riya|al|an|ir|id)\w*$"),
    "v_send": re.compile(r"^anup+\w*$"),
    "v_tell": re.compile(r"^so+ll?(u|i|ren|unga|iru|ida|iten)\w*$"),
    "v_add": re.compile(r"^(pod|pot+)(u|unga|uren|uven|idu|en)\w*$"),
    "v_keep": re.compile(r"^(vach|vech|vaich)\w*$"),
    "v_take": re.compile(r"^edu(th|t|k|nga)\w*$"),
    "v_show": re.compile(r"^ka+t+(u|i|unga|ren|ura)\w*$"),
    "v_see": re.compile(r"^pa+(r|th|t)(u|unga|ka|kanum|kalam|ren)\w*$"),
    "v_delete": re.compile(r"^(nee?kk?u\w*|az?hi\w*|alichi\w*)$"),
    "v_finish": re.compile(r"^mud(i|in)\w*$"),
    "v_search": re.compile(r"^the+d+(u|i|unga|ren)\w*$"),
    "v_change": re.compile(r"^maa?(tt?r?|th)(u|i|unga|ren|inga)\w*$"),
    "v_go": re.compile(r"^po(i|y)\w*$|^(poren|pogiren|poganum|pogalam|pona|ponen|poga|poitu)$"),
    "v_come": re.compile(r"^(var(en|uven|uvean|ugiren|um)|vand?h?(u|e)\w*|vaa+|vaa?nga|vanga)$"),
    "v_call": re.compile(r"^koo?p(i|u)\w*$"),
    "v_write": re.compile(r"^(e|ae)(l|zh|zl)uth?(u|i|unga|ren)\w*$"),
}
_TA_VERBS: dict[str, re.Pattern] = {
    "do": re.compile(r"^(பண்ண|பண்ணு|பண்றேன்|பண்ணுங்க|பண்ணிட்டியா|பண்ணிட்டேன்|செய்|செய்யு|செய்ய|செய்து|செய்தேன்)\S*$"),
    "v_send": re.compile(r"^அனுப்\S*$"),
    "v_tell": re.compile(r"^சொல்\S*$"),
    "v_add": re.compile(r"^போடு\S*$|^போட்\S*$"),
    "v_keep": re.compile(r"^வச்ச\S*$|^வைத்\S*$"),
    "v_take": re.compile(r"^எடு\S*$"),
    "v_show": re.compile(r"^காட்ட\S*$|^காட்டு\S*$"),
    "v_see": re.compile(r"^பார்\S*$"),
    "v_delete": re.compile(r"^(நீக்கு|அழி)\S*$"),
    "v_finish": re.compile(r"^முடி\S*$"),
    "v_search": re.compile(r"^தேடு\S*$"),
    "v_change": re.compile(r"^மாற்று\S*$|^மாத்து\S*$"),
    "v_go": re.compile(r"^(போய்|போயி|போறேன்|போகிறேன்|போகணும்|போனேன்)\S*$"),
    "v_come": re.compile(r"^(வரேன்|வருவேன்|வந்துட்டேன்|வந்தேன்|வாங்க|வா)$"),
    "v_call": re.compile(r"^கூப்பிடு\S*$|^அழை\S*$"),
    "v_write": re.compile(r"^எழுது\S*$"),
}

_QUESTION_ENDINGS = re.compile(r"(tiya|tingala|ringala|riya|venduma|irukka|iruka|irukinga|aagum|aaguma|ah\?)$")


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (exact_index, skeleton_index): surface/skeleton -> concepts."""
    exact: dict[str, set[str]] = {}
    skel: dict[str, set[str]] = {}
    for concept, forms in _RAW.items():
        for group_i, group in enumerate(forms):
            for form in group.split():
                exact.setdefault(form.lower(), set()).add(concept)
                if group_i < 2 and concept not in _EXACT_ONLY:  # Latin-script forms get phonetic matching
                    skel.setdefault(skeleton(form), set()).add(concept)
    return exact, skel


@lru_cache(maxsize=1)
def _skel_keys() -> list[str]:
    return [k for k in _index()[1] if len(k) >= 5]


@lru_cache(maxsize=1)
def tanglish_words() -> frozenset[str]:
    # Latin loanwords ("mention", "ready", "call") live in the tg group so they resolve to
    # concepts, but they are not evidence of Tanglish, so drop anything that is also English.
    en = english_words()
    exact_tg = set(_TG_EXTRA)
    for _, tg, _ in _RAW.values():
        exact_tg.update(w for w in tg.split() if w.lower() not in en)
    return frozenset(w.lower() for w in exact_tg)


@lru_cache(maxsize=1)
def _tanglish_skeletons() -> frozenset[str]:
    return frozenset(skeleton(w) for w in tanglish_words() if len(w) >= 3)


@lru_cache(maxsize=1)
def english_words() -> frozenset[str]:
    words = set(_EN_STOP)
    for en, _, _ in _RAW.values():
        words.update(en.split())
    return frozenset(w.lower() for w in words)


def is_tanglish_word(token: str) -> bool:
    low = token.lower()
    if low in english_words() and low not in tanglish_words():
        return False
    if low in tanglish_words():
        return True
    if _TG_VERBS["do"].match(low):
        return True
    return len(low) >= 4 and skeleton(low) in _tanglish_skeletons() and low not in english_words()


def verb_concepts(token: str) -> set[str]:
    patterns = _TA_VERBS if is_tamil_token(token) else _TG_VERBS
    low = token.lower()
    return {c for c, rx in patterns.items() if rx.match(low)}


def concepts_for(token: str) -> set[str]:
    """All concepts a token can express. Handles spelling variance and glued suffixes."""
    exact, skel = _index()
    out: set[str] = set()
    for stem in stems(token):
        low = stem.lower()
        if low in exact:
            out |= exact[low]
            break
        if not is_tamil_token(stem):
            sk = skeleton(low)
            if sk in skel and len(sk) >= 3:
                out |= skel[sk]
                break
            if len(sk) >= 5:
                # Tanglish spelling variance rarely changes the first sound, so requiring it keeps
                # unrelated words ("vilakku" = explanation vs "ilakku" = goal) from fuzzy-matching.
                near = [k for k in difflib.get_close_matches(sk, _skel_keys(), n=3, cutoff=0.86) if k[0] == sk[0]]
                if near:
                    out |= skel[near[0]]
                    break
    out |= verb_concepts(token)
    return out


def looks_like_question(token: str) -> bool:
    return bool(_QUESTION_ENDINGS.search(token.lower()))
