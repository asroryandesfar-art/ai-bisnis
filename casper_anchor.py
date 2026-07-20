import hashlib
import json
import logging
import os
import sys
import time

import httpx

logger = logging.getLogger(__name__)

# pycspr lives in vendor/ (Windows build). APPEND (not insert-front): vendor/ must
# be a FALLBACK path only. It ships Windows-binary packages (e.g. PIL with
# *.win_amd64.pyd and no Linux _imaging) — inserting it at the FRONT shadows the
# real system Pillow and breaks reportlab/PIL (document & image generation) for the
# whole process once this module is imported. Appending lets real system packages
# win while pycspr (present only in vendor) is still importable as a fallback.
_vendor = os.path.join(os.path.dirname(__file__), "vendor")
if _vendor not in sys.path:
    sys.path.append(_vendor)

from pycspr.types.crypto.complex import PrivateKey  # noqa: E402
from pycspr.types.crypto.simple import KeyAlgorithm  # noqa: E402
from pycspr.types.node.rpc.complex import DeployOfStoredContractByHash, DeployArgument  # noqa: E402
from pycspr.types.cl import CLV_String, CLV_U64  # noqa: E402
import pycspr  # noqa: E402

CASPER_CHAIN = os.getenv("CASPER_CHAIN", "casper-test")
CASPER_RPC = os.getenv("CASPER_RPC_URL", "https://node.testnet.casper.network/rpc")

_PVK_HEX = os.getenv("CASPER_PVK_HEX", "")
_PBK_HEX = os.getenv("CASPER_PBK_HEX", "")

# AI Proof Registry contract deployed on Casper Testnet (Casper Agentic Buildathon 2026)
# Install deploy: f176f0b01541848d36834b9dc7d10f0dcfd9b921542c54ea11199ee8670620f8 (block 8301223)
# Package hash (for DoraHacks submission): 897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
CONTRACT_HASH = "15009cd4a6489c904b699c0a1f292e7e5557e823e54c236539c9ce9973ee2323"
CONTRACT_PACKAGE_HASH = "897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0"
EXPLORER_CONTRACT = f"https://testnet.cspr.live/contract-package/{CONTRACT_PACKAGE_HASH}"


def _load_keypair() -> PrivateKey:
    if _PVK_HEX and _PBK_HEX:
        pvk_bytes = bytes.fromhex(_PVK_HEX)
        pbk_bytes = bytes.fromhex(_PBK_HEX)
    else:
        pvk_bytes, pbk_bytes = pycspr.get_key_pair()
        logger.warning("CASPER_PVK_HEX not set — using ephemeral keypair")
    return PrivateKey(algo=KeyAlgorithm.ED25519, pbk=pbk_bytes, pvk=pvk_bytes)


def compute_session_hash(org_id: str, session_id: str, summary: str) -> str:
    """SHA-256 of the AI session data."""
    raw = json.dumps(
        {"org_id": org_id, "session_id": session_id, "summary": summary},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _build_contract_args(
    session_hash: str,
    ai_action_hash: str,
    workflow_hash: str,
    invoice_hash: str,
    approval_hash: str,
    timestamp: int,
) -> list:
    """Build DeployArgument list for the store_proof entry point."""
    return [
        DeployArgument("session_hash",  CLV_String(session_hash)),
        DeployArgument("ai_action_hash", CLV_String(ai_action_hash)),
        DeployArgument("workflow_hash",  CLV_String(workflow_hash)),
        DeployArgument("invoice_hash",   CLV_String(invoice_hash)),
        DeployArgument("approval_hash",  CLV_String(approval_hash)),
        DeployArgument("timestamp",      CLV_U64(timestamp)),
    ]


async def anchor_session(
    org_id: str,
    session_id: str,
    summary: str,
    ai_action_hash: str = "",
    workflow_hash: str = "",
    invoice_hash: str = "",
    approval_hash: str = "",
) -> dict:
    """
    Call the AI Proof Registry smart contract on Casper Testnet.
    Stores an immutable proof record keyed by session_hash.
    Returns deploy hash, contract details, and explorer URL.
    """
    session_hash = compute_session_hash(org_id, session_id, summary)
    timestamp = int(time.time())

    pvk = _load_keypair()
    params = pycspr.create_deploy_parameters(account=pvk, chain_name=CASPER_CHAIN)
    payment = pycspr.create_standard_payment(5_000_000_000)  # 5 CSPR gas budget

    # Build session: call store_proof entry point on the deployed contract
    args = _build_contract_args(
        session_hash=session_hash,
        ai_action_hash=ai_action_hash or session_hash[:32],
        workflow_hash=workflow_hash or hashlib.sha256(f"workflow:{session_id}".encode()).hexdigest(),
        invoice_hash=invoice_hash or hashlib.sha256(f"invoice:{org_id}:{session_id}".encode()).hexdigest(),
        approval_hash=approval_hash or hashlib.sha256(f"approval:{org_id}:{timestamp}".encode()).hexdigest(),
        timestamp=timestamp,
    )

    session = DeployOfStoredContractByHash(
        hash=bytes.fromhex(CONTRACT_HASH),
        entry_point="store_proof",
        args=args,
    )

    deploy = pycspr.create_deploy(params=params, payment=payment, session=session)
    approval = pycspr.create_deploy_approval(deploy, pvk)
    deploy.approvals.append(approval)

    deploy_dict = pycspr.to_json(deploy)
    deploy_hash = deploy_dict["hash"]

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "account_put_deploy",
        "params": {"deploy": deploy_dict},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(CASPER_RPC, json=rpc_payload)
        resp.raise_for_status()
        result = resp.json()

    if "error" in result:
        raise RuntimeError(f"Casper RPC error: {result['error']}")

    returned_hash = result.get("result", {}).get("deploy_hash", deploy_hash)

    logger.info("Casper store_proof deploy_hash=%s session_hash=%s", returned_hash, session_hash)
    return {
        "deploy_hash": returned_hash,
        "session_hash": session_hash,
        "contract_package_hash": CONTRACT_PACKAGE_HASH,
        "account_key": pvk.account_key.hex(),
        "explorer_url": f"https://testnet.cspr.live/deploy/{returned_hash}",
        "contract_url": EXPLORER_CONTRACT,
    }
