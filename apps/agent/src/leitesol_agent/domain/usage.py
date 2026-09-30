"""Consumo da LLM em uma pergunta: chamadas e tokens, sem conteúdo."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LlmUsage:
    model: str | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageMeter:
    """Acumula o consumo das chamadas de uma única pergunta."""

    def __init__(self) -> None:
        self._usage = LlmUsage()

    def add(self, *, model: str, input_tokens: int, output_tokens: int) -> None:
        self._usage = LlmUsage(
            model=model,
            calls=self._usage.calls + 1,
            input_tokens=self._usage.input_tokens + input_tokens,
            output_tokens=self._usage.output_tokens + output_tokens,
        )

    def snapshot(self) -> LlmUsage:
        return self._usage
