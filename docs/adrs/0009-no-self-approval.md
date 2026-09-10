# 0009. No self-approval on promotion decisions

Status: Accepted

## Context

The brief asks explicitly: "can the requester approve their own production promotion?" None of the inspected systems have an approval concept to set precedent either way - `ai-operations`' `approved_by` field is an unauthenticated free-text string with no check against who submitted the related request.

## Decision

`PromotionDecision.decided_by` must not equal the corresponding `PromotionRequest.requested_by`, enforced at write time in application logic backed by a DB check, regardless of role - an Admin requesting their own promotion still needs a different Reviewer or Admin to approve it.

## Alternatives considered

- **Allow Admin self-approval as a role privilege.** Rejected - undermines the entire point of having a review step; an Admin's elevated permissions should mean they can approve *others'* requests broadly, not that review doesn't apply to them.
- **Make this a configurable policy rather than a hard rule.** Rejected per the brief's non-goal of avoiding enterprise-IAM-style configurability where the domain doesn't need it - this is a simple, universal rule with no legitimate exception in the current organization.

## Consequences

A single-person team (or an Admin acting alone) cannot promote their own work to production without involving a second person - this is the intended friction, not an oversight. Small teams may find this adds real latency; no exception is built for that case in this design.
