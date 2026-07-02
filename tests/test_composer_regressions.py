import json
from pathlib import Path

from vera.composer import compose


ROOT = Path(__file__).resolve().parents[1]
ANCHORS = ROOT / "examples" / "compose-anchor-pairs.json"


def test_anchor_pairs_still_pass():
    with ANCHORS.open("r", encoding="utf-8") as fh:
        cases = json.load(fh)

    for case in cases:
        result = compose(
            category=case["input"]["category"],
            merchant=case["input"]["merchant"],
            trigger=case["input"]["trigger"],
            customer=case["input"].get("customer"),
        )
        assert result.body == case["output"]["body"]
        assert result.cta == case["output"]["cta"]
        assert result.send_as == case["output"]["send_as"]
        assert result.suppression_key == case["output"]["suppression_key"]
        assert result.rationale == case["output"]["rationale"]
        assert result.template_name == case["output"]["template_name"]
        assert result.template_params == case["output"]["template_params"]
