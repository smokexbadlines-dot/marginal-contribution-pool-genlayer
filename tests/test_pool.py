"""Direct-mode tests of settlement, ordering, evidence, and replay guards."""

from datetime import datetime, timezone
import hashlib
import json

import pytest


CONTRACT = "contracts/MarginalContributionPool.py"
URL_A = "https://raw.githubusercontent.com/example/docs/" + "a" * 40 + "/guide.md"
URL_B = "https://raw.githubusercontent.com/example/docs/" + "b" * 40 + "/guide.md"
NONCE_A = "1" * 64
NONCE_B = "2" * 64
GOAL_A = "Explain installation on Windows with prerequisites, commands, and a verification step."
GOAL_B = "Explain installation on Linux with prerequisites, commands, and a verification step."


def ts(day: int) -> int:
    return int(datetime(2026, 10, day, tzinfo=timezone.utc).timestamp())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def commitment(goal_mask: int, owner, url: str, sha: str, nonce: str) -> str:
    owner_text = "0x" + owner.hex() if isinstance(owner, bytes) else str(owner).lower()
    return hashlib.sha256(
        f"MCP2\n{goal_mask}\n{owner_text}\n{url}\n{sha}\n{nonce}".encode()
    ).hexdigest()


def start_pool(direct_vm, direct_deploy, reward_a=10, reward_b=20):
    direct_vm.warp("2026-10-16T00:00:00Z")
    pool = direct_deploy(CONTRACT, "Documentation pool", ts(17), ts(18), ts(20))
    pool.add_goal(GOAL_A, reward_a)
    pool.add_goal(GOAL_B, reward_b)
    pool.seal()
    direct_vm.value = reward_a + reward_b
    pool.fund()
    direct_vm.value = 0
    assert pool.pool()[3] is True
    return pool


def add_submission(direct_vm, pool, owner, goal, url, text, nonce):
    sha = digest(text)
    with direct_vm.prank(owner):
        submission_id = pool.commit(1 << goal, commitment(1 << goal, owner, url, sha, nonce))
    return submission_id, sha


def reveal_submission(direct_vm, pool, owner, submission_id, url, sha, nonce):
    with direct_vm.prank(owner):
        pool.reveal(submission_id, url, sha, nonce)


def add_mask_submission(direct_vm, pool, owner, mask, url, text, nonce):
    sha = digest(text)
    with direct_vm.prank(owner):
        submission_id = pool.commit(mask, commitment(mask, owner, url, sha, nonce))
    return submission_id, sha


def test_multi_goal_marginal_value_uses_only_new_coverage(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    pool = start_pool(direct_vm, direct_deploy)
    messages = []
    direct_vm._gl_call_hook = lambda _vm, request: messages.append(request) or None
    windows = "Windows: install Python; run pip install project; verify with project --version."
    linux = "Linux: install Python; run pip install project; verify with project --version."
    first, first_sha = add_mask_submission(direct_vm, pool, direct_alice, 3, URL_A, windows, NONCE_A)
    second, second_sha = add_mask_submission(direct_vm, pool, direct_bob, 3, URL_B, linux, NONCE_B)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, first, URL_A, first_sha, NONCE_A)
    reveal_submission(direct_vm, pool, direct_bob, second, URL_B, second_sha, NONCE_B)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"/" + "a" * 40 + r"/", {"status": 200, "body": windows})
    direct_vm.mock_llm(r"Goal: .*Windows", '{"verdict":"MET"}')
    direct_vm.mock_llm(r"Goal: .*Linux", '{"verdict":"NOT_MET"}')
    assert pool.resolve_next() == "MET"
    assert int(pool.pool()[7]) == 0
    assert pool.submission(first)[6] == "REVEALED"
    assert int(pool.submission(first)[10]) == 1
    assert pool.resolve_next() == "NOT_MET"
    assert pool.submission(first)[6] == "PAID"
    assert int(pool.submission(first)[12]) == 10
    assert int(pool.pool()[7]) == 10
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"/" + "b" * 40 + r"/", {"status": 200, "body": linux})
    direct_vm.mock_llm(r"Goal: .*Linux", '{"verdict":"MET"}')
    assert pool.resolve_next() == "MET"
    assert pool.submission(second)[6] == "PAID"
    assert int(pool.submission(second)[9]) == 2
    assert int(pool.submission(second)[10]) == 2
    assert int(pool.submission(second)[12]) == 20
    assert int(pool.pool()[7]) == 30
    assert int(pool.goal(0)[3]) == int(first)
    assert int(pool.goal(1)[3]) == int(second)
    transfers = [request["EthSend"] for request in messages if "EthSend" in request]
    assert [transfer["value"] for transfer in transfers] == [10, 20]
    with direct_vm.expect_revert("no pending submission"):
        pool.resolve_next()


