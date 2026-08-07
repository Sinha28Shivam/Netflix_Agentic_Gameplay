"""
VerificationJudge — the AI half of compliance checking, used only when
ComplianceOracle genuinely cannot resolve a check with a rule.

This implements the "Verification Judge" box from the architecture
diagram: "Only ambiguous cases reach an AI judge, with confidence +
human triage." Three properties make this honest rather than a relabeled
version of the old ComplianceAgent:

1. It is only ever called for checks the oracle returned "AMBIGUOUS" or
   "REQUIRES_VISUAL_JUDGMENT" on — see compliance_agent.py's routing.
   It is never the default path.
2. Every verdict carries a confidence score. Below CONFIDENCE_THRESHOLD,
   the finding is marked needs_human_review=True and is NOT treated as
   a final pass/fail — it's queued, matching Q9's "human reviews
   anything uncertain" claim.
3. The prompt is scoped to genuinely visual judgments only (contrast,
   crowding, "does this look like an ad is disguised as gameplay") —
   things that cannot be reduced to a string match or a number compare.
   It does not re-do anything ComplianceOracle already covers.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.config import DECIDER_MODEL

CONFIDENCE_THRESHOLD = 0.75  # below this, the finding is queued for a human, not treated as a verdict

JUDGE_SYSTEM_PROMPT = """
You are the Verification Judge for an automated game-QA system.

You are called ONLY for checks that cannot be reduced to an exact rule —
genuinely visual judgments. You are NOT a general compliance checker;
exact things (prices, required phrases, durations, element pixel sizes)
are already handled elsewhere and you will not be asked about them.

You will be given ONE specific question to judge about a screenshot.
Answer ONLY that question. Do not invent additional findings.

Return ONLY JSON in this schema:
{
  "verdict": "pass" | "fail",
  "confidence": 0.0,
  "reasoning": "one sentence, specific to what you observed"
}

If you are not confident, say so honestly with a low confidence score —
a low-confidence answer routed to a human is correct behavior, not a
failure on your part. Return JSON only.
"""

# The fixed set of questions this judge is allowed to answer. Anything not
# on this list should be a new ComplianceOracle rule, not a judge prompt —
# keeping this list short and explicit is what stops "AI opinion" from
# silently regrowing to cover everything, the way the original
# ComplianceAgent did.
AMBIGUOUS_CHECK_REGISTRY = {
    "text_contrast_adequate": "Does the body text on this screen have adequate contrast against its background for comfortable reading?",
    "ad_clearly_labeled": "If an advertisement is visible, is it clearly distinguishable from gameplay (e.g. labeled, bordered, or otherwise set apart)?",
    "color_only_information": "Is any essential game information (e.g. valid/invalid placement, danger state) conveyed by color alone with no other visual cue (icon, text, pattern)?",
    "tap_target_visual_size": "Do interactive buttons look large enough to tap reliably with a thumb? (Use this only when no pixel bounding-box data is available — prefer the exact size check otherwise.)",
}


@dataclass
class JudgeFinding:
    check_id: str
    question: str
    verdict: str               # "pass" | "fail" | "needs_human_review"
    confidence: float
    reasoning: str
    needs_human_review: bool
    deterministic: bool = False
    scene: str = ""


class VerificationJudge:
    def __init__(self, client, confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self.client = client
        self.confidence_threshold = confidence_threshold
        self.human_review_queue: List[JudgeFinding] = []

    def judge(self, screenshot_b64: str, scene: str, check_id: str) -> JudgeFinding:
        if check_id not in AMBIGUOUS_CHECK_REGISTRY:
            raise ValueError(
                f"'{check_id}' is not a registered ambiguous check. "
                f"If this can be reduced to a rule, add it to ComplianceOracle instead "
                f"of routing it here — see AMBIGUOUS_CHECK_REGISTRY in this file."
            )

        question = AMBIGUOUS_CHECK_REGISTRY[check_id]

        # Native Anthropic Messages API (matches the client qa_common builds and
        # the orchestrator passes in). The old OpenAI-style
        # `client.chat.completions.create(... image_url ...)` only worked with the
        # dead orchestrator's OpenAI client.
        response = self.client.messages.create(
            model=DECIDER_MODEL,
            max_tokens=200,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Scene: {scene}\nQuestion: {question}"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        },
                    ],
                },
            ],
        )

        parsed = self._parse(response.content[0].text)
        confidence = float(parsed.get("confidence", 0.0))
        raw_verdict = parsed.get("verdict", "fail")

        needs_review = confidence < self.confidence_threshold
        finding = JudgeFinding(
            check_id=check_id,
            question=question,
            verdict="needs_human_review" if needs_review else raw_verdict,
            confidence=confidence,
            reasoning=parsed.get("reasoning", ""),
            needs_human_review=needs_review,
            scene=scene,
        )

        if needs_review:
            self.human_review_queue.append(finding)

        return finding

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        # Parse failure is itself a confidence-0 signal, not a silent fail verdict
        return {"verdict": "fail", "confidence": 0.0, "reasoning": "Could not parse judge response"}

    def pending_human_review(self) -> List[JudgeFinding]:
        return list(self.human_review_queue)