# Issue #117 – Headscale 0.29.3 → 0.29.4

## Scope

Validation and production upgrade plan for Headscale 0.29.4.

Related:
- Issue #117
- PR #114 – pinned Headscale version and SHA256
- Issue #85 – Headscale backups

## Completed validation

### Package upgrade

Test environment: isolated Debian 13 Docker container with `--network none`.

- Headscale 0.29.3 installed successfully.
- Package upgrade to 0.29.4 completed successfully.
- `dpkg-query` reported `install ok installed`.
- Headscale binary reported `v0.29.4`.

### Snapshot restoration

The latest available Headscale backup snapshot was restored to a separate
20 GB disk and attached to the jumphost in READ_ONLY mode.

The restored filesystem was mounted with `ro,noload`.

The snapshot contained:
- Headscale configuration and policy
- SQLite database
- Noise private key

SQLite integrity check returned `ok`.

### Isolated database validation

A copy of the restored data was tested with Headscale 0.29.4.
The original copy was retained separately for rollback.

Headscale 0.29.4 `configtest` completed without a reported error.

Database comparison:

| Check | Original | Migration test | Rollback test |
|---|---|---|---|
| SQLite integrity | OK | OK | OK |
| Users | 7 | 7 | 7 |
| Nodes | 6 | 6 | 6 |
| User IDs | 1–7 | 1–7 | 1–7 |
| Node IDs | 1–6 | 1–6 | 1–6 |

### Rollback validation

- Headscale 0.29.3 was successfully reinstalled in the test container.
- A separate rollback copy was created from the original restored data.
- Version 0.29.3 passed `configtest` against the rollback copy.
- The migrated database was never opened using the older binary.

The tests did not start a Headscale server or connect test clients to
the production tailnet. They validate package installation, database
integrity and configuration loading, not live client connectivity.

## Production prerequisites

- Confirm all Tailscale clients run version 1.80.0 or later.
- Agree on a maintenance window with the team.
- Prevent new node registrations during maintenance.
- Verify IAP access independently of Tailscale.
- Confirm backup and rollback responsibilities.
- Keep PR #114 unmerged until the maintenance window.

## Production upgrade plan

1. Record current service, users, nodes, routes and DNS state.
2. Stop Headscale and take a consistent full backup of
   `/etc/headscale` and `/var/lib/headscale` outside the boot disk.
3. Preserve ownership, permissions, database files and Noise key.
4. Mask the service to prevent package post-installation auto-restart.
5. Install the verified Headscale 0.29.4 package.
6. Coordinate merge of PR #114 in the same maintenance window.
7. Unmask and start Headscale after package/configuration checks.
8. Verify service status, logs, users, node IDs, routes, DNS and clients.

## Rollback

If the upgrade fails, stop Headscale and restore the complete
pre-upgrade backup together with Headscale 0.29.3.

Do not run the old binary against a database already migrated by
0.29.4. Do not purge the package.

Changes made after the backup may be lost during rollback.

## Status

Isolated validation completed. Production upgrade and post-upgrade
verification are pending. Issue #117 must remain open until then.