def test_goal_mask_bounds_and_commitment_domain(direct_vm, direct_deploy, direct_alice):
    pool = start_pool(direct_vm, direct_deploy)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("invalid goal mask"):
            pool.commit(0, "3" * 64)
        with direct_vm.expect_revert("invalid goal mask"):
            pool.commit(4, "3" * 64)
        submission_id = pool.commit(3, commitment(3, direct_alice, URL_A, digest("x"), NONCE_A))
    direct_vm.warp("2026-10-17T00:00:00Z")
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("commitment mismatch"):
            pool.reveal(submission_id, URL_A, digest("x"), NONCE_B)
        pool.reveal(submission_id, URL_A, digest("x"), NONCE_A)
    assert int(pool.submission(submission_id)[0]) == 3


def test_source_change_during_multi_goal_assessment_voids_unpaid_credit(
    direct_vm, direct_deploy, direct_alice
):
    pool = start_pool(direct_vm, direct_deploy)
    text = "Windows and Linux installation instructions with commands and verification."
    submission_id, sha = add_mask_submission(
        direct_vm, pool, direct_alice, 3, URL_A, text, NONCE_A
    )
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, submission_id, URL_A, sha, NONCE_A)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": text})
    direct_vm.mock_llm(r"Goal: .*Windows", '{"verdict":"MET"}')
    assert pool.resolve_next() == "MET"
    assert int(pool.submission(submission_id)[10]) == 1
    assert int(pool.pool()[7]) == 0
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        r"raw\.githubusercontent\.com", {"status": 200, "body": text + " tampered"}
    )
    assert pool.resolve_next() == "INVALID"
    assert pool.submission(submission_id)[6] == "INVALID"
    assert int(pool.pool()[7]) == 0
    assert pool.goal(0)[2] is False
    direct_vm.warp("2026-10-20T00:00:00Z")
    assert int(pool.expire()) == 30


def test_marginal_reward_and_duplicate_guard(direct_vm, direct_deploy, direct_alice, direct_bob):
    pool = start_pool(direct_vm, direct_deploy)
    messages = []
    direct_vm._gl_call_hook = lambda _vm, request: messages.append(request) or None
    text = "Windows: install Python; run pip install project; verify with project --version."
    first, sha = add_submission(direct_vm, pool, direct_alice, 0, URL_A, text, NONCE_A)
    second, sha2 = add_submission(direct_vm, pool, direct_bob, 0, URL_B, text, NONCE_B)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, first, URL_A, sha, NONCE_A)
    reveal_submission(direct_vm, pool, direct_bob, second, URL_B, sha2, NONCE_B)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": text})
    direct_vm.mock_llm(r"Judge whether", '{"verdict":"MET"}')
    assert pool.resolve_next() == "MET"
    assert pool.goal(0)[2] is True
    assert int(pool.pool()[7]) == 10
    assert pool.submission(first)[6] == "PAID"
    assert pool.submission(second)[6] == "REDUNDANT"
    forged_same_verdict = json.dumps(
        {"source_sha256": "0" * 64, "verdict": "MET"},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert direct_vm.run_validator(leader_result=forged_same_verdict) is False
    transfers = [request["EthSend"] for request in messages if "EthSend" in request]
    assert len(transfers) == 1
    assert transfers[0]["value"] == 10
    assert str(transfers[0]["address"]).lower() == "0x" + direct_alice.hex()
    with direct_vm.expect_revert("no pending submission"):
        pool.resolve_next()
    assert int(pool.pool()[7]) == 10
    direct_vm.warp("2026-10-20T00:00:00Z")
    assert int(pool.expire()) == 20
    assert int(pool.pool()[8]) == 20
    transfers = [request["EthSend"] for request in messages if "EthSend" in request]
    assert len(transfers) == 2
    assert transfers[1]["value"] == 20


def test_rejected_first_submission_allows_later_one(direct_vm, direct_deploy, direct_alice, direct_bob):
    pool = start_pool(direct_vm, direct_deploy)
    first_text = "A short note without Linux instructions."
    second_text = "Linux: install Python; run pip install project; verify with project --version."
    first, first_sha = add_submission(direct_vm, pool, direct_alice, 1, URL_A, first_text, NONCE_A)
    second, second_sha = add_submission(direct_vm, pool, direct_bob, 1, URL_B, second_text, NONCE_B)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, first, URL_A, first_sha, NONCE_A)
    reveal_submission(direct_vm, pool, direct_bob, second, URL_B, second_sha, NONCE_B)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"/" + "a" * 40 + r"/", {"status": 200, "body": first_text})
    direct_vm.mock_web(r"/" + "b" * 40 + r"/", {"status": 200, "body": second_text})
    direct_vm.mock_llm(r"A short note", '{"verdict":"NOT_MET"}')
    direct_vm.mock_llm(r"Linux: install", '{"verdict":"MET"}')
    assert pool.resolve_next() == "NOT_MET"
    assert int(pool.pool()[7]) == 0
    assert pool.resolve_next() == "MET"
    assert int(pool.pool()[7]) == 20
    assert int(pool.goal(1)[3]) == int(second)


