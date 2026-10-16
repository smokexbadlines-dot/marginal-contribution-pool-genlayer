# Marginal Contribution Pool

A standalone GenLayer Native Intelligent Contract that funds a bounded set of public contribution goals. Contributors submit pinned artifacts in a commit–reveal round. GenLayer validators judge whether each artifact meets each claimed goal. Deterministic contract code pays only for goals that the submission adds to the pool's accepted coverage.

## Mechanism

The sponsor freezes up to six observable goals, each with a fixed GEN reward. A contributor commits to an artifact and a bitmask of claimed goals before the reveal window. After reveal, anyone can call `resolve_next()`; the contract itself selects the earliest pending submission and its first unassessed, uncovered claimed goal. The caller cannot select a candidate, goal, verdict, amount, or recipient.

Each judgment is one goal against one pinned raw GitHub file. The leader and validators independently fetch the complete raw bytes, verify the committed SHA-256, and classify the claim as `MET`, `NOT_MET`, or `UNCLEAR`. They must agree exactly on the canonical report containing the verdict and observed SHA-256. Hash mismatch is `INVALID` and closes the whole submission. Missing, oversized, malformed, or ambiguous evidence remains `UNCLEAR`; two such attempts close that goal as inconclusive.

After every claimed, uncovered goal is assessed, code computes the marginal reward:

```text
new coverage = goals judged MET for this submission − goals already covered
reward = sum of frozen rewards for new coverage
```

The submission is then settled once. Accepted goals become covered and name this submission as their winner. A later submission claiming only covered goals becomes `REDUNDANT` without another judgment. A submission adding no coverage is `NO_GAIN` or `INCONCLUSIVE`. The accounting invariant is `paid + refunded <= funded`, and each goal has one winner at most. The LLM never chooses a payment amount.

This is an ordered set-cover mechanism, rather than a first-qualifying bounty for one goal. A multi-goal submission can earn a partial reward, and every accepted submission changes what later submissions can add. It is separate from PolicyConflictReducer: that contract minimizes an incompatible clause set against a source policy, while this one allocates fixed rewards over an evolving coverage set. It may still resemble other contribution or bounty contracts; check the Portal cohort before claiming novelty.

## Lifecycle and API

1. Deploy with a title and `commit_deadline < reveal_deadline < resolution_deadline`, as Unix seconds. The last deadline must be within 90 days; reveal and resolution windows must each be at least one hour.
2. The sponsor calls `add_goal(criterion, reward)` for each goal, then `seal()` and payable `fund()`. Commitments open only when the pool is fully funded. Extra funding is refunded at expiry.
3. Before `commit_deadline`, a contributor calls `commit(goal_mask, commitment)`. Bit 0 claims goal 0, bit 1 claims goal 1, and so on. For two goals, mask `3` claims both. The pool allows 24 submissions and four claims per goal.
4. During the reveal window, the same contributor calls `reveal(submission_id, url, sha256, nonce)`.
5. During the resolution window, anyone calls `resolve_next()` repeatedly. Each call either marks one unrevealed commitment, judges one goal, or settles a submission that has nothing left to judge. The contract processes submissions by commitment order. Read `submission(id)` after each call to see its status and masks.
6. After `resolution_deadline`, anyone calls `expire()` once to mark pending submissions `EXPIRED` and refund all unpaid accounted funds to the sponsor.

Views: `pool()`, `goal(index)`, `submission(id)`. Submission IDs start at 1; goal indices start at 0. A submission view ends with `assessed_mask`, `met_mask`, `inconclusive_mask`, and `earned_wei`. A `MET` verdict can leave a multi-goal submission in `REVEALED` until its other claims are resolved; payment occurs only at settlement.

## Commitment recipe

Use a pinned URL of the form `https://raw.githubusercontent.com/OWNER/REPO/40_HEX_COMMIT/PATH`. Hash the **raw response bytes** with SHA-256. Choose a private 32-byte random nonce, represented as 64 lowercase hex characters. The commitment is the SHA-256 of UTF-8 text with these six lines and no trailing newline:

