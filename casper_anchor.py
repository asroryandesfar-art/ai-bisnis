import hashlib
import json
import logging
import os
import sys

import httpx

logger = logging.getLogger(__name__)

# pycspr lives in vendor/ on Windows builds; on Linux fastapi is on sys.path so
# vendor is skipped — add it explicitly just for pycspr.
_vendor = os.path.join(os.path.dirname(__file__), "vendor")
if _vendor not in sys.path:
    sys.path.insert(0, _vendor)

from pycspr.types.crypto.complex import PrivateKey  # noqa: E402
from pycspr.types.crypto.simple import KeyAlgorithm  # noqa: E402
import pycspr  # noqa: E402

CASPER_CHAIN = os.getenv("CASPER_CHAIN", "casper-test")
# Official Casper 2.0 testnet HTTPS RPC — no proxy needed, accessible on port 443
CASPER_RPC = os.getenv(
    "CASPER_RPC_URL", "https://node.testnet.casper.network/rpc"
)
# Store hex-encoded private key in env; generate a fresh one if absent (dev only)
_PVK_HEX = os.getenv("CASPER_PVK_HEX", "")
_PBK_HEX = os.getenv("CASPER_PBK_HEX", "")


def _load_keypair() -> PrivateKey:
    if _PVK_HEX and _PBK_HEX:
        pvk_bytes = bytes.fromhex(_PVK_HEX)
        pbk_bytes = bytes.fromhex(_PBK_HEX)
    else:
        pvk_bytes, pbk_bytes = pycspr.get_key_pair()
        logger.warning("CASPER_PVK_HEX not set — using ephemeral keypair (deploys won't land)")
    return PrivateKey(algo=KeyAlgorithm.ED25519, pbk=pbk_bytes, pvk=pvk_bytes)


def compute_session_hash(org_id: str, session_id: str, summary: str) -> str:
    """SHA-256 of the AI session data. Used as correlation anchor on Casper."""
    raw = json.dumps(
        {"org_id": org_id, "session_id": session_id, "summary": summary},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _hash_to_correlation_id(hex_hash: str) -> int:
    """Truncate SHA-256 to a u64 for Casper correlation_id."""
    return int(hex_hash[:16], 16) & 0x7FFF_FFFF_FFFF_FFFF


# Fallback: a known live testnet validator, used when RPC query fails.
_FALLBACK_PROPOSER = bytes.fromhex(
    "01c26fa809f1a4a5949d899137c76fd2a261e35c5427036f0fdd6dabc68068e5a1"
)


async def _get_proposer_key() -> bytes:
    """Return the most-recent block proposer's account key (always a funded validator)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                CASPER_RPC,
                json={"jsonrpc": "2.0", "id": 1, "method": "chain_get_block", "params": {}},
            )
            data = resp.json()
        bws = data["result"]["block_with_signatures"]
        block = bws.get("block", bws)
        header = block.get("header", {})
        proposer_hex = header.get("proposer", "")
        if proposer_hex:
            return bytes.fromhex(proposer_hex)
    except Exception:
        pass
    return _FALLBACK_PROPOSER


async def anchor_session(org_id: str, session_id: str, summary: str) -> dict:
    """
    Build and submit a Casper transfer deploy whose correlation_id encodes the
    SHA-256 of the AI session. Returns the deploy hash and session hash.
    """
    session_hash = compute_session_hash(org_id, session_id, summary)
    correlation_id = _hash_to_correlation_id(session_hash)

    pvk = _load_keypair()
    params = pycspr.create_deploy_parameters(account=pvk, chain_name=CASPER_CHAIN)

    # Casper 2.0 rejects self-transfers ("Invalid purse"); use the most-recent
    # block proposer as the recipient — it is always a live, funded validator.
    # The hash anchor lives in correlation_id; the recipient is irrelevant.
    target_key = await _get_proposer_key()
    deploy = pycspr.create_transfer(
        params=params,
        amount=2_500_000_000,   # 2.5 CSPR minimum transfer (testnet only)
        target=target_key,
        correlation_id=correlation_id,
    )
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

    logger.info("Casper anchor deploy_hash=%s session_hash=%s", returned_hash, session_hash)
    return {
        "deploy_hash": returned_hash,
        "session_hash": session_hash,
        "account_key": pvk.account_key.hex(),
        "explorer_url": f"https://testnet.cspr.live/deploy/{returned_hash}",
    }
