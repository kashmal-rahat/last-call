"""Export Pydantic models to JSON Schemas in shared/schemas/."""

import json
import os
import sys

# Ensure shared package is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared")))

from lastcall_shared.models import (
    AgentBuyerInfo,
    AgentDealBrief,
    BatchAttempt,
    BatchRecord,
    Branch,
    BuyerHistory,
    CallRecord,
    CallResult,
    ConfirmedQuantity,
    DealBrief,
    DealRecord,
    FreshnessResult,
    GeoPoint,
    InspectorMeta,
    ItemAssessment,
    LadderDecision,
    LadderMeta,
    LadderResult,
    MartRules,
    NegotiationPolicy,
    NegotiationState,
    ObservedQuantity,
    OutboxMessage,
    PriceEntry,
    ProduceProfile,
    QuantityEstimate,
    ScoutCandidate,
    ScoutMeta,
    ScoutResult,
    ScreenedOut,
    StaffTask,
    StageProfile,
    StepPlan,
)

MODELS = {
    "StepPlan": StepPlan,
    "BatchAttempt": BatchAttempt,
    "FreshnessResult": FreshnessResult,
    "DealBrief": DealBrief,
    "AgentDealBrief": AgentDealBrief,
    "AgentBuyerInfo": AgentBuyerInfo,
    "CallResult": CallResult,
    "ItemAssessment": ItemAssessment,
    "QuantityEstimate": QuantityEstimate,
    "ObservedQuantity": ObservedQuantity,
    "InspectorMeta": InspectorMeta,
    "ConfirmedQuantity": ConfirmedQuantity,
    "NegotiationPolicy": NegotiationPolicy,
    "NegotiationState": NegotiationState,
    "CallRecord": CallRecord,
    "BatchRecord": BatchRecord,
    "DealRecord": DealRecord,
    "OutboxMessage": OutboxMessage,
    "StaffTask": StaffTask,
    "ProduceProfile": ProduceProfile,
    "StageProfile": StageProfile,
    "PriceEntry": PriceEntry,
    "MartRules": MartRules,
    "LadderDecision": LadderDecision,
    "LadderMeta": LadderMeta,
    "LadderResult": LadderResult,
    "Branch": Branch,
    "GeoPoint": GeoPoint,
    "BuyerHistory": BuyerHistory,
    "ScoutCandidate": ScoutCandidate,
    "ScreenedOut": ScreenedOut,
    "ScoutMeta": ScoutMeta,
    "ScoutResult": ScoutResult,
}


def main():
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared", "schemas"))
    os.makedirs(out_dir, exist_ok=True)

    for name, model_cls in MODELS.items():
        schema = model_cls.model_json_schema()
        target_path = os.path.join(out_dir, f"{name}.json")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
        print(f"Exported {name} -> {target_path}")


if __name__ == "__main__":
    main()
