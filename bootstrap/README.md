# CI deploy permissions

`cicd-role.tf` defines a custom role for the current root module's Compute
resources. It excludes IAM administration, service-account impersonation and
bucket administration. State object access remains in the authoritative bucket
policy in `main.tf`; do not add a separate bucket IAM member.

The role is granted at project level. It reduces available operations but does
not isolate Compute resources belonging to other teams. VM metadata writes are
still powerful. Restricting who can use the CI identity is separate work in #28.
Attaching a service account (#46) or adding other resource types requires a new
permission review; do not add broad roles as a workaround.

## Controlled rollout

Bootstrap is applied manually from reviewed, merged code. Root CI does not apply it.

1. An operator with custom-role management and project IAM permissions reviews
   and applies bootstrap with `retire_legacy_cicd_roles = false` (the default).
   This adds the role and its binding while retaining Editor and Network Admin.
   Existing grants move to indexed Terraform addresses without recreating them.
2. Verify permission coverage using an isolated test identity with only the new
   role and the required test-state access, in an explicitly approved test
   environment. Cover creation, update and deletion, including firewall changes,
   VM metadata/start-stop and state locking. A green plan or deploy while Editor
   remains assigned does **not** prove the replacement role is sufficient.
3. After verification, set `retire_legacy_cicd_roles = true` in the committed
   bootstrap inputs. Review a fresh plan: retire only the two legacy grants and
   preserve the custom role, its binding and the bucket policy. Apply in a
   controlled window and verify root plan/deploy with the actual CI identity.
4. Keep an independent operator with project IAM rights available for rollback.
   If necessary, restore the legacy grants by setting the variable to `false`
   and reviewing/applying bootstrap; CI must not grant itself permissions.

Do not close #10 after the additive first step. Editor remains effective until
the retirement step completes. Review all bootstrap changes together, including
any pending bucket-policy or audit-log changes, before applying a saved plan.

`terraform test` uses mocked providers and plan-only runs. It checks the absence
of identity administration, required firewall permissions and the rollout switch;
it does not prove live authorization or access isolation.

References: [Compute API permissions](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert),
[custom roles](https://docs.cloud.google.com/iam/docs/creating-custom-roles).
