# Project-level permissions for the resources managed by the root module.
# This is a permission reduction, not isolation from other teams' Compute resources.
# IAM, WIF, bucket administration and service-account impersonation are excluded.
# Object access remains in the existing authoritative bucket policy in main.tf.
resource "google_project_iam_custom_role" "cicd_deploy" {
  project     = var.project_id
  role_id     = "team${var.team_id}TerraformDeploy"
  title       = "Team ${var.team_id} Terraform deploy"
  description = "Manage root-module Compute resources without IAM administration."
  stage       = "GA"

  permissions = [
    # Resource discovery and asynchronous operation polling.
    "compute.projects.get",
    "compute.regions.get",
    "compute.zones.get",
    "compute.zones.list",
    "compute.globalOperations.get",
    "compute.regionOperations.get",
    "compute.zoneOperations.get",
    "compute.machineTypes.get",
    "compute.diskTypes.get",
    "resourcemanager.projects.get",
    "serviceusage.services.use",

    # Existing VPC, managed subnet, static external address and routes.
    "compute.networks.get",
    "compute.networks.updatePolicy",
    "compute.subnetworks.create",
    "compute.subnetworks.delete",
    "compute.subnetworks.get",
    "compute.subnetworks.update",
    "compute.subnetworks.expandIpCidrRange",
    "compute.subnetworks.setPrivateIpGoogleAccess",
    "compute.subnetworks.use",
    "compute.subnetworks.useExternalIp",
    "compute.addresses.create",
    "compute.addresses.delete",
    "compute.addresses.get",
    "compute.addresses.setLabels",
    "compute.addresses.use",
    "compute.routes.create",
    "compute.routes.delete",
    "compute.routes.get",

    # Firewall writes are not included in roles/compute.networkAdmin.
    "compute.firewalls.create",
    "compute.firewalls.delete",
    "compute.firewalls.get",
    "compute.firewalls.update",

    # Jumphost lifecycle, metadata and networking; no attached service account.
    "compute.instances.create",
    "compute.instances.delete",
    "compute.instances.get",
    "compute.instances.start",
    "compute.instances.stop",
    "compute.instances.setMachineType",
    "compute.instances.setMetadata",
    "compute.instances.setTags",
    "compute.instances.setLabels",
    "compute.instances.addAccessConfig",
    "compute.instances.deleteAccessConfig",
    "compute.instances.updateAccessConfig",
    "compute.instances.updateNetworkInterface",
    "compute.instances.setScheduling",
    "compute.instances.setDiskAutoDelete",
    "compute.instances.attachDisk",
    "compute.instances.detachDisk",
    "compute.instances.addResourcePolicies",
    "compute.instances.removeResourcePolicies",
    "compute.disks.create",
    "compute.disks.delete",
    "compute.disks.get",
    "compute.disks.resize",
    "compute.disks.setLabels",
    "compute.disks.use",
    "compute.images.get",
    "compute.images.getFromFamily",
    "compute.images.useReadOnly",

    # Daily instance start/stop schedule.
    "compute.resourcePolicies.create",
    "compute.resourcePolicies.delete",
    "compute.resourcePolicies.get",
    "compute.resourcePolicies.update",
    "compute.resourcePolicies.use",
  ]
}

resource "google_project_iam_member" "cicd_deploy" {
  project = var.project_id
  role    = google_project_iam_custom_role.cicd_deploy.name
  member  = "serviceAccount:${google_service_account.cicd.email}"
}
