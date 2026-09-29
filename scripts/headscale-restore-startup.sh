#!/bin/bash
# Disposable restore VM only. Supply restore-check and restore-binary-sha256 metadata.
set -euo pipefail
umask 077
case "$(hostname)" in
  team5-restore-129-*) ;;
  *) echo 'Refusing to run on a non-test host.' >&2; exit 1 ;;
esac

metadata=http://metadata.google.internal/computeMetadata/v1/instance/attributes
curl --fail --silent --show-error --max-time 15 -H 'Metadata-Flavor: Google' \
  "$metadata/restore-check" -o /usr/local/bin/headscale-restore-check.py
chmod 755 /usr/local/bin/headscale-restore-check.py
binary_sha=$(curl --fail --silent --show-error --max-time 15 -H 'Metadata-Flavor: Google' \
  "$metadata/restore-binary-sha256")
[[ "$binary_sha" =~ ^[a-f0-9]{64}$ ]]

# The clean image must never start production services. Disable unrelated background work.
systemctl mask apt-daily.timer apt-daily-upgrade.timer google-osconfig-agent.service
systemctl stop --no-block apt-daily.timer apt-daily-upgrade.timer google-osconfig-agent.service
printf 'RESTORE129_BOOT_READY\n'
lsblk -J -o NAME,UUID,PARTUUID,RO,MOUNTPOINTS

# Attach only after reviewing the clean boot disk's IDs. Do not reboot with the clone.
for _ in $(seq 1 120); do
  test ! -b /dev/disk/by-id/google-restore-source-part1 || break
  sleep 5
done
test -b /dev/disk/by-id/google-restore-source-part1
test "$(blockdev --getro /dev/disk/by-id/google-restore-source)" = 1
mkdir -p /mnt/restore-source
trap 'umount /mnt/restore-source || true' EXIT
mount -o ro,noload,nodev,nosuid,noexec /dev/disk/by-id/google-restore-source-part1 /mnt/restore-source
printf 'RESTORE129_SOURCE_PARTITIONS\n'
lsblk -J -o NAME,UUID,PARTUUID,RO,MOUNTPOINTS
python3 /usr/local/bin/headscale-restore-check.py \
  --snapshot-root /mnt/restore-source --binary-sha256 "$binary_sha"
printf 'RESTORE129_NORMAL_PASS\n'
python3 /usr/local/bin/headscale-restore-check.py \
  --snapshot-root /mnt/restore-source --binary-sha256 "$binary_sha" --abort-after-start
printf 'RESTORE129_ABORT_PASS\n'
umount /mnt/restore-source
trap - EXIT
test -z "$(find /var/tmp -maxdepth 1 -name 'headscale-restore-129-*' -print -quit)"
if pgrep -x headscale >/dev/null; then exit 1; fi
printf 'RESTORE129_ALL_PASS\n'
