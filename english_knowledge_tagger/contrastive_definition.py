"""Automatic contrastive definition drafts built only from definition-train rows."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Mapping, Sequence

from .candidate_labeling import (
    LabelingServiceConfig,
    LabelingServiceError,
    Transport,
    _http_transport,
)
from .conversion_gate import _extract_json_payload


PROMPT_VERSION = "contrastive-definition-generator-v1"


@dataclass(frozen=True)
class ContrastiveDefinitionCandidate:
    candidate_id: str
    definition_text: str
    positive_criteria: str
    neighbor_exclusions: tuple[str, ...]
    insufficient_rule: str
    co_label_rule: str
    appearance_dependency_rule: str


@dataclass(frozen=True)
class ContrastiveDefinitionResult:
    candidates: tuple[ContrastiveDefinitionCandidate, ...]
    raw_response: str
    elapsed_ms: float
    prompt_chars: int


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def build_contrastive_definition_task(
    packet_rows: Sequence[Mapping[str, object]],
    *,
    ambiguity_manifest: Mapping[str, object],
    canonical_label: str,
) -> dict[str, object]:
    """Aggregate only definition-train rows for one label."""
    source_definitions: dict[str, str] = {}
    examples_by_decision: dict[str, list[dict[str, str]]] = {
        "keep": [],
        "remove": [],
        "uncertain": [],
    }
    legacy_label: str | None = None
    seen_questions: set[str] = set()
    for row in packet_rows:
        if row.get("canonical_label") != canonical_label:
            continue
        variant = row.get("definition_variant")
        definition = row.get("definition_text")
        if isinstance(variant, str) and isinstance(definition, str) and definition.strip():
            source_definitions.setdefault(variant, definition.strip())
        if isinstance(row.get("legacy_label"), str):
            legacy_label = str(row["legacy_label"])
        if row.get("split") != "definition_train":
            continue
        question_id = str(row.get("question_id"))
        if question_id in seen_questions:
            continue
        seen_questions.add(question_id)
        decision = row.get("pseudo_gold_decision")
        question = row.get("question_text")
        if decision in examples_by_decision and isinstance(question, str) and question.strip():
            examples_by_decision[str(decision)].append(
                {"decision": str(decision), "question_text": question.strip()}
            )
    if not source_definitions:
        raise ValueError("contrastive definition task has no source definitions")
    if legacy_label is None:
        raise ValueError("contrastive definition task has no legacy label")
    raw_labels = ambiguity_manifest.get("labels")
    if not isinstance(raw_labels, list):
        raise ValueError("ambiguity manifest labels must be a list")
    profile = next(
        (
            item
            for item in raw_labels
            if isinstance(item, Mapping) and item.get("canonical_label") == canonical_label
        ),
        None,
    )
    if profile is None:
        raise ValueError("canonical label is absent from ambiguity manifest")
    neighbors = profile.get("confusion_neighbors")
    if not isinstance(neighbors, list):
        raise ValueError("ambiguity profile confusion_neighbors must be a list")
    train_examples = [
        example
        for decision in ("keep", "remove", "uncertain")
        for example in examples_by_decision[decision][:12]
    ]
    return {
        "schema_version": "contrastive-definition-task-v1",
        "canonical_label": canonical_label,
        "legacy_label": legacy_label,
        "source_definitions": [
            {"variant": variant, "definition": definition}
            for variant, definition in sorted(source_definitions.items())
        ],
        "confusion_neighbors": neighbors,
        "train_examples": train_examples,
        "train_example_counts": {
            decision: len(items) for decision, items in examples_by_decision.items()
        },
    }


def build_contrastive_definition_prompt(task: Mapping[str, object]) -> str:
    label = _text(task.get("legacy_label"), field="legacy_label")
    definitions = task.get("source_definitions")
    neighbors = task.get("confusion_neighbors")
    examples = task.get("train_examples")
    if not isinstance(definitions, list) or not isinstance(neighbors, list) or not isinstance(examples, list):
        raise ValueError("contrastive definition task lists are malformed")
    return f"""你是初中英语知识点释义设计员。根据既有释义、训练折样例和高频混淆邻居，生成三份不同措辞但边界完整的实验释义。

