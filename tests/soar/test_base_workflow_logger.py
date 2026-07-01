from soar.workflows.base import BaseWorkflow


class DummyWorkflow(BaseWorkflow):
    def run(self, context):
        return {"ok": True}


def test_base_workflow_has_logger():
    wf = DummyWorkflow()
    assert hasattr(wf, "_logger")
    assert wf._logger is not None
