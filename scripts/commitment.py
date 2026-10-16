"""Compute a MarginalContributionPool submission commitment.

Usage:
  python scripts/commitment.py GOAL_MASK WALLET_ADDRESS PINNED_RAW_URL SHA256 NONCE
"""

import hashlib
import re
import sys


def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    goal_mask, wallet, url, sha256, nonce = sys.argv[1:]
    if not goal_mask.isdecimal() or int(goal_mask) < 1 or int(goal_mask) > 63:
        raise SystemExit("GOAL_MASK must be a decimal integer from 1 to 63")
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet) is None:
        raise SystemExit("WALLET_ADDRESS must be 0x followed by 40 hex characters")
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise SystemExit("SHA256 must be 64 lowercase hex characters")
    if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
        raise SystemExit("NONCE must be 64 lowercase hex characters")
    message = f"MCP2\n{int(goal_mask)}\n{wallet.lower()}\n{url}\n{sha256}\n{nonce}"
    print(hashlib.sha256(message.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    main()