目标标签：{label}

既有释义：
{json.dumps(definitions, ensure_ascii=False)}

高频混淆邻居：
{json.dumps(neighbors, ensure_ascii=False)}

仅限 definition-train 的样例：
{json.dumps(examples, ensure_ascii=False)}

每份释义必须分别给出：正向必要条件、相邻标签排除、信息不足规则、允许共标规则，以及“出现相关词不等于答案直接依赖”的规则。不得引用题号，不得声称修改老师 taxonomy。

只输出 JSON：
{{"definitions":[{{"candidate_id":"D3-1","positive_criteria":"...","neighbor_exclusions":["..."],"insufficient_rule":"...","co_label_rule":"...","appearance_dependency_rule":"..."}},{{"candidate_id":"D3-2",...}},{{"candidate_id":"D3-3",...}}]}}"""


def _string_list(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise LabelingServiceError(f"contrastive definition {field} must be a string list")
    return tuple(item.strip() for item in value)


def _render_definition(item: Mapping[str, object]) -> ContrastiveDefinitionCandidate:
    candidate_id = _text(item.get("candidate_id"), field="candidate_id")
    positive = _text(item.get("positive_criteria"), field="positive_criteria")
    exclusions = _string_list(item.get("neighbor_exclusions"), field="neighbor_exclusions")
    if not exclusions:
        raise LabelingServiceError("contrastive definition requires neighbor exclusions")
    insufficient = _text(item.get("insufficient_rule"), field="insufficient_rule")
    co_label = _text(item.get("co_label_rule"), field="co_label_rule")
    appearance = _text(
        item.get("appearance_dependency_rule"), field="appearance_dependency_rule"
    )
    definition = "\n".join(
        (
            f"正向必要条件：{positive}",
            f"相邻标签排除：{'；'.join(exclusions)}",
            f"信息不足：{insufficient}",
            f"允许共标：{co_label}",
            f"出现与依赖：{appearance}",
        )
    )
    return ContrastiveDefinitionCandidate(
        candidate_id=candidate_id,
        definition_text=definition,
        positive_criteria=positive,
        neighbor_exclusions=exclusions,
        insufficient_rule=insufficient,
        co_label_rule=co_label,
        appearance_dependency_rule=appearance,
    )


class ContrastiveDefinitionClient:
    def __init__(
        self,
        config: LabelingServiceConfig,
        *,
        transport: Transport | None = None,
    ):
        if not config.endpoint:
            raise ValueError("contrastive definition endpoint must be non-empty")
        self._config = config
        self._transport = transport or _http_transport

    def generate(self, task: Mapping[str, object]) -> ContrastiveDefinitionResult:
        prompt = build_contrastive_definition_prompt(task)
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        started = time.perf_counter_ns()
        response = self._transport(
            self._config.endpoint,
            {
                "model": self._config.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": self._config.max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            self._config.timeout_seconds,
            headers,
        )
        try:
            raw = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LabelingServiceError("contrastive definition response has no content") from error
        if not isinstance(raw, str):
            raise LabelingServiceError("contrastive definition response content must be a string")
        payload = _extract_json_payload(raw)
        definitions = payload.get("definitions")
        if not isinstance(definitions, list) or len(definitions) != 3:
            raise LabelingServiceError("contrastive definition response requires exactly three definitions")
        candidates = tuple(
            _render_definition(item)
            if isinstance(item, Mapping)
            else (_ for _ in ()).throw(
                LabelingServiceError("contrastive definition item must be an object")
            )
            for item in definitions
        )
        expected = {"D3-1", "D3-2", "D3-3"}
        if {item.candidate_id for item in candidates} != expected:
            raise LabelingServiceError("contrastive definition candidate IDs must be D3-1..D3-3")
        return ContrastiveDefinitionResult(
            candidates=candidates,
            raw_response=raw,
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
            prompt_chars=len(prompt),
        )


def expand_stability_packet_with_definition_candidates(
    packet_rows: Sequence[Mapping[str, object]],
    *,
    candidates: Sequence[Mapping[str, object]],
    split: str,
) -> tuple[dict[str, object], ...]:
    """Create D3 rows for one split without exposing any other split."""
    if split not in {"definition_dev", "locked_test"}:
        raise ValueError("contrastive definitions may only expand dev or locked_test")
    indexed_candidates: dict[str, str] = {}
    for item in candidates:
        candidate_id = _text(item.get("candidate_id"), field="candidate_id")
        definition = _text(item.get("definition_text"), field="definition_text")
        if candidate_id in indexed_candidates:
            raise ValueError("duplicate contrastive definition candidate_id")
        indexed_candidates[candidate_id] = definition
    base_by_question: dict[str, Mapping[str, object]] = {}
    for row in packet_rows:
        if row.get("split") != split:
            continue
        question_id = str(row.get("question_id"))
        if question_id not in base_by_question or row.get("definition_variant") == "D0":
            base_by_question[question_id] = row
    expanded: list[dict[str, object]] = []
    for question_id, base in sorted(base_by_question.items()):
        for candidate_id, definition in sorted(indexed_candidates.items()):
            expanded.append(
                {
                    **base,
                    "review_id": f"{PROMPT_VERSION}:{candidate_id}:{base.get('canonical_label')}:{question_id}",
                    "definition_variant": candidate_id,
                    "definition_text": definition,
                    "definition_source": "auto_contrastive_train_only",
                }
            )
    return tuple(expanded)


def _rank(group: Mapping[str, object]) -> tuple[float, float, float, float]:
    precision = group.get("unanimous_keep_precision")
    agreement = group.get("three_run_decision_agreement")
    false_rate = group.get("high_confidence_false_positive_rate")
    prompt_chars = group.get("mean_prompt_chars")
    return (
        float(precision) if isinstance(precision, (int, float)) else -1.0,
        float(agreement) if isinstance(agreement, (int, float)) else -1.0,
        -float(false_rate) if isinstance(false_rate, (int, float)) else -1.0,
        -float(prompt_chars) if isinstance(prompt_chars, (int, float)) else float("-inf"),
    )


def select_contrastive_definition(
    summary: Mapping[str, object], *, canonical_label: str
) -> dict[str, object]:
    """Select a passing D3 dev definition only when it strictly beats D0-D2."""
    groups = summary.get("groups")
    if not isinstance(groups, Mapping):
        raise ValueError("terminal stability summary groups must be an object")
    relevant: dict[str, Mapping[str, object]] = {}
    prefix = f"{canonical_label}|"
    for key, group in groups.items():
        if (
            isinstance(key, str)
            and key.startswith(prefix)
            and key.endswith("|definition_dev")
            and isinstance(group, Mapping)
        ):
            relevant[key.split("|")[1]] = group
    baselines = [
        (variant, group)
        for variant, group in relevant.items()
        if variant in {"D0", "D1", "D2"} and group.get("passes_precision_first_gate") is True
    ]
    candidates = [
        (variant, group)
        for variant, group in relevant.items()
        if variant.startswith("D3-") and group.get("passes_precision_first_gate") is True
    ]
    if not candidates:
        return {"status": "hold", "reason": "no D3 candidate passes dev gate"}
    best_candidate = max(candidates, key=lambda item: (_rank(item[1]), item[0]))
    if baselines:
        best_baseline = max(baselines, key=lambda item: (_rank(item[1]), item[0]))
        if _rank(best_candidate[1]) <= _rank(best_baseline[1]):
            return {
                "status": "hold",
                "reason": "best D3 candidate does not beat the best passing baseline",
                "best_baseline_variant": best_baseline[0],
            }
    return {
        "status": "selected",
        "canonical_label": canonical_label,
        "definition_variant": best_candidate[0],
        "dev_metrics": dict(best_candidate[1]),
    }