def test_wrong_hash_and_forged_leader_rejected(direct_vm, direct_deploy, direct_alice):
    pool = start_pool(direct_vm, direct_deploy)
    text = "Windows: install Python, run the installer, and verify the command."
    submission_id, sha = add_submission(direct_vm, pool, direct_alice, 0, URL_A, text, NONCE_A)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, submission_id, URL_A, sha, NONCE_A)
    direct_vm.warp("2026-10-18T00:00:00Z")
    changed = text + " altered"
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": changed})
    assert pool.resolve_next() == "INVALID"
    assert pool.submission(submission_id)[6] == "INVALID"
    assert pool.submission(submission_id)[5] == digest(changed)
    assert int(pool.pool()[7]) == 0
    forged = json.dumps(
        {"source_sha256": digest(changed), "verdict": "MET"},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert direct_vm.run_validator(leader_result=forged) is False
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 503, "body": ""})
    assert direct_vm.run_validator() is False


def test_uncertainty_bounded_then_refund(direct_vm, direct_deploy, direct_alice):
    pool = start_pool(direct_vm, direct_deploy)
    text = "Potential documentation"
    submission_id, sha = add_submission(direct_vm, pool, direct_alice, 0, URL_A, text, NONCE_A)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, submission_id, URL_A, sha, NONCE_A)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 503, "body": ""})
    assert pool.resolve_next() == "UNCLEAR"
    assert pool.resolve_next() == "UNCLEAR"
    assert pool.submission(submission_id)[6] == "INCONCLUSIVE"
    with direct_vm.expect_revert("no pending submission"):
        pool.resolve_next()
    direct_vm.warp("2026-10-20T00:00:00Z")
    assert int(pool.expire()) == 30
    assert pool.pool()[4] is True
    with direct_vm.expect_revert("not expirable"):
        pool.expire()


