from pydantic import BaseModel, model_validator

# From claude.md §8's system prompt, rule 5: "Split tagged_script on paragraph
# boundaries into chunks of at most 2500 characters each." Independent of
# elevenlabs_client.py's own ~4,500-char safety-margin chunking (a separate,
# later concern — see DECISIONS.md's M2 entry).
MAX_TTS_CHUNK_CHARS = 2500


class OrchestratorRequest(BaseModel):
    emotion_brief: str
    script: str


class OrchestratorOutput(BaseModel):
    tagged_script: str
    tts_chunks: list[str]
    style_prompt: str
    negative_notes: str
    emotion_summary: str

    @model_validator(mode="after")
    def _check_chunks_reconstruct_tagged_script(self) -> "OrchestratorOutput":
        if not self.tts_chunks:
            raise ValueError("tts_chunks must not be empty")
        if "".join(self.tts_chunks) != self.tagged_script:
            raise ValueError(
                "tts_chunks concatenation does not exactly equal tagged_script "
                "(claude.md §8 rule 5)"
            )
        for i, chunk in enumerate(self.tts_chunks):
            if len(chunk) > MAX_TTS_CHUNK_CHARS:
                raise ValueError(
                    f"tts_chunks[{i}] is {len(chunk)} chars, over the "
                    f"{MAX_TTS_CHUNK_CHARS}-char limit (claude.md §8 rule 5)"
                )
        return self

    @model_validator(mode="after")
    def _check_style_prompt_mentions_talking(self) -> "OrchestratorOutput":
        if "talking" not in self.style_prompt.lower():
            raise ValueError(
                "style_prompt must include 'talking, speaking directly to camera' "
                "(claude.md §8 rule 7)"
            )
        return self
