"""GRPO objective over masked tokens (torch; imported only by the trainer backend).

    ratio_t   = exp(logp_t - old_logp_t)                     old = rollout checkpoint, computed before the first update
    pg_t      = -min(ratio_t * A_t, clip(ratio_t, 1-eps, 1+eps) * A_t)
    kl_t      = exp(ref_t - logp_t) - (ref_t - logp_t) - 1   k3 estimator of KL(pi || pi_ref), >= 0, 0 iff equal
    loss      = sum_t mask_t * (pg_t + beta * kl_t)          the caller divides by the step's target-token count

A_t is the turn advantage of the assistant turn token t belongs to (training.rl.advantage); mask = assistant tool-call
tokens only, the same labels SFT trains on."""
from __future__ import annotations


def grpo_token_loss(logp, old_logp, ref_logp, advantages, mask, *, clip_epsilon: float, kl_beta: float):
    import torch
    ratio = torch.exp(logp - old_logp)
    pg = -torch.minimum(ratio * advantages, torch.clamp(ratio, 1 - clip_epsilon, 1 + clip_epsilon) * advantages)
    delta = ref_logp - logp
    kl = torch.exp(delta) - delta - 1
    return ((pg + kl_beta * kl) * mask).sum()
