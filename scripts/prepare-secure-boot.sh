#!/bin/bash
# Debian 13 / GCE migration. Run prepare, reboot with Secure Boot OFF, then finalize.
# This script never restarts the VM or changes its GCP Secure Boot setting.
set -euo pipefail
export LC_ALL=C
export DEBIAN_FRONTEND=noninteractive

die() { printf '%s\n' "$*" >&2; exit 1; }
if [[ $# != 2 || ! $1 =~ ^(prepare|finalize|check)$ ]]; then
    die "Usage: $0 prepare|finalize|check EXPECTED_GCE_INSTANCE_NAME"
fi
phase=$1
expected_instance=$2
[[ $EUID == 0 ]] || die 'Run this script as root.'
actual_instance=$(curl --max-time 10 -fsS -H 'Metadata-Flavor: Google' \
    http://metadata.google.internal/computeMetadata/v1/instance/name)
[[ $actual_instance == "$expected_instance" ]] || die 'GCE instance name does not match the expected target.'
source /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 && $(dpkg --print-architecture) == amd64 ]] || die 'Only Debian 13 amd64 is supported.'
[[ -d /sys/firmware/efi/efivars ]] || die 'UEFI boot is required.'
exec 9>/run/lock/prepare-secure-boot.lock
flock -n 9 || die 'Another kernel migration is running.'

state_dir=/var/lib/secureboot-kernel-migration
grub_override=/etc/default/grub.d/99-secureboot-migration.cfg
old_package=linux-image-6.18.9+deb13-cloud-amd64-unsigned

verify_kernel() {
    local kernel=$1 owner
    owner=$(dpkg-query -S "/boot/vmlinuz-$kernel")
    [[ $owner == "linux-image-$kernel: /boot/vmlinuz-$kernel" ]] || die 'Kernel is not owned by the expected signed-image package.'
    [[ $(dpkg-query -W -f='${source:Package}' "linux-image-$kernel") == linux-signed-amd64 ]] || die 'Unexpected kernel source package.'
    [[ -z $(dpkg -V "linux-image-$kernel") ]] || die 'Kernel package verification failed.'
    python3 - "$kernel" <<'PY'
import pathlib, struct, sys
kernel = pathlib.Path('/boot/vmlinuz-' + sys.argv[1]).read_bytes()
pe = struct.unpack_from('<I', kernel, 0x3c)[0]
assert kernel[pe:pe + 4] == b'PE\0\0', 'Not a PE image'
optional = pe + 24
assert struct.unpack_from('<H', kernel, optional)[0] == 0x20b, 'Not PE32+'
offset, size = struct.unpack_from('<II', kernel, optional + 112 + 8 * 4)
assert offset > 0 and size > 8 and offset + size <= len(kernel), 'Missing embedded signature'
print('Signed-package kernel verified; firmware trust is verified by the subsequent Secure Boot test.')
PY
}

if [[ $phase == prepare ]]; then
    if [[ -e $state_dir/target-kernel ]]; then
        die 'Preparation already exists. Inspect the saved state; reboot and finalize if appropriate.'
    fi
    [[ ! -e $grub_override ]] || die 'A GRUB override already exists; inspect it before continuing.'
    [[ $(dpkg-query -W -f='${db:Status-Status}' "$old_package") == installed ]] || die 'The expected unsigned lab kernel is not installed.'
    [[ $(uname -r) == 6.18.9+deb13-cloud-amd64 ]] || die 'Unexpected running kernel; reassess the migration.'
    mkdir -p "$state_dir"
    chmod 700 "$state_dir"
    cp -a /etc/default/grub "$state_dir/grub.before"
    cp -a /etc/default/grub.d "$state_dir/grub.d.before"
    apt-mark showhold >"$state_dir/holds.before"
    apt-get --error-on=any update
    # Install the supported stable cloud metapackage, retaining the old kernel for rollback.
    apt-get --simulate --no-remove --no-install-recommends install linux-image-cloud-amd64
    apt-get -y --no-remove --no-install-recommends install linux-image-cloud-amd64
    target_package=$(dpkg-query -W -f='${Depends}' linux-image-cloud-amd64 | grep -oE 'linux-image-[0-9][^ ,(]+' | head -n1)
    [[ $target_package =~ ^linux-image-[0-9][0-9a-z.+-]*-cloud-amd64$ ]] || die 'Could not identify the signed cloud kernel dependency.'
    target_kernel=${target_package#linux-image-}
    verify_kernel "$target_kernel"
    update-grub
    # The old backports kernel has a higher version, so select the signed stable kernel explicitly.
    python3 - "$target_kernel" "$grub_override" <<'PY'
import pathlib, re, sys
kernel, output = sys.argv[1:]
config = pathlib.Path('/boot/grub/grub.cfg').read_text()
submenus = re.findall(r"^submenu .* '([^']+)' \{", config, re.M)
entries = re.findall(r"^\s*menuentry .* '([^']+)' \{", config, re.M)
submenu = [x for x in submenus if x.startswith('gnulinux-advanced-')]
entry = [x for x in entries if x.startswith('gnulinux-' + kernel + '-advanced-')]
assert len(submenu) == len(entry) == 1, 'Expected exactly one normal signed-kernel entry'
with pathlib.Path(output).open('x') as stream:
    stream.write('# Temporary selection until the unsigned kernel is removed.\n')
    stream.write('GRUB_DEFAULT="' + submenu[0] + '>' + entry[0] + '"\n')
PY
    printf '%s\n' "$target_kernel" >"$state_dir/target-kernel"
    update-grub
    grub-script-check /boot/grub/grub.cfg
    printf 'Prepared %s. Reboot with Secure Boot OFF, verify SSH/sudo, then run finalize.\n' "$target_kernel"
elif [[ $phase == finalize ]]; then
    [[ -f $state_dir/target-kernel ]] || die 'Preparation state is missing.'
    target_kernel=$(cat "$state_dir/target-kernel")
    [[ $(uname -r) == "$target_kernel" ]] || die 'Boot the prepared signed kernel before removing the old kernel.'
    verify_kernel "$target_kernel"
    if [[ $(dpkg-query -W -f='${db:Status-Status}' "$old_package" 2>/dev/null || true) == installed ]]; then
        apt-get --simulate purge "$old_package" >"$state_dir/removal-plan.txt"
        cat "$state_dir/removal-plan.txt"
        unexpected=$(awk '$1 == "Remv" || $1 == "Purg" {print $2}' "$state_dir/removal-plan.txt" | grep -vx "$old_package" || true)
        [[ -z $unexpected ]] || die 'Removal would affect other packages; inspect the plan.'
        apt-mark unhold "$old_package"
        if ! apt-get -y purge "$old_package"; then
            apt-mark hold "$old_package" || true
            die 'Kernel removal failed. Inspect package state before continuing.'
        fi
    fi
    # Return to the normal GRUB selection so future signed kernel updates become the default.
    rm -f "$grub_override"
    update-grub
    grub-script-check /boot/grub/grub.cfg
    printf 'Unsigned lab kernel removed. Keep the snapshot until Secure Boot and network tests pass.\n'
else
    verify_kernel "$(uname -r)"
    python3 - <<'PY'
import pathlib
variable = pathlib.Path('/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c')
enabled = variable.read_bytes()[4] == 1
print('Firmware Secure Boot enabled:', enabled)
lockdown = pathlib.Path('/sys/kernel/security/lockdown')
if lockdown.exists():
    print('Kernel lockdown:', lockdown.read_text().strip())
assert enabled, 'Secure Boot has not been enabled and verified yet'
PY
fi