def test_authorization_windows_and_replay(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp("2026-10-16T00:00:00Z")
    pool = direct_deploy(CONTRACT, "Documentation pool", ts(17), ts(18), ts(20))
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("sponsor only"):
            pool.add_goal(GOAL_A, 10)
    pool.add_goal(GOAL_A, 10)
    pool.seal()
    with direct_vm.expect_revert("cannot seal"):
        pool.seal()
    direct_vm.value = 10
    pool.fund()
    direct_vm.value = 0
    text = "Windows guide"
    sub_id, sha = add_submission(direct_vm, pool, direct_alice, 0, URL_A, text, NONCE_A)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("duplicate commitment"):
            pool.commit(1, commitment(1, direct_alice, URL_A, sha, NONCE_A))
    direct_vm.warp("2026-10-17T00:00:00Z")
    with direct_vm.expect_revert("commits closed"):
        pool.commit(1, "3" * 64)
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("submitter only"):
            pool.reveal(sub_id, URL_A, sha, NONCE_A)
    reveal_submission(direct_vm, pool, direct_alice, sub_id, URL_A, sha, NONCE_A)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("already revealed"):
            pool.reveal(sub_id, URL_A, sha, NONCE_A)


def test_copied_commitment_cannot_block_original_owner(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    pool = start_pool(direct_vm, direct_deploy)
    text = "Windows installation instructions."
    sha = digest(text)
    copied = commitment(1, direct_alice, URL_A, sha, NONCE_A)
    with direct_vm.prank(direct_bob):
        stolen_id = pool.commit(1, copied)
    with direct_vm.prank(direct_alice):
        original_id = pool.commit(1, copied)
    assert pool.submission(stolen_id)[2] != pool.submission(original_id)[2]
    direct_vm.warp("2026-10-17T00:00:00Z")
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("commitment mismatch"):
            pool.reveal(stolen_id, URL_A, sha, NONCE_A)
    reveal_submission(direct_vm, pool, direct_alice, original_id, URL_A, sha, NONCE_A)
    assert pool.submission(original_id)[6] == "REVEALED"


def test_unrevealed_cannot_block_queue(direct_vm, direct_deploy, direct_alice, direct_bob):
    pool = start_pool(direct_vm, direct_deploy)
    text = "Windows: install Python; run pip install project; verify with project --version."
    first, _ = add_submission(direct_vm, pool, direct_alice, 0, URL_A, text, NONCE_A)
    second, sha = add_submission(direct_vm, pool, direct_bob, 0, URL_B, text, NONCE_B)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_bob, second, URL_B, sha, NONCE_B)
    direct_vm.warp("2026-10-18T00:00:00Z")
    assert pool.resolve_next() == "UNREVEALED"
    assert pool.submission(first)[6] == "UNREVEALED"
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": text})
    direct_vm.mock_llm(r"Judge whether", '{"verdict":"MET"}')
    assert pool.resolve_next() == "MET"
    assert int(pool.goal(0)[3]) == int(second)


def test_evidence_bounds_and_bad_utf8_are_inconclusive(direct_vm, direct_deploy, direct_alice):
    pool = start_pool(direct_vm, direct_deploy)
    bad_bytes = b"\xff"
    sha = hashlib.sha256(bad_bytes).hexdigest()
    commit_hash = commitment(1, direct_alice, URL_A, sha, NONCE_A)
    with direct_vm.prank(direct_alice):
        submission_id = pool.commit(1, commit_hash)
    direct_vm.warp("2026-10-17T00:00:00Z")
    reveal_submission(direct_vm, pool, direct_alice, submission_id, URL_A, sha, NONCE_A)
    direct_vm.warp("2026-10-18T00:00:00Z")
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": "x" * 12001})
    assert pool.resolve_next() == "UNCLEAR"
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"raw\.githubusercontent\.com", {"status": 200, "body": bad_bytes})
    assert pool.resolve_next() == "UNCLEAR"
    assert pool.submission(submission_id)[6] == "INCONCLUSIVE"
    assert int(pool.pool()[7]) == 0


def test_deadlines_bounded(direct_vm, direct_deploy):
    direct_vm.warp("2026-10-16T00:00:00Z")
    with direct_vm.expect_revert("pool too long"):
        direct_deploy(CONTRACT, "Long pool", ts(17), ts(18), ts(31) + 90 * 86400)


def test_permissionless_expiry_closes_pending_submission(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    pool = start_pool(direct_vm, direct_deploy)
    submission_id, _ = add_submission(
        direct_vm, pool, direct_alice, 0, URL_A, "unfinished", NONCE_A
    )
    direct_vm.warp("2026-10-20T00:00:00Z")
    with direct_vm.prank(direct_bob):
        assert int(pool.expire()) == 30
    assert pool.submission(submission_id)[6] == "EXPIRED"
    assert int(pool.pool()[8]) == 30
    with direct_vm.expect_revert("pool inactive"):
        pool.resolve_next()


def test_full_funding_required(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp("2026-10-16T00:00:00Z")
    pool = direct_deploy(CONTRACT, "Documentation pool", ts(17), ts(18), ts(20))
    pool.add_goal(GOAL_A, 10)
    pool.seal()
    direct_vm.value = 5
    pool.fund()
    direct_vm.value = 0
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("commits closed"):
            pool.commit(1, "3" * 64)
    direct_vm.value = 7
    pool.fund()
    direct_vm.value = 0
    assert pool.pool()[3] is True
    direct_vm.warp("2026-10-20T00:00:00Z")
    assert int(pool.expire()) == 12