```text
MCP2
<decimal goal mask>
<lowercase 0x wallet address>
<pinned raw URL>
<64-char lowercase artifact SHA-256>
<64-char lowercase nonce>
```

Compute it with `python scripts/commitment.py GOAL_MASK WALLET_ADDRESS PINNED_RAW_URL SHA256 NONCE`. Keep the URL, SHA-256, and nonce until reveal. `MCP2` intentionally changes the commitment domain from the earlier prototype; old commitments cannot be revealed against this source.

The contract stores a second, sender-bound hash of the submitted commitment. Copying another account's visible commitment cannot take over or directly invalidate that account's reveal. A copied commitment still occupies one of the bounded claim slots, so this does not eliminate Sybil spam.

## Local verification

The contract pins `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` and was checked with GenVM `v0.3.0-rc7`. Probe the runner on the chosen network before deploying; a local lint pass does not establish network support.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
$env:GENVM_VERSION = 'v0.3.0-rc7'
$env:PYTHONIOENCODING = 'utf-8'
genvm-lint check contracts/MarginalContributionPool.py
```

The 14 direct-mode tests use mocked web and LLM responses. They cover ordered marginal rewards, partial and duplicate coverage, mask and commitment guards, copied commitments, forged leader reports, wrong hashes, a source change during multi-goal assessment, unavailable and malformed evidence, bounded retries, permissions, replay, deadlines, emitted transfer instructions, and permissionless refunds. They do **not** prove live validator consensus or actual GEN transfers.

## Live proof before submission

1. Probe the pinned runner with a small contract on the target GenLayer network. Probe the selected raw GitHub URLs from validators, and measure their raw byte lengths against the 12,000-byte cap.
2. Deploy this exact source from a pushed commit. Verify the on-chain source matches the Git blob byte for byte.
3. Use two narrow goals and two pinned artifacts to demonstrate a partial first contribution, a second contribution that fills the remaining goal, and a redundant duplicate. Also demonstrate a wrong-hash rejection and a permissionless expiry refund. Use an artifact containing a prompt-injection attempt as an adversarial case.
4. For every transaction, record transaction hash, finalization status, leader execution result, and state read-back. Verify outgoing GEN transfers or balance changes separately. A finalized transaction with failed execution is not a successful demo.
5. Publish a release manifest with source commit, blob hash, runner, network, constructor arguments, contract address, receipts, expected failures, and read-backs. The public repo and explorer links must resolve without login before Portal submission.

## Limits

- A qualifying verdict means validators agreed that a pinned artifact meets a frozen goal. It does not prove who authored the artifact or measure broader real-world impact.
- The sponsor must choose specific, observable goals. The contract bounds their size but does not semantically screen vague wording.
- Up to four commitments can claim each goal. This bounds execution but permits a well-funded spammer to occupy slots. Transaction fees and source visibility do not by themselves solve Sybil resistance.
- Exact verdict comparison can fail to reach consensus on borderline evidence. Use clear source text and goal wording for live demonstrations.
- A pending submission may remain unsettled when the resolution window closes; `expire()` deterministically refunds unpaid funds.
- External EOA transfers are emitted for finalization. Direct-mode tests inspect emitted instructions and state, not final chain-layer balances.

## GenLayer references

- [Intelligent Contracts](https://docs.genlayer.com/developers/intelligent-contracts/introduction)
- [Non-determinism and validator functions](https://docs.genlayer.com/developers/intelligent-contracts/features/non-determinism)
- [Web Access](https://docs.genlayer.com/developers/intelligent-contracts/features/web-access)
- [Value Transfers](https://docs.genlayer.com/developers/intelligent-contracts/features/value-transfers)
- [Testing](https://docs.genlayer.com/developers/intelligent-contracts/testing)
