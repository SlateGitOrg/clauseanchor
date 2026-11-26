import pytest

from clauseanchor.evaluate import run_eval
from clauseanchor.model import FaultPlan
from clauseanchor.playbook import load_playbook
from clauseanchor.seed import load_gold, write_dataset

SAMPLE = """MASTER SERVICES AGREEMENT

This agreement is made between A ("Supplier") and B ("Customer").

1. Definitions
1.1 In this Agreement:
(a) "Fees" means the amounts payable by Customer under each Order Form;
(b) "Security Incident" means a breach of security affecting Customer Data; and
(c) "Initial Term" means the period of twelve (12) months from the Effective Date.
2. Limitation of Liability
2.1 Subject to Section 2.3, Supplier's aggregate liability under this Agreement shall not
exceed twenty-four (24) months of the Fees.
2.2 Supplier shall:
(a) notify Customer of any Security Incident within seventy-two (72) hours;
(b) cooperate with Customer by:
(i) preserving logs; and
(ii) sharing findings; and
(c) keep records.
2.3 Notwithstanding Section 2.1, Supplier's liability for a Security Incident shall not
exceed six (6) months of the Fees.

IN WITNESS WHEREOF the parties have signed.
"""


@pytest.fixture(scope="session")
def sample_text() -> str:
    return SAMPLE


@pytest.fixture(scope="session")
def playbook():
    return load_playbook()


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    write_dataset(out, seed=7)
    return out


@pytest.fixture(scope="session")
def gold(dataset):
    return load_gold(dataset / "gold.json")


@pytest.fixture(scope="session")
def plan(dataset):
    return FaultPlan.load(dataset / "fault_plan.yaml")


@pytest.fixture(scope="session")
def eval_run(dataset):
    return run_eval(dataset)
