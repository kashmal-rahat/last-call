"""Billing kill switch Cloud Function (Milestone 2B Step 12).

Triggered by Pub/Sub budget alert notifications.
If costAmount >= budgetAmount * KILL_RATIO:
1. Tests for 'resourcemanager.projects.deleteBillingAssignment' permission.
2. If SIMULATE_DEACTIVATION=true, logs 'SIMULATED disable'.
3. Otherwise unlinks billing account from the project.
"""

import base64
import json
import logging
import os

import functions_framework
from googleapiclient import discovery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("billing_guard")
logger.setLevel(logging.INFO)


@functions_framework.cloud_event
def billing_guard(cloud_event):
    """Processes Pub/Sub budget alert event."""
    pubsub_msg = cloud_event.data.get("message", {})
    data_b64 = pubsub_msg.get("data")
    if not data_b64:
        logger.warning("No data payload in Pub/Sub budget message")
        return

    data_str = base64.b64decode(data_b64).decode("utf-8")
    try:
        notification_data = json.loads(data_str)
    except Exception as e:
        logger.error(f"Failed to parse budget alert JSON: {e}")
        return

    cost_amount = float(notification_data.get("costAmount", 0.0))
    budget_amount = float(notification_data.get("budgetAmount", 0.0))
    kill_ratio = float(os.getenv("KILL_RATIO", "1.0"))
    simulate = os.getenv("SIMULATE_DEACTIVATION", "true").lower() in ("true", "1")
    project_id = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "kayrox-last-call"))

    logger.info(
        f"Billing alert received for {project_id}: cost={cost_amount}, budget={budget_amount}, "
        f"kill_ratio={kill_ratio}, simulate={simulate}"
    )

    if budget_amount > 0 and cost_amount >= budget_amount * kill_ratio:
        logger.warning(
            f"Cost threshold reached or exceeded ({cost_amount} >= {budget_amount * kill_ratio}). "
            f"Checking permissions to disable billing..."
        )

        crm_service = discovery.build("cloudresourcemanager", "v1", cache_discovery=False)
        billing_service = discovery.build("cloudbilling", "v1", cache_discovery=False)
        project_name = f"projects/{project_id}"

        # 1. Test permissions
        res = (
            crm_service.projects()
            .testIamPermissions(
                resource=project_id,
                body={"permissions": ["resourcemanager.projects.deleteBillingAssignment"]},
            )
            .execute()
        )

        permissions = res.get("permissions", [])
        if "resourcemanager.projects.deleteBillingAssignment" not in permissions:
            logger.error("Missing required permission 'resourcemanager.projects.deleteBillingAssignment' to disable billing!")
            return

        # 2. Simulate or deactivate
        if simulate:
            logger.warning("SIMULATED disable: billing would be detached now.")
            print("SIMULATED disable: billing would be detached now.", flush=True)
        else:
            logger.warning(f"Disabling billing for {project_name} now...")
            billing_service.projects().updateBillingInfo(
                name=project_name,
                body={"billingAccountName": ""},
            ).execute()
            logger.info("Billing successfully detached.")
    else:
        logger.info("Cost is within budget limits; no action taken.")
