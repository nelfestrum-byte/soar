import json
import os
import sys

import yaml

from soar.actions import actions
from soar.connectors import connectors
from soar.logger import setup_logging
from soar.workflows import workflows

setup_logging(level="INFO")

config_path = os.environ.get("SOAR_CONFIG", "config.yaml")
external_dirs = {}
try:
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    soar_config = config.get("soar", {})
    external_dirs = {
        "workflows": soar_config.get("workflows_dir"),
        "connectors": soar_config.get("connectors_dir"),
        "actions": soar_config.get("actions_dir"),
    }
except Exception:
    pass

workflows.init(external_dir=external_dirs.get("workflows"))
connectors.init(external_dir=external_dirs.get("connectors"))
actions.init(external_dir=external_dirs.get("actions"))


def main():
    os.environ.get("SOAR_JOB_ID", "")
    workflow_name = os.environ.get("SOAR_WORKFLOW_NAME", "")
    context_str = os.environ.get("SOAR_CONTEXT", "{}")
    os.environ.get("SOAR_LOG_PATH", "")

    try:
        context = json.loads(context_str)
    except json.JSONDecodeError:
        context = {}

    result = workflows.execute(workflow_name, context)

    output = {
        "success": result.success,
        "workflow_name": result.workflow_name,
        "duration_seconds": result.duration_seconds,
        "data": result.data,
    }
    if result.error:
        output["error"] = str(result.error)

    print(json.dumps(output))

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
