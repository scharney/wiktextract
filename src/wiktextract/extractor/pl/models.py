from pydantic import BaseModel, ConfigDict, Field


class PolishBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
        validate_default=True,
    )


class Sense(PolishBaseModel):
    glosses: list[str] = []
    tags: list[str] = []
    raw_tags: list[str] = []
    topics: list[str] = []
    categories: list[str] = []
    sense_index: str = ""


class WordEntry(PolishBaseModel):
    model_config = ConfigDict(title="Polish Wiktionary")

    word: str = Field(description="Word string")
    lang_code: str = Field(description="Wiktionary language code")
    lang: str = Field(description="Localized language name")
    pos: str = Field(default="", description="Part of speech type")
    pos_text: str = ""
    senses: list[Sense] = []
    title: str = Field(default="", description="Redirect page source title")
    redirect: str = Field(default="", description="Redirect page target title")
    categories: list[str] = []
    tags: list[str] = []
    raw_tags: list[str] = []