from pydantic import BaseModel, ConfigDict, Field


class DutchBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        validate_default=True,
    )


class Example(DutchBaseModel):
    text: str = ""
    translation: str = ""
    ref: str = ""


class AltForm(DutchBaseModel):
    word: str


class Sense(DutchBaseModel):
    glosses: list[str] = []
    tags: list[str] = []
    raw_tags: list[str] = []
    categories: list[str] = []
    examples: list[Example] = []
    form_of: list[AltForm] = []


class Sound(DutchBaseModel):
    ipa: str = Field(default="", description="International Phonetic Alphabet")
    audio: str = Field(default="", description="Audio file name")
    wav_url: str = ""
    oga_url: str = ""
    ogg_url: str = ""
    mp3_url: str = ""
    opus_url: str = ""
    flac_url: str = ""
    tags: list[str] = []
    raw_tags: list[str] = []


class Linkage(DutchBaseModel):
    word: str
    tags: list[str] = []
    raw_tags: list[str] = []
    roman: str = ""
    sense: str = Field(default="", description="Definition of the word")
    sense_index: int = Field(
        default=0, ge=0, description="Number of the definition, start from 1"
    )


class Translation(DutchBaseModel):
    lang_code: str = Field(
        default="",
        description="Wiktionary language code of the translation term",
    )
    lang: str = Field(default="", description="Translation language name")
    word: str = Field(default="", description="Translation term")
    sense: str = Field(default="", description="Translation gloss")
    sense_index: int = Field(
        default=0, ge=0, description="Number of the definition, start from 1"
    )
    tags: list[str] = []
    raw_tags: list[str] = []
    roman: str = ""


class WordEntry(DutchBaseModel):
    model_config = ConfigDict(title="Dutch Wiktionary")
    word: str = Field(description="Word string", min_length=1)
    lang_code: str = Field(description="Wiktionary language code", min_length=1)
    lang: str = Field(description="Localized language name", min_length=1)
    pos: str = Field(description="Part of speech type", min_length=1)
    pos_title: str = ""
    senses: list[Sense] = []
    categories: list[str] = []
    tags: list[str] = []
    raw_tags: list[str] = []
    etymology_index: str = Field(default="", exclude=True)
    sounds: list[Sound] = []
    anagrams: list[Linkage] = []
    antonyms: list[Linkage] = []
    derived: list[Linkage] = []
    proverbs: list[Linkage] = []
    holonyms: list[Linkage] = []
    homophones: list[Linkage] = []
    hypernyms: list[Linkage] = []
    hyponyms: list[Linkage] = []
    metonyms: list[Linkage] = []
    paronyms: list[Linkage] = []
    related: list[Linkage] = []
    rhymes: list[Linkage] = []
    synonyms: list[Linkage] = []
    translations: list[Translation] = []