from dataclasses import dataclass, field


@dataclass(frozen=True)
class AblationConfig:
    memory: bool = True
    context_compression: bool = True
    checkpoint: bool = True
    total_budget: int = 3000
    unbounded_total_budget: int = 1_000_000
    unbounded_section_budgets: dict = field(default_factory=lambda: {
        "prefix": 200_000,
        "memory_index": 100_000,
        "checkpoint": 100_000,
        "working_memory": 100_000,
        "relevant_memory": 100_000,
        "history": 500_000,
    })


BASELINE = AblationConfig(memory=False, context_compression=False, checkpoint=False)
CURRENT = AblationConfig(memory=True, context_compression=True, checkpoint=True)
